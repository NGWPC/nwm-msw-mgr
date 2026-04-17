"""
Tests for the msw-mgr update_fcst_run_workflow, chaining off of a regionalization run
"""

import pytest
import os
import json
import yaml
from pathlib import Path
from unittest.mock import patch

from mswm.build_inputs import RealizationBuilder
from conftest import _make_region_input_config, _make_fcst_input_config


def _run_region_build(tmp_work_dir):
    """Run a regionalization workflow to use as source for update_fcst_run"""

    config = _make_region_input_config(tmp_work_dir)
    rb = RealizationBuilder(config_overrides=config)
    with (
        patch("mswm.build_inputs.gfun.create_partition_file", return_value=None)
    ):
        rb.build_region_realization()
    return rb


@pytest.fixture
def region_build(tmp_work_dir, dummy_files):
    """Run update_fcst_run and return the RealizationBuilder"""
    return _run_region_build(tmp_work_dir)


@pytest.fixture
def update_fcst_run_build(region_build, tmp_work_dir, tmp_path):
    """Run update_fcst_run and return the RealizaitonBuilder class"""
    config = _make_fcst_input_config(tmp_work_dir)
    src_run_path = Path(region_build.work_dir)
    dst_run_path = tmp_path / "updated_fcst" / "01123000"

    rb = RealizationBuilder(
        config_overrides=config,
        src_run_path=str(src_run_path),
        dst_run_path=str(dst_run_path),
    )
    with (
        patch("mswm.build_inputs.gfun.create_partition_file", return_value=None)
    ):
        rb.update_fcst_run()

    return rb, src_run_path, dst_run_path


class TestUpdateFcstRun:
    """Tests for update_fcst_run workflow"""

    @pytest.fixture(autouse=True)
    def _setup(self, update_fcst_run_build):
        self.rb, self.src, self.dst_run_path = update_fcst_run_build
        self.dst = self.dst_run_path
        self.real_file = self.rb.realization_file
        with open(self.real_file) as f:
            self.real_data = json.load(f)

    def test_dst_created(self):
        assert self.dst.exists()

    def test_basin_in_dst_path(self):
        assert "01123000" in str(self.dst)

    def test_files_copied(self):
        ignore_dirs = {'Output', 'state_save', 'forcing_config'}
        src_files = {f.name for f in self.src.rglob("*") if f.is_file() and not any(part in ignore_dirs for part in f.parts) and f.suffix != '.log'}
        dst_files = {f.name for f in self.dst.rglob("*") if f.is_file()}
        assert src_files.issubset(dst_files)

    def test_path_references_updated(self):
        for f in self.dst.rglob("*.json"):
            assert str(self.src) not in f.read_text()

    def test_realization_is_valid(self):
        assert isinstance(self.real_data, dict)
        assert "time" in self.real_data
        assert "routing" in self.real_data
        assert "formulation_groups" in self.real_data

    def test_realization_time_fields(self):
        assert self.real_data["time"]["start_time"] is not None
        assert self.real_data["time"]["end_time"] is not None
        assert self.real_data["time"]["output_interval"] == 3600

    def test_forcing_config_file(self):
        assert os.path.isfile(self.rb.forcing_config_file)
        with open(self.rb.forcing_config_file) as f:
            cfg = yaml.safe_load(f)
        assert isinstance(cfg, dict)

    def test_troute_config_file(self):
        troute_files = [f for f in os.listdir(self.rb.input_dir) if "troute" in f]
        assert len(troute_files) == 1
        with open(os.path.join(self.rb.input_dir, troute_files[0])) as f:
            cfg = yaml.safe_load(f)
        assert isinstance(cfg, dict)
        assert cfg["compute_parameters"]["restart_parameters"]["start_datetime"] is not None

    def test_src_not_provided_raises(self, tmp_work_dir):
        config = _make_fcst_input_config(tmp_work_dir)
        rb = RealizationBuilder(
            config_overrides=config,
            dst_run_path="/some/dst"
        )
        with pytest.raises(ValueError):
            rb.update_fcst_run()

    def test_dst_not_provided_raises(self, tmp_work_dir, region_build):
        config = _make_fcst_input_config(tmp_work_dir)
        rb = RealizationBuilder(
            config_overrides=config,
            src_run_path=str(region_build.work_dir)
        )
        with pytest.raises(ValueError):
            rb.update_fcst_run()
