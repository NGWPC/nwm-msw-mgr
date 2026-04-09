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


## Docker container

### Requirements
To build and run nwm-msw-mgr in Docker, you need:
- Docker Engine


### Build
To build the nwm-msw-mgr continer:

```bash
docker build --tag=nwm-msw-mgr .
```

## Testing
To run nwm-msw-mgr integration tests:
```bash
pip install -e ".[test]"
pytest tests/ -v
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

### Forecast, Hindcast, & Lagged Ensemble Workflow

Modify the realization and configuration files from an existing calibration run for a forecast run of ngen. If executing a Hindcast or Lagged Ensemble run through the nwm-fcst-mgr, the fcst-mgr will orchestrate these calls to the mswm.

Medium range lagged ensembles cycles are run with with forcing inputs lagged at 6 hour intervals, with open and closed loop AnA start up states. Members 1 and no_da have no forcing time lags, while Members 2-6 have sequential 6 hour time lags. All lagged ensemble ngen runs are orchestrated to begin at the same time and run for either 10 days (Members 1 and no_da) or 8.5 days (Members 2-6). The no_da member should be initialized with a state load from an open loop cycle. Members 1-6 should be initialized with
a state load from a closed loop cycle. The lagged ensemble workflow can only be executed with a medium range configuration.

#### CLI

```bash
python -m mswm.manager build_fcst \
    /path/to/input_forecast.config \
    /path/to/valid_best.yaml \
    my_forecast_run \
    --use_cold_start \
    --save_state \
    --load_state_from /path/to/saved_state/
```

#### Python

```python
from mswm.manager import build_fcst

build_fcst(
    input_path="/path/to/input_forecast.config",
    valid_yaml="/path/to/valid_best.yaml",
    fcst_run_name="my_forecast_run",
    use_cold_start=False,
    use_warm_start=False,
    use_hindcast=False,
    use_lagged_ens=False,
    hind_cycle=None,
    prev_hind_cycle=None
    lagged_ens_mem=None,
    forcing_lag=None,
    save_state=True,
    load_state_from="/path/to/saved_state/"
)
```

#### Arguments
- `input_path` - Path to user-generated forecast configuration file
- `valid_best.yaml` - Path to validation yaml file from previous nwm-cal-mgr run
- `fcst_run_name` - Relative path for output folder (e.g., 'fcst_run1')
- `--use_cold_start` - (optional) Generate files for cold start period (True) or forecast period (False)
- `--use_warm_start` - (optional) Generate files for hindcasting warm start run
- `--use_hindcast` - (optional) Generate files for hindcast run
- `--use_lagged_ens` - (optional) Generate files for lagged ensemble run
- `--hind_cycle` - (optional) Cycle interval in hours for hindcast run
- `--prev_hind_cycle` - (optional) Cycle value in hours for previous hindcast cycle
- `--lagged_ens_mem` - (optional) Name of medium range lagged ensemble member (mem1-mem6, no_da)
- `--forcing_lag` - (optional) Number of hours lagged ensemble forcing valid time is lagged from start of ngen run
- `--save_state` - (optional) Save model state files at the end of a run (typically a cold start)
- `--load_save_state` - (optional) Path to directory containing model states to load at beginning of run (typically a forecast run)

#### Example:
**Cold start:**
```bash
python -m mswm.manager build_fcst input.config valid.yaml fcst_run1 --use_cold_start --save_state
```

**Forecast:**
```bash
python -m mswm.manager build_fcst input.config valid.yaml fcst_run1 --load_state_from /path/to/saved_state/
```

**Warm start:**
```bash
python -m mswm.manager build_fcst input.config valid_yaml hind_run1 --use_warm_start --save_state
```

**Hindcast (cycle 0):**
```bash
python -m mswm.manager build_fcst input.config valid.yaml hind_run1 --use_hindcast --hind_cycle 0 --load_state_from /path/to/saved_state/
```

**Hindcast (cycle 1, 3 hour interval):**
```bash
python -m mswm.manager build_fcst input.config valid.yaml hind_run1 --use hindcast --hind_cycle 3 --hind_cycle 0 --load_state_from /path/to/saved_state/
```

**Lagged Ensemble (no da member):**
```bash
python -m mswm.manager build_fcst input.config valid.yaml lagged_ens_no_da--use_lagged_ens --lagged_ens_mem no_da --load_state_from /path/to/open_loop_saved_state/
```

**Lagged Ensemble (member 1):**
```bash
python -m mswm.manager build_fcst input.config valid.yaml lagged_ens_mem1--use_lagged_ens --lagged_ens_mem mem1 --load_state_from /path/to/closed_loop_saved_state/
```

#### Lagged Ensemble Time Handling:
Each lagged ensemble member uses forcing data from different lagged forecast cycle times, offset by a member-specific lag time. Members 1 to 6 have lag times of 0, 6, 12, 18, 24, and 30 hours respectively. The no DA member uses the same time handling as Member 1, but loads from a different saved state state during operational use. Member 1 is a 10 day medium range forecast that uses forcing inputs that are valid at the user-supplied cycle datetime with no time lag. Members 2-6 are each 8.5 day ngen runs that begin at the same time as Member 1, but use forcing inputs from sequentially older cycles. The 6 hours difference in RefcstBDateProc values in the Forcing Engine configuration templates across members describes which past cycle each member is using. The ForecastInputHorizon values in the Forcing Engine configuration templates describe the time in hours from the RefcstBDateProc to the end of each members ngen run. The time handling to align the ngen run times is handled by the nwm-msw-mgr. 

When a user requests lagged ensemble runs at 2015-10-03 00:00:
 
Member 1: 10 day forecast beginning at 2015-10-02 00:00, using 10-03 00z forcing (14400 hrs)
Member 2: 8.5 day forecast beginning at 2015-10-02 00:00, using 10-02 18z forcing (12600 hrs)
Member 3: 8.5 day forecast beginning at 2015-10-02 00:00, using 10-02 12z forcing (12960 hrs)
Member 4: 8.5 day forecast beginning at 2015-10-02 00:00, using 10-02 06z forcing (13320 hrs)
Member 5: 8.5 day forecast beginning at 2015-10-02 00:00, using 10-02 00z forcing (13680 hrs)
Member 6: 8.5 day forecast beginning at 2015-10-02 00:00, using 10-01 18z forcing (14040 hrs)

---

### Regionalization Workflow

Generate model realization and configuration files for a regionalization run of ngen using grouped catchment formulations and parameters.
The default parameter workflow can also be used to set up cold start, forecast, and hindcast runs.

#### CLI
**Regionalization run:**
```bash
python -m mswm.manager build_region /path/to/input_realization.config
```

**Cold start with state save:**
```bash
python -m mswm.manager build_region /path/to/input_realization.config --use_cold_start --save_state
```

**Forecast with state load and checkpointing:**
```bash
python -m mswm.manager build_region /path/to/input_realization.config --load_state_From /path/to/state_saving/ --checkpoint_interval 100
```

#### Python
```python
from mswm.manager import build_region

real_path = build_region(
    input_path='/path/to/input_realization.config',
    use_cold_start=False,
    load_state_from=None,
    save_state=False,
    checkpoint_interval=None
)
```

#### Arguments
- `input_path` - Path to user-generated regionaliztion configuration file
- `--use_cold_start` - (optional) Generate files for a cold start period (default: `False`)
- `--load_state_from` - (optional) Path to directory containig model states to load at beginning of run
- `--save_state` - (optional) Save model state files at the end of a run (default: `False`)
-  `--checkpoint_interval` - (optional) Checkpointing interval in integer number of timesteps (checkpointing disabled if not provided)

### Required Files
Regionalization mode requires additional files in your input directory, which are referenced in the input.config file.

- **formulation_assignment.csv** - Maps formulations and parameters to regionalization groups
- **catchment_groups.csv** - Maps catchments to regionalization groups

See `/example_inputs/regionalization/` for example files.

---

### Default Parameter Workflow
Generate model realization and configuration files for a run of ngen with default catchment parameters.
The default parameter workflow can also be used to set up cold start, forecast, and hindcast runs.

#### CLI
** Default run:**
```bash
python -m mswm.manager build_default /path/to/input.config
```

** Cold start with state save:**
```bash
python -m mswm.manager build_default /path/to/input.config --use_cold_start --save_state
```

** Forecast with state load and checkpointing:**
```bash
python -m mswm.manager build_default /path/to/input.config --load_state_from /path/to/state_saving/ --checkpoint_interval 10
```

#### Python
```python
from mswm.manager import build_default

build_default(
    input_path='/path/to/input.config',
    use_cold_start=False,
    load_state_from=None,
    save_state=False,
    checkpoint_interval=None
)
```

#### Arguments
- `input_path` - Path to user-generated configuration file
- `--use_cold_start` - (optional) Generate files for a cold start period (default: `False`)
- `--load_state_from` - (optional) Path to directory containig model states to load at beginning of run
- `--save_state` - (optional) Save model state files at the end of a run (default: `False`)
-  `--checkpoint_interval` - (optional) Checkpointing interval in integer number of timesteps (checkpointing disabled if not provided)

---

### Checkpoint Restart Workflow
Copy an existing run folder to a new path and configure it to resume form a saved checkpoint state.
This is used when a run was interrupted mid-execution and saved checkpoint states are available, allowing the run to continue from the last checkpoint.

#### CLI
```bash
python -m mswm.utils.checkpoint_restart \
    /path/to/existing/run/ \
    /path/to/new/run/ \
    /path/to/checkpoint/state/
```

#### Python
```python
from mswm.utils.checkpoint_restart import checkpoint_restart

checkpoint_restart(
    src_path="/path/to/existing/run",
    dst_path="/path/to/new/run",
    checkpoint_state_path="/path/to/checkpoint/folder/"
)
```
#### Arguments
- `src_path` - Path to existing run folder to copy
- `dst_path` - Path to the destination run folder
- `checkpoint_state_path` - Path to the /checkpoint/ state folder to load for run restart (Note: this should point to the root checkpoint folder, not the specific checkpoint iteration subfolder)


#### Example
```bash
python -m mswm.utils.checkpoint_restart \
    /run_ngen/default/default_fcst/01123000/ \
    /run_ngen/default/default_fcst_restart/01123000/ \
    /run_ngen/default/default_fcst/01123000/checkpoint/
```

#### Notes
- The existing run folder is copied to the destination path before any modifications are made
- Log files, the `/Output/` folder, `/state_save/` folder, and `/forcing_config/` folder are excluded from the copy
- The `checkpoint_state_path` input should point to the root `/checkpoint/` folder in the run directory, as Ngen automatically uses the most recent checkpoint iteration from within that folder
- Any existing checkpoint load configuration in the realization file is replaced by the new one when checkpoint_restart is called
- Checkpoint states are generated during a run when `--checkpoint_interval` is specified in `build_default` or `build_region`

---

### Update Forecast Run Workflow
Copy an existing default or regionalization forecast run to a new run folder and update the forcing engine configuration, realization, and t-route config files based on a new forecast input.config file.
This workflow is intended for operational forecast uses where an existing forecast is re-used with updated forcing inputs. This workflow is not intended to update forecast runs based off of an existing validation run.

#### CLI
```bash
python -m mswm.manager update_fcst \
    /path/to/input.config \
    /path/to/existing/run/ \
    /path/to/new/run/
```

#### Python
```python
from mswm.manager import update_fcst_run

update_fcst_run(
    input_path="/path/to/input.config",
    src_run_path="/path/to/existing/run/",
    dst_run_path="/path/to/new/run/"
)
```

#### Arguments
- `input_path` - Path to input configuration file containing an updated `[Forcing]` section
- `src_run_path` - Path to the existing default or regionalization run folder (e.g., `/run_ngen/regionalization/reg_fcst/01123000/`)
- `src_run_path` - Path to the destination run folder (e.g., `/run_ngen/regionalization/new_reg_fcst/01123000/`)

---

### Topoflow-Glacier Validation
To validate whether catchments in a given basin have sufficient glacier coverage to apply Topoflow-Glacier, the validate_topoflow function can be called.
The validate_topoflow function will return a JSON with a status of True if there are catchments in the basin where Topoflow-Glacier can be applied (>=50% glacier coverage).
The validate_topoflow function will return a JSON with a status of False if there are no catchments in the basin where Topoflow-Glacier can be applied.

#### CLI
```bash
python -m mswm.manager validate_topoflow \
    01123000 \
    conus \
    False
```

#### Python
```python
from mswm.build_inputs import validate_topoflow

validate_topoflow(basin_id='01123000', domain='conus', ngen_cerf=False)
```

#### Arguments
- `basin_id` - String identifier of the basin
- `domain` - String identifier of the region (conus, prvi, ak, hi, gl)
- `ngen_cerf` - Boolean flag indicating the runtime environment

---

---

---

# nwm-msw-mgr Input Configuration File Reference
This section describes all configuration parameters in the `input.config` file used by the nwm-msw-mgr. Full example files for each run type are available in `/example_inputs/`

## General Section: `[General]`
Configuration parameters that apply to all run types except `forecast`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `basin` | string | Yes | Stream gage ID at basin outlet or VPU basin identified |
| `subset_type` | string | Yes | Type of basin subset: `gage` or `vpu` |
| `domain` | string | Yes | Region of requested basin: `conus`, `hi`, `ak`, `prvi`, or `gl` |
| `environment` | string | Yes | Type of run environment: `test` or `oe` |
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

## Module Properties Section: `[ModuleProperties]`
Configuration parameters that only apply to specific modules.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `is_aet_rootzone` | boolean | No | CFE rootzone option for actual evapotranspiration only used if CFE is in the formulation (default: `False`) |
| `pet_method` | int | No | Integer (1-5) used to specify the PET method to be used |

## Regionalization Section: `[Regionalization]`
Parameters required only for regionalization runs. Section does not need to be supplied for other run types.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `form_assign_file` | path | Regionalization | Path to formulation assignment CSV file mapping formulations and parameters to regionalization groups. |
| `cat_grp_file` | path | Regionalization | Path to catchment groups CSV file mapping catchments to regionalization groups. |

## Calibration Section: `[Calibration]`
Parameters required only for calibration runs. Section does not need to be supplied for other run types.

| Parameter                 | Type | Required | Description                                                                                                                                                                                                       |
|---------------------------|------|----------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `optimization_algorithm`  | string | Calibration | Optimization algorithm: `dds`, `pso`, or `gwo`.                                                                                                                                                                   |
| `swarm_size`              | integer | Calibration | Population size for PSO or GWO algorithms.                                                                                                                                                                        |
| `c1`                      | float | No | PSO cognitive parameter (default: `2.0`)                                                                                                                                                                          |
| `c2`                      | float | No | PSO social parameter (default: `2.0`)                                                                                                                                                                             |
| `w`                       | float | No | PSO intertia weight (default: `0.7`)                                                                                                                                                                              |
| `objective_function`      | string | Calibration | Objective function for optimization: `kge`, `nse`, `nnse`, `nselog`, `corr`, `csi`, `pod`, `rmse`, `mae`, `rsr`, `far`, `pkbias`, `pkte`, `evbias`, `bpias`, `lseg_fdc`, `hseg_fdc`.                              |
| `start_iteration`         | integer | No | Starting iteration number (default: `0`)                                                                                                                                                                          |
| `number_iteration`        | integer | Calibration | Number of iterations to run.                                                                                                                                                                                      |
| `restart`                 | integer | No | Restart from stopped iteration: `0` = no restart (default), `1` = restart (currently only 0 supported)                                                                                                            |
| `calib_output_vars`       | boolean | No | Write output variables during calibration iterations (default: `False`)                                                                                                                                           |
| `valid_output_vars`       | boolean | No | Write output variables during validation runs (default: `True`)                                                                                                                                                   |
| `calib_start_period`      | datetime | Calibration | Calibration simulation start time (format: `YYYY-MM-DD HH:MM:SS`).                                                                                                                                                |
| `calib_end_period`        | datetime | Calibration | Calibration simulation end time (format: `YYYY-MM-DD HH:MM:SS`).                                                                                                                                                  |
| `calib_eval_start_period` | datetime | Calibration | Calibration evaluation start time, excludes warm up period (format: `YYYY-MM-DD HH:MM:SS`).                                                                                                                       |
| `calib_eval_end_period`   | datetime | Calibration | Calibration evaluation end time, excludes warm up period (format: `YYYY-MM-DD HH:MM:SS`).                                                                                                                         |
| `valid_start_period`      | datetime | Calibration | Validation simulation start time (format: `YYYY-MM-DD HH:MM:SS`).                                                                                                                                                 |
| `valid_end_period`        | datetime | Calibration | Validation simulation end time (format: `YYYY-MM-DD HH:MM:SS`).                                                                                                                                                   |
| `valid_eval_start_period` | datetime | Calibration | Validation evaluation start time(format: `YYYY-MM-DD HH:MM:SS`).                                                                                                                                                  |
| `valid_eval_end_period`   | datetime | Calibration | Validation evaluation end time(format: `YYYY-MM-DD HH:MM:SS`).                                                                                                                                                    |
| `full_eval_start_period`  | datetime | Calibration | Full evluation period start (calibration + validation) (format: `YYYY-MM-DD HH:MM:SS`).                                                                                                                           |
| `full_eval_end_period`    | datetime | Calibration | Full evluation period end (calibration + validation)(format: `YYYY-MM-DD HH:MM:SS`).                                                                                                                              |
| `save_plot_iter`          | integer | No | Save plots at iterations: `0` = no (default), `1` = yes with iteration number in filename                                                                                                                         |
| `save_plot_iter_freq`     | integer | No | Iteration interval for saving plots default: `1`                                                                                                                                                                  |
| `streamflow_threshold`    | float | No | Streamflow threshold in cms for categorical scores (optional: if not specified, categorical metrics skipped)                                                                                                      |
| `station_name`            | string | No | Streamflow station name for plot titles (optional)                                                                                                                                                                |
| `ngen_cerf`               | boolean | No | Whether running from ngenCERF server (default: `false`)                                                                                                                                                           |
| `calibration_run_id`      | integer | No | Calibration run ID from ngenCERF (only needed when `ngen_cerf = true`)                                                                                                                                            |
| `auth_token`              | string | No | Authentication token from ngenCERF (only needed when `ngen_cerf = true`)                                                                                                                                          |
| `ngencerf_base_url`       | string | No | Base url for the ngenCERF server (only needed when `ngen_cerf = true`)                                                                                                                                              |
| `user_email`              | string | No | Email address to receive run completion notification (optional)                                                                                                                                                   |
| `calib_parameter_file`    | path | Calibration | Path to calibration parameter files. Can be: (1) folder with tab-delimited CSV files per module, (2) folder with comma-delimited CSV files per module, (3) single file with all parameters in fixed-width format. |

## NWM Output Variable Section `[NWMOuput]`
Parameters for activating full set of NWM output variables. Only used for forecast, default, and regionalization runs.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `nwm_output_variables` | bool | No | Boolean flag to activate output of full set of NWM output variables |


## Forcing Section: `[Forcing]`
Parameters for forcing engine configuration. Required for all run types, including forecast.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `forcing_provider` | string | Yes | Forcing provider: `csv` or `bmi` |
| `forcing_dir` | path | CSV provider | Directory for CSV forcing data. Required if `forcing_provider = csv`. |
| `forcing_template_dir` | path | BMI provider | Directory containing forcing engine template configuration files. Required in `forcing_provider = bmi`.|
| `root_dir` | path | BMI Proivder | Root directory for forecast files. Required if `forcing_provider = bmi`. Typically `/ngencerf/data/forecast_work` for ngencerf or `/ngen-app/data` for local runs. |
| `forcing_configuration` | string | BMI provider | Forcing engine configuration: `aorc`, `nwm`, or other forecast configuration. Required if `forcing_provider = bmi`. |
| `forcing_static_dir` | string | BMI provider | Path to forcing engine static geogrid files (only used for NWM retrospective) |
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
│   │           ├── state_save/                            # Folder containing state saving files from cold start run
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
When generating run files for a hindcast (using the nwm-fcst-mgr), multiple sets of input files for each warm start and hindcast iteration are created in the `/Output/` folder of a completed calibration run.

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
│   │       └──  [hind_run_name]/
│   │           ├── warm_start_3                      # Warm Start run providing start up states to hindcast cycle at 3 hours
│   │           │   ├── Input/
│   │           │   ├── logs/
│   │           │   └── Output/
│   │           └── warm_start_6                      # Warm Start run providing start up states to hindcast cycle at 6 hours
│   │               ├── Input/
│   │               ├── logs/
│   │               └── Output/
│   └── Hindcast_Run
│       └── [hind_run_name]/
│           ├── hindcast_0                          # Hindcast run at 0 hours, using saved states from Cold Start run
│           │   ├── Input/
│           │   ├── logs/
│           │   └── Output/     
│           ├── hindcast_3                          # Hindcast run at 3 hours, using saved states from Warm Start run at 3 hours
│           │   ├── Input/
│           │   ├── logs/
│           │   └── Output/  
│           └── hindcast_6                         # Hindcast run at 6 hours, using saved states from Warm Start run at 6 hours
│               ├── Input/
│               ├── logs/
│               └── Output/                         
```

### Lagged Ensemble Directory Structure
When generating run files for a medium range lagged ensemble (using the nwm-fcst-mgr), multiple sets of input files for lagged ensemble member are created in the `/Output/` folder of a completed calibration run.

```bash
├── /[Output]/                                         # Top level forecast file structure, within calibration run /Output/
│   ├── Calibration_Run/                               # Output run folder from previous calibration run
│   ├── Validation_Run/                                # Output run folder from previous validation run
│   └── Lagged_Ensemble_Run
│       └── [lagged_ens_run_name]/
│           ├── lagged_ens_mem1/                       # Lagged Ensemble member 1 run, using saved states from Closed Loop AnA
│           │   ├── Input/
│           │   ├── logs/
│           │   └── Output/   
│           ├── lagged_ens_noda/                       # Lagged Ensemble no data assimilation run, using saved states from Open Loop AnA
│           │   ├── Input/
│           │   ├── logs/
│           │   └── Output/   
│           ├── lagged_ens_mem2/                       # Lagged Ensemble member 2 run, using saved states from Closed Loop AnA
│           │   ├── Input/
│           │   ├── logs/
│           │   └── Output/
│           ├── lagged_ens_mem3/                       # Lagged Ensemble member 3 run, using saved states from Closed Loop AnA
│           ├── lagged_ens_mem4/                       # Lagged Ensemble member 4 run, using saved states from Closed Loop AnA
│           ├── lagged_ens_mem5/                       # Lagged Ensemble member 5 run, using saved states from Closed Loop AnA
│           └── lagged_ens_mem6/                       # Lagged Ensemble member 6 run, using saved states from Closed Loop AnA                    
```

## NWM Output Variables
The NWM output variable system provides a standardized way to produce a full set of NWM output variables from any supported Ngen formulation, regardless of which modules are included in the primary formulation

NWM output variables are defined in `/utils/nwm_output_variables.py` as a registry of required variables, each with a name, units, and a list of valid provider modules. When `nwm_output_variables` is enable in the `input.config` file,
the msw-mgr queries this registry against the existing formulation to determine which variables are already satisfied and which require additional adapter modules to be satisfied.

This feature is currently supported for **default**, **forecast**, and **regionalization** run types only. To enable NWM output variables, add the following to `input.config`:
```ini
[NWMOutput]
nwm_output_variables = True
```

### Adapter Modules
When the primary formulation cannot satisfy all required NWM output variables, the msw-mgr automatically identifies and adds adapter modules, which are non-interactive modules that run alongside the primary formulation solely to produce the missing output variables. Adapter modules are inserted into the realization file's module list but are configured so that they do not influence the primary formulation's behavior. For example, if a NoahOWP-CFE formulation is missing soil moisture outputs, SFT and SMP adapters may be added to produce those variables without affecting the the streamflow simulations produced by the original formulation.

SLOTH is added automatically when required to satisfy static input variables needed by adapter moduels. Any existing SLOTH parameters from the primary formulation are preserved and updated as needed to avoid conflicts.

### Workflow
1. The primary formulation BMI config files are created first using only the original formulation
2. Adapter module BMI config files are then created separately, using the full combined module list so that inter-module dependencies are satisfied
3. The realization file is assemble for the primary formulation, then updated to append adapter module sections and NWM output variable entries to the output variable list
4. For regionalization runs, each formulation group is handled independently since different groups may require different adapter modules
