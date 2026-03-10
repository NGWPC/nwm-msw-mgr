"""
Fixtures for msw-mgr end-to-end tests
"""

import os
import pytest
from pathlib import Path
import mswm

from mswm.utils.input_configuration import (
    InputConfig,
    GeneralConfig,
    ModulePropertiesConfig,
    ForcingConfig,
    DataFileConfig,
    CalibConfig,
    RegionConfig,
    ParallelConfig,
)

# Set paths to test data
test_data_dir = Path(__file__).parent / "data"
test_gpkg = test_data_dir / "hydrofabric" / "hydrofabric.gpkg"
test_calib_params = test_data_dir / "calib_params"
test_region_dir = test_data_dir / "regionalization"
test_forcing_configs = test_data_dir / "forcing_configs"


@pytest.fixture
def tmp_work_dir(tmp_path):
    """Temporary directory that serves as main_dir for test run"""
    return str(tmp_path)


@pytest.fixture
def dummy_files(tmp_work_dir):
    """"Create dummy library, ngen, and partitionGenerator files expected by msw-mgr"""
    libs = {
        "libsurfacebmi.so": "noah_owp_modular_lib",
        "libcfebmi.so": "cfe_lib",
        "libslothmodel.so": "sloth_lib",
    }

    # Create dummy libraries
    for name in libs:
        Path(tmp_work_dir, name).touch()

    # Create dummy ngen executable
    Path(tmp_work_dir, "ngen").touch()

    # Create partition generator file
    Path(tmp_work_dir, "partitionGenerator")

    return libs


def _make_calib_input_config(tmp_work_dir):
    """Build an InputConfig pydantic object for a calibration run with noah-owp-modular and cfe-s"""
    # Get package root for parameter files
    pkg_root = Path(mswm.__file__).parent
    noah_parameter_dir = str(pkg_root / "module_parameter_files" / "noah-owp-modular")

    general = GeneralConfig(
        basin="01123000",
        run_type="calibration",
        domain="conus",
        models="noah-owp-modular, cfe-s",
        formulation="noah_cfes",
        main_dir=tmp_work_dir,
        output_precip=True,
        output_swe=True,
        output_sm=True,
    )
    module_properties = ModulePropertiesConfig(
        cfe_aet_rootzone=1
    )
    forcing = ForcingConfig(
        forcing_provider="bmi",
        forcing_template_dir=str(test_forcing_configs),
        root_dir=tmp_work_dir,
        forcing_configuration="aorc",
    )
    datafile = DataFileConfig(
        hydrofab_file=str(test_gpkg),
        ngen_exe_file=os.path.join(tmp_work_dir, "ngen"),
        noah_owp_modular_lib=os.path.join(tmp_work_dir, "libsurfacebmi.so"),
        cfe_lib=os.path.join(tmp_work_dir, "libcfebmi.so"),
        sloth_lib=os.path.join(tmp_work_dir, "libslothmodel.so"),
        noah_parameter_dir=noah_parameter_dir
    )
    calibration = CalibConfig(
        optimization_algorithm="dds",
        objective_function="kge",
        calib_output_vars=True,
        valid_output_vars=True,
        start_iteration=0,
        number_iteration=2,
        restart=0,
        calib_start_period="2015-10-01 00:00:00",
        calib_end_period="2017-09-30 23:00:00",
        calib_eval_start_period="2016-10-01 00:00:00",
        calib_eval_end_period="2017-09-30 23:00:00",
        valid_start_period="2014-10-01 00:00:00",
        valid_end_period="2017-09-30 23:00:00",
        valid_eval_start_period="2015-10-01 00:00:00",
        valid_eval_end_period="2016-09-30 23:00:00",
        full_eval_start_period="2015-10-01 00:00:00",
        full_eval_end_period="2017-09-30 23:00:00",
        save_output_iter=0,
        save_plot_iter=0,
        save_plot_iter_freq=1,
        streamflow_threshold=3.88,
        station_name="Test Gauge",
        ngen_cerf=False,
        calib_parameter_file=str(test_calib_params)
    )
    parallel = ParallelConfig(
        parallel_ngen_exe=os.path.join(tmp_work_dir, "ngen"),
        partition_generator_exe=os.path.join(tmp_work_dir, "partitionGenerator"),
        nprocs=2,
    )
    return InputConfig(
        General=general,
        ModuleProperties=module_properties,
        Forcing=forcing,
        DataFile=datafile,
        Calibration=calibration,
        Parallel=parallel,
    )


def _make_region_input_config(tmp_work_dir):
    """Build an InputConfig pydantic object for a regionalization run"""
    # Get package root for parameter files
    pkg_root = Path(mswm.__file__).parent
    noah_parameter_dir = str(pkg_root / "module_parameter_files" / "noah-owp-modular")

    general = GeneralConfig(
        basin="01123000",
        run_type="regionalization",
        domain="conus",
        formulation="region",
        main_dir=tmp_work_dir,
        start_period="2015-10-01 00:00:00",
        end_period="2016-09-30 23:00:00",
        output_precip=True,
        output_swe=True,
        output_sm=True,
    )
    forcing = ForcingConfig(
        forcing_provider="bmi",
        forcing_template_dir=str(test_forcing_configs),
        root_dir=tmp_work_dir,
        forcing_configuration="aorc",
    )
    datafile = DataFileConfig(
        hydrofab_file=str(test_gpkg),
        ngen_exe_file=os.path.join(tmp_work_dir, "ngen"),
        noah_owp_modular_lib=os.path.join(tmp_work_dir, "libsurfacebmi.so"),
        cfe_lib=os.path.join(tmp_work_dir, "libcfebmi.so"),
        sloth_lib=os.path.join(tmp_work_dir, "libslothmodel.so"),
        noah_parameter_dir=noah_parameter_dir
    )
    region = RegionConfig(
        form_assign_file=os.path.join(test_region_dir, "formulation_assignment.csv"),
        cat_grp_file=os.path.join(test_region_dir, "catchment_groups.csv"),
    )
    parallel = ParallelConfig(
        parallel_ngen_exe=os.path.join(tmp_work_dir, "ngen"),
        partition_generator_exe=os.path.join(tmp_work_dir, "partitionGenerator"),
        nprocs=2,
    )
    return InputConfig(
        General=general,
        Forcing=forcing,
        DataFile=datafile,
        Regionalization=region,
        Parallel=parallel,
    )


def _make_fcst_input_config(tmp_work_dir):
    """Build an InputConfig pydantic object for a forecast run"""
    forcing = ForcingConfig(
        forcing_provider="bmi",
        forcing_template_dir=str(test_forcing_configs),
        root_dir=tmp_work_dir,
        forcing_configuration="short_range",
        cycle_datetime="2025-09-01 00:00:00",
        cold_start_datetime="2025-08-01 00:00:00",
    )
    return InputConfig(
        Forcing=forcing,
    )


def _make_lagged_ens_input_config(tmp_work_dir):
    """Build an InputConfig pydantic object for a lagged ensemble run"""
    forcing = ForcingConfig(
        forcing_provider="bmi",
        forcing_template_dir=str(test_forcing_configs),
        root_dir=tmp_work_dir,
        forcing_configuration="medium_range",
        cycle_datetime="2025-09-01 00:00:00",
        cold_start_datetime="2025-08-01 00:00:00",
    )
    return InputConfig(
        Forcing=forcing,
    )
