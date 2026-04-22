"""
Tests for the msw-mgr calibration workflow
"""

import pytest
import os
import json
import yaml
from unittest.mock import patch

from mswm.build_inputs import RealizationBuilder
from conftest import _make_calib_input_config


class TestCalibBuild:
    """End-to-end tests for calibration realization build workflow"""

    @pytest.fixture(autouse=True)
    def _build(self, tmp_work_dir, dummy_files):
        """Minimal test: confirm calibration pipeline runs to completion"""

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

        self.rb = rb

    # Calibration Tests
    # Workflow states
    def test_run_type(self):
        assert self.rb.run_type == "calibration"

    def test_work_dir(self):
        assert "kge_dds" in self.rb.work_dir

    # Calibration settings
    def test_strategy(self):
        assert self.rb.general_cfg["strategy"]["algorithm"] == "dds"
        assert self.rb.general_cfg["strategy"]["type"] == "estimation"

    def test_iterations(self):
        assert self.rb.general_cfg["iterations"] == 2

    # Time periods
    def test_calib_time_period(self):
        tp = self.rb.time_period["run_time_period"]
        assert tp["calib"][0] == "2015-10-01 00:00:00"
        assert tp["calib"][1] == "2017-09-30 23:00:00"

    def test_valid_time_period(self):
        tp = self.rb.time_period["run_time_period"]
        assert tp["valid"][0] == "2014-10-01 00:00:00"
        assert tp["valid"][1] == "2017-09-30 23:00:00"

    def test_valid_evaluation_period(self):
        ep = self.rb.time_period["evaluation_time_period"]
        assert ep["full"][0] == "2015-10-01 00:00:00"
        assert ep["full"][1] == "2017-09-30 23:00:00"

    # Model dict
    def test_model_dict_eval_params(self):
        ep = self.rb.model_dict["eval_params"]
        assert ep["objective"] == "kge"
        assert ep["evaluation_start"] == "2016-10-01 00:00:00"
        assert ep["basinID"] == "01123000"

    def test_model_dict_strategy(self):
        assert self.rb.model_dict["strategy"] == "uniform"

    # Realization file
    def test_realization_file_exists(self):
        assert os.path.isfile(self.rb.realization_file)

    def test_realization_is_valid_json(self):
        with open(self.rb.realization_file) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_realization_has_formulations(self):
        with open(self.rb.realization_file) as f:
            data = json.load(f)
        assert "global" in data
        assert "formulations" in data["global"]

    def test_realization_times(self):
        with open(self.rb.realization_file) as f:
            data = json.load(f)
        assert data["time"]["start_time"] == "2015-10-01 00:00:00"
        assert data["time"]["end_time"] == "2017-09-30 23:00:00"

    # Troute configs
    def test_num_troute_configs(self):
        assert len(self.rb.run_configs) == 3

    def test_troute_calib_config_exists(self):
        path = os.path.join(
            self.rb.work_dir, "Input",
            f"{self.rb.basin}_troute_config_calib.yaml",
        )
        assert os.path.isfile(path)

    def test_troute_valid_configs_exists(self):
        for suffix in ["valid_control", "valid_best"]:
            path = os.path.join(
                self.rb.work_dir, "Input",
                f"{self.rb.basin}_troute_config_{suffix}.yaml",
            )
            assert os.path.isfile(path), f"Missing troute config: {suffix}"

    # Calib config yaml
    def test_calib_config_file_exists(self):
        assert os.path.isfile(self.rb.calib_config_file)

    def test_calib_config_is_valid_yaml(self):
        with open(self.rb.calib_config_file) as f:
            cfg = yaml.safe_load(f)
        assert isinstance(cfg, dict)

    def test_calib_config_has_general(self):
        with open(self.rb.calib_config_file) as f:
            cfg = yaml.safe_load(f)
        assert "general" in cfg
        assert cfg["general"]["strategy"]["algorithm"] == "dds"

    def test_calib_config_has_model(self):
        with open(self.rb.calib_config_file) as f:
            cfg = yaml.safe_load(f)
        assert "model" in cfg
        assert cfg["model"]["eval_params"]["objective"] == "kge"

    # BMI config files
    def test_cfe_configs_exist(self):
        cfe_dir = os.path.join(self.rb.input_dir, "cfe-s_input")
        assert os.path.isdir(cfe_dir)
        files = os.listdir(cfe_dir)
        assert len(files) == len(self.rb.catids)

    def test_noah_configs_exist(self):
        noah_dir = os.path.join(self.rb.input_dir, "noah-owp-modular_input")
        assert os.path.isdir(noah_dir)
        input_files = [f for f in os.listdir(noah_dir) if f.endswith(".input")]
        assert len(input_files) == len(self.rb.catids)
