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
from conftest import _make_calib_input_config, _make_fcst_input_config, _make_lagged_ens_input_config


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


class TestFcstBuild:
    """End-to-end tests for forecast realization build workflow"""

    @pytest.fixture(autouse=True)
    def _build(self, tmp_work_dir, dummy_files, calib_build, valid_yaml_from_calib):
        """Minimal test: confirm forecast pipeline runs to completion"""

        # Create input config
        config = _make_fcst_input_config(tmp_work_dir)

        # Initialize builder
        rb = RealizationBuilder(
            config_overrides=config,
            valid_yaml=valid_yaml_from_calib,
            fcst_run_name="test_fcst",
            load_state_from="/path/to/state"
        )

        # Mock file operations that require external dependencies
        with (
            patch("mswm.build_inputs.gfun.create_partition_file", return_value=None),
            patch("pathlib.Path.exists", return_value=True)
        ):
            # Run calibration workflow
            rb.build_fcst_realization()

        self.rb = rb
        self.calib_rb = calib_build

    # Forecasts Tests
    # Workflow states
    # This test will be addressed by maxkipp-restrict-aorc-forcing-to-conus
    # def test_run_type(self):
    #     assert self.rb.run_type == "forecast"

    def test_basename_opt(self):
        assert self.rb.basename_opt == "fcst"

    def test_fcst_dir_created(self):
        assert os.path.isdir(self.rb.input_dir)

    def test_fcst_run_name_in_path(self):
        assert "test_fcst" in str(self.rb.input_dir)

    def test_forecast_run_dir(self):
        assert "Forecast_Run" in str(self.rb.input_dir)

    def test_load_state_path(self):
        assert "/path/to/state" in str(self.rb.load_state_from)

    # Yaml loading
    def test_valid_conf_has_general(self):
        assert "general" in self.rb.valid_conf

    def test_valid_conf_has_model(self):
        assert "model" in self.rb.valid_conf
        assert "realization" in self.rb.valid_conf["model"]

    def test_valid_conf_realization(self):
        assert "valid_best" in self.rb.valid_conf["model"]["realization"]

    # Realization loaded from calibration output
    def test_realization_loaded_from_calib(self):
        assert hasattr(self.rb, "real_config")
        assert isinstance(self.rb.real_config, dict)

    def test_loaded_realization_formulations(self):
        assert "global" in self.rb.real_config
        assert "formulations" in self.rb.real_config["global"]

    # Forecast realization file
    def test_realization_file_exists(self):
        assert os.path.isfile(self.rb.realization_file)

    def test_realization_is_valid_json(self):
        with open(self.rb.realization_file) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_realization_preserves_structure(self):
        with open(self.rb.realization_file) as f:
            data = json.load(f)
        assert "time" in data
        assert "global" in data
        assert "routing" in data

    def test_realization_has_formulations(self):
        with open(self.rb.realization_file) as f:
            data = json.load(f)
        assert "formulations" in data["global"]
        assert len(data["global"]["formulations"]) > 0

    def test_realization_time_fields(self):
        with open(self.rb.realization_file) as f:
            data = json.load(f)
        assert data["time"]["start_time"] is not None
        assert data["time"]["end_time"] is not None
        assert data["time"]["output_interval"] == 3600

    def test_realization_state_load(self):
        with open(self.rb.realization_file) as f:
            data = json.load(f)
        assert "state_saving" in data
        assert data["state_saving"][0]["label"] == "State load"
        assert data["state_saving"][0]["direction"] == "load"
        assert data["state_saving"][0]["path"] == "/path/to/state"
        assert data["state_saving"][0]["type"] == "FilePerUnit"
        assert data["state_saving"][0]["when"] == "StartOfRun"

    def test_realization_filename_uses_fcst(self):
        filename = os.path.basename(str(self.rb.realization_file))
        assert "fcst" in filename

    # Noah BMI configs updated for forecast
    def test_noah_fcst_configs_created(self):
        noah_dir = os.path.join(str(self.rb.input_dir), "noah-owp-modular_input")
        assert os.path.isdir(noah_dir)
        input_files = [f for f in os.listdir(noah_dir) if f.endswith(".input")]
        assert len(input_files) > 0

    # Troute updated for forecast
    def test_troute_fcst_config_created(self):
        fcst_dir = str(self.rb.input_dir)
        troute_files = [f for f in os.listdir(fcst_dir) if "troute" in f and f.endswith(".yaml")]
        assert len(troute_files) == 1
        assert "fcst" in troute_files[0]

    def test_troute_fcst_config_is_valid_yaml(self):
        fcst_dir = str(self.rb.input_dir)
        troute_files = [f for f in os.listdir(fcst_dir) if "troute" in f and f.endswith(".yaml")]
        with open(os.path.join(fcst_dir, troute_files[0])) as f:
            cfg = yaml.safe_load(f)
        assert isinstance(cfg, dict)


class TestFcstColdStartBuild:
    """End-to-end tests for cold start forecast realization build workflow"""

    @pytest.fixture(autouse=True)
    def _build(self, tmp_work_dir, dummy_files, calib_build, valid_yaml_from_calib):
        """Minimal test: confirm cold start forecast pipeline runs to completion"""

        # Create input config
        config = _make_fcst_input_config(tmp_work_dir)

        # Initialize builder
        rb = RealizationBuilder(
            config_overrides=config,
            valid_yaml=valid_yaml_from_calib,
            fcst_run_name="test_fcst",
            use_cold_start=True,
            save_state=True
        )

        # Mock file operations that require external dependencies
        with (
            patch("mswm.build_inputs.gfun.create_partition_file", return_value=None)
        ):
            # Run calibration workflow
            rb.build_fcst_realization()

        self.rb = rb

    # Workflow states
    def test_cold_start_basename(self):
        assert self.rb.basename_opt == "cold_start"

    def test_cold_start_run_type(self):
        assert self.rb.run_type == "cold_start"

    def test_cold_start_dir_name(self):
        assert "Cold_Start_Run" in str(self.rb.input_dir)

    def test_save_state(self):
        assert self.rb.save_state is True

    # Cold start realization
    def test_cold_start_realization_written(self):
        assert os.path.isfile(self.rb.realization_file)
        filename = os.path.basename(str(self.rb.realization_file))
        assert "cold_start" in filename

    def test_cold_start_realization_is_valid_json(self):
        with open(self.rb.realization_file) as f:
            data = json.load(f)
        assert isinstance(data, dict)
        assert "time" in data
        assert "global" in data

    def test_cold_start_troute_config_created(self):
        fcst_dir = str(self.rb.input_dir)
        troute_files = [f for f in os.listdir(fcst_dir) if "troute" in f and f.endswith(".yaml")]
        assert len(troute_files) == 1
        assert "cold_start" in troute_files[0]

    def test_realization_statesave(self):
        with open(self.rb.realization_file) as f:
            data = json.load(f)
        assert "state_saving" in data
        assert data["state_saving"][0]["label"] == "Save at end of run"
        assert data["state_saving"][0]["direction"] == "save"
        assert data["state_saving"][0]["path"] == str(Path(self.rb.work_dir) / "state_save")
        assert data["state_saving"][0]["type"] == "FilePerUnit"
        assert data["state_saving"][0]["when"] == "EndOfRun"


class TestFcstWarmStartBuild:
    """End-to-end tests for warm start forecast realization build workflow"""

    @pytest.fixture(autouse=True)
    def _build(self, tmp_work_dir, dummy_files, calib_build, valid_yaml_from_calib):
        """Minimal test: confirm warm start forecast pipeline runs to completion"""

        # Create input config
        config = _make_fcst_input_config(tmp_work_dir)

        # Initialize builder
        rb = RealizationBuilder(
            config_overrides=config,
            valid_yaml=valid_yaml_from_calib,
            fcst_run_name="test_fcst",
            use_warm_start=True,
            save_state=True,
            load_state_from="/path/to/state"
        )

        # Mock file operations that require external dependencies
        with (
            patch("mswm.build_inputs.gfun.create_partition_file", return_value=None),
            patch("pathlib.Path.exists", return_value=True)
        ):
            # Run calibration workflow
            rb.build_fcst_realization()

        self.rb = rb

    # Workflow states
    def test_warm_start_basename(self):
        assert self.rb.basename_opt == "warm_start"

    def test_warm_start_run_type(self):
        assert self.rb.run_type == "warm_start"

    def test_warm_start_dir_name(self):
        assert "Warm_Start_Run" in str(self.rb.input_dir)

    def test_save_state(self):
        assert self.rb.save_state is True

    def test_load_state_path(self):
        assert "/path/to/state" in str(self.rb.load_state_from)

    # Warm start realization
    def test_warm_start_realization_written(self):
        assert os.path.isfile(self.rb.realization_file)
        filename = os.path.basename(str(self.rb.realization_file))
        assert "warm_start" in filename

    def test_warm_start_realization_is_valid_json(self):
        with open(self.rb.realization_file) as f:
            data = json.load(f)
        assert isinstance(data, dict)
        assert "time" in data
        assert "global" in data

    def test_warm_start_troute_config_created(self):
        fcst_dir = str(self.rb.input_dir)
        troute_files = [f for f in os.listdir(fcst_dir) if "troute" in f and f.endswith(".yaml")]
        assert len(troute_files) == 1
        assert "warm_start" in troute_files[0]

    def test_realization_statesave(self):
        with open(self.rb.realization_file) as f:
            data = json.load(f)
        assert "state_saving" in data
        assert data["state_saving"][0]["label"] == "State load"
        assert data["state_saving"][0]["direction"] == "load"
        assert data["state_saving"][0]["path"] == "/path/to/state"
        assert data["state_saving"][0]["type"] == "FilePerUnit"
        assert data["state_saving"][0]["when"] == "StartOfRun"
        assert data["state_saving"][1]["label"] == "Save at end of run"
        assert data["state_saving"][1]["direction"] == "save"
        assert data["state_saving"][1]["path"] == str(Path(self.rb.work_dir) / "state_save")
        assert data["state_saving"][1]["type"] == "FilePerUnit"
        assert data["state_saving"][1]["when"] == "EndOfRun"


class TestHindcastBuild:
    """End-to-end tests for hindcast realization build workflow"""

    @pytest.fixture(autouse=True)
    def _build(self, tmp_work_dir, dummy_files, calib_build, valid_yaml_from_calib):
        """Minimal test: confirm hindcast pipeline runs to completion"""

        # Create input config
        config = _make_fcst_input_config(tmp_work_dir)

        # Initialize builder
        rb = RealizationBuilder(
            config_overrides=config,
            valid_yaml=valid_yaml_from_calib,
            fcst_run_name="test_hind",
            use_hindcast=True,
            hind_cycle=3,
            prev_hind_cycle=0,
            load_state_from="/path/to/state"
        )

        # Mock file operations that require external dependencies
        with (
            patch("mswm.build_inputs.gfun.create_partition_file", return_value=None),
            patch("pathlib.Path.exists", return_value=True)
        ):
            # Run calibration workflow
            rb.build_fcst_realization()

        self.rb = rb

    # Workflow states
    def test_hindcast_basename(self):
        assert self.rb.basename_opt == "hind"

    def test_hind_run_type(self):
        assert self.rb.run_type == "hindcast"

    def test_hindcast_dir_name(self):
        assert "Hindcast_Run" in str(self.rb.input_dir)

    def test_load_state_path(self):
        assert "/path/to/state" in str(self.rb.load_state_from)

    # Hindcast realization
    def test_hindcast_realization_written(self):
        assert os.path.isfile(self.rb.realization_file)
        filename = os.path.basename(str(self.rb.realization_file))
        assert "hind" in filename

    def test_hindcast_realization_is_valid_json(self):
        with open(self.rb.realization_file) as f:
            data = json.load(f)
        assert isinstance(data, dict)
        assert "time" in data
        assert "global" in data

    def test_hindcast_troute_config_created(self):
        fcst_dir = str(self.rb.input_dir)
        troute_files = [f for f in os.listdir(fcst_dir) if "troute" in f and f.endswith(".yaml")]
        assert len(troute_files) == 1
        assert "hind" in troute_files[0]

    def test_realization_statesave(self):
        with open(self.rb.realization_file) as f:
            data = json.load(f)
        assert "state_saving" in data
        assert data["state_saving"][0]["label"] == "State load"
        assert data["state_saving"][0]["direction"] == "load"
        assert data["state_saving"][0]["path"] == "/path/to/state"
        assert data["state_saving"][0]["type"] == "FilePerUnit"
        assert data["state_saving"][0]["when"] == "StartOfRun"

    def test_hindcast_variables(self):
        assert self.rb.hind_cycle == 3
        assert self.rb.prev_hind_cycle == 0


class TestLaggedEnsBuild:
    """End-to-end tests for lagged ensemble realization build workflow"""

    @pytest.fixture(autouse=True)
    def _build(self, tmp_work_dir, dummy_files, calib_build, valid_yaml_from_calib):
        """Minimal test: confirm lagged ensemble pipeline runs to completion"""

        # Create input config
        config = _make_lagged_ens_input_config(tmp_work_dir)

        # Initialize builder
        rb = RealizationBuilder(
            config_overrides=config,
            valid_yaml=valid_yaml_from_calib,
            fcst_run_name="test_lagged_ens",
            use_lagged_ens=True,
            lagged_ens_mem="mem2",
            forcing_lag=6,
            load_state_from="/path/to/state"
        )

        # Mock file operations that require external dependencies
        with (
            patch("mswm.build_inputs.gfun.create_partition_file", return_value=None),
            patch("pathlib.Path.exists", return_value=True)
        ):
            # Run calibration workflow
            rb.build_fcst_realization()

        self.rb = rb

    # Workflow states
    def test_lagged_ens_basename(self):
        assert self.rb.basename_opt == "lagged_ens"

    # def test_lagged_ens_run_type(self):
    #     assert self.rb.run_type == "lagged_ens"

    def test_lagged_ens_dir_name(self):
        assert "Lagged_Ensemble_Run" in str(self.rb.input_dir)

    def test_load_state_path(self):
        assert "/path/to/state" in str(self.rb.load_state_from)

    # LAgged Ensemble realization
    def test_lagged_ens_realization_written(self):
        assert os.path.isfile(self.rb.realization_file)
        filename = os.path.basename(str(self.rb.realization_file))
        assert "lagged_ens" in filename

    def test_lagged_ens_realization_is_valid_json(self):
        with open(self.rb.realization_file) as f:
            data = json.load(f)
        assert isinstance(data, dict)
        assert "time" in data
        assert "global" in data

    def test_lagged_ens_troute_config_created(self):
        fcst_dir = str(self.rb.input_dir)
        troute_files = [f for f in os.listdir(fcst_dir) if "troute" in f and f.endswith(".yaml")]
        assert len(troute_files) == 1
        assert "lagged_ens" in troute_files[0]

    def test_realization_statesave(self):
        with open(self.rb.realization_file) as f:
            data = json.load(f)
        assert "state_saving" in data
        assert data["state_saving"][0]["label"] == "State load"
        assert data["state_saving"][0]["direction"] == "load"
        assert data["state_saving"][0]["path"] == "/path/to/state"
        assert data["state_saving"][0]["type"] == "FilePerUnit"
        assert data["state_saving"][0]["when"] == "StartOfRun"

    def test_lagged_ens_variables(self):
        assert self.rb.lagged_ens_mem == "mem2"
        assert self.rb.forcing_lag == 6
