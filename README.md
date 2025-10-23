# nwm-msw-mgr - Model Setup Workflow Manager

[![Tests](https://github.com/NGWPC/nwm-msw-mgr/actions/workflows/test.yml/badge.svg)](https://github.com/NGWPC/nwm-msw-mgr/actions/workflows/test.yml)

## Description
The Model Setup Workflow Manager generates realization and configuration files for running ngen in calibration, validation, forecast, and regionalization modes. mswm can either be run from the command line or called directly from Python scripts.

## Installation

### Clone mswm

```bash
cd [NGEN_REG_ROOT]
git clone -b development --recurse-submodules https://github.com/NGWPC/nwm-msw-mgr.git
```

### Build the environment

To run the program, one would need an environment for successfully running ngen.

If you already have an environment for running ngen, you can use the same venv.

1. `source [VENV_ROOT]/env.ngen/bin/activate`
2. `cd nwm-msw-mgr`
3. `pip install .`

where `[VENV_ROOT]` is the location of your Python virtual environment.


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
To build and run nwm-msw-mgr in Docker, you need:
- Docker Engine


### Build
To build the nwm-msw-mgr continer:

```bash
docker build --tag=nwm-msw-mgr .
```


## Usage

mswm provides four primary workflows for generating ngen realization and configuration files: **calibration**, **forecast**, **default parameters**, and **regionalization**. Each can be run from the CLI or called directly from Python.

### Calibration Workflow

Generate model realization and configuration files for a calibration/validation run of ngen.

#### CLI

```bash
python -m mswm.manager build_calib /path/to/input.config
```

#### Python

```python
from mswm.manager import build_calib

build_calib(input_path="/path/to/input.config")
```

#### Arguments

- `input_path` - Path to user-generated input configuration file

---

### Forecast & Hindcast Workflow

Modify the realization and configuration files from an existing calibration run for a forecast run of ngen. If running a forecast or Hindcast through the nwm-fcst-mgr, the fcst-mgr will orchestrate these calls to the mswm.

#### CLI

```bash
python -m mswm.manager build_fcst \
    /path/to/input_forecast.config \
    /path/to/valid_best.yaml \
    my_forecast_run \
    --use_cold_start
```

#### Python

```python
from mswm.manager import build_fcst

build_fcst(
    input_path="/path/to/input_forecast.config",
    valid_yaml="/path/to/valid_best.yaml",
    fcst_run_name="my_forecast_run",
    use_cold_start=True,
    use_warm_start=False,
    use_hindcast=False,
    hind_cycle=None,
    prev_hind_cycle=None
)
```

#### Arguments
- `input_path` - Path to user-generated forecast configuration file
- `valid_best.yaml` - Path to validation yaml file from previous nwm-cal-mgr run
- `fcst_run_name` - Relative path for output folder (e.g., 'fcst_run1')
- `--use_cold_start` - (optional) Generate files for cold start period (True) or forecast period (False)
- `--use_warm_start` - (optional) Generate files for hindcasting warm start run
- `--use_hindcast` - (optional) Generate files for hindcast run
- `--hind_cycle` - (optional) Cycle interval in hours for hindcast run
- `--prev_hind_cycle` - (optional) Cycle value in hours for previous hindcast cycle

#### Example
**Cold start:**
```bash
python -m mswm.manager build_fcst input.config valid.yaml fcst_run1 --use_cold_start
```

**Forecast:**
```bash
python -m mswm.manager build_fcst input.config valid.yaml fcst_run1
```

**Warm start:**
```bash
python -m mswm.manager build_fcst input.config valid_yaml hind_run1 --use_warm_start
```

**Hindcast (cycle 0):**
```bash
python -m mswm.manager build_fcst input.config valid.yaml hind_run1 --use_hindcast --hind_cycle 0
```

**Hindcast (cycle 1, 3 hour interval):**
```bash
python -m mswm.manager build_fcst input.config valid.yaml hind_run1 --use hindcast --hind_cycle 3 --hind_cycle 0
```

---

### Regionalization Workflow

Generate model realization and configuration files for a regionalization run of ngen using grouped catchment formulations and parameters.

#### CLI
```bash
python -m mswm.manager build_region /path/to/input_realization.config
```

#### Python
```python
from mswm.manager import build_region

real_path = build_region(input_path='/path/to/input_realization.config')
```

#### Arguments
- `input_path` - Path to user-generated regionaliztion configuration file

### Required Files
Regionalization mode requires additional files in your input directory, which are referenced in the input.config file.

- **formulation_assignment.csv** - Maps formulations and parameters to regionalization groups
- **catchment_groups.csv** - Maps catchments to regionalization groups

See `/example_inputs/regionalization/` for example files.

---

### Default Parameter Workflow
Generate model realization and configuration files for a run of ngen with default catchment parameters.

#### CLI
```bash
python -m mswm.manager build_default /path/to/input.config
```

#### Python
```python
from mswm.manager import build_default

build_default(
    input_path='/path/to/input.config'
)
```

#### Arguments
- `input_path` - Path to user-generated configuration file

# nwm-msw-mgr Input Configuration File Reference
This section describes all configuration parameters in the `input.config` file used by the nwm-msw-mgr. Full example files for each run type are available in `/example_inputs/`

## General Section: `[General]`
Configuration parameters that apply to all run types except `forecast`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `basin` | string | Yes | Stream gage ID at basin outlet or VPU basin identified |
| `run_type` | string | Yes | Run type : `calibration`, `regionalization`, or `default` |
| `models` | string | Yes | Comma-separated list of models for the formulation. **Note:** t-route is automatically added if not selected; sloth is automatically added when needed. |
| `formulation` | string | Yes | User-defined formulation run name |
| `main_dir` | path | Yes | Main directory to store input, output, and other files |
| `start_period` | datetime | Default, Regionalization | Simulation start time (format: `YYYY-MM-DD HH:MM:SS`). Required for default and calibration runs; overridden by calibration time variables for calibration runs. |
| `end_period` | datetime | Default, Regionalization | Simulation end time (format: `YYYY-MM-DD HH:MM:SS`). Required for default and calibration runs; overridden by calibration time variables for calibration runs. |
| `output_precip` | boolean | No | Output precipitation from forcing files to catchment CSV files (default: `False`) |
| `output_swe` | boolean | No | Output snow water equivalent from snow module to catchment CSV files (default: `False`) |
| `output_sm` | boolean | No | Output soil moisture to catchment CSV files (default: `False`) |
| `sm_profile_depth` | string | No | Comma-separated depths in meters for soil moisture profile output (default: `0.1, 0.4, 1.0, 2.0`) |
| `sm_frac_depth` | float | No | Depth in meters for soil moisture fraction calculation (default: `0.4`) |
| `is_aet_rootzone` | boolean | No | CFE rootzone option for actual evapotranspiration only used if CFE is in the formulation (default: `False`) |

## Regionalization Section: `[Regionalization]`
Parameters required only for regionalization runs. Section does not need to be supplied for other run types.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `form_assign_file` | path | Regionalization | Path to formulation assignment CSV file mapping formulations and parameters to regionalization groups. |
| `cat_grp_file` | path | Regionalization | Path to catchment groups CSV file mapping catchments to regionalization groups. |

## Calibration Section: `[Calibration]`
Parameters required only for calibration runs. Section does not need to be supplied for other run types.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `optimization_algorithm` | string | Calibration | Optimization algorithm: `dds`, `pso`, or `gwo`. |
| `swarm_size` | integer | Calibration | Population size for PSO or GWO algorithms. |
| `c1` | float | No | PSO cognitive parameter (default: `2.0`) |
| `c2` | float | No | PSO social parameter (default: `2.0`) |
| `w` | float | No | PSO intertia weight (default: `0.7`) |
| `objective_function` | string | Calibration | Objective function for optimization: `kge`, `nse`, `nnse`, `nselog`, `corr`, `csi`, `pod`, `rmse`, `mae`, `rsr`, `far`, `pkbias`, `pkte`, `evbias`, `bpias`, `lseg_fdc`, `hseg_fdc`. |
| `start_iteration` | integer | No | Starting iteration number (default: `0`) |
| `number_iteration` | integer | Calibration | Number of iterations to run. |
| `restart` | integer | No | Restart from stopped iteration: `0` = no restart (default), `1` = restart (currently only 0 supported) |
| `calib_output_vars` | boolean | No | Write output variables during calibration iterations (default: `False`) |
| `valid_output_vars` | boolean | No | Write output variables during validation runs (default: `True`) |
| `calib_start_period` | datetime | Calibration | Calibration simulation start time (format: `YYYY-MM-DD HH:MM:SS`). |
| `calib_end_period` | datetime | Calibration | Calibration simulation end time (format: `YYYY-MM-DD HH:MM:SS`). |
| `calib_eval_start_period` | datetime | Calibration | Calibration evaluation start time, excludes warm up period (format: `YYYY-MM-DD HH:MM:SS`). |
| `calib_eval_end_period` | datetime | Calibration | Calibration evaluation end time, excludes warm up period (format: `YYYY-MM-DD HH:MM:SS`). |
| `valid_start_period` | datetime | Calibration | Validation simulation start time (format: `YYYY-MM-DD HH:MM:SS`). |
| `valid_end_period` | datetime | Calibration | Validation simulation end time (format: `YYYY-MM-DD HH:MM:SS`). |
| `valid_eval_start_period` | datetime | Calibration | Validation evaluation start time(format: `YYYY-MM-DD HH:MM:SS`). |
| `valid_eval_end_period` | datetime | Calibration | Validation evaluation end time(format: `YYYY-MM-DD HH:MM:SS`). |
| `full_eval_start_period` | datetime | Calibration | Full evluation period start (calibration + validation) (format: `YYYY-MM-DD HH:MM:SS`). |
| `full_eval_end_period` | datetime | Calibration | Full evluation period end (calibration + validation)(format: `YYYY-MM-DD HH:MM:SS`). |
| `save_plot_iter` | integer | No | Save plots at iterations: `0` = no (default), `1` = yes with iteration number in filename |
| `save_plot_iter_freq` | integer | No | Iteration interval for saving plots default: `1` |
| `streamflow_threshold` | float | No | Streamflow threshold in cms for categorical scores (optional: if not specified, categorical metrics skipped) |
| `station_name` | string | No | Streamflow station name for plot titles (optional) |
| `ngen_cerf` | boolean | No | Whether running from ngenCERF server (default: `false`) |
| `calibration_run_id` | integer | No | Calibration run ID from ngenCERF (only needed when `ngen_cerf = true`) |
| `auth_token` | string | No | Authentication token from ngenCERF (only needed when `ngen_cerf = true`) |
| `user_email` | string | No |Email address to receive run completion notification (optional) |
| `calib_parameter_file` | path | Calibration | Path to calibration parameter files. Can be: (1) folder with tab-delimited CSV files per module, (2) folder with comma-delimited CSV files per module, (3) single file with all parameters in fixed-width format. |

## Forcing Section: `[Forcing]`
Parameters for forcing engine configuration. Required for all run types, including forecast.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `forcing_provider` | string | Yes | Forcing provider: `csv` or `bmi` |
| `forcing_dir` | path | CSV provider | Directory for CSV forcing data. Required if `forcing_provider = csv`. |
| `forcing_template_dir` | path | BMI provider | Directory containing forcing engine template configuration files. Required in `forcing_provider = bmi`.|
| `root_dir` | path | BMI Proivder | Root directory for forecast files. Required if `forcing_provider = bmi`. Typically `/ngencerf/data/forecast_work` for ngencerf or `/ngen-app/data` for local runs. |
| `forcing_configuration` | string | BMI provider | Forcing engine configuration: `aorc`, `nwm`, or other forecast configuration. Required if `forcing_provider = bmi`. |
| `cycle_datetime` | datetime | No | Cycle start time for forecast (format: `YYYY-MM-DD HH:MM:SS`). Only used for forecast runs with BMI forcing. |
| `cold_start_datetime` | datetime | No | Cold start period end time (format: `YYYY-MM-DD HH:MM:SS`). Only used for forecast runs with BMI forcing. |

## DataFile Section: `[DataFile]`
Parameters for data files and library paths. Required for all run types, excluding forecast.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `hydrofab_file` | path | Yes | Path to hydrofabric geopackage file |
| `obs_dir` | path | No | Directory for streamflow observations. If blank, observations retrieved from NWIS on-the-fly during calibration/validation |
| `nwmretro_file` | path | No | Path to NWM retrospective streamflow simulation file. If blank, NWM metrics not calculated during validation runs. |
| **BMI Config Directories** | | | |
| `topoflow_bmi_dir` | path | No | Directory for TopoFlow BMI config files (auto-generated if blank) |
| `noah_owp_modular_bmi_dir` | path | No | Directory for Noah-OWP-Modular BMI config files (auto-generated if blank) |
| `snow_17_bmi_dir` | path | No | Directory for Snow-17 BMI config files (auto-generated if blank) |
| `ueb_bmi_dir` | path | No | Directory for UEB BMI config files (auto-generated if blank) |
| `pet_bmi_dir` | path | No | Directory for PET BMI config files (auto-generated if blank) |
| `smp_bmi_dir` | path | No | Directory for SMP BMI config files (auto-generated if blank) |
| `sft_bmi_dir` | path | No | Directory for SFT BMI config files (auto-generated if blank) |
| `cfe_s_bmi_dir` | path | No | Directory for CFE-S BMI config files (auto-generated if blank) |
| `cfe_x_bmi_dir` | path | No | Directory for CFE-X BMI config files (auto-generated if blank) |
| `topmodel_bmi_dir` | path | No | Directory for TOPMODEL BMI config files (auto-generated if blank) |
| `sac_sma_bmi_dir` | path | No | Directory for SAC-SMA BMI config files (auto-generated if blank) |
| `lasam_bmi_dir` | path | No | Directory for LASAM BMI config files (auto-generated if blank) |
| `lstm_bmi_dir` | path | No | Directory for LSTM BMI config files (auto-generated if blank) |
| `t_route__bmi_dir` | path | No | Directory for T-Route BMI config files (auto-generated if blank) |
| **Parameter Directories** | | | |
| `noah_parameter_dir` | path | If using Noah | Directory for Noah-OWP-Modular parameter files. |
| `ueb_parameter_dir` | path | If using UEB | Directory for UEB parameter files. |
| `lasam_parameter_dir` | path | If using LASAM | Directory for LASAM parameter files. |
| `lstm_parameter_dir` | path | If using LSTM | Directory for LSTM parameter files. |
| `sac_parameter_dir` | path | If using SAC-SMA | Directory for SAC-SMA parameter files. |
| `snow_17_parameter_dir` | path | If using SNOW-17 | Directory for SNOW-17 parameter files. |
| **Executables and Libraries** | | | |
| `ngen_exe_file` | path | Yes | Path to compiled ngen executable |
| `sloth_lib` | path | If using sloth | Path to sloth library |
| `cfe_lib` | path | If using CFE | Path to CFE library |
| `lasam_lib` | path | If using LASAM | Path to LASAM library |
| `noah_owp_modular_lib` | path | If using Noah | Path to Noah-OWP-Modular library |
| `pet_lib` | path | If using PET | Path to PET library |
| `sac_sma_lib` | path | If using SAC-SMA | Path to SAC-SMA library |
| `sft_lib` | path | If using SFT | Path to SFT library |
| `smp_lib` | path | If using SMP | Path to SMP library |
| `snow-17_lib` | path | If using Noah | Path to SNOW-17 library |
| `topmodel_lib` | path | If using TOPMODEL | Path to TOPMODEL library |
| `ueb_lib` | path | If using UEB | Path to UEB library |

## Parallel Section: `[Parallel]`
Parameters for parallel processing configuration.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `parallel_ngen_exe` | path | No | Path to parallel executable (only used if `nprocs > 1`) |
| `partition_generator_exe` | path | No | Path to partition generator executable (only used if `nprocs > 1`) |
| `nprocs` | integer | No | Number of processors for parallel execution (default: `1` = serial execution) |

---

## Configuration Notes

### Run Type Dependencies
- **Calibration runs** require all parameters in the General, Calibration, Forcing, and DataFile sections
- **Regionalization runs** require parameters in the General, Calibration, Forcing, Regionalization, DataFile section
- **Default runs** require all parameters in the General, Forcing, and DataFile sections
- Parameters for unused run types can be left blank

### Datetime Format
All datetime parameters use the format: `YYYY-MM-DD HH:MM:SS` (UTC)

### Path Expansion
Paths with `~` are expanded to the user's home directory. Example: 
- `~/ngwpc/run_ngen` -> `/home/username/ngwpc/run_ngen`

### Available Modules
**Glacier/Snow:** noah-owp-modular, snow-17, ueb, topoflow-glacier
**Evapotranspiration:** pet, noah-owp-modular
**Soil Modular:** smp, sft (only paired with cfe-s, cfe-x, lasam, or topmodel)
**Rainfall-Runoff:** cfe-s, cfe-x, topmodel, sac-sma, lasam
**Machine Learning:** lstm (only paired with t-route)
**Routing:** t-route (always required)
**Utility:** sloth (automatically added if cfe-s, cfe-x, or lasam selected)

### Objective Function
Available optimization metrics for calibration:
- `kge` - Kling-Gupta Efficiency
- `nse` - Nash-Sutcliffe Efficiency
- `nnse` - Normalized NSE
- `nselog` - NSE of log-transformed flows
- `corr` - Correlation
- `csi` - Critical Success Index
- `pod` - Probability of Detection
- `rmse` - Root Mean Square Error
- `mae` - Mean Absolute Error
- `rsr` - Ratio of RMSE to Standard Deviation
- `far` - False Alarm Rate
- `pkbias` - Peak Bias
- `pkte` - Peak Timing Error
- `evbias` - Extreme Value Bias
- `pbias` - Percent Bias
- `lseg_fdc` - Low Segment Flow Duration Curve
- `hseg_fdc` - High Segment Flow Duration Curve

### Optimization Algorithm
- `dds` - Dynamically Dimensioned Search
- `pso` - Particle Swarm Optimization
- `gwo` - Grey Wolf Optimizer

### Forcing Providers
- `csv` - Use catchment-specific CSV files for forcing data
- `bmi` - Use BMI-based forcing engine

## Input Directory Structure

For calibration, the Model Setup Workflow Manager stores run files under the structure `/objfunc_optalg/my_run_name/basin/` (ex: `/kge_dds/calib_1/01123000/`).
For regionalization, run files are stored in `/regionalization/my_run_name/basin/` (`ex: `/regionalization/region_1/vpu01`)

```bash
├── /[objfunc]_[optalg]/[my_run_name]/[basin]/              # Top level file structure, dependent on run type
│   ├── Input/
│   │   ├── cfe-s_input/
│   │   │   ├── [cat_id]_bmi_config_cfe.txt            # CFE-S parameter file per catchment 
│   │   │   └── ...
│   │   ├── noah-owp-modular_input/
│   │   │   ├── GENPARM.TBL                            # Noah-OWP-Modular general parameter static file
│   │   │   ├── MPTABLE.TBL                            # Noah-OWP-Modular vegetation parameter static file
│   │   │   ├── SOILPARM.TBL                           # Noah-OWP-Modular soil parameter static file
│   │   │   ├── [cat_id]_calib.input                   # Noah-OWP-Modular parameter file per catchment (calibration)
│   │   │   ├── [cat_id]_valid.input                   # Noah-OWP-Modular parameter file per catchment (validation)
│   │   │   └── ...
│   │   ├── forcing/                                   
│   │   │   └── [cat_id].csv                           # Symlinked forcing csv files (if csv forcing provider used)
│   │   ├── forcing_config/
│   │   │   └── *_config.yaml                          # BMI forcing engine provider config file (if bmi forcing provider used)
│   │   ├── [basin]_config_calib.yaml                  # Calibration configuration file (calibration only)  
│   │   ├── [basin]_crosswalk.json                     # Gage-to-catchment mapping (calibration only)  
│   │   ├── [basin]_hourly_discharge.csv               # Streamflow observations at calibration gage (calibration only)
│   │   ├── [basin]_troute_config_calib.yaml           # T-route configuration file (naming based on run type)
│   │   ├── [basin]_troute_config_valid_control.yaml   # T-route configuration file (secondary validation files for calibration only)
│   │   ├── [basin]_troute_config_valid_best.yaml      # T-route configuration file (secondary validation files for calibration only)
│   │   ├── [basin].gpkg                               # Hydrofabric geopackage
│   │   ├── ngen                                       # Symlinked ngen executable
│   │   ├── libcfebmi.so                               # Symlinked CFE library file
│   │   ├── libslothmodel.so                           # Symlinked sloth library file
│   │   └── libsurfacebmi.so                           # Symlinked noah-owp-modular library file
│   ├── [basin]_realization_config_bmi_*.json          # Realization file used to orchestrate run
│   ├── logs/
│   │   └── mswm.log                                   # MSWM log file
│   └── Output/                                        # Output folder created by the nwm-cal-mgr during a calibration run
```

### Forecast Directory Structure
When generating run files for a forecast (using the nwm-fcst-mgr), input files are created in the `/Output/` folder of a completed calibration run.

```bash
├── /[Output]/                                         # Top level forecast file structure, within calibration run /Output/
│   ├── Calibration_Run/                               # Output run folder from previous calibration run
│   ├── Validation_Run/                                # Output run folder from previous validation run
│   ├── Model_State_Run/  
│   │   └── Cold_Start_Run/                            # Cold Start run providing start up states for forecast (if --use_cold_start)
│   │       └── [fcst_run_name]/
│   │           ├── Input/
│   │           │    ├── [module]_input/               # Module parameter files if modifications required from calibration
│   │           │    └── forcing_config/               # BMI forcing engine provider config file (if bmi forcing provider used)
│   │           ├── logs/
│   │           └── Output/                            # Output run folder from nwm-fcst-mgr execution
│   └── Forecast_Run/
│       └── [fcst_run_name]/
│   │       ├── Input/
│   │       │    ├── [module]_input/                   # Module parameter files if modifications required from calibration
│   │       │    └── forcing_config/                   # BMI forcing engine provider config file (if bmi forcing provider used)
│   │       ├── logs/
│   │       └── Output/                                # Output run folder from nwm-fcst-mgr execution
```

### Hindcast Directory Structure
When generating run files for a hindcast (using the nwm-fcst-mgr), multiple sets of input files for each warm start and hindcast iterationare created in the `/Output/` folder of a completed calibration run.

```bash
├── /[Output]/                                         # Top level forecast file structure, within calibration run /Output/
│   ├── Calibration_Run/                               # Output run folder from previous calibration run
│   ├── Validation_Run/                                # Output run folder from previous validation run
│   ├── Model_State_Run/  
│   │   ├── Cold_Start_Run/                            # Cold Start run providing start up states to first hindcast cycle (if --use_cold_start)
│   │   │   └── [hind_run_name]/
│   │   │       ├── Input/
│   │   │       ├── logs/
│   │   │       └── Output/                            
│   │   └── Warm_Start_Run/
│   │       ├── [hind_run_name]_3/                     # Warm Start run providing start up states to hindcast cycle at 3 hours
│   │       │   ├── Input/
│   │       │   ├── logs/
│   │       │   └── Output/
│   │       └── [hind_run_name]_6/                     # Warm Start run providing start up states to hindcast cycle at 6 hours
│   │           ├── Input/
│   │           ├── logs/
│   │           └── Output/
│   └── Hindcast_Run
│       ├── [hind_run_name]_0/                         # Hindcast run at 0 hours, using saved states from Cold Start run
│       │   ├── Input/
│       │   ├── logs/
│       │   └── Output/     
│       ├── [hind_run_name]_3/                         # Hindcast run at 3 hours, using saved states from Warm Start run at 3 hours
│       │   ├── Input/
│       │   ├── logs/
│       │   └── Output/  
│       └── [hind_run_name]_6/                         # Hindcast run at 6 hours, using saved states from Warm Start run at 6 hours
│           ├── Input/
│           ├── logs/
│           └── Output/                         
```