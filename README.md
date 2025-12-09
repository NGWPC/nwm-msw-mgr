# nwm-msw-mgr - Model Setup Workflow Manager

## Description
The Model Setup Workflow Manager generates realization and configuration files for running ngen in calibration, validation, forecast, and regionalization modes. mswm can either be run from the command line or called directly by ngen model runs.

## Installation

### Clone mswm

cd [NGEN_REG_ROOT]

git clone -b development --recurse-submodules https://github.com/NGWPC/nwm-msw-mgr.git

### Build the environment

To run the program, one would need an environment for successfully running ngen.

If you already have an environment for running ngen, you can use the same venv.

1. source [VENV_ROOT]/env.ngen/bin/activate

Once the venv is activated, run:

1. cd nwm-msw-mgr
2. pip install .

## Usage

The two primary functionalities of mswm, generating realization files to run ngen (`build_inputs.py`) and editing validation realization files during ngen-cal iterations (`edit_configs.py`), are orchestrated by `manager.py`. Users will most directly use mswm from the command line to create realization files for default parameters, calibration, forecasting, and regionalization runs of ngen.

### Calibration
The mswm.manager script in calibration mode takes two command line arguments:
1. Command for calibration mode (build_calib)
2. Path to the user generated input.config file

To generate the model realization file and config_calib yaml file for a calibration run of ngen:
1. python -m mswm.manager build_calib path/to/input.config

Within Python scripts, calibration input files can be generated calling the build_calib realization function:
1. from mswm.manager import build_calib
2. build_calib(input_path="path/to/input.config")

### Forecast
The forecast mode of nwm-msw-mgr modifies files from an existing calibration run using nwm-cal-mgr for a forecast run of ngen.

The mswm.manager script in forecast mode takes five command line arguments:
1. Command for forecast mode (build_fcst)
2. Path to a user generated input_forecast.config file, which describes the desired forecast cycle and configuration
3. Path to the config validation yaml file from a prior run of nwm-cal-mgr
4. Relative path to the folder to be created for storing inputs/outputs from running ngen in nwm-fcst-mgr (ex: 'fcst_run1')
5. Boolean flag to generate realization and bmi config files for a cold start period (True) or for the primary forecast period (False)

To generate the model realization file and BMI config files for a forecast run of ngen from an existing calibration run:
1. python -m mswm.manager build_fcst path/to/input_forecast.config path/to/Output/Validation_Run/01123000_config_valid_best.yaml fcst_run1 --use_cold_start

Within Python scripts, forecast input files can be generated calling the build_fcst realization function:
1. from mswm.manager import build_fcst
2. build_fcst(input_path="path/to/input_forecast.config, valid_yaml="path/to/valid_best_yaml", fcst_run_name="fcst_run1", use_cold_start=False)

### Default Parameter Run
The mswm.manager script in default parameter mode takes three command line arguments:
1. Command for default parameter mode (build_default)
2. Path to the user generated input.config file
3. Optional cold start flag if user requests a forecast

To generate the model realization file and BMI config files for a run of ngen with default catchment parameters using either historical or forecast forcings:
1. python -m mswm.manager build_default path/to/input_default.config --use_cold_start

Within Python scripts, default parameter input files can be generated calling the build_default realization function:
1. from mswm.manager import build_default
2. build_default(input_path="path/to/input.config", use_cold_start=False)

### Regionalization
To generate the model realization file and BMI config files for a regionalization run of ngen:
1. python -m mswm.manager build_region path/to/input_regionalization.config

The mswm.manager script in regionalization mode takes two command line arguments:
1. Command for calibration mode (build_region)
2. Path to the user generated input_regionalization.config file

Note that the input.config file used for regionalization differs from that of the one used for calibration. Regionalization also requires formulation_assignment.csv and catchment_groups.csv files, which provide formulations, parameter values, and catchment assignments for each regionalization group (see example files in /example_inputs/regionalization/).

Within Python scripts, regionalization input files can be generated calling the build_region realization function:
1. from mswm.build_inputs import RealizationBuilder
2. build_region(input_path="path/to/input_regionalization.config")

### Topoflow-Glacier Validation
To validate whether catchments in a given basin have sufficient glacier coverage to apply Topoflow-Glacier, the validate_topoflow function can be called:
1. python -m mswm.manager validate_topoflow 01123000 conus False

The mswm.manager script in topoflow validation mode takes two command line arguments:
1. Command for topoflow validation mode (validate_topoflow)
2. Basin id
3. Domain id (conus, prvi, ak, hi, gl)
4. NgenCERF Flag (True = running inside NgenCERF, False = running outside NgenCERF)

The validate_topoflow function will return a JSON with a status of True if there are catchments in the basin where Topoflow-Glacier can be applied (>=50% glacier coverage).
The validate_topoflow function will return a JSON with a status of False if there are no catchments in the basin where Topoflow-Glacier can be applied.

Within Python scripts, regionalization input files can be generated calling the build_region realization function:
1. from mswm.build_inputs import validate_topoflow
2. validate_topoflow(basin_id='01123000', domain='conus', ngen_cerf=False)

## Docker container

### Requirements


### Build


### Running



## Contributing
State if you are open to contributions and what your requirements are for accepting them.

For people who want to make changes to your project, it's helpful to have some documentation on how to get started. Perhaps there is a script that they should run or some environment variables that they need to set. Make these steps explicit. These instructions could also be useful to your future self.

You can also document commands to lint the code or run tests. These steps help to ensure high code quality and reduce the likelihood that the changes inadvertently break something. Having instructions for running tests is especially helpful if it requires external setup, such as starting a Selenium server for testing in a browser.

## Authors and acknowledgment


## License
For open source projects, say how it is licensed.

## Project status
If you have run out of energy or time for your project, put a note at the top of the README saying that development has slowed down or stopped completely. Someone may choose to fork your project or volunteer to step in as a maintainer or owner, allowing your project to keep going. You can also make an explicit request for maintainers.
