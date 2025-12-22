"""
This module contains functions to manage the initial creation of configuration files

@author: Jeffrey Wade, Xia Feng, Nels Frazer
"""

import copy
import logging
from datetime import datetime
import json
import os
from pathlib import Path
import shutil

import pandas as pd
import yaml


logger = logging.getLogger(__name__)


def create_valid_config_file(yaml_file: Path, valid_run_path: Path, valid_config_file: Path, valid_run_name: str) -> None:
    """
    Create configuration yaml file for valiation control and best runs.

    Parameters:
    ----------
    yaml_file : calibration configuration yaml file
    valid_run_path : directory for validation run
    valid_config_file : realization configuration file for control or best run
    valid_run_name : control or best validation run

    """
    with open(yaml_file) as file:
        y = yaml.safe_load(file)

    d = copy.deepcopy(y)
    d['general']['name'] = valid_run_name
    f = d['general']['yaml_file']
    d['general']['yaml_file'] = os.path.join(valid_run_path, os.path.basename(f).replace('calib', valid_run_name))
    d['model']['realization'] = os.path.join(valid_run_path, valid_config_file)
    with open(d['general']['yaml_file'], 'w') as yfile:
        yaml.dump(d, yfile, sort_keys=False, default_flow_style=False, indent=2)
    logger.info("Config file for {} is created at {}".format(valid_run_name, d['general']['yaml_file']))


def create_valid_realization_file(agent: 'Agent', eval_params: 'EvaluationOptions', params: 'pd.DataFrame', valid_run_name: str) -> None:
    """
    Create model realization file for valiation control and best runs.

    Parameters:
    ----------
    agent : Agent object
    eval_params: EvaluationOptions object
    params :  calibration parameters
    valid_run_name: name for validation run (valid_best,valid_control,valid_worker#_iter#)

    """

    # Retrieve output variables from calib_yaml
    with open(agent.yaml_file) as file:
        y = yaml.safe_load(file)

    general_dict = y.get('general', {})

    if valid_run_name == "valid_control":
        agent.model.update_config(0, params)
    elif valid_run_name == "valid_best":
        if agent.algorithm != "dds":
            agent.model.update_config("global_best", params)
        else:
            agent.model.update_config(eval_params._best_params_iteration, params)
    else:
        agent.model.update_config(valid_run_name, params)

    # Write realization to file after updating configuration
    agent.model.strategy.write_realization_file(path=Path(agent.valid_path))

    # Create realization file for validation run
    # agent.model.update_config(0, params, path = Path(agent.valid_path))
    configfl = os.path.join(agent.valid_path, os.path.basename(str(agent.realization_file)))
    config_valid_file = os.path.join(agent.valid_path, os.path.basename(configfl).replace("calib", valid_run_name))
    shutil.move(configfl, config_valid_file)
    with open(config_valid_file) as fl:
        config_valid = json.load(fl)

    # Replace calib simulation time period with valid sumulation period
    config_valid['time']['start_time'] = datetime.strftime(eval_params._valid_range[0], '%Y-%m-%d %H:%M:%S')
    config_valid['time']['end_time'] = datetime.strftime(eval_params._valid_range[1], '%Y-%m-%d %H:%M:%S')

    # Set realization type
    if 'global' in config_valid and config_valid['global']:
        real_type = 'global'
    elif 'formulation_groups' in config_valid and config_valid['formulation_groups']:
        real_type = 'grouped'
    else:
        logger.critical("Realization file type not recognized.")

    # Replace forcing engine config file path with validation path
    if real_type == 'global':
        if config_valid['global']['forcing']['provider'] == 'ForcingsEngineLumpedDataProvider':
            fe_config = Path(config_valid['global']['forcing']['params']['init_config'])
            config_valid['global']['forcing']['params']['init_config'] = fe_config.with_name(fe_config.stem + '_valid' + fe_config.suffix)
    elif real_type == 'grouped':
        if config_valid['forcing_groups']['forcing_grp1']['provider'] == 'ForcingsEngineLumpedDataProvider':
            fe_config = Path(config_valid['forcing_groups']['forcing_grp1']['params']['init_config'])
            config_valid['forcing_groups']['forcing_grp1']['params']['init_config'] = fe_config.with_name(fe_config.stem + '_valid' + fe_config.suffix)

    # correct path for init_config for validation runs for modules with time periods info in these files
    # (currently Noah-OWP-Modular, UEB, and TopoFlow)
    if real_type == 'global':
        formulations = config_valid['global']['formulations']
    elif real_type == 'grouped':
        formulations = []
        for grp_name, grp_formulations in config_valid['formulation_groups'].items():
            formulations.extend(grp_formulations)

    for formulation in formulations:
        for m in formulation['params']['modules']:
            if m['params']['model_type_name'] in ['NoahOWP', 'UEB', 'BmiTopoflowGlacier']:
                m1 = m['params']['init_config']
                m['params']['init_config'] = os.path.join(os.path.dirname(m1), os.path.basename(m1).replace('calib', 'valid'))

    # Replace t-route yaml file
    rt = os.path.basename(config_valid['routing']['t_route_config_file_with_path']).replace('calib', valid_run_name)
    rt = os.path.join(os.path.dirname(config_valid['routing']['t_route_config_file_with_path']), rt)
    config_valid['routing']['t_route_config_file_with_path'] = rt

    # Add output variables to validation realization
    logger.info("Setting validation output variables")
    if real_type == "global":
        valid_output_vars = general_dict.get('valid_output_vars', [])
        valid_output_headers = general_dict.get('valid_output_headers', [])
        valid_output_units = general_dict.get('valid_output_units', [])
        valid_output_index = general_dict.get("valid_output_index", [])
        if len(valid_output_vars) != 0:
            output_vars = []
            for var, hdr, unit, idx in zip(valid_output_vars, valid_output_headers, valid_output_units, valid_output_index):
                entry = {"name": var, "header": hdr, "units": unit}
                if idx != "0":  # only include index if it's not the default 0
                    entry["index"] = idx
                output_vars.append(entry)
            config_valid['global']['formulations'][0]['params']['output_variables'] = output_vars
        else:
            config_valid['global']['formulations'][0]['params']['output_variables'] = []
    elif real_type == "grouped":
        # Support per-group output variables for Topoflow Glacier calibration
        valid_output_vars_grp = general_dict.get('valid_output_vars_grp', {})
        valid_output_headers_grp = general_dict.get('valid_output_headers_grp', {})
        valid_output_units_grp = general_dict.get('valid_output_units_grp', {})
        valid_output_index_grp = general_dict.get("valid_output_index_grp", [])

        for grp_name, grp_formulations in config_valid['formulation_groups'].items():
            # Get output vars for this group from yaml
            grp_valid_vars = valid_output_vars_grp.get(grp_name, [])
            grp_valid_headers = valid_output_headers_grp.get(grp_name, [])
            grp_valid_units = valid_output_units_grp.get(grp_name, [])
            grp_valid_index = valid_output_index_grp.get(grp_name, [])

        if len(valid_output_vars) != 0:
            output_vars = []
            for var, hdr, unit, idx in zip(grp_valid_vars, grp_valid_headers, grp_valid_units, grp_valid_index):
                entry = {"name": var, "header": hdr, "units": unit}
                if idx != "0":  # only include index if it's not the default 0
                    entry["index"] = idx
                output_vars.append(entry)
            for formulation in grp_formulations:
                formulation['params']['output_variables'] = output_vars
            logger.info(f"valid_output_vars set for group {grp_name}: {output_vars}")
        else:
            for formulation in grp_formulations:
                formulation['params']['output_variables'] = []

    logger.info(f"valid_output_vars set in realization: {config_valid['global']['formulations'][0]['params']['output_variables']}")

    # Write realization file for validation run
    with open(config_valid_file, 'w') as outfile:
        json.dump(config_valid, outfile, indent=4, default=str, separators=(", ", ": "), sort_keys=False)

    # Write yaml configuration file for validation run
    create_valid_config_file(agent.yaml_file, agent.valid_path, config_valid_file, valid_run_name)
