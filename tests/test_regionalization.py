"""
Tests for the msw-mgr regionalization workflow
"""

import pytest
import os
import json
from unittest.mock import patch

from mswm.build_inputs import RealizationBuilder
from conftest import _make_region_input_config, _make_region_nwm_output_input_config


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
            assert "cfes" in form or "lasam" in form
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
        assert self.rb.grp_params["noah"]["gage2"]["MP"] == 8

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

    def test_lasam_configs_exist(self):
        lasam_dir = os.path.join(self.rb.input_dir, "lasam_input")
        assert os.path.isdir(lasam_dir)
        files = os.listdir(lasam_dir)
        assert len(files) == 3

    def test_noah_configs_exist(self):
        noah_dir = os.path.join(self.rb.input_dir, "noah-owp-modular_input")
        assert os.path.isdir(noah_dir)
        input_files = [f for f in os.listdir(noah_dir) if f.endswith(".input")]
        assert len(input_files) == len(self.rb.catids)


class TestRegionNWMOutputBuild:
    """End-to-end tests for regionalization realization build workflowwith nwm output variables"""

    @pytest.fixture(autouse=True)
    def _build(self, tmp_work_dir, dummy_files):
        """Minimal test: confirm regionalization pipeline runs to completion"""

        # Create input config
        config = _make_region_nwm_output_input_config(tmp_work_dir)

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
            assert "cfes" in form or "lasam" in form
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
        assert self.rb.grp_params["noah"]["gage2"]["MP"] == 8

    def test_grp_aet_rootzone(self):
        assert self.rb.grp_aet_rootzone["gage1"] == 1
        assert self.rb.grp_aet_rootzone["gage2"] == 0

    # NWM Output Variable tests
    def test_adapters(self):
        assert hasattr(self.rb, 'adapters')
        assert all(x in self.rb.adapters for x in ['sloth', 'sft', 'smp'])
        assert hasattr(self.rb, 'grp_to_adapters')
        assert all(x in self.rb.grp_to_adapters['gage1'] for x in ['sloth', 'sft', 'smp'])
        assert all(x in self.rb.grp_to_adapters['gage2'] for x in ['sloth', 'sft', 'smp'])

    def test_output_variables_grp1(self):
        assert hasattr(self.rb, 'output_nwm_vars')
        assert hasattr(self.rb, 'grp_to_nwm_output_dicts')
        nwm_outputs = [x['nwm_name'] for x in self.rb.grp_to_nwm_output_dicts['gage1']]
        nwm_required_outputs = ['sfcheadsubrt', 'qBucket', 'ACSNOM', 'SNOWT_AVG', 'SOILICE', 'SOILSAT_TOP', 'QRAIN', 'FSNO', 'SNOWH',
                                'SNLIQ', 'SNEQV', 'QSNOW', 'SOIL_T', 'SOIL_M', 'SFCRNOFF', 'TRAD', 'LH', 'FIRA', 'HFX']
        assert nwm_outputs == nwm_required_outputs

    def test_output_variables_grp2(self):
        assert hasattr(self.rb, 'output_nwm_vars')
        assert hasattr(self.rb, 'grp_to_nwm_output_dicts')
        nwm_outputs = [x['nwm_name'] for x in self.rb.grp_to_nwm_output_dicts['gage2']]
        nwm_required_outputs = ['sfcheadsubrt', 'qBucket', 'ACSNOM', 'SNOWT_AVG', 'SOILICE', 'SOILSAT_TOP', 'QRAIN', 'FSNO', 'SNOWH',
                                'SNLIQ', 'SNEQV', 'QSNOW', 'SOIL_T', 'SOIL_M', 'SFCRNOFF', 'TRAD', 'LH', 'FIRA', 'HFX']
        assert nwm_outputs == nwm_required_outputs

    def test_nwm_units_grp1(self):
        nwm_units = [x['nwm_units'] for x in self.rb.grp_to_nwm_output_dicts['gage1']]
        nwm_required_units = ['mm', 'm3/s', 'mm', 'K', '1', '1', 'mm/s', '1', 'm',
                              'mm', 'kg/m2', 'mm/s', 'K', 'm3/m3', 'mm', 'K', 'W/m2', 'W/m2', 'W/m2']
        assert nwm_units == nwm_required_units

    def test_nwm_units_grp2(self):
        nwm_units = [x['nwm_units'] for x in self.rb.grp_to_nwm_output_dicts['gage2']]
        nwm_required_units = ['mm', 'm3/s', 'mm', 'K', '1', '1', 'mm/s', '1', 'm',
                              'mm', 'kg/m2', 'mm/s', 'K', 'm3/m3', 'mm', 'K', 'W/m2', 'W/m2', 'W/m2']
        assert nwm_units == nwm_required_units

    def test_nwm_providers_grp1(self):
        nwm_providers = [x['provider'] for x in self.rb.grp_to_nwm_output_dicts['gage1']]
        nwm_required_providers = ['cfes', 'cfes', 'noah', 'noah', 'sft', 'smp', 'noah', 'noah', 'noah',
                                  'noah', 'noah', 'noah', 'sft', 'smp', 'cfes', 'noah', 'noah', 'noah', 'noah']
        assert nwm_providers == nwm_required_providers

    def test_nwm_providers_grp2(self):
        nwm_providers = [x['provider'] for x in self.rb.grp_to_nwm_output_dicts['gage2']]
        nwm_required_providers = ['lasam', 'lasam', 'noah', 'noah', 'sft', 'smp', 'noah', 'noah', 'noah',
                                  'noah', 'noah', 'noah', 'sft', 'smp', 'lasam', 'noah', 'noah', 'noah', 'noah']
        assert nwm_providers == nwm_required_providers

    def test_nwm_provider_vars_grp1(self):
        nwm_provider_vars = [x['provider_var'] for x in self.rb.grp_to_nwm_output_dicts['gage1']]
        nwm_required_provider_vars = ['NWM_PONDED_DEPTH', 'DEEP_GW_TO_CHANNEL_FLUX_M3_PER_S', 'ACSNOM', 'SNOWT_AVG', 'soil_ice_fraction', 'soil_moisture_fraction', 'QRAIN', 'FSNO', 'SNOWH',
                                      'SNLIQ', 'SNEQV_kg_m2', 'QSNOW', 'soil_temperature_profile', 'soil_moisture_profile', 'SFCRNOFF', 'TRAD', 'LH', 'FIRA', 'FSH']
        assert nwm_provider_vars == nwm_required_provider_vars

    def test_nwm_provider_vars_grp2(self):
        nwm_provider_vars = [x['provider_var'] for x in self.rb.grp_to_nwm_output_dicts['gage2']]
        nwm_required_provider_vars = ['nwm_ponded_depth', 'groundwater_to_stream_recharge_m3_per_s', 'ACSNOM', 'SNOWT_AVG', 'soil_ice_fraction', 'soil_moisture_fraction', 'QRAIN', 'FSNO', 'SNOWH',
                                      'SNLIQ', 'SNEQV_kg_m2', 'QSNOW', 'soil_temperature_profile', 'soil_moisture_profile', 'surface_runoff', 'TRAD', 'LH', 'FIRA', 'FSH']
        assert nwm_provider_vars == nwm_required_provider_vars

    def test_nwm_ouputs_in_realization_grp1(self):
        assert len(self.rb.real_config['formulation_groups']['gage1'][0]['params']['output_variables']) == 21

    def test_nwm_ouputs_in_realization_grp2(self):
        assert len(self.rb.real_config['formulation_groups']['gage2'][0]['params']['output_variables']) == 21

    def test_adapters_in_realization_grp1(self):
        assert len(self.rb.real_config['formulation_groups']['gage1'][0]['params']['modules']) == 5
        modules = [x['params']['model_type_name'] for x in self.rb.real_config['formulation_groups']['gage1'][0]['params']['modules']]
        assert all(x in modules for x in ['SLOTH', 'NoahOWP', 'SMP', 'SFT', 'CFE'])

    def test_adapters_in_realization_grp2(self):
        assert len(self.rb.real_config['formulation_groups']['gage2'][0]['params']['modules']) == 5
        modules = [x['params']['model_type_name'] for x in self.rb.real_config['formulation_groups']['gage2'][0]['params']['modules']]
        assert all(x in modules for x in ['SLOTH', 'NoahOWP', 'SMP', 'SFT', 'LASAM'])

    def test_sloth_after_adapters_grp1(self):
        expected_sloth_params = {
            "sloth_ice_fraction_schaake(1,double,1,node)": 0.0,
            "sloth_ice_fraction_xinanjiang(1,double,1,node)": 0.0,
            "sloth_smp(1,double,1,node)": 0.0,
            "sloth_soil_storage(1,double,m,node)": 1e-10,
            "sloth_soil_storage_change(1,double,m,node)": 0.0,
            "soil_moisture_wetting_fronts(1,double,1,node)": 0.0,
            "soil_thickness_layered(1,double,1,node)": 0.0,
            "soil_depth_wetting_fronts(1,double,m,node)": 0.0,
            "num_wetting_fronts(1,int,1,node)": 1.0,
            "Qb_topmodel(1,double,m h^-1,node)": 0.0,
            "Qv_topmodel(1,double,m h^-1,node)": 0.0,
            "global_deficit(1,double,m,node)": 0.0
        }
        assert self.rb.real_config['formulation_groups']['gage1'][0]['params']['modules'][0]["params"]["model_params"] == expected_sloth_params

    def test_sloth_after_adapters_grp2(self):
        expected_sloth_params = {
            'sloth_soil_storage(1,double,m,node)': 1e-10,
            'sloth_soil_storage_change(1,double,m,node)': 0.0,
            'Qb_topmodel(1,double,m h^-1,node)': 0.0,
            'Qv_topmodel(1,double,m h^-1,node)': 0.0,
            'global_deficit(1,double,m,node)': 0.0,
            'potential_evapotranspiration_rate(1,double,1,node)': 0.0,
            "num_wetting_fronts(1,int,1,node)": 1.0
        }
        assert self.rb.real_config['formulation_groups']['gage2'][0]['params']['modules'][0]["params"]["model_params"] == expected_sloth_params

    def test_sft_adapter_configs_created(self):
        sft_dir = os.path.join(str(self.rb.input_dir), "sft_input")
        assert os.path.isdir(sft_dir)
        input_files = [f for f in os.listdir(sft_dir) if f.endswith(".txt")]
        assert len(input_files) == 7

    def test_smp_adapter_configs_created(self):
        smp_dir = os.path.join(str(self.rb.input_dir), "smp_input")
        assert os.path.isdir(smp_dir)
        input_files = [f for f in os.listdir(smp_dir) if f.endswith(".txt")]
        assert len(input_files) == 7

    # BMI config files
    def test_cfes_configs_exist(self):
        cfes_dir = os.path.join(self.rb.input_dir, "cfe-s_input")
        assert os.path.isdir(cfes_dir)
        files = os.listdir(cfes_dir)
        assert len(files) == 4

    def test_lasam_configs_exist(self):
        lasam_dir = os.path.join(self.rb.input_dir, "lasam_input")
        assert os.path.isdir(lasam_dir)
        files = os.listdir(lasam_dir)
        assert len(files) == 3

    def test_noah_configs_exist(self):
        noah_dir = os.path.join(self.rb.input_dir, "noah-owp-modular_input")
        assert os.path.isdir(noah_dir)
        input_files = [f for f in os.listdir(noah_dir) if f.endswith(".input")]
        assert len(input_files) == len(self.rb.catids)
