"""
This module contains functions to manage the initial creation of configuration files

@author: Jeffrey Wade, Xia Feng
"""

import copy
from pathlib import Path
import os
import logging
import re
import math
from datetime import datetime
import geopandas as gpd
import pandas as pd
import json
import yaml
from collections import defaultdict
from pydantic import ValidationError, validate_call
import subprocess

from mswm.utils import ginputfunc as gfun
from mswm.utils import settings
from mswm.utils.log_level import log_level_set, MODULE_NAME
from mswm.utils.input_configuration import InputConfig


# Initialize MSWM setup logger
main_logger = logging.getLogger()
logger = None
if not main_logger.hasHandlers():
    # When running outside of Django, configure basic logging to stderr
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt=settings.DEFAULT_DATETIME_FORMAT,
    )


class RealizationBuilder:
    """
    This class reads a .conf file from disk (input_path) during calls to method `build_*_realization()`.
    Optionally, the configurations can be taken from config_overrides, if provided.

    `config_overrides` (class argument and property): InputConfig
        When this is provided as an argument to class construction, it is used instead of
        reading configuration from disk, and `config_overrides_mode__amend` is set to False.

        This can also be provided after class construction, in order to cause the configuration to be
        updated per-section, per-key, using the overrides, rather than fully replaced.

    `config_overrides_mode__amend` (property): bool
        When this is True, then the overrides from `config_overrides` are applied per-section, per-key,
        rather than wholesale replacing the configurations read from disk.

        When `config_overrides` are provided during class instantiation, this property is set to False (overrides will fully replace configuration, no aspect of configuration from disk will be used).
        When `config_overrides` are not provided during class instantiation, this property is set to True (overrides will amend configuration read from disk).
        This property can be changed after instantiating this class, before calling one of the `build_*_realization()` methods.
    """

    def __init__(self, input_path: str | None = None, valid_yaml: str | None = None, use_cold_start: bool = False, forcing_path: str | None = None, fcst_run_name: str | None = None, config_overrides: InputConfig | None = None):

        # Private attributes controlled by public properties.
        self._config_overrides: InputConfig | None
        self._config_overrides_mode__amend: bool

        if config_overrides:
            if input_path:
                raise ValueError("Must provide `input_path` or `config_overrides` (both were provided)")
            self.input_path = None
            self.config_overrides = config_overrides
            self.config_overrides_mode__amend = False

        elif input_path:
            if config_overrides:
                raise ValueError("Must provide `input_path` or `config_overrides` (both were provided)")
            self.input_path = Path(input_path)
            self.config_overrides = None
            self.config_overrides_mode__amend = True

        else:
            raise ValueError("Must provide `input_path` or `config_overrides`")

        self.valid_yaml = Path(valid_yaml) if valid_yaml else None

        self.use_cold_start = use_cold_start
        self.forcing_path = Path(forcing_path) if forcing_path else None
        self.fcst_run_name = fcst_run_name if fcst_run_name else None

        # Initialize this to empty dict so that config override has a target even when input_path is not used
        self.input_configs = {}
        main_logger.info(f"Initialized RealizationBuilder with {input_path}")

    @property
    def config_overrides(self):
        return self._config_overrides

    @config_overrides.setter
    @validate_call
    def config_overrides(self, new: InputConfig | None):
        self._config_overrides = new

    @property
    def config_overrides_mode__amend(self):
        return self._config_overrides_mode__amend

    @config_overrides_mode__amend.setter
    def config_overrides_mode__amend(self, new: bool):
        self._config_overrides_mode__amend = new

    def __load_config(self):
        """
        Read input.config file
        """
        import configparser

        if self.input_path is None:
            main_logger.debug("self.input_path is None")
            if self.config_overrides is None:
                raise ValueError(f"self.input_path = {self.input_path} and self.config_overrides = {self.config_overrides}")
            return

        # Confirm input file exists
        self.input_path = Path(self.input_path).absolute()
        if not self.input_path.exists():
            try:
                raise FileNotFoundError(f'Input file not found: {self.input_path}')
            except FileNotFoundError as e:
                main_logger.critical(e)
                raise

        # Read input config file
        try:
            self.config = configparser.ConfigParser()
            self.config.read(self.input_path)
        except FileNotFoundError as e:
            main_logger.critical(f"Input file not found: {self.input_path}\n{e}")
            raise
        except configparser.Error as e:
            main_logger.critical(f"ConfigParser error reading config file: {self.input_path}\n{e}")
            raise
        except Exception as e:
            main_logger.critical(f"Unexpected error loading config: {self.input_path}\n{e}")
            raise

        main_logger.info(f"Input.config file loaded from: {self.input_path}")

        # Raise error if config file is empty
        if not {section: dict(self.config[section]) for section in self.config.sections()}:
            try:
                raise ValueError(f'Input.config file is empty or contains no valid sections: {self.input_path}')
            except ValueError as e:
                main_logger.critical(e)
                raise

        self.__validate_config()

    def __validate_config(self):
        """
        Validate input.config file using Pydantic (input_configuration.py)
        """
        # Convert input.config to dictionary
        configs = {}
        for sec in self.config.sections():
            configs[sec] = {}
            for key, val in self.config.items(sec):
                # Strip trailing whitespaces from optional variables
                val_strip = val.strip()
                configs[sec][key] = val_strip if val_strip else None

        # Validate input.config structure and variables using Pydantic
        try:
            model = InputConfig(**configs)
        except ValidationError as e:
            main_logger.critical(f"Input.config Pydantic validation failed: {self.input_path}{e}")
            raise

        self.input_configs_class = model
        self.input_configs = model.model_dump()

    def __override_config(self) -> None:
        """
        Override the current config in-memory, either partially or in full.

        Variable Class Attributes Used as Parameters
        ----------
        self.config_overrides : InputConfig
            If None, this method does nothing.

        self.config_overrides_mode__amend : bool
            If True, then the individual keys from `overrides` will replace individual keys
            from the existing config dictionary `self.input_configs`, but keys which are missing
            from `overrides` will be ignored (will not be deleted from `self.input_configs`).
                Use case: iterating over a list of forecast types without altering the start time.

            If False, then the `overrides` object will be used wholly as-is, fully replacing
            the existing config dictionary.  Therefore `overrides` must be a complete configuration in this case.
                Use case: building a full configuration in memory
        """
        if not self.config_overrides:
            main_logger.info(f"self.config_overrides = {self.config_overrides}, will not apply overrides")
            return

        main_logger.info(f"Will apply config overrides with self.config_overrides_mode__amend={self.config_overrides_mode__amend}")

        if self.config_overrides_mode__amend:
            configs = copy.deepcopy(self.input_configs)
            for section_override, dict_override in self.config_overrides.model_dump().items():
                if dict_override is None:
                    continue
                if (section_override not in configs) or (configs[section_override] is None):
                    configs[section_override] = {}
                for k, v in dict_override.items():
                    configs[section_override][k] = v
        else:
            configs = self.config_overrides.model_dump()

        model = InputConfig(**configs)
        main_logger.info("Applying config overrides")
        self.input_configs_class = model
        self.input_configs = model.model_dump()

    def _load_yaml(self):
        """
        Read yaml-based configuration file from previous ngen calibration run
        """
        # Confirm config yaml file exists
        self.valid_yaml = Path(self.valid_yaml).absolute()
        if not self.valid_yaml.exists():
            try:
                raise FileNotFoundError(f'Config valid yaml file does not exist: {self.valid_yaml}')
            except FileNotFoundError as e:
                main_logger.critical(e)
                raise

        # Read the yaml-based configuration file
        try:
            with open(self.valid_yaml) as file:
                self.valid_conf = yaml.safe_load(file)
        except FileNotFoundError as e:
            main_logger.critical(f'Config valid yaml file does not exist: {self.valid_yaml}\n{e}')
            raise
        except yaml.YAMLError as e:
            main_logger.critical(f"YAML parsing error in valid config yaml file: {self.valid_yaml}\n{e}")
            raise
        except Exception as e:
            main_logger.critical(f"Unexpected error loading valid config yaml file at: {self.valid_yaml}\n{e}")
            raise

        main_logger.info(f"Configuration yaml file loaded: {self.valid_yaml}")

    def _create_fcst_dir(self):
        """
        Create directory for forecast run
        """
        # create fcst directory
        try:
            fcst_dir0 = Path(self.valid_conf['general']['yaml_file']).parent.parent
        except KeyError as e:
            main_logger.critical(f"Yaml file path not found in config valid yaml file: {e}")
            raise
        except FileNotFoundError as e:
            main_logger.critical(f"Invalid yaml file path: {self.valid_conf['general']['yaml_file']} - {e}")
            raise

        # Create forecast run directory or cold start run directory
        fcst_dir_name = 'Cold_Start_Run' if self.use_cold_start else 'Forecast_Run'
        self.input_dir = Path(fcst_dir0, fcst_dir_name, self.fcst_run_name)

        # Set file basename for forecast or cold start
        self.basename_opt = 'fcst' if not self.use_cold_start else 'cold_start'

        # Set run_type to forecast for log generation
        self.run_type = 'forecast' if not self.use_cold_start else 'cold start'

        try:
            self.input_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            main_logger.critical(f"[MSWM] Invalid yaml file path: {self.input_dir} - {e}")
            raise

        main_logger.info(f'[MSWM] Run directory created at: {self.input_dir}')

    def _parse_yaml(self):
        """
        Read realization file, hydrofabric gpkg and ngen executable paths from yaml file
        """
        # Set realization file path
        try:
            self.real_input_file = Path(self.valid_conf['model']['realization']).absolute()

            # Get hydrofabric gpkg paths
            self.gpkg_cats = self.valid_conf['model']['catchments']
            self.gpkg_nexus = self.valid_conf['model']['nexus']

            # Get ngen executable path
            self.ngen_exe = self.valid_conf['model']['binary']
        except Exception as e:
            logger.critical(f"Yaml config valid file is missing fields: {self.valid_yaml}\n{e}")
            raise

        logger.info("Yaml file parsed")

    def _load_reg_formulation(self):
        """
        Load regionalization formulation CSV file containing formulation groups and parameters
        """
        # Retrieve paths from input.config
        self.regionalization = self.input_configs.get('Regionalization')
        self.assign_path = Path(self.regionalization['form_assign_file'])
        self.cat_grp_path = Path(self.regionalization['cat_grp_file'])

        # Confirm regionalization formulation assignment file exists
        self.assign_file = Path(self.assign_path).absolute()
        if not self.assign_file.exists():
            try:
                raise FileNotFoundError(f'Regionalization formulation file does not exist: {self.assign_file}')
            except FileNotFoundError as e:
                logger.critical(e)
                raise

        # Confirm catchment group file exists
        self.cat_grp_file = Path(self.cat_grp_path).absolute()
        if not self.cat_grp_file.exists():
            try:
                raise FileNotFoundError(f'Regionalization catchment group file does not exist: {self.cat_grp_file}')
            except FileNotFoundError as e:
                logger.critical(e)
                raise

        # Load regionalization formulation assignment and catchment group files
        self.reg_df = pd.read_csv(self.assign_file, dtype={'gage_id': str})
        self.cat_grp_df = pd.read_csv(self.cat_grp_file, dtype={'gage_id': str})

        # Check that formulation file is not empty
        if self.reg_df.empty:
            try:
                raise ValueError(f"Regionalization formulation file is empty: {self.assign_file}")
            except ValueError as e:
                logger.critical(e)
                raise

        # Check that catchment group file is not empty
        if self.cat_grp_df.empty:
            try:
                raise ValueError(f"Regionalization catchment group file is empty: {self.cat_grp_file}")
            except ValueError as e:
                logger.critical(e)
                raise

        # Check that formulation file is properly formatted
        form_req_columns = {'gage_id', 'formulation'}
        if not form_req_columns.issubset(self.reg_df.columns):
            missing_cols = form_req_columns - set(self.reg_df.columns)
            try:
                raise ValueError(f"Regionalization formulation file is missing required columns: {missing_cols}")
            except ValueError as e:
                logger.critical(e)
                raise

        # Check that catchment group file is properly formatted
        cat_req_columns = {'gage_id', 'divide_id'}
        if not cat_req_columns.issubset(self.cat_grp_df.columns):
            missing_cols = cat_req_columns - set(self.cat_grp_df.columns)
            try:
                raise ValueError(f"Regionalization formulation file is missing required columns: {missing_cols}")
            except ValueError as e:
                logger.critical(e)
                raise

        if self.cat_grp_df["divide_id"].isnull().all():
            try:
                raise ValueError(f"Regionalization catchment group file must not have missing values: {self.cat_grp_file}")
            except ValueError as e:
                logger.critical(e)
                raise

        logger.info(f"Regionalization formulation file loaded: {self.assign_file}")
        logger.info(f"Regionalization catchment group file loaded: {self.cat_grp_file}")

    def _load_reg_catchments(self):
        """"
        Load grouped catchment files produced by regionalization and store grouped catchment ids
        """
        # Relate formulation groups to catchment IDS
        self.grp_to_cat = (self.cat_grp_df.groupby("gage_id")["divide_id"].apply(list).to_dict())

        logger.info(f"Regionalization catchment files loaded from: {self.assign_file}")

    def _parse_reg_params(self):
        """
        Extract regionalization parameters for each group and module
        """
        # Set modules and associated calibratable parameters
        params_dict = {
            'cfes': ['b', 'satdk', 'satpsi', 'slope',
                     'maxsmc', 'wltsmc', 'max_gw_storage', 'Cgw', 'expon',
                     'refkdt', 'Kn', 'Klf', 'is_aet_rootzone'],
            'cfex': ['b', 'satdk', 'satpsi', 'slope',
                     'maxsmc', 'wltsmc', 'max_gw_storage', 'Cgw', 'expon',
                     'refkdt', 'Kn', 'Klf', 'is_aet_rootzone', 'a_Xinanjiang_inflection_point_parameter',
                     'b_Xinanjiang_shape_parameter', 'x_Xinanjiang_shape_parameter'],
            'lasam': ['ponded_depth_max', 'field_capacity', 'smcmin', 'smcmax', 'van_genuchten_alpha', 'van_genuchten_n', 'hydraulic_conductivity'],
            'noah': ['RSURF_EXP', 'CWP', 'VCMX25', 'MP', 'MFSNO', 'RSURF_SNOW', 'SCAMAX'],
            'sac': ['uztwm', 'uzfwm', 'lztwm', 'lzfsm', 'lzfpm', 'adimp', 'uzk', 'lzpk', 'lzsk', 'zperc',
                    'rexp', 'pctim', 'pfree', 'riva', 'side', 'rserv'],
            'snow17': ['scf', 'mfmax', 'mfmin', 'uadj', 'si', 'pxtemp', 'nmf', 'tipm', 'plwhc', 'daygm'],
            'topmodel': ['szm', 't0', 'td', 'chv', 'rv', 'srmax', 'sr0', 'xk0'],
            'ueb': ['ems', 'cg', 'zo', 'rho', 'rhog', 'ks', 'de', 'avo', 'df', 'apr', 'cc', 'hcan', 'lai', 'subalb']
        }

        # For each module, retrieve group and corresponding parameter values
        # Raise errors for non-numeric strings, leaving empty parameter values out of realization section
        self.grp_params = {}
        errors = []
        for mod, params in params_dict.items():
            self.grp_params[mod] = {}
            for _, row in self.reg_df.iterrows():
                group = row['gage_id']
                param_values = {}
                for param in params:
                    if param not in self.reg_df.columns:
                        continue
                    value = row[param]
                    # If parameter is empty, leave out of parameter dictionary
                    if not math.isnan(value):
                        try:
                            param_values[param] = float(value)
                        except (ValueError, TypeError):
                            errors.append(f"Invalid parameter value in regionalization formulation file at: {mod}: {group}: {param}: {value}")
                self.grp_params[mod][group] = param_values

        # Log and raise errors for bad parameters
        if errors:
            for e in errors:
                logger.critical(e)
            err_message = "\n".join(errors)
            raise ValueError(f"Parameter valdiation failed:\n{err_message}")

        logger.info(f"Regionalization parameters loaded from: {self.assign_file}")

    def _load_realization(self):
        """
        Load realization json file
        """
        # Confirm realization file exists
        if not self.real_input_file.exists():
            try:
                raise FileNotFoundError(f'Realization input file does not exist: {self.real_input_file}')
            except FileNotFoundError as e:
                logger.critical(e)
                raise

        # Read realization file
        try:
            with open(self.real_input_file) as fp:
                self.real_config = json.load(fp)
        except FileNotFoundError as e:
            logger.critical(f"Realization input file does not exist: {self.real_input_file}\n{e}")
            raise
        except json.JSONDecodeError as e:
            logger.critical(f"Error parsing json from realization file: {self.real_input_file}\n{e}")
            raise
        except Exception as e:
            logger.critical(f"Unexpected error reading realization file: {self.real_input_file}\n{e}")

    def _parse_config(self):
        """
        Parse sections from input.config file
        """
        # reassign config sections for convenience
        self.conf1 = self.input_configs.get('General')
        self.run_type = self.conf1.get("run_type") if self.conf1 else None
        self.domain = self.conf1.get("domain") + "_hf" if self.conf1 else None
        self.basin = self.conf1['basin'] if self.conf1 else None

        # Set envca flag for CONUS Environment Canada gages
        self.envca = self.conf1.get("envca") if self.conf1 else None

        # Load run_type specific config section or empty dict for default
        run_key = (self.run_type or "").capitalize()
        self.conf2 = self.input_configs.get(run_key, {})
        self.ngen_cerf = self.conf2.get('ngen_cerf') or False

        # Retrieve input.config sections
        self.conf3 = self.input_configs.get('DataFile')
        self.forcingSec = self.input_configs.get('Forcing')
        self.parallelSec = self.input_configs.get('Parallel')

        # Use parallel ngen only when the number of processors is greater than 1
        if not self.parallelSec or self.parallelSec.get("nprocs", 0) < 2:
            self.parallelSec = None

    def _create_input_dir(self):
        """
        Create input directory to store realization file and BMI config files
        """
        # Set run directory based on run_type
        self.basin = self.conf1['basin']
        obj_fnc = self.conf2.get('objective_function') or "none"
        opt_alg = self.conf2.get('optimization_algorithm') or "none"
        if self.run_type == 'calibration':
            run_dir = os.path.join(self.conf1['main_dir'], '_'.join([obj_fnc, opt_alg]))
        elif self.run_type == 'regionalization':
            run_dir = os.path.join(self.conf1['main_dir'], 'regionalization')
        elif self.run_type == 'default':
            run_dir = os.path.join(self.conf1['main_dir'], 'default')

        # Form input directory paths
        self.work_dir = os.path.join(run_dir, self.conf1['formulation'] + '/' + self.basin)
        self.input_dir = os.path.join(self.work_dir, 'Input/')

        # Create directory
        try:
            os.makedirs(self.input_dir, exist_ok=True)
        except Exception as e:
            main_logger.critical(f"Invalid input directory: {e}. Check `main_dir` variable")
            raise

        main_logger.info(f"Input directory created at: {self.input_dir}")

    def _init_log(self):
        """
        Initialize logging depending on run type
        """
        # Set location for msw-mgr log
        if self.run_type in ('forecast', 'cold start'):
            log_path = os.path.join(self.input_dir, 'logs')
        else:
            log_path = os.path.join(self.work_dir, 'logs')

        # Initialize logging
        log_level_set(log_path)
        global logger
        logger = logging.getLogger(MODULE_NAME)
        gfun.init_ginput_logger()
        logger.info(f"Building {self.run_type} realization from: {self.input_path}")

    def _parse_forcing_engine(self):
        """
        Extract forcing engine parameters from input.config
        """
        # Retrieve forcing engine variables
        self.forcing_provider = self.forcingSec.get('forcing_provider', None)
        self.forcing_configuration = self.forcingSec.get('forcing_configuration', None)
        self.forcing_template_dir = self.forcingSec.get('forcing_template_dir', None)
        self.root_dir = self.forcingSec.get('root_dir', None)
        self.global_domain = self.forcingSec.get('global_domain', "CONUS")

        # Retrieve cold_start_time
        self.cold_start_datetime = self.forcingSec.get('cold_start_datetime', None)

        if self.forcing_provider == 'bmi' and self.forcing_configuration is not None:

            # Set forcing engine variables for forecast
            if self.forcing_configuration not in ['nwm', 'aorc']:

                # Retrieve forcing engine variables
                cycle_datetime = self.forcingSec.get('cycle_datetime')
                self.cycle_hour = self.forcingSec.get('cycle_hour')

                # Construct cycle date and cycle hour
                cycle_dt = datetime.strptime(cycle_datetime, settings.DEFAULT_DATETIME_FORMAT)
                self.cycle_date = cycle_dt.strftime("%Y-%m-%d")
                self.cycle_hour = cycle_dt.strftime("%H") + "z"

                # Construct forcing template file name
                if self.use_cold_start:
                    forcing_region = next((f"_{reg}" for reg in ["alaska", "hawaii", "puertorico"] if reg in self.forcing_configuration), "")
                    self.forcing_configuration_str = f"cold_start{forcing_region}_config.yml"
                else:
                    self.forcing_configuration_str = f"{self.forcing_configuration}_config.yml"

            # Set forcing engine variables for historical forcing
            else:
                self.forcing_configuration_str = f"{self.forcing_configuration}_config.yml"

            # Ensure forcing template file exists
            self.forcing_template_file = (Path(self.forcing_template_dir) / self.forcing_configuration_str).absolute()
            if not self.forcing_template_file.exists():
                try:
                    raise FileNotFoundError(f'Forcing template file does not exist: {self.forcing_template_file}')
                except FileNotFoundError as e:
                    logger.critical(e)
                    raise

            # Read forcing template file
            try:
                with open(self.forcing_template_file) as file:
                    self.forcing_template = yaml.safe_load(file)
            except FileNotFoundError as e:
                logger.critical(f'Config file does not exist: {self.forcing_template_file}\n{e}')
                raise
            except yaml.YAMLError as e:
                logger.critical(f"YAML parsing error in config file: {self.forcing_template_file}\n{e}")
                raise
            except Exception as e:
                logger.critical(f"Unexpected error loading config at: {self.forcing_template_file}\n{e}")
                raise

            if self.forcing_configuration not in ['nwm', 'aorc']:
                # Retrieve ngen start and end time based on forecast cycle date, hour and configuration
                self.fcst_start, self.fcst_end = gfun.create_fcst_times(self.forcing_template, self.cycle_date, self.cycle_hour, self.use_cold_start, self.cold_start_datetime)
            else:
                # Set default fcst_start/fcst_end values
                self.fcst_start = None
                self.fcst_end = None

            logger.info('Ngen start and end time set from forcing cycle')

    def _parse_time(self):
        """
        Set run time variables for calibration, regionalization, and default runs
        """
        # Retrieve time period for calibration
        if self.run_type == 'calibration':
            self.time_period = {"run_time_period": {"calib": [self.conf2['calib_start_period'], self.conf2['calib_end_period']],
                                                    "valid": [self.conf2['valid_start_period'], self.conf2['valid_end_period']]},
                                "evaluation_time_period": {"calib": [self.conf2['calib_eval_start_period'], self.conf2['calib_eval_end_period']],
                                                           "valid": [self.conf2['valid_eval_start_period'], self.conf2['valid_eval_end_period']],
                                                           "full": [self.conf2['full_eval_start_period'], self.conf2['full_eval_end_period']]}}
        # Retrieve time period for regionalization
        elif self.run_type == 'regionalization':
            self.time_period = {"run_time_period": {"region": [self.conf1['start_period'], self.conf1['end_period']]}}
        # Retrieve time period for default
        elif self.run_type == 'default':
            self.time_period = {"run_time_period": {"default": [self.conf1['start_period'], self.conf1['end_period']]}}

        # Confirm times are properly formatted and in correct order
        errors = []
        for outer_key, run_dict in self.time_period.items():
            for run_type, times in run_dict.items():
                time_vals = []
                for i, time_str in enumerate(times):
                    try:
                        time_vals.append(datetime.strptime(time_str.strip(), settings.DEFAULT_DATETIME_FORMAT))
                    except ValueError:
                        errors.append(f"Invalid datetime format: {outer_key}: {run_type}: {time_str}")
                if time_vals[0] >= time_vals[1]:
                    errors.append(f"Start time must be before end time: {outer_key}: {run_type}: {time_vals[0]} >= {time_vals[1]}")

        # Raise time format errors
        if errors:
            for e in errors:
                logger.critical(e)
            err_message = "\n".join(errors)
            raise ValueError(f"Time period valdiation failed:\n{err_message}")

        logger.info('Run time period validated')

    def _parse_calib_settings(self):
        """
        Parse input.config settings for calibration run
        """

        # Retrieve general settings for calibration
        algorithm = (self.conf2.get('optimization_algorithm', "") or "none").lower()
        swarm_size = self.conf2['swarm_size']
        start_iteration = self.conf2.get('start_iteration') or 0
        number_iteration = self.conf2.get('number_iteration') or 0
        restart = self.conf2.get('restart') or 0

        strategy = {'type': 'estimation', 'algorithm': algorithm}
        if algorithm == 'pso':
            strategy.update({'parameters': {'pool': swarm_size, 'particles': swarm_size,
                             'options': {'c1': self.conf2['c1'], 'c2': self.conf2['c2'], 'w': self.conf2['w']}}})
        if algorithm == 'gwo':
            strategy.update({'parameters': {'pool': swarm_size, 'particles': swarm_size}})

        # Set general config
        self.general_cfg = {'strategy': strategy, 'name': 'calib', 'log': True, 'workdir': None, 'yaml_file': None,
                            'start_iteration': start_iteration, 'iterations': number_iteration,
                            'restart': restart}

        logger.info('Calibration settings parsed')

    def _parse_modules(self):
        """
        Read modules from input.config file and ensure formulation is valid
        """

        logger.info(f"Available module names: {settings.modules_all['name_ui'].tolist()}")

        # Retrieve modules from config file
        modules0 = [x.replace(" ", "") for x in re.split(',', self.conf1['models'])]
        self.modules = []
        invalid_modules = []

        # Ensure modules match possible options provided in settings
        for m1 in modules0:
            filtered = settings.modules_all.loc[settings.modules_all['name_ui'] == m1.lower(), 'module']

            if filtered.empty:
                invalid_modules.append(m1)

            else:
                self.modules.append(filtered.iloc[0])

        # Raise an error if any invalid modules were found
        if invalid_modules:
            try:
                raise ValueError(f"Invalid module(s) found: {', '.join(invalid_modules)}. Please check your configuration.")
            except ValueError as e:
                logger.critical(e)
                raise

        # add sloth if CFE, LASAM, Topmodel is selected
        if (any(x in self.modules for x in ['cfes', 'cfex', 'lasam'])) or ('topmodel' in self.modules and 'smp' in self.modules) and 'sloth' not in self.modules:
            logger.info("CFE, LASAM, or SMP/Topmodel is used in the formulation. SLOTH added to module list")
            self.modules = ['sloth'] + self.modules

        # make sure SMP and SFT are always selected together
        if 'smp' in self.modules and 'sft' not in self.modules:
            logger.info('SMP and SFT must be selected together. SFT added to module list')
            self.modules = self.modules + ['sft']
        if 'sft' in self.modules and 'smp' not in self.modules:
            logger.info('SMP and SFT must be selected together. SMP added to module list')
            self.modules = self.modules + ['smp']

        # always ensure troute is included
        if 'troute' not in self.modules:
            logger.info("T-Route must be included in the formulation. T-Route added to module list")
            self.modules = self.modules + ['troute']

        # make sure SMP, SFT, SAC-SMA, and LASAM are not paired with PET, as PET does not provide the required inputs
        if any(m in self.modules for m in ('smp', 'sft', 'sac-sma', 'lasam')) and 'pet' in self.modules:
            try:
                raise ValueError("PET does not supply the required inputs for SMP, SFT, SAC-SMA, and LASAM. Add NOAH-OWP-Modular to formulation.")
            except ValueError as e:
                logger.critical(e)
                raise

        # rearrange modules in order of hydrologic processes
        self.modules = [m1 for m1 in settings.modules_all['module'] if m1 in self.modules]

        # Reorder "sft" and "smp"
        if "sft" in self.modules and "smp" in self.modules:
            smp_index = self.modules.index("smp")
            sft_index = self.modules.index("sft")
            if smp_index > sft_index:
                self.modules.remove("smp")
                self.modules.insert(sft_index, "smp")

        # Retrieve is_aet_rootzone flag for cfe
        self.is_aet_rootzone = self.conf1.get('is_aet_rootzone') or 0

        # If Topoflow in modules,validate glacier coverage and create grouped realizations
        if 'topoflow' in self.modules:
            # Call Icefabric API to check glacier coverage
            self.topoflow_ipe = gfun.call_icefabric_ipe('topoflow', ['topoflow'], self.basin, self.domain, self.ngen_cerf)

            # Retrieve list of catchments where glaciated percent >= 50
            glacier_thresh = 50
            topo_cats = [key for key, val in self.topoflow_ipe.items() if val.get('glacier_percent', 0) >= glacier_thresh]

            # Ensure catchments exist where topoflow-glacier can be applied
            if len(topo_cats) == 0:
                logger.warning(f"No catchments with >={glacier_thresh}% glacier coverage. "
                               "Removing Topoflow from formulation.")
                self.modules.remove('topoflow')
                logger.info(f"Updated module list (TopoFlow removed): {self.modules}")
            else:
                # Create grouped realizations if glaciated catchments exist
                mod_notopo = self.modules.copy()
                mod_notopo.remove('topoflow')
                self.grp_to_form = {}
                self.grp_to_form['group_1'] = mod_notopo
                self.grp_to_form['group_2'] = ['topoflow']

                # Map catchments to groups based on glacier coverage
                nontopo_cats = [key for key, val in self.topoflow_ipe.items() if val.get('glacier_percent', 0) < glacier_thresh]

                self.grp_to_cat = {'group_1': topo_cats,
                                   'group_2': nontopo_cats}

                # If CFE in modules, retrieve is_aet_rootzone flag
                self.grp_is_aet_rootzone = {}
                self.grp_is_aet_rootzone['group_1'] = self.is_aet_rootzone
                self.grp_is_aet_rootzone['group_2'] = 0

                logger.info(f"Final list of modules in formulation: 'group1': {mod_notopo}, 'group2': ['topoflow']")

    def _parse_reg_modules(self):
        """
        Retrieve modules from regionalization formulation file and ensure formulation is valid
        This could potentially be combined with _parse_modules to not repeat code
        """
        logger.info(f"Available module names: {settings.modules_all['name_ui'].tolist()}")
        self.grp_to_form = {}
        self.grp_is_aet_rootzone = {}

        for idx, row in self.reg_df.iterrows():
            modules0 = [x.replace(" ", "") for x in re.split(' ', row['formulation'])]
            modules = []
            invalid_modules = []

            # Ensure modules match possible options provided in settings
            for m1 in modules0:
                filtered = settings.modules_all.loc[settings.modules_all['name_ui'] == m1.lower(), 'module']

                # Add invalid modules to list
                if filtered.empty:
                    invalid_modules.append(m1)

                else:
                    modules.append(filtered.iloc[0])

            # Raise an error if any invalid modules were found
            if invalid_modules:
                try:
                    raise ValueError(f"Invalid module(s) found: {', '.join(invalid_modules)}. Please check your configuration.")
                except ValueError as e:
                    logger.critical(e)
                    raise

            # add sloth if CFE, LASAM, Topmodel is selected
            if (any(x in modules for x in ['cfes', 'cfex', 'lasam'])) or ('topmodel' in modules and 'smp' in modules) and 'sloth' not in modules:
                logger.info(f"CFE, LASAM, or SMP/Topmodel is used in the formulation. SLOTH added to module list: {row['gage_id']}")
                modules = ['sloth'] + modules

            # make sure SMP and SFT are always selected together
            if 'smp' in modules and 'sft' not in modules:
                logger.info(f"SMP and SFT must be selected together. SFT added to module list: {row['gage_id']}")
                modules = modules + ['sft']
            if 'sft' in modules and 'smp' not in modules:
                logger.info(f"SMP and SFT must be selected together. SMP added to module list: {row['gage_id']}")
                modules = modules + ['smp']

            # always ensure troute is included
            if 'troute' not in modules:
                logger.info(f"T-Route must be included in the formulation. T-Route added to module list: {row['gage_id']}")
                modules = modules + ['troute']

            # make sure SMP, SFT, SAC-SMA, and LASAM are not paired with PET, as PET does not provide the required inputs
            if any(m in modules for m in ('smp', 'sft', 'sac', 'lasam')) and 'pet' in modules:
                try:
                    raise ValueError("PET does not supply the required inputs for SMP, SFT, SAC-SMA, and LASAM. Add NOAH-OWP-Modular to formulation.")
                except ValueError as e:
                    logger.critical(e)
                    raise

            # rearrange modules in order of hydrologic processes
            modules = [m1 for m1 in settings.modules_all['module'] if m1 in modules]

            # Reorder "sft" and "smp"
            if "sft" in modules and "smp" in modules:
                smp_index = modules.index("smp")
                sft_index = modules.index("sft")
                if smp_index > sft_index:
                    modules.remove("smp")
                    modules.insert(sft_index, "smp")

            # If CFE in modules, retrieve is_aet_rootzone flag
            self.grp_is_aet_rootzone[row['gage_id']] = 0
            if any(m in modules for m in ['cfes', 'cfex']):
                if 'is_aet_rootzone' in self.reg_df.columns:
                    self.grp_is_aet_rootzone[row['gage_id']] = row['is_aet_rootzone']

            # Store with regionalization group id
            self.grp_to_form[row['gage_id']] = modules

            logger.info(f"Final list of modules in formulation for {row['gage_id']}: {modules}")

    def _validate_processes(self):
        """
        Check that formulation has all required hydrological processes
        """
        # check modules selected for each process
        procs = []
        for p1 in settings.modules_all['process']:
            procs = list(set(procs + p1))

        def validate_formulation(modules, label=None):
            """Inner helper function to validate a single formulation or grouped formulations"""

            for p1 in procs:
                mods = [m1 for m1 in modules if p1 in settings.modules_all.loc[settings.modules_all['module'] == m1, 'process'].values[0]]

                # make sure only one module is selected for each process (except for Soil_moisture and Glacier_snow)
                if len(mods) > 1 and p1 not in ['Soil_moisture', 'Glacier_snow']:
                    try:
                        raise Exception(f'Only one module can be selected for {p1} process')
                    except Exception as e:
                        logger.critical(e)
                        raise

                # one and only one module must be selected for rainfall-runoff and PET
                if (p1 in ['Evapotranspiration', 'Rainfall_runoff']) and (len(mods) == 0):
                    try:
                        raise Exception(f'At least one module must be selected for {p1} process')
                    except Exception as e:
                        logger.critical(e)
                        raise

        # Validation formulations using helper function
        if hasattr(self, 'grp_to_form') and self.grp_to_form:
            for grp, form in self.grp_to_form.items():
                validate_formulation(form, label=grp)
                logger.info(f"Module processes validated for {grp}")
        else:
            validate_formulation(self.modules)
            logger.info("Module processes validated")

    def _map_cat_to_grp(self):
        """
        Map catchments to formulation groups and assign is_aet_rootzone flags for cfe
        """
        # Relate catchments and their groups
        if hasattr(self, 'grp_to_cat') and self.grp_to_cat:
            self.cat_to_grp = {}
            self.cat_to_aet_rootzone = {}
            for grp, cats in self.grp_to_cat.items():
                for cat in cats:
                    self.cat_to_grp[cat] = grp
                    # Assign aet_rootzone flags for cfe
                    self.cat_to_aet_rootzone[cat] = self.grp_is_aet_rootzone.get(grp, 0)

    def _map_cat_to_form(self):
        """
        Map catchments to grouped formulations
        """
        # Relate catchments and their formulations
        if hasattr(self, 'grp_to_cat') and self.grp_to_cat:
            self.cat_to_form = {}
            for cat, grp in self.cat_to_grp.items():
                self.cat_to_form[cat] = self.grp_to_form[grp]

    def _map_mod_to_cat(self):
        """
        Map modules used in each catchment for regionalization
        """
        # Find the catchments that use each module
        if hasattr(self, 'grp_to_cat') and self.grp_to_cat:
            self.mod_to_cat = defaultdict(list)
            for cat, modules in self.cat_to_form.items():
                for module in modules:
                    self.mod_to_cat[module].append(cat)

    def _set_lib_paths(self):
        """
        Set library files for all modules included in the formulation
        """
        # Set library files
        self.lib_file = {}
        if self.run_type == 'regionalization':
            modules1 = list(set(m1 for form in self.grp_to_form.values() for m1 in form if m1 not in ['troute', 'lstm', 'topoflow']))
            self.all_mod = modules1.copy()

            # Add LSTM to all_mod if it's used in a formulation
            if any('lstm' in form for form in self.grp_to_form.values()):
                self.all_mod.append('lstm')
        else:
            modules1 = [m1 for m1 in self.modules if m1 not in ['troute', 'lstm', 'topoflow']]

        # Reformat library file paths to match input.config format
        for m1 in modules1:
            m2 = settings.modules_all.loc[settings.modules_all['module'] == m1, 'name_ui'].iloc[0]
            m2 = m2 if m2 not in ['cfe-s', 'cfe-x'] else 'cfe'
            self.lib_file[m1] = self.conf3[m2.replace("-", "_") + '_lib']

        # Confirm that library paths exist if not using server
        if not hasattr(self, 'conf2') or 'ngen_cerf' not in self.conf2 or self.conf2['ngen_cerf'] is False:
            errors = []
            for mod, lib_path in self.lib_file.items():
                if not Path(lib_path).is_file():
                    errors.append(f"Library file not found for {mod}: {lib_path}")

            # Raise errors
            if errors:
                for e in errors:
                    logger.critical(e)
                err_message = "\n".join(errors)
                raise ValueError(f"Library path valdiation failed:\n{err_message}")

        logger.info("Module libarary paths set")

    def _symlink_ngen(self):
        """
        Symlink ngen executable into Input run folder
        """
        # Set Symlink ngen path
        try:
            exe_path = Path(self.conf3['ngen_exe_file']).resolve()
        except FileNotFoundError as e:
            logger.critical(f"ngen executable not found: {self.conf3['ngen_exe_file']}: {e}")
            raise
        symlink_path = Path(self.input_dir) / "ngen"

        # Remove existing symlink
        if os.path.exists(symlink_path) or os.path.islink(symlink_path):
            try:
                symlink_path.unlink()
            except Exception as e:
                logger.error(f"Failed to remove existing {symlink_path}: {e}")
                raise

        # Link ngen executable
        try:
            os.symlink(exe_path, symlink_path)
            logger.info("Created symlink to ngen executable")
        except OSError as e:
            logger.critical(f"Failed to create symlink: {symlink_path} -> {exe_path}: {e}")
            raise

    @staticmethod
    def file_crs_epsg(file_name: str) -> int:
        logger.debug(f"Getting EPSG code of: {file_name}")
        gdf = gpd.read_file(file_name)
        return gdf.crs.to_epsg()

    def _extract_hydrofabric(self):
        """
        Extract hydrofabric geopackage and form catchment, nexus, and crosswalk files
        """

        # Retrieve gpkg from Icefabric API or symlink existing file if provided
        self.gpkg_file = self.conf3.get('hydrofab_file')
        if self.gpkg_file is None:
            # If gpkg_file not provided, retrieve gpkg from icefabric and save to file
            self.gpkg_file = gfun.call_icefabric_gpkg(self.basin, self.domain, self.input_dir, self.environment)
        else:
            # Ensure user provided geopackage file exists
            if not os.path.exists(self.gpkg_file):
                try:
                    raise Exception(f'Geo package file does not exist: {self.gpkg_file}')
                except Exception as e:
                    logger.critical(e)
                    raise

        # Set cat, nexus, and walk files
        self.cat_file = os.path.join(self.input_dir, os.path.basename(self.gpkg_file))
        self.nexus_file = os.path.join(self.input_dir, os.path.basename(self.gpkg_file))
        self.walk_file = self.input_dir + '{}'.format(self.basin) + '_crosswalk.json'

        if self.file_crs_epsg(self.gpkg_file) in (4326, 5070):
            try:
                # Symlink gpkg_file to Input directory if provided by user
                if self.conf3.get('hydrofab_file') is not None:
                    if not os.path.exists(self.cat_file):
                        os.symlink(self.gpkg_file, self.cat_file)
                        logger.info(f'Symlink created from {self.gpkg_file} to {self.cat_file}')
            except OSError as e:
                msg = f"Failed to create symlink: {self.gpkg_file} -> {self.cat_file}: {e}"
                logger.critical(msg)
                raise RuntimeError(msg) from e
        else:
            # TODO implement either a temporary reprojected file per job (to save space), or a permanent global set of reprojected files (to save time)
            cmd = ["ogr2ogr", "-overwrite", "-f", "GPKG", "-t_srs", "EPSG:4326", self.cat_file, self.gpkg_file]
            logger.info(f"Reprojecting gpkg to a new EPSG:4326 file via cmd: {' '.join(cmd)}")
            try:
                subprocess.check_call(cmd)
            except Exception as e:
                msg = f"Failed to reproject gpkg via cmd: {' '.join(cmd)}: {e}"
                logger.critical(msg)
                raise RuntimeError(msg) from e

        # Create crosswalk file between catchments and gages for calibration run
        if self.run_type == 'calibration':
            gfun.create_walk_file(self.basin, self.gpkg_file, self.walk_file)
            logger.info(f"Crosswalk file created at: {self.walk_file}")

        # Read catchment parameter values from geopackage divide-attributes
        attr_lyrname = "divide-attributes"
        logger.info(f"Reading layer {repr(attr_lyrname)} from file: {repr(self.gpkg_file)}")
        try:
            self.attr_file = gpd.read_file(self.gpkg_file, layer=attr_lyrname)
            self.attr_file.set_index("divide_id", inplace=True)
            # Update hydrofabic attribute names based on region and minor parameter value fixes
            self.attr_file = gfun.change_hydrofab_attr(self.attr_file, self.divides_layer)
        except Exception as e:
            logger.critical(f"Error while reading geopackage file: {e}")
            raise

        # Read catchment divide layer from hydrofabric
        try:
            self.divides_layer = gpd.read_file(self.gpkg_file, layer='divides')
            self.catids = self.divides_layer['divide_id'].tolist()
        except Exception as e:
            logger.critical(f"Error while reading geopackage file: {e}")
            raise

    def _extract_forcing(self):
        """
        Extract forcing files and symlink to input directory
        """

        # Create forcing directory
        self.forcing_path = os.path.join(self.input_dir, 'forcing')

        try:
            os.makedirs(self.forcing_path, exist_ok=True)
        except Exception as e:
            logger.critical(f"Invalid forcing directory: {e}. Check `main_dir` variable")
            raise

        # For csv provider
        if self.forcing_provider == 'csv':

            # Retrieve forcing_provider and forcing_dir
            self.forcing_dir = (self.forcingSec.get('forcing_dir', "") or None)

            # Symlink forcing files
            missing_catchment_files = []
            for catID in self.catids:
                ffile = os.path.join(self.forcing_dir, catID + '.csv')
                # Make sure we have the file
                if not os.path.exists(ffile):
                    logger.info(f'Forcing file {ffile} does not exist')
                    missing_catchment_files.append(ffile)
                else:

                    # Remove existing symlink
                    target = os.path.join(self.forcing_path, os.path.basename(ffile))
                    if os.path.exists(target) or os.path.islink(target):
                        try:
                            os.unlink(target)
                        except Exception as e:
                            logger.error(f"Failed to remove existing {target}: {e}")
                            raise

                    try:
                        os.symlink(ffile, target)
                    except OSError as e:
                        logger.critical(f"Failed to create symlink: {ffile} -> {target}: {e}")
                        raise

            if missing_catchment_files:
                try:
                    raise Exception(f"Missing catchment files in forcing data: {self.forcing_dir}")
                except Exception as e:
                    logger.critical(e)
                    raise

            # Set dummy forcing_config_file variable
            self.forcing_config_file = ""

            logger.info(f"Extracted CSV forcing data from: {self.forcing_dir}")

    def _configure_forcing_engine(self):
        """
        Extract forcing engine parameters and configure forcing engine yml files
        """
        if self.forcing_provider == 'bmi':

            # Set target directory for forcing config file
            self.forcing_config_dir = Path(self.input_dir) / 'forcing_config'
            self.forcing_config_file = self.forcing_config_dir / self.forcing_configuration_str

            # Set geopackage file path
            gpkg_file = self.cat_file if hasattr(self, "cat_file") and self.cat_file else self.gpkg_cats

            if self.forcing_configuration not in ['nwm', 'aorc']:
                # Update forecast dynamic parameters in forcing engine configuration file
                gfun.update_fcst_forcing_config(self.cycle_date, self.cycle_hour, self.root_dir, self.forcing_template, gpkg_file, self.forcing_config_dir,
                                                self.forcing_config_file, self.use_cold_start, self.cold_start_datetime)
            else:
                # Update historical dynamic parameters in forcing engine configuration file
                gfun.update_hist_forcing_config(self.time_period, self.root_dir, self.forcing_template, gpkg_file, self.forcing_config_dir, self.forcing_config_file, self.run_type, self.global_domain)

            logger.info(f"Configured BMI forcing engine: {self.forcing_config_file}")

    def _extract_streamflow_obs(self):
        """
        Extract streamflow gage observations if provided
        """
        # Extract streamflow observation
        if 'obs_dir' in self.conf3.keys() and self.conf3['obs_dir'] is not None:
            try:
                obs = pd.read_csv(os.path.join(self.conf3['obs_dir'], self.basin + '_hourly_discharge.csv'))[['dateTime', 'q_cms']]
                obs = obs.rename(columns={'dateTime': 'value_date', 'q_cms': 'obs_flow'})
            except Exception as e:
                logger.critical(f"Failed to read streamflow observations: {e}")
                raise

            self.obsflow_file = self.input_dir + '{}'.format(self.basin) + '_hourly_discharge.csv'

            try:
                obs.to_csv(self.obsflow_file, index=False)
            except Exception as e:
                logger.critical(f"Failed to write hourly discharge to: {self.obsflow_file} - {e}")
                raise

            logger.info(f"Extracted streamflow observations from: {self.conf3['obs_dir']}")
        else:
            self.obsflow_file = None

    def _set_output_vars(self):
        """
        Set SWE and Soil Moisture output variables
        """
        # whether to output SWE, soil moisture, or precip (default to False)
        self.output_dict = dict()
        for s1 in ['output_swe', 'output_sm', 'output_precip']:
            if (s1 not in self.conf1.keys()) or (self.conf1[s1] is None) or (self.conf1[s1] == ''):
                # Default output_precip to True if not specified
                self.output_dict[s1] = True if s1 == 'output_precip' else False
            else:
                self.output_dict[s1] = self.conf1[s1]

        # define depth (in meters) for output soil moisture
        val = self.conf1.get("sm_frac_depth")
        self.output_dict["sm_frac_depth"] = 0.4 if val in (None, "") else float(val)
        self.output_dict["sm_profile_depth"] = (
            [float(v) for v in self.conf1["sm_profile_depth"]]
            if "sm_profile_depth" in self.conf1 and self.conf1["sm_profile_depth"] is not None
            else [0.1, 0.4, 1.0, 2.0]
        )

        # Retrieve calib and valid output variable settings
        self.calib_output_vars = self.conf2.get('calib_output_vars')
        self.valid_output_vars = self.conf2.get('valid_output_vars')

        self.calib_output_vars = False if self.calib_output_vars is None else self.calib_output_vars
        self.valid_output_vars = True if self.valid_output_vars is None else self.valid_output_vars

        logger.info("Set output variables")

    def _update_fcst_realization(self):
        """
        Update forcing and time related info in realization file
        """
        self.real_config = gfun.update_forcing_in_realization(self.real_config, self.forcing_path, self.forcing_config_file, self.fcst_start, self.fcst_end, self.basename_opt)
        logger.info("Updated forecast realization file")

    def _update_fcst_noah_ueb_topo(self):
        """
        For UEB, TopoFlow, and Noah-OWP-Modular, create new BMI config files with new time info, and
        update path to BMI configs in realization file accordingly
        """
        self.real_config = gfun.update_noah_ueb_topo_times(self.real_config, self.input_dir)
        logger.info("Updated noah and ueb config files for forecast if used")

    def _update_fcst_troute(self):
        """
        Update BMI config files for t-route for forecast period
        """
        self.real_config = gfun.update_troute(self.real_config, self.input_dir, self.basename_opt)
        logger.info("Updated noah and ueb config files for forecast")

    def _create_bmi_configs(self):
        """
        Generate BMI config files for modules or link to existing config files
        """
        if self.run_type == 'calibration':
            self.run_configs = ['_troute_config_calib.yaml', '_troute_config_valid_control.yaml', '_troute_config_valid_best.yaml']
        elif self.run_type == 'default':
            self.run_configs = ['_troute_config_default.yaml']

        if hasattr(self, 'grp_to_cat') and self.grp_to_cat:
            # Retrieve unique modules in all formulations, maintaining formulation order
            mod_all = list(dict.fromkeys(item for lst in self.grp_to_form.values() for item in lst))
        else:
            mod_all = self.modules.copy()

        # Ensure cfes and cfex are first in mod_all, and troute last
        if 'cfes' in mod_all:
            mod_all = ['cfes'] + [m1 for m1 in mod_all if m1 != 'cfes']
        if 'cfex' in mod_all:
            mod_all = ['cfex'] + [m1 for m1 in mod_all if m1 != 'cfex']
        if 'troute' in mod_all:
            mod_all.remove('troute')
            mod_all.append('troute')

        # loop through modules to create input files
        for m1 in mod_all:

            # module name used by the UI
            m2 = settings.modules_all.loc[settings.modules_all['module'] == m1, 'name_ui'].iloc[0]

            # define module input directory
            mod_input_dir = os.path.join(self.input_dir, m2 + '_input')

            # Retrieve catchments that use each module
            if hasattr(self, 'grp_to_cat') and self.grp_to_cat:
                cat_mod = self.mod_to_cat[m1]
            else:
                cat_mod = self.catids.copy()

            # Skip config generation for sloth
            if m1 in ['sloth']:
                continue

            # Create input file directory
            if m1 != 'troute':
                try:
                    os.makedirs(mod_input_dir, exist_ok=True)
                except Exception as e:
                    logger.critical(f"Failed to create input directory for {m1}: {mod_input_dir} - {e}")
                    raise

            # Create BMI config files from scratch if paths not provided
            if m1 in ['cfes', 'cfex']:
                gfun.create_cfe_input(cat_mod, mod_all, self.attr_file, mod_input_dir, self.run_type, self.is_aet_rootzone)
            elif m1 == 'topmodel':
                gfun.create_topmodel_input(cat_mod, self.attr_file, mod_input_dir)
            elif m1 == 'ueb':
                gfun.create_ueb_input(cat_mod, self.time_period, self.attr_file, self.conf3[m1 + '_parameter_dir'], mod_input_dir, '', self.run_type)
            elif m1 == 'snow17':
                gfun.create_snow17_input(cat_mod, self.attr_file, self.conf3[m2.replace("-", "_") + '_parameter_dir'], mod_input_dir)
            elif m1 == "pet":
                pass
                # gfun.create_pet_input(cat_mod, self.attr_file, mod_input_dir)
            elif m1 == "sac":
                gfun.create_sac_input(cat_mod, self.attr_file, self.conf3[m1 + '_parameter_dir'], mod_input_dir)
            elif m1 == 'noah':
                gfun.create_noah_input(cat_mod, self.time_period, self.attr_file, self.conf3[m1 + '_parameter_dir'], mod_input_dir, self.run_type)
            elif m1 == 'lstm':
                gfun.create_lstm_input(cat_mod, self.attr_file, self.conf3['lstm_parameter_dir'], mod_input_dir)
            elif m1 == 'sft':
                sft_dir = os.path.join(self.input_dir, 'sft_input')
                smp_dir = os.path.join(self.input_dir, 'smp_input')
                gfun.create_sft_smp_input(cat_mod, self.modules, self.attr_file, sft_dir, smp_dir, self.run_type, self.output_dict['sm_frac_depth'],
                                          self.output_dict['sm_profile_depth'])
            elif m1 == 'smp':
                pass
            elif m1 == 'lasam':
                gfun.create_lasam_input(cat_mod, self.modules, self.attr_file, mod_input_dir, self.conf3['lasam_parameter_dir'], self.run_type)
            elif m1 == 'topoflow-glacier':
                gfun.create_topoflow_glacier_input(cat_mod, self.attr_file, self.time_period, mod_input_dir, self.run_type)
            elif m1 == 'troute':
                routing_config_file = os.path.join(self.work_dir + '/Input', '{}'.format(self.basin))
                gfun.create_troute_config(self.cat_file, self.time_period, routing_config_file, self.run_configs, self.run_type)

            if m1 != 'troute':
                logger.info(f'{m1}: input config files created at: {mod_input_dir}')

        logger.info("Created BMI config files for all modules in the formulation")

    def _create_reg_bmi_configs(self):
        """
        Generate BMI config files for modules for regionalization
        """

        self.run_configs = ['_troute_config_region.yaml']

        # Retrieve unique modules in all formulations, maintaining formulation order
        mod_all = list(dict.fromkeys(item for lst in self.grp_to_form.values() for item in lst))

        # Ensure cfes and cfex are first in mod_all
        if 'cfes' in mod_all:
            mod_all = ['cfes'] + [m1 for m1 in mod_all if m1 != 'cfes']
        if 'cfex' in mod_all:
            mod_all = ['cfex'] + [m1 for m1 in mod_all if m1 != 'cfex']

        # loop through modules to create input files
        for m1 in mod_all:

            # module name used by the UI
            m2 = settings.modules_all.loc[settings.modules_all['module'] == m1, 'name_ui'].iloc[0]

            # define and store module input directory
            mod_input_dir = os.path.join(self.input_dir, m2 + '_input')
            if os.path.isdir(mod_input_dir):
                if os.path.islink(mod_input_dir):
                    try:
                        os.unlink(mod_input_dir)
                    except Exception as e:
                        logger.error(f"Failed to remove existing {mod_input_dir}: {e}")
                        raise

            # Retrieve catchments that use each module
            cat_mod = self.mod_to_cat[m1]

            # If module requires full formulation, retrieve formulation for each catchment
            if m1 in ['cfes', 'cfex', 'sft', 'lasam']:
                form_cat = [self.cat_to_form[cat] for cat in cat_mod]

            # Modify existing BMI config files if filepaths provided (ignoring troute for now)
            # Skip config generation for sloth
            if m1 in ['sloth']:
                pass

            # Create input file directory
            if m1 != 'troute':
                try:
                    os.makedirs(mod_input_dir, exist_ok=True)
                except Exception as e:
                    logger.critical(f"Failed to create input directory for {m1}: {mod_input_dir} - {e}")
                    raise

            # Create BMI config files from scratch if paths not provided
            if m1 in ['cfes', 'cfex']:
                gfun.create_cfe_input(cat_mod, form_cat, self.attr_file, mod_input_dir, self.run_type, self.cat_to_aet_rootzone)
            elif m1 == 'topmodel':
                gfun.create_topmodel_input(cat_mod, self.attr_file, mod_input_dir)
            elif m1 == 'ueb':
                gfun.create_ueb_input(cat_mod, self.time_period, self.attr_file, self.conf3[m1 + '_parameter_dir'], mod_input_dir, '', self.run_type)
            elif m1 == 'snow17':
                gfun.create_snow17_input(cat_mod, self.attr_file, self.conf3[m2.replace("-", "_") + '_parameter_dir'], mod_input_dir)
            elif m1 == "pet":
                pass
                # gfun.create_pet_input_reg(cat_mod, self.attr_file, mod_input_dir)
            elif m1 == "sac":
                gfun.create_sac_input(cat_mod, self.attr_file, self.conf3[m1 + '_parameter_dir'], mod_input_dir)
            elif m1 == 'noah':
                gfun.create_noah_input(cat_mod, self.time_period, self.attr_file, self.conf3[m1 + '_parameter_dir'], mod_input_dir, self.run_type)
            elif m1 == 'lstm':
                gfun.create_lstm_input(cat_mod, self.attr_file, self.conf3['lstm_parameter_dir'], mod_input_dir)
            elif m1 == 'sft':
                sft_dir = os.path.join(self.input_dir, 'sft_input')
                smp_dir = os.path.join(self.input_dir, 'smp_input')

                # Loop through schemes that could be paired with SMP/SFT (CFES/CFEX/LASAM)
                # SMP/SFT could be paired with CFES/CFEX/LASAM simulatenously in different formulations, so configs must be generated separately
                for scheme in ['cfes', 'cfex', 'lasam', 'topmodel']:
                    # Retrieve formulation groups where CFES/CFEX/LASAM co-occur with SFT
                    scheme_sft_grps = [grp for grp, mods in self.grp_to_form.items() if scheme in mods and 'sft' in mods]

                    if scheme_sft_grps:
                        # Retrieve catchments and formulations corresponding to scheme
                        scheme_cat = [cat for grp in scheme_sft_grps for cat in self.grp_to_cat[grp]]
                        scheme_form = [self.cat_to_form[cat] for cat in scheme_cat]

                        # Create SFT/SMP inputs
                        gfun.create_sft_smp_input(scheme_cat, scheme_form, self.attr_file, sft_dir, smp_dir, self.run_type,
                                                  self.output_dict['sm_frac_depth'], self.output_dict['sm_profile_depth'])

            # Skip smp, inputs created in tandem with sft
            elif m1 == 'smp':
                continue
            elif m1 == 'lasam':
                gfun.create_lasam_input(cat_mod, form_cat, self.attr_file, mod_input_dir, self.conf3['lasam_parameter_dir'], self.run_type)
            elif m1 == 'topoflow-glacier':
                gfun.create_topoflow_glacier_input(cat_mod, self.attr_file, self.time_period, mod_input_dir, self.run_type)
            elif m1 == 'troute':
                routing_config_file = os.path.join(self.work_dir + '/Input', '{}'.format(self.basin))
                gfun.create_troute_config(self.cat_file, self.time_period, routing_config_file, self.run_configs, self.run_type)
            if m1 != 'troute':
                logger.info(f'{m1}: input config files created at: {mod_input_dir}')

        logger.info("Created BMI config files for all modules in each regionalization formulation")

    def _write_realization(self):
        """
        Write realization file for calibration and default runs
        """
        # Set file suffix
        if self.run_type == 'calibration':
            file_suffix = 'calib'
        else:
            file_suffix = self.run_type

        # Set BMI config directories
        self.realization_file = self.work_dir + '/{}'.format(self.basin) + '_realization_config_bmi_' + file_suffix + '.json'
        routing_config_file = os.path.join(self.work_dir + '/Input', '{}'.format(self.basin) + self.run_configs[0])
        bmi_dir = {}
        for m1 in self.modules:
            m2 = settings.modules_all.loc[settings.modules_all['module'] == m1, 'name_ui'].iloc[0]
            bmi_dir[m1] = os.path.join(self.input_dir, m2 + '_input')
        rt_dict = {"routing": {"t_route_config_file_with_path": routing_config_file}}

        # Write realization file
        if hasattr(self, 'grp_to_form') and self.grp_to_form:
            self.output_config = gfun.create_reg_realization_file(self.work_dir, self.lib_file, bmi_dir, self.forcing_provider, self.forcing_path, self.forcing_config_file, self.realization_file,
                                                                  self.time_period, rt_dict, self.output_dict, self.calib_output_vars, self.run_type, self.cat_to_grp, self.grp_to_form, {})
        else:
            self.output_config = gfun.create_realization_file(self.work_dir, self.lib_file, bmi_dir, self.forcing_provider, self.forcing_path, self.forcing_config_file, self.realization_file,
                                                              self.modules, self.time_period, rt_dict, self.output_dict, self.calib_output_vars, self.run_type)

    def _write_region_realization(self):
        """
        Write realization file for regionalization runs
        """
        # Create model realization file for regionalization
        self.realization_file = self.work_dir + '/{}'.format(self.basin) + '_realization_config_bmi_region.json'
        routing_config_file = os.path.join(self.work_dir + '/Input', '{}'.format(self.basin) + self.run_configs[0])

        # Set BMI config directories
        bmi_dir = {}
        for m1 in self.all_mod:
            m2 = settings.modules_all.loc[settings.modules_all['module'] == m1, 'name_ui'].iloc[0]
            bmi_dir[m1] = os.path.join(self.input_dir, m2 + '_input')
        rt_dict = {"routing": {"t_route_config_file_with_path": routing_config_file}}

        # Write realization file
        self.output_config = gfun.create_reg_realization_file(self.work_dir, self.lib_file, bmi_dir, self.forcing_provider, self.forcing_path, self.forcing_config_file, self.realization_file,
                                                              self.time_period, rt_dict, self.output_dict, {}, self.run_type, self.cat_to_grp, self.grp_to_form, self.grp_params)

    def _write_fcst_realization(self):
        """
        Write updated forecast realization file
        """
        # Update realization file basename
        new_basename = os.path.basename(self.real_input_file).replace("valid_best", self.basename_opt)

        # save the new realization file
        self.realization_file = Path(self.input_dir, new_basename)
        try:
            with open(self.realization_file, 'w') as outfile:
                json.dump(self.real_config, outfile, indent=4, separators=(", ", ": "), sort_keys=False)
        except TypeError as e:
            logger.critical(f"Failed to dump realization data to JSON: {self.realization_file}\n{e}")
            raise
        except OSError as e:
            logger.critical(f"Unexpected error while writing realization data to JSON: {self.realization_file}\n{e}")
            raise

        logger.info(f"Realization file is created at: {self.realization_file}")

    def _write_partition(self):
        """
        Write parallel processing partition file
        """
        self.part_file = gfun.create_partition_file(self.parallelSec['partition_generator_exe'],
                                                    self.cat_file,
                                                    self.parallelSec['nprocs'],
                                                    self.work_dir,
                                                    self.basin) if self.parallelSec else None

        logger.info(f"Partition file is created at: {self.part_file}")

    def _create_calib_model_dict(self):
        """
        Create calibration model dictionary used to create config yaml file
        """
        # Set site name
        site_name = (f"USGS {self.conf1['basin']}" + (f": {self.conf2['station_name']}" if self.conf2.get('station_name') else ""))
        objective_function = self.conf2.get('objective_function') or "none"
        save_output_iter = self.conf2.get('save_output_iter') or 0
        save_plot_iter = self.conf2.get('save_plot_iter') or 0
        save_plot_iter_freq = self.conf2.get('save_plot_iter_freq') or 0
        streamflow_threshold = self.conf2.get('streamflow_threshold') or 0.0
        user_email = self.conf2.get('user_email') or ''
        strategy = 'grouped' if 'topoflow' in self.modules else 'uniform'

        # Create calibration configuration file
        self.calib_config_file = os.path.join(self.work_dir + '/Input', '{}'.format(self.basin) + '_config_calib.yaml')
        self.model_dict = {'type': 'ngen', 'binary': self.conf3['ngen_exe_file'], 'realization': self.realization_file,
                           'catchments': self.cat_file, 'nexus': self.nexus_file,
                           'crosswalk': self.walk_file, 'obsflow': self.obsflow_file, 'strategy': strategy, 'params': None,
                           'eval_params': {'objective': objective_function,
                                           'evaluation_start': self.time_period['evaluation_time_period']['calib'][0],
                                           'evaluation_stop': self.time_period['evaluation_time_period']['calib'][1],
                                           'valid_start_time': self.time_period['run_time_period']['valid'][0],
                                           'valid_end_time': self.time_period['run_time_period']['valid'][1],
                                           'valid_eval_start_time': self.time_period['evaluation_time_period']['valid'][0],
                                           'valid_eval_end_time': self.time_period['evaluation_time_period']['valid'][1],
                                           'full_eval_start_time': self.time_period['evaluation_time_period']['full'][0],
                                           'full_eval_end_time': self.time_period['evaluation_time_period']['full'][1],
                                           'save_output_iteration': save_output_iter,
                                           'save_plot_iteration': save_plot_iter,
                                           'save_plot_iter_freq': save_plot_iter_freq,
                                           'basinID': self.conf1['basin'],
                                           'threshold': streamflow_threshold,
                                           'site_name': site_name,
                                           'user': user_email},
                           }

        # update the model dict to enable parallel processing
        self.model_dict.update({'partitions': self.part_file}) if self.parallelSec else None
        self.model_dict.update({'parallel': int(self.parallelSec['nprocs'])}) if self.parallelSec else None
        self.model_dict.update({'binary': self.parallelSec['parallel_ngen_exe']}) if self.parallelSec else None

        # Set NWM retrospective
        if 'nwmretro_file' in self.conf3.keys():
            if self.conf3['nwmretro_file'] is not None:
                self.model_dict['nwmflow'] = self.conf3['nwmretro_file']

        logger.info("Formatted calibration configuration settings for output")

    def _write_calib_configuration(self):
        """
        Create calibration configuration yaml file
        """
        # Create general config dictionary for output
        general_dict = self.general_cfg.copy()
        general_dict['workdir'] = self.work_dir
        general_dict['yaml_file'] = self.calib_config_file

        # items related to running from GUI
        for s1 in ['calibration_run_id', 'ngen_cerf', 'auth_token']:
            general_dict[s1] = self.conf2[s1]

        # Set output variables
        if self.valid_output_vars:
            general_dict['valid_output_vars'] = self.output_config['output_variables']
            general_dict['valid_output_headers'] = self.output_config['output_header_fields']
            general_dict['valid_output_units'] = self.output_config['output_units']
            general_dict["valid_output_index"] = self.output_config["output_index"]

        # Create calibration config file
        gfun.create_calib_config_file(self.conf2['calib_parameter_file'], self.modules, self.work_dir, general_dict, self.model_dict, self.calib_config_file)

    def build_calib_realization(self):
        """
        Replicate functionality of create_input.py, saving calibration realization file to output_path and formatting other input files
        Returns output path to realization and calib_config files
        """
        self.load_config_apply_overrides()
        self._parse_config()
        self._create_input_dir()
        self._init_log()

        if self.run_type != 'calibration':
            try:
                raise ValueError(f"Unexpected run_type {self.run_type} for build_calib_realization. Must be `calibration`.")
            except ValueError as e:
                logging.critical(e)
                raise

        self._parse_forcing_engine()
        self._parse_time()
        self._parse_calib_settings()
        self._parse_modules()
        self._validate_processes()
        self._map_cat_to_grp()
        self._map_cat_to_form()
        self._map_mod_to_cat()
        self._set_lib_paths()
        self._extract_hydrofabric()
        self._extract_forcing()
        self._configure_forcing_engine()
        self._extract_streamflow_obs()
        self._set_output_vars()
        self._create_bmi_configs()
        self._write_realization()
        self._write_partition()
        self._create_calib_model_dict()
        self._write_calib_configuration()

        logger.info("Calibration run set up successfully")

    def build_region_realization(self):
        """
        Creating regionalization realization file from formulation_assignment file generated by regionalization
        """
        self.load_config_apply_overrides()
        self._parse_config()
        self._create_input_dir()
        self._init_log()

        if self.run_type != 'regionalization':
            try:
                raise ValueError(f"Unexpected run_type {self.run_type} for build_region_realization. Must be `regionalization`.")
            except ValueError as e:
                logging.critical(e)
                raise

        self._parse_forcing_engine()
        self._load_reg_formulation()
        self._load_reg_catchments()
        self._parse_time()
        self._parse_reg_params()
        self._parse_reg_modules()
        self._validate_processes()
        self._map_cat_to_grp()
        self._map_cat_to_form()
        self._map_mod_to_cat()
        self._set_lib_paths()
        self._symlink_ngen()
        self._extract_hydrofabric()
        self._extract_forcing()
        self._configure_forcing_engine()
        self._set_output_vars()
        self._create_reg_bmi_configs()
        self._write_region_realization()
        self._write_partition()

        logger.info("Regionalization run set up successfully")

    def load_config_apply_overrides(self):
        """Load the config file from disk and apply overrides.
        If config overrides are applied with amend = False, then skip reading the config file."""
        if self.config_overrides and (not self.config_overrides_mode__amend):
            logging.info("Skipping load of config file since overrides will replace entire config (no amend)")
        else:
            self.__load_config()
        self.__override_config()

    def build_fcst_realization(self):
        """
        Replicate functionality of ngen-fcst, creating realization file from validation yaml file and formatting other input files
        """
        self.load_config_apply_overrides()
        self._load_yaml()
        self._create_fcst_dir()
        self._init_log()
        self._parse_yaml()
        self._parse_config()
        self._load_realization()
        self._parse_forcing_engine()
        self._extract_forcing()
        self._configure_forcing_engine()
        self._update_fcst_realization()
        self._update_fcst_noah_ueb_topo()
        self._update_fcst_troute()
        self._write_fcst_realization()

        if self.use_cold_start:
            logger.info("Cold start run set up successfully")
        else:
            logger.info("Forecast run set up successfully")

    def build_default_realization(self):
        """
        Create realization and BMI config files using default parameter values for each catchment
        """
        self.load_config_apply_overrides()
        self._parse_config()
        self._create_input_dir()
        self._init_log()

        if self.run_type != 'default':
            try:
                raise ValueError(f"Unexpected run_type {self.run_type} for build_default_realization. Must be `default`.")
            except ValueError as e:
                logging.critical(e)
                raise

        self._parse_forcing_engine()
        self._parse_time()
        self._parse_modules()
        self._validate_processes()
        self._map_cat_to_grp()
        self._map_cat_to_form()
        self._map_mod_to_cat()
        self._set_lib_paths()
        self._symlink_ngen()
        self._extract_hydrofabric()
        self._extract_forcing()
        self._configure_forcing_engine()
        self._set_output_vars()
        self._create_bmi_configs()
        self._write_realization()
        self._write_partition()

        logger.info("Default run set up successfully")


def validate_topoflow(basin_id: str, domain: str, ngen_cerf: bool) -> dict:
    """Validate Topoflow-Glacier applicability by checking glacier coverage in basin catchments

    Retrieves glacier coverage from Icefabric API and identifies catchments with >50% glacier coverage
    that are suitable for Topflow-Glacier application

    Args:
        basin_id: basin identifier
        domain: domain identifier
    """

    # Retrieve glacier coverage data from Icefabric API
    domain_hf = domain + "_hf"
    ipe = gfun.call_icefabric_ipe('topoflow', ['topoflow'], basin_id, domain_hf, ngen_cerf)

    # Filter catchments by glacier percent >50%
    glacier_thresh = 50
    glacier_cat = sum(1 for val in ipe.values() if val.get('glacier_percent', ) >= glacier_thresh)

    # Return json message for Topoflow-Glacier applicability
    if glacier_cat >= 1:
        return {'result': True}
    else:
        return {
            'result': False,
            'message': f'No catchments meet glacier coverage threshold of {glacier_thresh}% for Topoflow-Glacier Application'
        }
