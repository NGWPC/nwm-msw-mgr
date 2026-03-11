"""
Tests for the msw-mgr regionalization workflow
"""

import pytest
import os
import json
import yaml
from pathlib import Path
from unittest.mock import patch

from mswm.build_inputs import RealizationBuilder
from conftest import _make_region_input_config


class TestRegionBuild:
    """End-to-end tests for regionalization realization build workflow"""

    @pytest.fixture(autouse=True)
    def _build(self, tmp_work_dir, dummy_files):
        """Minimal test: confirm regionalization pipeline runs to completion"""

        # Create input config
        config = _make_region_input_config(tmp_work_dir)

        # Initialize builder
        rb = RealizationBuilder(config_overrides=config)

        # Mock file operations that require external dependencies
        with (
            patch("mswm.build_inputs.gfun.create_partition_file", return_value=None)
        ):
            # Run regionalization workflow
            rb.build_region_realization()

        self.rb = rb

    # Regionalization Tests
    # Workflow states
    def test_run_type(self):
        assert self.rb.run_type == "regionalization"

    def test_work_dir(self):
        assert "regionalization" in self.rb.work_dir

    # Group catchment mappings
    def test_grp_to_cat_populated(self):
        assert len(self.rb.grp_to_cat) == 2
        all_cats = [c for cats in self.rb.grp_to_cat.values() for c in cats]
        assert set(all_cats) == set(self.rb.catids)

    def test_cat_to_grp_populated(self):
        for cat in self.rb.catids:
            assert cat in self.rb.cat_to_grp

    def test_grp_to_form_has_modules(self):
        for grp, form in self.rb.grp_to_form.items():
            assert "sloth" in form
            assert "noah" in form
            assert "cfes" in form or "cfex" in form
            assert "troute" in form

    def test_cat_to_form_populated(self):
        for cat in self.rb.catids:
            assert "noah" in self.rb.cat_to_form[cat]

    def test_mod_to_cat_populated(self):
        assert set(self.rb.mod_to_cat["noah"]) == set(self.rb.catids)

    # Regionalization parameters
    def test_grp_params_parsed(self):
        assert "noah" in self.rb.grp_params
        assert self.rb.grp_params["noah"]["gage1"]["MP"] == 9
        assert self.rb.grp_params["noah"]["gage2"]["MP"] == 9

    def test_grp_aet_rootzone(self):
        assert self.rb.grp_aet_rootzone["gage1"] == 1
        assert self.rb.grp_aet_rootzone["gage2"] == 0

    # Time periods
    def test_calib_time_period(self):
        tp = self.rb.time_period["run_time_period"]["region"]
        assert tp[0] == "2015-10-01 00:00:00"
        assert tp[1] == "2016-09-30 23:00:00"

    # Realization file
    def test_realization_file_exists(self):
        assert os.path.isfile(self.rb.realization_file)

    def test_realization_is_valid_json(self):
        with open(self.rb.realization_file) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_realization_has_times(self):
        with open(self.rb.realization_file) as f:
            data = json.load(f)
        assert "time" in data
        assert data["time"]["start_time"] == "2015-10-01 00:00:00"
        assert data["time"]["end_time"] == "2016-09-30 23:00:00"

    def test_realization_has_cat_formulations(self):
        with open(self.rb.realization_file) as f:
            data = json.load(f)
        assert "catchments" in data
        assert "formulation_groups" in data
        for cat in self.rb.catids:
            assert str(cat) in data["catchments"], f"Missing catchment {cat} in realization"

    def test_realization_has_routing(self):
        with open(self.rb.realization_file) as f:
            data = json.load(f)
        assert "routing" in data

    # Troute config
    def test_num_troute_configs(self):
        assert len(self.rb.run_configs) == 1
        assert "_troute_config_region.yaml" in self.rb.run_configs[0]

    def test_troute_config_exists(self):
        path = os.path.join(
            self.rb.work_dir, "Input",
            f"{self.rb.basin}_troute_config_region.yaml",
        )
        assert os.path.isfile(path)

    # BMI config files
    def test_cfes_configs_exist(self):
        cfes_dir = os.path.join(self.rb.input_dir, "cfe-s_input")
        assert os.path.isdir(cfes_dir)
        files = os.listdir(cfes_dir)
        assert len(files) == 4

    def test_cfex_configs_exist(self):
        cfex_dir = os.path.join(self.rb.input_dir, "cfe-x_input")
        assert os.path.isdir(cfex_dir)
        files = os.listdir(cfex_dir)
        assert len(files) == 4

    def test_noah_configs_exist(self):
        noah_dir = os.path.join(self.rb.input_dir, "noah-owp-modular_input")
        assert os.path.isdir(noah_dir)
        input_files = [f for f in os.listdir(noah_dir) if f.endswith(".input")]
        assert len(input_files) == len(self.rb.catids)
