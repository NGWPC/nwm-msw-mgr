"""
Tests for the msw-mgr forecast workflow, chaining off of a calibration build
"""

import pytest
import json
from pathlib import Path
from unittest.mock import patch

from mswm.build_inputs import RealizationBuilder
from mswm.utils.copy_run_folder import copy_run_folder
from mswm.utils.checkpoint_restart import checkpoint_restart
from conftest import _make_region_input_config


def _run_region_build(tmp_work_dir):
    """Run a region workflow with checkpointing enabled"""
    # Create input config
    config = _make_region_input_config(tmp_work_dir)

    # Initialize builder
    rb = RealizationBuilder(
        config_overrides=config,
        checkpoint_interval=2,
    )

    # Mock file operations that require external dependencies
    with (
        patch("mswm.build_inputs.gfun.create_partition_file", return_value=None)
    ):
        # Run region workflow
        rb.build_region_realization()

    return rb


@pytest.fixture
def region_build(tmp_work_dir, dummy_files):
    """Run a region build workflow"""
    return _run_region_build(tmp_work_dir)


@pytest.fixture
def checkpoint_state_folder(tmp_path):
    """Create a minimal checkpoint state folder"""
    state = tmp_path / "state_save"
    state.mkdir()
    (state / "cat-1_state").write_text("{}")
    return state


@pytest.fixture
def copied_run_folder(region_build, tmp_path):
    """Run copy_run_folder once and return src/dst paths"""
    src = Path(region_build.input_dir)
    dst = tmp_path / "dst_run"
    copy_run_folder(str(src), str(dst))
    return src, dst


@pytest.fixture
def checkpoint_run_folder(region_build, tmp_path, checkpoint_state_folder):
    """Run checkpoint_restart and return src, dst, state, realization file and data"""
    src = Path(region_build.work_dir)
    dst = tmp_path / "dst_checkpoint"
    checkpoint_restart(str(src), str(dst), str(checkpoint_state_folder))
    real_file = list(dst.rglob("*realization*.json"))[0]
    with open(real_file) as f:
        real_data = json.load(f)
    return src, dst, checkpoint_state_folder, real_file, real_data


class TestCheckpointSaving:
    """Tests for checkpoint state saving configuration in realization"""

    @pytest.fixture(autouse=True)
    def _setup(self, region_build):
        self.rb = region_build
        with open(self.rb.realization_file) as f:
            self.real_data = json.load(f)

    def test_state_saving_added(self):
        assert "state_saving" in self.real_data

    def test_state_saving_config(self):
        save_configs = [
            s for s in self.real_data["state_saving"]
            if (s.get("when") == "Checkpoint" and s.get("direction") == "save")
        ]
        assert len(save_configs) == 1
        assert save_configs[0] == {
            "direction": "save",
            "label": "Save at checkpoint",
            "path": str(Path(self.rb.work_dir) / "checkpoint"),
            "type": "FilePerUnit",
            "when": "Checkpoint",
            "frequency": 2
        }, f"Actual config: {save_configs[0]}"

    def test_checkpoint_interval(self):
        save_configs = [
            s for s in self.real_data["state_saving"]
            if s.get("when") == "Checkpoint"
        ]
        assert save_configs[0]["frequency"] == 2


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

    def test_dst_exists_raises(self, region_build, tmp_path):
        src = Path(region_build.work_dir)
        dst2 = tmp_path / "dst_overwrite"
        dst2.mkdir()
        (dst2 / "old_file.txt").write_text("old_content")
        with pytest.raises(FileExistsError):
            copy_run_folder(str(src), str(dst2))

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
        assert self.real_data["state_saving"][1] == {
            "direction": "load",
            "label": "Load from checkpoint",
            "path": str(self.state.resolve()),
            "type": "FilePerUnit",
            "when": "Checkpoint"
        }

    def test_checkpoint_state_not_found_raises(self, region_build, tmp_path):
        with pytest.raises(FileNotFoundError):
            checkpoint_restart(
                str(Path(region_build.input_dir)),
                str(tmp_path / "dst2"),
                str(tmp_path / "nonexistent")
            )

    def test_no_realization_file_raises(self, tmp_path):
        empty_src = tmp_path / "empty_src"
        empty_src.mkdir()
        with pytest.raises(FileNotFoundError):
            checkpoint_restart(
                str(empty_src),
                str(tmp_path / "dst2"),
                str(self.state)
            )
