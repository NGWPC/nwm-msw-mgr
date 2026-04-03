"""
Tests for the msw-mgr forecast workflow, chaining off of a calibration build
"""

import pytest
import os
import json
import yaml
from pathlib import Path
from unittest.mock import patch

from mswm.build_inputs import RealizationBuilder
from mswm.utils.copy_run_folder import copy_run_folder
from mswm.utils.checkpoint_restart import checkpoint_restart
from conftest import _make_calib_input_config, _make_fcst_input_config


def _run_calib_build(tmp_work_dir):
    """Run a calibration workflow"""
    # Create input config
    config = _make_calib_input_config(tmp_work_dir)

    # Initialize builder
    rb = RealizationBuilder(config_overrides=config)

    # Mock file operations that require external dependencies
    with (
        patch("mswm.build_inputs.gfun.create_partition_file", return_value=None)
    ):
        # Run calibration workflow
        rb.build_calib_realization()

    return rb


def _create_valid_best_from_calib(calib_rb):
    """Create a valid_best realization and yaml from a completed calibration build"""
    # Copy calib to valid realization
    calib_real_path = str(calib_rb.realization_file)
    valid_best_real_path = calib_real_path.replace("_calib.", "_valid_best.")

    with open(calib_real_path) as f:
        real_data = json.load(f)

    # Update troute path to valid_best
    troute_path = real_data["routing"]["t_route_config_file_with_path"]
    real_data["routing"]["t_route_config_file_with_path"] = troute_path.replace("_calib.", "_valid_best.")

    with open(valid_best_real_path, "w") as f:
        json.dump(real_data, f, indent=4)

    # Update the calib config YAML to point to the valid_best realization
    with open(calib_rb.calib_config_file) as f:
        calib_yaml = yaml.safe_load(f)

    calib_yaml["model"]["realization"] = valid_best_real_path

    with open(calib_rb.calib_config_file, "w") as f:
        yaml.dump(calib_yaml, f)

    return calib_rb.calib_config_file


@pytest.fixture
def calib_build(tmp_work_dir, dummy_files):
    """Run a calibration build workflow"""
    return _run_calib_build(tmp_work_dir)


@pytest.fixture
def valid_yaml_from_calib(calib_build):
    """Create valid_best files from calib output"""
    return _create_valid_best_from_calib(calib_build)


@pytest.fixture
def fcst_build(tmp_work_dir, dummy_files, calib_build, valid_yaml_from_calib):
    """Run a forecast build workflow to use as source for copy/checkpoint"""
    config = _make_fcst_input_config(tmp_work_dir)
    rb = RealizationBuilder(
        config_overrides=config,
        valid_yaml=valid_yaml_from_calib,
        fcst_run_name="test_fcst"
    )
    with (
        patch("mswm.build_inputs.gfun.create_partition_file", return_value=None)
    ):
        rb.build_fcst_realization()
    return rb


@pytest.fixture
def checkpoint_state_folder(tmp_path):
    """Create a minimal checkpoint state folder"""
    state = tmp_path / "state_save"
    state.mkdir()
    (state / "cat-1_state").write_text("{}")
    return state


@pytest.fixture
def copied_run_folder(fcst_build, tmp_path):
    """Run copy_run_folder once and return src/dst paths"""
    src = Path(fcst_build.input_dir)
    dst = tmp_path / "dst_run"
    copy_run_folder(str(src), str(dst))
    return src, dst


@pytest.fixture
def checkpoint_run_folder(fcst_build, tmp_path, checkpoint_state_folder):
    """Run checkpoint_restart and return src, dst, state, realization file and data"""
    src = Path(fcst_build.work_dir)
    dst = tmp_path / "dst_checkpoint"
    with patch("mswm.utils.log_level.log_level_set"):
        checkpoint_restart(str(src), str(dst), str(checkpoint_state_folder))
    real_file = list(dst.rglob("*realization*.json"))[0]
    with open(real_file) as f:
        real_data = json.load(f)
    return src, dst, checkpoint_state_folder, real_file, real_data


class TestCopyRunFolder:
    """Tests for copy_run_folder utility"""

    @pytest.fixture(autouse=True)
    def _setup(self, copied_run_folder):
        self.src, self.dst = copied_run_folder

    def test_dst_created(self):
        assert self.dst.exists()

    def test_files_copied(self):
        src_files = {f.name for f in self.src.rglob("*") if f.is_file()}
        dst_files = {f.name for f in self.dst.rglob("*") if f.is_file()}
        assert src_files.issubset(dst_files)

    def test_log_files_excluded(self):
        assert len(list(self.dst.rglob("*.log"))) == 0

    def test_output_dir_excluded(self):
        assert not (self.dst / "Output").exists()

    def test_path_references_updated(self):
        for f in self.dst.rglob("*.json"):
            content = f.read_text()
            assert str(self.src) not in content

    def test_dst_overwritten_if_exists(self, fcst_build, tmp_path):
        src = Path(fcst_build.work_dir)
        dst2 = tmp_path / "dst_overwrite"
        dst2.mkdir()
        (dst2 / "old_file.txt").write_text("old_content")
        copy_run_folder(str(src), str(dst2))
        assert not (dst2 / "old_file.txt").exists()

    def test_src_not_found_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            copy_run_folder(
                str(tmp_path / "nonexistent"),
                str(tmp_path / "dst")
            )

    def test_src_not_dir_raises(self, tmp_path):
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("content")
        with pytest.raises(ValueError):
            copy_run_folder(str(file_path), str(tmp_path / "dst"))


class TestCheckpointRestart:
    """Tests for checkpoint_restart utility"""

    @pytest.fixture(autouse=True)
    def _setup(self, checkpoint_run_folder):
        self.src, self.dst, self.state, self.real_file, self.real_data = checkpoint_run_folder

    def test_dst_created(self):
        assert self.dst.exists()

    def test_realization_file_exists(self):
        assert self.real_file.exists()

    def test_state_saving_added(self):
        assert "state_saving" in self.real_data

    def test_state_saving_config(self):
        assert self.real_data["state_saving"][0] == {
            "direction": "load",
            "label": "State load",
            "path": str(self.state.resolve()),
            "type": "FilePerUnit",
            "when": "StartOfRun"
        }

    def test_checkpoint_state_not_found_raises(self, fcst_build, tmp_path):
        with patch("mswm.utils.log_level.log_level_set"):
            with pytest.raises(FileNotFoundError):
                checkpoint_restart(
                    str(Path(fcst_build.input_dir)),
                    str(tmp_path / "dst2"),
                    str(tmp_path / "nonexistent")
                )

    def test_no_realization_file_raises(self, tmp_path):
        empty_src = tmp_path / "empty_src"
        empty_src.mkdir()
        with patch("mswm.utils.log_level.log_level_set"):
            with pytest.raises(FileNotFoundError):
                checkpoint_restart(
                    str(empty_src),
                    str(tmp_path / "dst2"),
                    str(self.state)
                )
