"""
This module contains functions to manage the initial creation of configuration files

@author: Jeffrey Wade, Xia Feng
"""

import copy
from pathlib import Path
import os
import ewts
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

from mswm.utils import ginputfunc as gfun
from mswm.utils import settings
from mswm.utils.input_configuration import InputConfig
from mswm.utils.nwm_output_variables import get_providers_for_formulation


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

    def __init__(self, input_path: str | None = None, valid_yaml: str | None = None, use_cold_start: bool = False, use_warm_start: bool = False,
                 use_hindcast: bool = False, use_lagged_ens: bool = False, forcing_path: str | None = None, fcst_run_name: str | None = None, hind_cycle: int | None = None, prev_hind_cycle: int | None = None,
                 lagged_ens_mem: str | None = None, forcing_lag: int | None = None, load_state_from: str | None = None, save_state: bool = False,
                 config_overrides: InputConfig | None = None):

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
        self.use_warm_start = use_warm_start
        self.use_hindcast = use_hindcast
        self.use_lagged_ens = use_lagged_ens
        self.forcing_path = Path(forcing_path) if forcing_path else None
        self.fcst_run_name = fcst_run_name if fcst_run_name else None
        self.hind_cycle = hind_cycle if hind_cycle else 0
        self.prev_hind_cycle = prev_hind_cycle if prev_hind_cycle else 0
        self.load_state_from = Path(load_state_from) if load_state_from else None
        self.save_state = save_state
        self.lagged_ens_mem = lagged_ens_mem if lagged_ens_mem else None
        self.forcing_lag = forcing_lag if forcing_lag else 0

        # Validate optional forecast flags
        fcst_modes = sum([self.use_cold_start, self.use_warm_start, self.use_hindcast, self.use_lagged_ens])
        if fcst_modes > 1:
            err = ("Invalid configuration: only one of 'use_cold_start', 'use_warm_start', 'use_hindcast', use_lagged_ens may be True.")
            main_logger.critical(err)
            raise ValueError(err)

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

    def _load_config(self):
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

        self._validate_config()

    def _validate_config(self):
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

    def _override_config(self) -> None:
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

        # Create cold start, warm start, or forecast run directory  run directory
        fcst_dir_name = (
            'Model_State_Run/Cold_Start_Run' if self.use_cold_start
            else ('Model_State_Run/Warm_Start_Run' if self.use_warm_start
                  else ('Hindcast_Run' if self.use_hindcast
                        else ('Lagged_Ensemble_Run' if self.use_lagged_ens
                              else 'Forecast_Run')))
        )

        # Set run_type to forecast for log generation
        self.run_type = (
            'cold_start' if self.use_cold_start
            else ('warm_start' if self.use_warm_start
                  else ('hindcast' if self.use_hindcast
                        else ('lagged_ens' if self.use_lagged_ens
                              else 'forecast')))
        )

        if self.use_hindcast or self.use_warm_start:
            self.work_dir = Path(fcst_dir0, fcst_dir_name, self.fcst_run_name, f"{self.run_type}_{self.hind_cycle}")
        elif self.use_lagged_ens:
            self.work_dir = Path(fcst_dir0, fcst_dir_name, self.fcst_run_name, f"{self.run_type}_{self.lagged_ens_mem}")
        else:
            self.work_dir = Path(fcst_dir0, fcst_dir_name, self.fcst_run_name)
        self.input_dir = self.work_dir / 'Input'

        # Set file basename based on forecast run type
        self.basename_opt = (
            'cold_start' if self.use_cold_start
            else ('warm_start' if self.use_warm_start
                  else ('hind' if self.use_hindcast
                        else ('lagged_ens' if self.use_lagged_ens
                              else 'fcst')))
        )

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
        cat_req_columns = {'gage_id', 'div_id'}
        if not cat_req_columns.issubset(self.cat_grp_df.columns):
            missing_cols = cat_req_columns - set(self.cat_grp_df.columns)
            try:
                raise ValueError(f"Regionalization formulation file is missing required columns: {missing_cols}")
            except ValueError as e:
                logger.critical(e)
                raise

        if self.cat_grp_df["div_id"].isnull().all():
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
        self.grp_to_cat = (self.cat_grp_df.groupby("gage_id")["div_id"].apply(list).to_dict())

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
            'ueb': ['ems', 'cg', 'zo', 'rho', 'rhog', 'ks', 'de', 'avo', 'df', 'apr', 'cc', 'hcan', 'lai', 'subalb'],
            'smp': ['maxsmc', 'satpsi', 'b'],
            'sft': ['maxsmc', 'satpsi', 'b']
        }

        # Parameter remapping for smp, sft
        param_name_map = {
            ('smp', 'maxsmc'): 'smcmax',
            ('sft', 'maxsmc'): 'smcmax'
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
                            model_param = param_name_map.get((mod, param), param)
                            param_values[model_param] = float(value)
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

    def _parse_config(self):
        """
        Parse sections from input.config file
        """
        # reassign config sections for convenience
        self.conf1 = self.input_configs.get('General')
        self.run_type = self.conf1.get("run_type") if self.conf1 else None
        self.domain = self.conf1.get("domain") if self.conf1 else None
        self.environment = self.conf1.get("environment") if self.conf1 else None
        self.basin = self.conf1['basin'] if self.conf1 else None
        self.subset_type = self.conf1.get("subset_type") if self.conf1 else None

        # Retrieve module properties inputs
        self.module_prop = self.input_configs.get("ModuleProperties")
        self.aet_rootzone = self.module_prop.get("cfe_aet_rootzone") if self.module_prop else 0
        self.pet_method = self.module_prop.get("pet_method") if self.module_prop else None

        # Retrieve NWM output variable inputs
        self.nwm_output_sec = self.input_configs.get("NWMOutput")
        self.output_nwm_vars = self.nwm_output_sec.get('nwm_output_variables') if self.nwm_output_sec else False

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

    def _parse_realization(self):
        """
        Read existing formulation modules from realization file
        """
        # Read modules from global or grouped formulation
        if 'global' in self.real_config:
            real_modules_sec = self.real_config['global']['formulations'][0]['params']['modules']
            real_modules = [m['params']['model_type_name'] for m in real_modules_sec]
            self.modules = [settings.modules_all[settings.modules_all['name_config'] == m].iloc[0]['module'] for m in real_modules]
        elif 'formulation_groups' in self.real_config:
            self.grp_to_form = {}
            self.grp_to_cat = {}
            self.grp_aet_rootzone = {}
            all_modules = []

            # Reconstruct grp_to_form from formulation groups
            for grp, forms in self.real_config['formulation_groups'].items():
                grp_modules = []
                for form in forms:
                    for m in form['params']['modules']:
                        name = m['params']['model_type_name']
                        module = settings.modules_all[settings.modules_all['name_config'] == name].iloc[0]['module']
                        grp_modules.append(module)
                        if module not in all_modules:
                            all_modules.append(module)
                self.grp_to_form[grp] = grp_modules
                self.grp_aet_rootzone[grp] = 0

            # Reconstruct grp_to_cat from catchments section
            for cat_id, cat_config in self.real_config.get('catchments', {}).items():
                grp = cat_config.get('formulations')
                if grp:
                    self.grp_to_cat.setdefault(grp, []).append(cat_id)

            self.modules = all_modules

        else:
            logger.critical("No support formulation format found in realization file.")
            raise ValueError("realization file must contain 'global' or 'formulation_groups'.")

        logger.info("Parsed modules and hydrofabric geopackage from existing realization file")

    def _get_nwm_output_variables(self):
        """
        Retrieve NWM output variables for a given formulation, including required adapter modules
        """

        logger.info("Run configured to produce full set of NWM output variables")

        if self.run_type == 'regionalization' or hasattr(self, 'grp_to_form'):
            # Query NWM output variables and adapters per formulation group
            self.grp_to_adapters = {}
            self.grp_to_nwm_output_dicts = {}
            all_adapters = set()

            for grp, modules in self.grp_to_form.items():
                nwm_output_dicts = get_providers_for_formulation(modules)
                adapters = list(set(r["provider"] for r in nwm_output_dicts if r["provider"] not in modules))

                # Add sloth if required
                mod_adapters = modules + adapters
                if (any(x in mod_adapters for x in ['cfes', 'cfex', 'lasam'])) or ('topmodel' in mod_adapters and 'smp' in mod_adapters) or ('sac' in mod_adapters and 'smp' in mod_adapters) and 'sloth' not in mod_adapters:
                    adapters = ['sloth'] + adapters

                self.grp_to_adapters[grp] = adapters
                self.grp_to_nwm_output_dicts[grp] = nwm_output_dicts
                all_adapters.update(adapters)
                logger.info(f"Adapter modules to produce full set of NWM output variables for group {grp}: {adapters}")

            self.adapters = list(all_adapters)

        else:
            # Query NWM output variables and providers for existing formulation
            self.nwm_output_dicts = get_providers_for_formulation(self.modules)

            # Identify required adapter modules that need to be added as non-interacting modules in the formulation
            self.adapters = list(set(r["provider"] for r in self.nwm_output_dicts if r["provider"] not in self.modules))

            # Add sloth to modules if required
            mod_adapters = self.modules + self.adapters
            if (any(x in mod_adapters for x in ['cfes', 'cfex', 'lasam'])) or ('topmodel' in mod_adapters and 'smp' in mod_adapters) or ('sac' in mod_adapters and 'smp' in mod_adapters) and 'sloth' not in mod_adapters:
                self.adapters = ['sloth'] + self.adapters

            logger.info(f"Adapter modules required to produce full set of NWM output variables: {self.adapters}")

    def _create_input_dir(self):
        """
        Create input directory to store realization file and BMI config files
        """
        # Set run directory based on run_type
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
        log_path = os.path.join(self.work_dir, 'logs')
        safe_run_type = re.sub(r"[^A-Za-z0-9._-]", "_", self.run_type)

        # Initialize logging
        global logger
        ewts.logger.reset_logger(ewts.MSW_MGR_ID)
        logger = ewts.logger.setup_logger(
            ewts.MSW_MGR_ID,
            level="INFO",
            log_dir=log_path,
            log_file_name=f"msw_mgr_{safe_run_type}.log",
            running_in_ngen=False,
            enabled=True,
            bind_now=True,
        )

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
        self.forcing_static_dir = self.forcingSec.get('forcing_static_dir', None)
        self.scratch_dir_override = self.forcingSec.get("scratch_dir_override", None)
        self.forcing_product_versions = self.forcingSec.get(
            "forcing_product_versions", None
        )

        # Raise error if forecast or cold start is run with CSV provider
        if self.forcing_provider == 'csv' and self.run_type in ('forecast', 'cold_start'):
            msg = f"Run type {self.run_type} requires bmi forcing provider, but {repr(self.forcing_provider)} was provided"
            logger.critical(msg)
            raise ValueError(msg)

        # Retrieve cold_start_time
        self.cold_start_datetime = self.forcingSec.get('cold_start_datetime', None)

        if self.forcing_provider == 'bmi' and self.forcing_configuration is not None:

            # Set forcing engine variables for forecast
            if self.forcing_configuration not in ['nwm', 'aorc']:

                # Retrieve forcing engine variables
                cycle_datetime = self.forcingSec.get('cycle_datetime')

                # Construct cycle date and cycle hour
                cycle_dt = datetime.strptime(cycle_datetime, settings.DEFAULT_DATETIME_FORMAT)
                self.cycle_date = cycle_dt.strftime("%Y-%m-%d")
                self.cycle_hour = cycle_dt.strftime("%H") + "z"

                # Construct forcing template file name
                if self.use_cold_start:
                    forcing_region = next((f"_{reg}" for reg in ["alaska", "hawaii", "puertorico"] if reg in self.forcing_configuration), "")
                    self.forcing_configuration_str = f"cold_start{forcing_region}_config.yml"

                elif self.use_warm_start:
                    forcing_region = next((f"_{reg}" for reg in ["alaska", "hawaii", "puertorico"] if reg in self.forcing_configuration), "")
                    self.forcing_configuration_str = f"standard_ana{forcing_region}_config.yml"
                elif self.use_lagged_ens:
                    # Check that use_lagged_ens is only used with medium_range configuration
                    if self.forcing_configuration != "medium_range":
                        msg = f"Lagged ensemble run must use medium range forcing configuration. {self.forcing_configuration} configuration cannot be used for a lagged ensemble."
                        logger.critical(msg)
                        raise ValueError(msg)
                    self.forcing_configuration_str = f"{self.forcing_configuration}_{self.lagged_ens_mem}_config.yml"
                else:
                    self.forcing_configuration_str = f"{self.forcing_configuration}_config.yml"

                # Initialize fcst_lookback
                self.fcst_lookback = 0

                # Read fcst_template to retrieve lookback used to set cold start/warm start end time
                if self.use_cold_start or self.use_warm_start:
                    fcst_template_file = (Path(self.forcing_template_dir) / f"{self.forcing_configuration}_config.yml").absolute()
                    if fcst_template_file.exists():
                        try:
                            with open(fcst_template_file) as f:
                                fcst_template = yaml.safe_load(f)
                        except FileNotFoundError as e:
                            logger.critical(f'Config file does not exist: {self.forcing_template_file}\n{e}')
                            raise
                        except yaml.YAMLError as e:
                            logger.critical(f"YAML parsing error in config file: {self.forcing_template_file}\n{e}")
                            raise
                        except Exception as e:
                            logger.critical(f"Unexpected error loading config at: {self.forcing_template_file}\n{e}")
                            raise
                        self.fcst_lookback = 0 if fcst_template['LookBack'] == -9999 else int(fcst_template['LookBack'] / 60)

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
                self.fcst_start, self.fcst_end = gfun.create_fcst_times(self.forcing_template, self.cycle_date, self.cycle_hour, self.use_cold_start,
                                                                        self.use_warm_start, self.hind_cycle, self.prev_hind_cycle, self.forcing_lag, self.cold_start_datetime, self.fcst_lookback)
                self.time_period = {"run_time_period": {self.run_type: [self.fcst_start, self.fcst_end]}}

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
        elif self.run_type in ('regionalization', 'default'):
            # Use fcst_start/fcst_end if set by forcing engine, otherwise fall back to config start and end times
            if getattr(self, 'fcst_start', None) and getattr(self, 'fcst_end', None):
                start = self.fcst_start
                end = self.fcst_end
            else:
                start = self.conf1['start_period']
                end = self.conf1['end_period']
                if not start or not end:
                    missing = [k for k, v in {'start_period': start, 'end_period': end}.items() if not v]
                    err = f"Missing required General config key(s) for default run: {', '.join(missing)}"
                    logger.critical(err)
                    raise ValueError(err)
            run_key = 'region' if self.run_type == 'regionalization' else 'default'
            self.time_period = {"run_time_period": {run_key: [start, end]}}

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

    @staticmethod
    def file_crs_epsg(file_name: str) -> int:
        logger.debug(f"Getting EPSG code of: {file_name}")
        gdf = gpd.read_file(file_name, layer='divides')
        return gdf.crs.to_epsg()

    def _extract_hydrofabric(self):
        """
        Extract hydrofabric geopackage and form catchment, nexus, and crosswalk files
        """

        # Retrieve gpkg from Icefabric API or symlink existing file if provided
        self.gpkg_file = self.conf3.get('hydrofab_file')
        if self.gpkg_file is None:
            # If gpkg_file not provided, retrieve gpkg from icefabric and save to file
            self.gpkg_file = gfun.call_icefabric_gpkg(self.basin, self.subset_type, self.domain, self.input_dir, self.environment, 'nhf')

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
            # Reproject geopackage to EPSG:4326
            logger.info(f"Reprojecting gpkg {self.gpkg_file} to EPSG:4326")
            try:
                gfun.reproject_gpkg(self.gpkg_file, self.cat_file)
            except Exception as e:
                logger.critical(str(e))
                raise

    def _read_hydrofabric(self):
        """
        Read catchment divides and flowpaths layers from hydrofabric
        """
        # Read catchment parameter values from geopackage divide-attributes
        gpkg_path = self.gpkg_cats if self.run_type in ('cold_start', 'warm_start', 'hindcast', 'lagged_ens', 'forecast') else self.gpkg_file

        # Read catchment divides, flowpaths, and gages layers from hydrofabric
        try:
            self.divides_df = gpd.read_file(gpkg_path, layer='divides')
            self.catids = self.divides_df['div_id'].tolist()
            self.divides_df.set_index('div_id', inplace=True)
            self.flowpaths_df = gpd.read_file(gpkg_path, layer='flowpaths')
            self.flowpaths_df.set_index('div_id', inplace=True)
            self.gages_df = gpd.read_file(gpkg_path, layer='gages')
        except Exception as e:
            logger.critical(f"Error while reading geopackage file: {e}")
            raise

        # Modify divides_df to set values of b, smcmax, satpsi values and set to defaults if they equal 0
        # Remove code after EDFS fixes NHF attributes
        self.divides_df.loc[self.divides_df['smcmax_mean'] == 0, 'smcmax_mean'] = 0.48
        self.divides_df.loc[self.divides_df['psisat_geomean'] == 0, 'psisat_geomean'] = 0.163
        self.divides_df.loc[self.divides_df['bexp_mode'] == 0, 'bexp_mode'] = 7.272

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
        if (any(x in self.modules for x in ['cfes', 'cfex', 'lasam'])) or ('topmodel' in self.modules and 'smp' in self.modules) or ('sac' in self.modules and 'smp' in self.modules) and 'sloth' not in self.modules:
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

        # make sure SMP, SFT are paired with Noah-OWP-Modular
        if any(m in self.modules for m in ('smp', 'sft')) and 'noah' not in self.modules:
            try:
                raise ValueError("NOAH-OWP-Modular required to supply inputs for SMP and SFT Add NOAH-OWP-Modular to formulation.")
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

        # If Topoflow-glacier in modules,validate glacier coverage and create grouped realizations
        if 'topoflow-glacier' in self.modules:

            # Retrieve list of catchments where glaciated percent >= 50
            glacier_thresh = 50
            topo_cats = self.divides_df[self.divides_df['glacier_percent'] >= glacier_thresh].index.tolist()
            nontopo_cats = self.divides_df[self.divides_df['glacier_percent'] < glacier_thresh].index.tolist()

            # Ensure catchments exist where topoflow-glacier can be applied
            if len(topo_cats) == 0:
                logger.warning(f"No catchments with >={glacier_thresh}% glacier coverage. "
                               "Removing Topoflow-Glacier from formulation.")
                self.modules.remove('topoflow-glacier')
                logger.info(f"Updated module list (TopoFlow removed): {self.modules}")
            else:
                # Create grouped realizations if glaciated catchments exist
                mod_notopo = self.modules.copy()
                mod_notopo.remove('topoflow-glacier')
                self.grp_to_form = {}
                self.grp_to_form['group_1'] = mod_notopo
                self.grp_to_form['group_2'] = ['topoflow-glacier']

                self.grp_to_cat = {'group_1': topo_cats,
                                   'group_2': nontopo_cats}

                # If CFE in modules, retrieve is_aet_rootzone flag
                self.grp_aet_rootzone = {}
                self.grp_aet_rootzone['group_1'] = self.aet_rootzone
                self.grp_aet_rootzone['group_2'] = 0

                logger.info(f"Final list of modules in formulation: 'group1': {mod_notopo}, 'group2': ['topoflow-glacier']")

    def _parse_reg_modules(self):
        """
        Retrieve modules from regionalization formulation file and ensure formulation is valid
        This could potentially be combined with _parse_modules to not repeat code
        """
        logger.info(f"Available module names: {settings.modules_all['name_ui'].tolist()}")
        self.grp_to_form = {}
        self.grp_aet_rootzone = {}

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
            if (any(x in modules for x in ['cfes', 'cfex', 'lasam'])) or ('topmodel' in modules and 'smp' in modules) or ('sac' in modules and 'smp' in modules) and 'sloth' not in modules:
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

            # make sure SMP, SFT are paired with Noah-OWP-Modular
            if any(m in modules for m in ('smp', 'sft')) and 'noah' not in modules:
                try:
                    raise ValueError(f"NOAH-OWP-Modular required to supply inputs for SMP and SFT. Add NOAH-OWP-Modular to formulation for {row['gage_id']}.")
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

            # If CFE in modules, retrieve aet_rootzone flag
            self.grp_aet_rootzone[row['gage_id']] = 0
            if any(m in modules for m in ['cfes', 'cfex']):
                if 'is_aet_rootzone' in self.reg_df.columns:
                    self.grp_aet_rootzone[row['gage_id']] = row['is_aet_rootzone']

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

                # make sure only one module is selected for each process (except for Soil_moisture, Glacier_snow, and Evapotranspiration)
                if len(mods) > 1 and p1 not in ['Soil_moisture', 'Glacier_snow', 'Evapotranspiration']:
                    try:
                        raise Exception(f'Only one module can be selected for {p1} process')
                    except Exception as e:
                        logger.critical(e)
                        raise

                # one and only one module must be selected for rainfall-runoff
                if (p1 in ['Rainfall_runoff']) and (len(mods) == 0):
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
        Map catchments to formulation groups and assign aet_rootzone flags for cfe
        """
        # Relate catchments and their groups
        if hasattr(self, 'grp_to_cat') and self.grp_to_cat:
            self.cat_to_grp = {}
            self.cat_to_aet_rootzone = {}
            for grp, cats in self.grp_to_cat.items():
                for cat in cats:
                    self.cat_to_grp[cat] = grp
                    # Assign aet_rootzone flags for cfe
                    self.cat_to_aet_rootzone[cat] = self.grp_aet_rootzone.get(grp, 0)

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
        modules1 = []
        if self.run_type == 'regionalization' or (hasattr(self, 'grp_to_form') and self.grp_to_form):
            modules1 = list(set(m1 for form in self.grp_to_form.values() for m1 in form if m1 not in ['troute', 'lstm', 'topoflow-glacier']))
            self.all_mod = modules1.copy()

            # Add LSTM to all_mod if it's used in a formulation
            for mod in ['lstm', 'topoflow-glacier']:
                if any(mod in form for form in self.grp_to_form.values()):
                    self.all_mod.append(mod)
        else:
            modules1 = [m1 for m1 in self.modules if m1 not in ['troute', 'lstm', 'topoflow-glacier']]

        # Append adapter modules to modules1
        if self.output_nwm_vars:
            modules1 += self.adapters

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
                logger.critical(f"Failed to remove existing {symlink_path}: {e}")
                raise

        # Link ngen executable
        try:
            os.symlink(exe_path, symlink_path)
            logger.info("Created symlink to ngen executable")
        except OSError as e:
            logger.critical(f"Failed to create symlink: {symlink_path} -> {exe_path}: {e}")
            raise

    def _extract_forcing(self):
        """
        Extract forcing files and symlink to input directory
        """

        # For csv provider
        if self.forcing_provider == 'csv':

            # Create forcing directory
            self.forcing_path = os.path.join(self.input_dir, 'forcing')

            try:
                os.makedirs(self.forcing_path, exist_ok=True)
            except Exception as e:
                logger.critical(f"Invalid forcing directory: {e}. Check `main_dir` variable")
                raise

            # Retrieve forcing_provider and forcing_dir
            self.forcing_dir = (self.forcingSec.get('forcing_dir', "") or None)

            # Symlink forcing files
            missing_catchment_files = []
            for catID in self.catids:
                ffile = os.path.join(self.forcing_dir, f'{catID}.csv')
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
                            logger.critical(f"Failed to remove existing {target}: {e}")
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

            # Set dummy forcing path
            self.forcing_path = ''

            # Set target directory for forcing config file
            self.forcing_config_dir = Path(self.input_dir) / 'forcing_config'
            self.forcing_config_file = self.forcing_config_dir / self.forcing_configuration_str

            # Set geopackage file path
            gpkg_file = self.cat_file if hasattr(self, "cat_file") and self.cat_file else self.gpkg_cats

            if self.forcing_configuration not in ['nwm', 'aorc']:
                # Update dynamic parameters in forcing engine configuration file
                gfun.update_fcst_forcing_config(self.cycle_date, self.cycle_hour, self.root_dir, self.forcing_template, gpkg_file, self.forcing_config_dir,
                                                self.forcing_config_file, self.use_cold_start, self.use_warm_start, self.hind_cycle, self.prev_hind_cycle,
                                                self.forcing_lag, self.cold_start_datetime, self.fcst_lookback,
                                                scratch_dir_override=self.scratch_dir_override,
                                                forcing_product_versions=self.forcing_product_versions,
                                                )
            else:
                # Update historical dynamic parameters in forcing engine configuration file
                gfun.update_hist_forcing_config(self.time_period, self.root_dir, self.forcing_template, gpkg_file, self.forcing_config_dir, self.forcing_config_file, self.run_type, self.domain, self.forcing_static_dir)

            logger.info(f"Configured BMI forcing engine: {self.forcing_config_file}")

    def _extract_streamflow_obs(self):
        """
        Extract streamflow gage observations if provided
        """
        # Extract streamflow observation
        if 'obs_dir' in self.conf3.keys() and self.conf3['obs_dir'] is not None:
            try:
                obs = pd.read_csv(os.path.join(self.conf3['obs_dir'], self.basin + '_hourly_discharge.csv'))[['time', 'q_cms']]
                obs = obs.rename(columns={'time': 'value_date', 'q_cms': 'obs_flow'})
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
            if self.output_nwm_vars:
                self.output_dict[s1] = True
            elif (s1 not in self.conf1.keys()) or (self.conf1[s1] is None) or (self.conf1[s1] == ''):
                # Default output_precip to True if not specified
                self.output_dict[s1] = True if s1 == 'output_precip' else False
            else:
                self.output_dict[s1] = self.conf1[s1]

        # define depth (in meters) for output soil moisture
        val = self.conf1.get("sm_frac_depth") if self.conf1 else None
        self.output_dict["sm_frac_depth"] = 0.4 if val in (None, "") else float(val)
        self.output_dict["sm_profile_depth"] = (
            [float(v) for v in self.conf1["sm_profile_depth"]]
            if self.conf1 is not None and "sm_profile_depth" in self.conf1 and self.conf1["sm_profile_depth"] is not None
            else [0.1, 0.4, 1.0, 2.0]
        )

        # Retrieve calib and valid output variable settings
        self.calib_output_vars = self.conf2.get('calib_output_vars') if self.conf2 else None
        self.valid_output_vars = self.conf2.get('valid_output_vars') if self.conf2 else None

        self.calib_output_vars = False if self.calib_output_vars is None else self.calib_output_vars
        self.valid_output_vars = True if self.valid_output_vars is None else self.valid_output_vars

        logger.info("Set output variables")

    def _create_bmi_configs(self, is_regionalization: bool = False):
        """
        Generate BMI config files for modules or link to existing config files
        Create BMI configs for formulation and adapter modules separately to ensure that adapters don't influence existing formulation

        Parameters
        ----------
        is_regionalization: bool
            If True, generate configs for regionalziation mode with multiple groups
            If False, generate configs for single formulation calibration/default mode.
        """
        if is_regionalization:
            self.run_configs = ['_troute_config_region.yaml']
            mod_all = list(dict.fromkeys(item for lst in self.grp_to_form.values() for item in lst))
        else:
            if self.run_type == 'calibration':
                self.run_configs = ['_troute_config_calib.yaml', '_troute_config_valid_control.yaml', '_troute_config_valid_best.yaml']
            elif self.run_type == 'default':
                self.run_configs = ['_troute_config_default.yaml']

        if self.run_type == 'regionalization' or (hasattr(self, 'grp_to_cat') and self.grp_to_cat):
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

        # Define bmi config loop iterations (modules to creat configs for; is adapter loop)
        # Only create adapter modules if requested when running forecast
        if hasattr(self, '_building_fcst_realization') and self._building_fcst_realization:
            loop_configs = []
        # Create bmi configs for modules in existing formulation
        else:
            loop_configs = [(mod_all, False)]

        # Add adapter modules if output_nwm_vars requested
        if hasattr(self, 'adapters') and self.adapters:
            adapter_all = [m for m in self.adapters if m != 'sloth']
            loop_configs.append((adapter_all, True))

        # loop through modules to create input files
        for mods_to_create, is_adapter_loop in loop_configs:
            for m1 in mods_to_create:

                # module name used by the UI
                m2 = settings.modules_all.loc[settings.modules_all['module'] == m1, 'name_ui'].iloc[0]

                # define module input directory
                mod_input_dir = os.path.join(self.input_dir, m2 + '_input')

                # Remove existing symlinked input dir
                if os.path.isdir(mod_input_dir) and os.path.islink(mod_input_dir):
                    try:
                        os.unlink(mod_input_dir)
                    except Exception as e:
                        logger.critical(f"failed to remove existing {mod_input_dir}: {e}")
                        raise

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

                # Determine cat_mod and mods_to_pass based on run_type and loop type
                if is_regionalization or hasattr(self, 'grp_to_form') and self.grp_to_form:
                    if is_adapter_loop:
                        cat_mod = [cat for grp, grp_adapters in self.grp_to_adapters.items()
                                   if m1 in grp_adapters for cat in self.grp_to_cat[grp]]
                        form_cat = [self.grp_to_form[grp] + self.grp_to_adapters[grp]
                                    for grp, grp_adapters in self.grp_to_adapters.items()
                                    if m1 in grp_adapters for _ in self.grp_to_cat[grp]]
                    else:
                        cat_mod = self.mod_to_cat[m1]
                        form_cat = [self.cat_to_form[cat] for cat in cat_mod]
                    mods_to_pass = form_cat
                else:
                    cat_mod = self.catids.copy()
                    mods_to_pass = mod_all + self.adapters if is_adapter_loop and hasattr(self, 'adapters') else mod_all

                # Create BMI config files from scratch if paths not provided
                if m1 in ['cfes', 'cfex']:
                    gfun.create_cfe_input(cat_mod, mods_to_pass, self.divides_df, mod_input_dir, self.run_type,
                                          self.cat_to_aet_rootzone if is_regionalization or hasattr(self, 'grp_to_form') else self.aet_rootzone,
                                          self.output_dict['sm_profile_depth'])
                elif m1 == 'topmodel':
                    gfun.create_topmodel_input(cat_mod, self.divides_df, self.flowpaths_df, mod_input_dir)
                elif m1 == 'ueb':
                    gfun.create_ueb_input(cat_mod, self.time_period, self.divides_df, self.conf3[m1 + '_parameter_dir'], mod_input_dir, self.run_type)
                elif m1 == 'snow17':
                    gfun.create_snow17_input(cat_mod, self.divides_df, mod_input_dir)
                elif m1 == "pet":
                    gfun.create_pet_input(cat_mod, self.divides_df, mod_input_dir, self.pet_method)
                elif m1 == "sac":
                    gfun.create_sac_input(cat_mod, self.divides_df, mod_input_dir)
                elif m1 == 'noah':
                    gfun.create_noah_input(cat_mod, self.time_period, self.divides_df, self.conf3[m1 + '_parameter_dir'], mod_input_dir, self.run_type)
                elif m1 == 'lstm':
                    gfun.create_lstm_input(cat_mod, self.divides_df, self.conf3['lstm_parameter_dir'], mod_input_dir)
                elif m1 == 'sft':
                    sft_dir = os.path.join(self.input_dir, 'sft_input')
                    smp_dir = os.path.join(self.input_dir, 'smp_input')

                    if is_regionalization or (hasattr(self, 'grp_to_form') and self.grp_to_form):
                        # Loop through schemes that could be paired with SMP/SFT
                        for scheme in ['cfes', 'cfex', 'lasam', 'topmodel', 'sac']:
                            if is_adapter_loop:
                                # Find groups where scheme is in formulation or adapter and sft is in adapter
                                scheme_sft_grps = [grp for grp, mods in self.grp_to_form.items()
                                                   if (scheme in mods or scheme in self.grp_to_adapters.get(grp, [])) and 'sft' in self.grp_to_adapters.get(grp, [])]
                            else:
                                # Find groups where scheme and sft are both in the formulation
                                scheme_sft_grps = [grp for grp, mods in self.grp_to_form.items()
                                                   if scheme in mods and 'sft' in mods]

                            if scheme_sft_grps:
                                # Retrieve catchments and formulations for groups using this scheme/sft combination
                                scheme_cat = [cat for grp in scheme_sft_grps for cat in self.grp_to_cat[grp]]
                                scheme_form = [self.grp_to_form[grp] + self.grp_to_adapters[grp]
                                               for grp in scheme_sft_grps for _ in self.grp_to_cat[grp]] if is_adapter_loop else [self.cat_to_form[cat] for cat in scheme_cat]
                                gfun.create_sft_smp_input(scheme_cat, scheme_form, self.divides_df, sft_dir, smp_dir, self.run_type,
                                                          self.output_dict['sm_frac_depth'], self.output_dict['sm_profile_depth'])
                    else:
                        gfun.create_sft_smp_input(cat_mod, mods_to_pass, self.divides_df, sft_dir, smp_dir, self.run_type,
                                                  self.output_dict['sm_frac_depth'], self.output_dict['sm_profile_depth'])
                elif m1 == 'smp':
                    pass
                elif m1 == 'lasam':
                    gfun.create_lasam_input(cat_mod, mods_to_pass, self.divides_df, mod_input_dir, self.conf3['lasam_parameter_dir'], self.run_type)
                elif m1 == 'topoflow-glacier':
                    gfun.create_topoflow_glacier_input(cat_mod, self.divides_df, self.time_period, mod_input_dir, self.run_type)
                elif m1 == 'troute':
                    routing_config_file = os.path.join(self.work_dir + '/Input', '{}'.format(self.basin))
                    gfun.create_troute_config(self.cat_file, self.time_period, routing_config_file, self.run_configs, self.run_type)

                    if m1 != 'troute':
                        logger.info(f'{m1}: input config files created at: {mod_input_dir}')

        log_msg = "Created BMI config files for all modules in each regionalization formulation" if is_regionalization else "Created BMI config files for all modules in the formulation"
        logger.info(log_msg)

    def _configure_model_states(self):
        """
        Configure state saving configuration in state saving and loading realization sections
        """
        if not self.load_state_from and not self.save_state:
            logger.info("No model state management configured.")

        # Ensure model state directories exist
        if self.save_state:
            self.save_state_to = Path(self.work_dir) / "state_save"
            self.save_state_to.mkdir(parents=True, exist_ok=True)
            logger.info(f"State save directory: {self.save_state_to}")

        if self.load_state_from:
            if not self.load_state_from.exists():
                msg = f"State load directory does not exist: {self.load_state_from}"
                logger.critical(msg)
                raise FileNotFoundError(msg)
            logger.info(f"State load directory: {self.load_state_from}")

        # Initialize state saving array
        state_saving = []

        # Add state loading configuration if specified
        if self.load_state_from:
            load_config = {
                "direction": "load",
                "label": "State load",
                "path": str(self.load_state_from),
                "type": "FilePerUnit",
                "when": "StartOfRun"
            }
            state_saving.append(load_config)
            logger.info("Configured state loading at start of run")

        # Add state saving configuration if specified
        if self.save_state:
            save_config = {
                "direction": "save",
                "label": "Save at end of run",
                "path": str(self.save_state_to),
                "type": "FilePerUnit",
                "when": "EndOfRun"
            }
            state_saving.append(save_config)
            logger.info("Configured state saving at end of run")

        # Add state saving to real_config if there are entries
        if state_saving:
            self.real_config['state_saving'] = state_saving
            logger.info("Model state configuration set in realization file")

    def _set_bmi_config_dir(self):
        """
        Set directories of BMI config files
        """
        if hasattr(self, '_building_fcst_realization') and self._building_fcst_realization:
            base_mods = []
        elif self.run_type == 'regionalization' or (hasattr(self, 'grp_to_form') and self.grp_to_form):
            base_mods = list(set(m1 for form in self.grp_to_form.values() for m1 in form if m1 != 'troute'))
        else:
            base_mods = self.modules

        bmi_mods = (self.adapters + base_mods) if self.output_nwm_vars else base_mods

        self.bmi_dir = {}
        for m1 in bmi_mods:
            m2 = settings.modules_all.loc[settings.modules_all['module'] == m1, 'name_ui'].iloc[0]
            self.bmi_dir[m1] = os.path.join(self.input_dir, m2 + '_input')

    def _update_fcst_noah_ueb_topo(self):
        """
        For UEB, TopoFlow-Glacier, and Noah-OWP-Modular, create new BMI config files with new time info, and
        update path to BMI configs in realization file accordingly
        """
        self.real_config = gfun.update_noah_ueb_topo_times(self.real_config, self.input_dir, self.basename_opt)
        logger.info("Updated noah and ueb config files for forecast if used")

    def _update_fcst_realization(self):
        """
        Update forcing and time related info in realization file
        Add NWM Output variable sections to realization if requested
        """
        self.real_config = gfun.update_forcing_in_realization(self.real_config, self.forcing_path, self.forcing_config_file, self.fcst_start, self.fcst_end, self.basename_opt)
        logger.info("Updated forecast realization file forcing and time information")

        # Update troute config file for forecast period
        self.real_config = gfun.update_troute(self.real_config, self.input_dir, self.basename_opt)

        if self.output_nwm_vars:
            self._apply_nwm_output_vars()

    def _assemble_realization(self):
        """
        Assemble realization file for calibration and default runs
        """
        # Set file paths
        routing_config_file = os.path.join(self.work_dir + '/Input', '{}'.format(self.basin) + self.run_configs[0])
        rt_dict = {"routing": {"t_route_config_file_with_path": routing_config_file}}

        # Assemble realization file
        if hasattr(self, 'grp_to_form') and self.grp_to_form:
            self.real_config, self.output_config = gfun.create_reg_realization_file(self.work_dir, self.lib_file, self.bmi_dir, self.forcing_provider, self.forcing_path, self.forcing_config_file,
                                                                                    self.time_period, rt_dict, self.output_dict, self.calib_output_vars, self.run_type, self.cat_to_grp, self.grp_to_form,
                                                                                    getattr(self, 'grp_params', {}))
        else:
            self.real_config, self.output_config = gfun.create_realization_file(self.work_dir, self.lib_file, self.bmi_dir, self.forcing_provider, self.forcing_path, self.forcing_config_file,
                                                                                self.modules, self.time_period, rt_dict, self.output_dict, self.calib_output_vars, self.run_type)

        # Update realization with NWM output variables if needed
        if self.output_nwm_vars:
            self._apply_nwm_output_vars()

    def _apply_nwm_output_vars(self):
        """
        Update realization config with NWM output variables for grouped or global formulations
        """
        if hasattr(self, 'grp_to_form') and self.grp_to_form:
            for grp in self.grp_to_form:
                self.real_config = gfun.update_realization_nwm_output(self.work_dir, self.lib_file, self.bmi_dir, self.forcing_provider,
                                                                      self.grp_to_adapters[grp], self.grp_to_form[grp], self.grp_to_nwm_output_dicts[grp], self.output_dict,
                                                                      self.real_config, self.run_type, grp=grp)
        else:
            self.real_config = gfun.update_realization_nwm_output(self.work_dir, self.lib_file, self.bmi_dir, self.forcing_provider,
                                                                  self.adapters, self.modules, self.nwm_output_dicts, self.output_dict,
                                                                  self.real_config, self.run_type)
        logger.info("Updated forecast realization file with NWM output variables and adapter modules")

    def _write_realization(self):
        """
        Write realization to file for all run types
        """
        # Set realization path based on run type
        if hasattr(self, '_building_fcst_realization') and self._building_fcst_realization:
            new_basename = os.path.basename(self.real_input_file).replace("valid_best", self.basename_opt)
            self.realization_file = Path(self.work_dir, new_basename)
        else:
            file_suffix = {'calibration': 'calib', 'regionalization': 'region'}.get(self.run_type, self.run_type)
            self.realization_file = self.work_dir + '/{}'.format(self.basin) + '_realization_config_bmi_' + file_suffix + '.json'

        # Write realization to file
        gfun.write_realization_to_file(self.real_config, self.realization_file)
        logger.info(f"Realization file created at: {self.realization_file}")

    def _write_partition(self):
        """
        Write parallel processing partition file
        """
        if getattr(self, "_building_fcst_realization", "") is True:
            cat_file = self.gpkg_cats
            partition_config_basename_prefix = "forecast"
            work_dir, sub_dir_name = os.path.split(self.input_dir)
        else:
            # Original behavior for "default", "calibration", and "regionalization", before forecast partitions were supported
            cat_file = self.cat_file
            partition_config_basename_prefix = self.basin
            work_dir = self.work_dir
            sub_dir_name = "Input"

        self.part_file = gfun.create_partition_file(self.parallelSec['partition_generator_exe'],
                                                    cat_file,
                                                    self.parallelSec['nprocs'],
                                                    work_dir,
                                                    partition_config_basename_prefix,
                                                    sub_dir_name) if self.parallelSec else None

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
        strategy = 'grouped' if 'topoflow-glacier' in self.modules else 'uniform'

        # Create crosswalk file between catchments and gages for calibration run
        self.walk_file = self.input_dir + '{}'.format(self.basin) + '_crosswalk.json'
        gfun.create_walk_file(self.basin, self.divides_df, self.gages_df, self.walk_file)
        logger.info(f"Crosswalk file created at: {self.walk_file}")

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
            if self.output_config and isinstance(next(iter(self.output_config.values())), dict):
                # Per group output variables
                general_dict['valid_output_vars_grp'] = {
                    grp: config['output_variables']
                    for grp, config in self.output_config.items()
                }
                general_dict['valid_output_headers_grp'] = {
                    grp: config['output_header_fields']
                    for grp, config in self.output_config.items()
                }
                general_dict['valid_output_units_grp'] = {
                    grp: config['output_units']
                    for grp, config in self.output_config.items()
                }
                general_dict['valid_output_index_grp'] = {
                    grp: config['output_index']
                    for grp, config in self.output_config.items()
                }
            else:
                # Global output variables
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
        self._extract_hydrofabric()
        self._read_hydrofabric()
        self._parse_modules()
        self._validate_processes()
        self._map_cat_to_grp()
        self._map_cat_to_form()
        self._map_mod_to_cat()
        self._set_lib_paths()
        self._extract_forcing()
        self._configure_forcing_engine()
        self._extract_streamflow_obs()
        self._set_output_vars()
        self._create_bmi_configs()
        self._set_bmi_config_dir()
        self._assemble_realization()
        self._write_realization()
        self._write_partition()
        self._create_calib_model_dict()
        self._write_calib_configuration()

        logger.info("Calibration run set up successfully")

        return self.realization_file

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
        self._extract_hydrofabric()
        self._read_hydrofabric()
        self._parse_reg_params()
        self._parse_reg_modules()
        self._validate_processes()
        self._map_cat_to_grp()
        self._map_cat_to_form()
        self._map_mod_to_cat()
        if self.output_nwm_vars:
            self._get_nwm_output_variables()
        self._set_lib_paths()
        self._symlink_ngen()
        self._extract_forcing()
        self._configure_forcing_engine()
        self._set_output_vars()
        self._create_bmi_configs(is_regionalization=True)
        self._set_bmi_config_dir()
        self._assemble_realization()
        self._write_realization()
        self._write_partition()

        logger.info("Regionalization run set up successfully")

        return self.realization_file

    def load_config_apply_overrides(self):
        """Load the config file from disk and apply overrides.
        If config overrides are applied with amend = False, then skip reading the config file."""
        if self.config_overrides and (not self.config_overrides_mode__amend):
            logging.info("Skipping load of config file since overrides will replace entire config (no amend)")
        else:
            self._load_config()
        self._override_config()

    def build_fcst_realization(self):
        """
        Creating realization file for cold start/warm start/forecast/hindcast/lagged ensemble runfrom validation yaml file and formatting other input files
        """
        self._building_fcst_realization = True

        self.load_config_apply_overrides()
        self._load_yaml()
        self._parse_config()
        self._create_fcst_dir()
        self._init_log()
        self._parse_yaml()
        self._load_realization()
        self._parse_forcing_engine()
        self._configure_forcing_engine()
        if self.output_nwm_vars:
            self._parse_realization()
            self._read_hydrofabric()
            self._map_cat_to_grp()
            self._map_cat_to_form()
            self._map_mod_to_cat()
            self._get_nwm_output_variables()
            self._set_lib_paths()
            self._set_output_vars()
            self._create_bmi_configs()
            self._set_bmi_config_dir()
        self._configure_model_states()
        self._update_fcst_noah_ueb_topo()
        self._update_fcst_realization()
        self._write_partition()
        self._write_realization()

        if self.use_cold_start:
            logger.info("Cold start run set up successfully")
        else:
            logger.info("Forecast run set up successfully")
        self._building_fcst_realization = False

        self._building_fcst_realization = False

        if self.save_state:
            return self.realization_file, self.save_state_to
        else:
            return self.realization_file

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
        self._extract_hydrofabric()
        self._read_hydrofabric()
        self._parse_modules()
        self._validate_processes()
        self._map_cat_to_grp()
        self._map_cat_to_form()
        self._map_mod_to_cat()
        if self.output_nwm_vars:
            self._get_nwm_output_variables()
        self._set_lib_paths()
        self._symlink_ngen()
        self._extract_forcing()
        self._configure_forcing_engine()
        self._set_output_vars()
        self._create_bmi_configs()
        self._set_bmi_config_dir()
        self._assemble_realization()
        self._write_realization()
        self._write_partition()

        logger.info("Default run set up successfully")

        return self.realization_file


def validate_topoflow_glacier(gpkg_file: str) -> dict:
    """Validate Topoflow-Glacier applicability by checking glacier coverage in basin catchments

    Args:
        gpkg_file: path to geopackage file
    """

    # Read attributes from provided geopackge
    attr_df = gpd.read_file(gpkg_file, layer='divides')

    # Count number of catchments with glacier percent >= 50%
    glacier_thresh = 50
    if "glacier_percent" in attr_df.columns:
        glacier_cat = (attr_df['glacier_percent'] >= glacier_thresh).sum()
    else:
        return {
            'result': False,
            'message': "'glacier_percent' column not found in geopackage attributes."
        }

    # Return json message for Topoflow-Glacier applicability
    if glacier_cat >= 1:
        return {'result': True}
    else:
        return {
            'result': False,
            'message': f'No catchments meet glacier coverage threshold of {glacier_thresh}% for Topoflow-Glacier Application'
        }
