"""
This module contains a variety of functions to create different input files.

@author: Jeffrey Wade, Xia Feng
"""

import copy
import logging
import datetime
import ewts
import glob
import json
import os
import math
import subprocess
from ambiance import Atmosphere
from pathlib import Path
from typing import List, Union, Dict, Any, Tuple
from collections import OrderedDict
import geopandas as gpd
import shapely
import pyogrio
import pandas as pd
import yaml
import httpx

from mswm.utils import settings

logger = None

# Suppress pyogrio logging
logging.getLogger("pyogrio").setLevel(logging.CRITICAL)


class QuotedDumper(yaml.SafeDumper):
    pass


class QuotedValueDumper(yaml.SafeDumper):
    pass


class UnquotedDumper(yaml.SafeDumper):
    pass


class ForcingDumper(yaml.SafeDumper):
    pass


def quoted_str_presenter(dumper, data):
    return dumper.represent_scalar('tag:yaml.org,2002:str', data, style="'")


def inline_list_presenter(dumper, data):
    return dumper.represent_sequence('tag:yaml.org,2002:seq', data, flow_style=True)


def quoted_value_presenter(dumper, data):
    if isinstance(data, str):
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style="'")
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)


ForcingDumper.add_representer(list, inline_list_presenter)
QuotedDumper.add_representer(str, quoted_str_presenter)
QuotedValueDumper.add_representer(str, quoted_value_presenter)


def is_probably_regex(pattern):
    return any(c in pattern for c in ['^', '$', '.', '(', '[', '|', '\\'])


__all__ = [
    'init_ginput_logger',
    'call_icefabric_gpkg',
    'reproject_gpkg',
    'create_walk_file',
    'create_cfe_input',
    'create_noah_input',
    'create_sft_smp_input',
    'create_snow17_input',
    'create_ueb_input',
    'create_sac_input',
    'update_lstm_parameters',
    'create_symlinks',
    'create_lstm_config',
    'create_lstm_input',
    'create_pet_input',
    'create_lasam_input',
    'create_topoflow_glacier_input',
    'create_topmodel_input',
    'update_noah_ueb_topo_times',
    'update_troute',
    'create_troute_config',
    'create_fcst_times',
    'replace_forcing_placeholders',
    'update_fcst_forcing_config',
    'update_hist_forcing_config',
    'update_forcing_in_realization',
    'get_forcing_vars_map',
    'map_var_names_forcing_engine',
    'var_mapping',
    'get_model_type_name',
    'create_lib_symlinks',
    'get_sloth_params',
    'get_smp_var_map',
    'build_base_config',
    'build_module_config',
    'build_output_vars',
    'create_realization_file',
    'create_reg_realization_file',
    'find_module_index',
    'update_realization_nwm_output',
    'write_realization_to_file',
    'create_calib_config_file',
    'create_partition_file',
]


def init_ginput_logger():
    """"
    Initialize ginputfunc.py logger once MSWM named logger is created
    """
    global logger
    logger = ewts.get_logger(ewts.MSW_MGR_ID).get_bound_logger()


def call_icefabric_gpkg(
        basin: str,
        subset_type: str,
        domain: str,
        output_dir: str,
        environment: str,
        source: str,
) -> str:
    """ Query icefabric API for geopackage

    Parameters
    ----------
    basin: basin name string
    subset_type: subset type string ('gage' or 'vpu')
    domain: domain name string (conus, ak, hi, prvi)
    output_dir: location to save gpkg
    environment: environment for icefabric API ('test' or 'oe')
    source: hydrofabric version ('hf' or 'nhf')

    Returns
    ----------
    dictionary of initial parameter estimates
    """

    # Check for VPU or gage subset_type
    if subset_type == 'vpu':
        id_type = 'vpu_id'
        file_prefix = 'vpu_'
    elif subset_type == 'gage':
        id_type = 'gage_id'
        file_prefix = 'gauge_'
    else:
        raise ValueError(f"Invalid subset_type: '{subset_type}'. Valid options are 'gage' and 'vpu'")

    # Check source value
    if source not in ('hf', 'nhf'):
        raise ValueError(f"Invalid source: '{source}'. Valid options are 'hf' and 'nhf'")

    # Check environment value
    if environment not in ('test', 'oe'):
        raise ValueError(f"Invalid environment: '{environment}'. Valid options are 'test' and 'oe'")

    # Set base endpoint
    if environment == 'test':
        url = f"http://edfs.test.nextgenwaterprediction.com/api/v1/hydrofabric/{basin}/gpkg"
    elif environment == 'oe':
        url = f"https://edfs.oe.nextgenwaterprediction.com/api/v1/hydrofabric/{basin}/gpkg"

    # Build query parameters
    params = {"id_type": id_type,
              "source": source,
              "domain": domain,
              "layers": ["divides", "flowpaths", "network", "nexus", "virtual_nexus", "virtual_flowpaths", "waterbodies", "gages", "reference_flowpaths", "hydrolocations"],
              }

    # Set output file path
    gpkg_fp = os.path.join(output_dir, f"{file_prefix}{basin}.gpkg")

    # Call icefabric API endpoint to save geopackage
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            with open(gpkg_fp, "wb") as f:
                f.write(resp.content)
            print(f"Saved geopackage file from Icefabric API to {gpkg_fp}")
    except httpx.TimeoutException as e:
        print(f"Icefabric API call timed out for {basin} gpkg. Request URL: {url}, params: {params}, {e}")
        raise
    except httpx.HTTPStatusError as e:
        print(f"Icefabric API call {basin} gpkg failed. Request URL: {url}, params: {params}, {e}")
        raise
    except ValueError:
        print(f"Icefabric API call did not return valid results for gpkg: {basin}.")
        raise
    except (OSError, IOError) as e:
        print(f"Failed to write gpkg file: {e}")
        raise

    # Return output gpkg path
    return gpkg_fp


def reproject_gpkg(src_file: Union[str, Path], dst_file: Union[str, Path], epsg: int = 4326) -> None:
    """
    Reproject all layers in a geopackage to a target CRS. Non-spatial tables are copied as is
    Reproject layers to a temporary file one at a time, then copy to destination location
    This avoids conflicts when the gpkg already exists at the destination when retrieved by Icefabric

    Parameters
    -----------
    src_file: path to source geopackage
    dst_file: path to destination geopackage
    epsg: target EPSG code, default 4326
    """
    src_file = Path(src_file)
    dst_file = Path(dst_file)
    tmp_file = dst_file.with_suffix(".tmp.gpkg")

    # Loop through all layers in the file to reproject
    try:
        for layer in gpd.list_layers(src_file)["name"]:
            gdf = gpd.read_file(src_file, layer=layer)
            if isinstance(gdf, gpd.GeoDataFrame):
                if gdf.crs is not None:
                    # Reproject spatial layer to new crs
                    gdf = gdf.to_crs(epsg=epsg)
                    # Strip Z coordinate sif present, ngen only supports 2D geometry
                    if gdf.has_z.any():
                        gdf['geometry'] = shapely.force_2d(gdf['geometry'])
                else:
                    logger.debug(f"Spatial layer '{layer}' has no CRS, copying as is")
                gdf.to_file(tmp_file, layer=layer, driver="GPKG", mode="a")
            else:
                # Write non-spatial table layers to gpkg
                pyogrio.write_dataframe(gdf, tmp_file, layer=layer, driver="GPKG", append=True)
        os.replace(tmp_file, dst_file)
    except Exception as e:
        if tmp_file.exists():
            tmp_file.unlink()
        logger.critical(f"Failed to reproject {src_file} to EPSG:{epsg}: {e}")
        raise


def create_walk_file(
        gageID: str,
        divides_df: gpd.GeoDataFrame,
        gages_df: gpd.GeoDataFrame,
        walk_file: Union[str, Path],
) -> None:
    """ Create crosswalk file

    Parameters
    ----------
    gageID: stream gage ID at the outlet of basin
    divides_df: dvidies layer of the hydrofabric GeoPackage file
    gages_df: gages layer of the hydrofabric GeoPackage file
    walk_file: output crosswalk file path

    Returns
    ----------
    None

    """

    # Filter for specified gage
    gage_match = gages_df[gages_df['site_no'] == gageID]
    if gage_match.empty:
        try:
            raise Exception(f"Gage id {gageID} not found in gages layer")
        except Exception as e:
            logger.critical(e)
            raise

    # Retrieve catchment ID (fp_id) for specified gage
    outlet_cat_id = gage_match['fp_id'].iloc[0]

    # Build crosswalk dictionary
    cw = {}
    for cat_id in divides_df.index:
        if cat_id == outlet_cat_id:
            cw[cat_id] = {"Gage_no": gageID}
        else:
            cw[cat_id] = {"Gage_no": ""}

    logger.info(f"Created crosswalk for gage {gageID} with outlet catchment {outlet_cat_id}")
    with open(walk_file, 'w') as outfile:
        json.dump(cw, outfile, indent=4, separators=(", ", ": "), sort_keys=False)


def create_cfe_input(
        catids: List[str],
        modules: Union[List[str], List[List[str]]],
        divides_df: gpd.GeoDataFrame,
        cfe_input_dir: Union[str, Path],
        run_type: str,
        is_aet_rootzone: Union[int, dict],
        sm_profile_depth: List[float] = [0.1, 0.4, 1.0, 2.0],
) -> None:
    """ Create BMI initial configuration file for CFE with Schaake or Xianjiang infiltration and runoff scheme

    Parameters
    ----------
    catids : catchment IDs in the basin
    modules: list of modules in the formulation
    divides_df: dataframe containing hydrofabric divides attributes
    cfe_input_dir: directory to save configuration files
    run_type: type of run (calib, regionalization, or default)
    is_aet_rootzone: flag for CFE rootzone option
    sm_profile_depth = list of soil moisture profile depths

    Returns
    ----------
    None
    """

    os.makedirs(cfe_input_dir, exist_ok=True)

    # Base configuration template
    base_config = [
        'forcing_file=BMI',
        'verbosity=1',
        'surface_runoff_scheme=GIUH',
        'DEBUG=0',
        'num_timesteps=10',
        'alpha_fc=0.33',
        'giuh_ordinates=0.55, 0.25, 0.2[]',
        'gw_storage=0.05[m/m]',
        'K_lf=0.01[]',
        'K_nash=0.003[1/m]',
        'nash_storage=0.0,0.0[]',
        'soil_params.depth=2.0[m]',
        'soil_params.expon=1[]',
        'soil_params.expon_secondary=1[]',
        'soil_storage=0.5[m/m]',
    ]

    # Set module list and rootzone flag for non-regionalization
    is_grouped = run_type == 'regionalization' or isinstance(modules[0], list)
    mods_list = None if is_grouped else modules
    rootzone_flag_default = None if is_grouped else (is_aet_rootzone if 'smp' in modules else 0)

    # Create bmi config files
    for i, catID in enumerate(catids):

        # Set module list and is_aet_rootzone flag for each catchment during regionalization
        mods = modules[i] if is_grouped else mods_list
        rootzone_flag = (is_aet_rootzone[catID] if 'smp' in mods else 0) if is_grouped else rootzone_flag_default

        # Set sft coupling and surface partitioning scheme
        scheme = 'Xinanjiang' if 'cfex' in mods else 'Schaake'
        sft_coupled = '1' if 'sft' in mods else '0'

        # Get catchment attributes
        cat_attrs = divides_df.loc[catID]

        # Build catchment specific configuration
        config = base_config.copy()
        config.insert(2, f'surface_water_partitioning_scheme={scheme}')

        # Add SFT parameters if in use
        if 'cfes' in mods:
            config.extend([
                f'is_sft_coupled={sft_coupled}',
                'ice_content_threshold=0.15'
            ])

        # Add catchment specific parameters
        config.extend([
            f'Cgw={cat_attrs["cgw"]}[m/hr]',
            f'expon={cat_attrs["expon"]}[]',
            f'max_gw_storage={cat_attrs["max_gw_storage"]}[m]',
            f'refkdt={cat_attrs["refkdt_mean"]}[]',
            f'soil_params.b={cat_attrs["bexp_mode"]}[]',
            f'soil_params.satdk={cat_attrs["dksat_geomean"]}[m/s]',
            f'soil_params.satpsi={cat_attrs["psisat_geomean"]}[m]',
            f'soil_params.slop={cat_attrs["slope1km_mean"]}[m/m]',
            f'soil_params.smcmax={cat_attrs["smcmax_mean"]}[m/m]',
            f'soil_params.wltsmc={cat_attrs["smcwlt_mean"]}[m/m]',
        ])

        # Add rootzone parameters if enabled
        if rootzone_flag == 1:
            config.extend([
                'is_aet_rootzone=1',
                'max_rootzone_layer=2[m]',
                'soil_layer_depths=' + ','.join(f'{float(depth):g}' for depth in sm_profile_depth) + '[m]\n'
            ])

        # Add Xinanjiang parameters if in use
        if scheme == 'Xinanjiang':
            config.extend([
                f'a_Xinanjiang_inflection_point_parameter={cat_attrs["a_xinanjiang_inflection_point_parameter"]}[]',
                f'b_Xinanjiang_shape_parameter={cat_attrs["b_xinanjiang_shape_parameter"]}[]',
                f'x_Xinanjiang_shape_parameter={cat_attrs["x_xinanjiang_shape_parameter"]}[]',
                'urban_decimal_fraction=0.0[]',  # TODO: Does this need to be specified for each catchment or is it a constant?
            ])

        # Write config file
        cfe_bmi_file = os.path.join(cfe_input_dir, f"{catID}_bmi_config_cfe.txt")
        with open(cfe_bmi_file, 'w') as f:
            f.write('\n'.join(config))


def create_noah_input(
        catids: List[str],
        time_period: dict,
        divides_df: gpd.GeoDataFrame,
        param_dir_source: Union[str, Path],
        noah_input_dir: Union[str, Path],
        run_type: str
) -> None:
    """ Create BMI configuration file for Noah-OWP-Modular

    Parameters
    ----------
    catids : catchment IDs in the basin
    time_period : simulation and evaluation time period
    divides_df: dataframe containing hydrofabric divides attributes
    param_dir_source : source directory containing Noah-OWP-Modular parameter files
    noah_input_dir: directory to save configuration files
    run_type: type of run (calib, regionalization, or default)

    Returns
    ----------
    None

    """

    os.makedirs(noah_input_dir, exist_ok=True)

    # Create symlink for parameter directory
    noah_par_tables = ['SOILPARM.TBL', 'MPTABLE.TBL', 'GENPARM.TBL']
    for par in noah_par_tables:
        src = os.path.join(param_dir_source, par)
        dst = os.path.join(noah_input_dir, par)
        if os.path.exists(dst) or os.path.islink(dst):
            try:
                os.unlink(dst)
            except Exception as e:
                logger.critical(f"Failed to remove existing {dst}: {e}")
                raise
        try:
            os.symlink(src, dst)
        except OSError as e:
            logger.critical(f"Failed to create symlink: {src} -> {dst}: {e}")
            raise

    # Generate files based on run type
    run_list_map = {
        'calibration': ['calib', 'valid'],
        'regionalization': ['region'],
    }
    run_list = run_list_map.get(run_type, [run_type])

    # Set base namelist section
    base_namelist = {
        'timing': [
            "  " + "dt".ljust(19) + "= 3600.0" + "                       ! timestep [seconds]",
            "  " + "forcing_filename".ljust(19) + "= '.'" + "                          ! file containing forcing data",
            "  " + "output_filename".ljust(19) + "= '.'",
        ],
        'parameters': [
            "  " + "parameter_dir".ljust(19) + f"= '{noah_input_dir}'",
            "  " + "general_table".ljust(19) + "= 'GENPARM.TBL'" + "                ! general param tables and misc params",
            "  " + "soil_table".ljust(19) + "= 'SOILPARM.TBL'" + "               ! soil param table",
            "  " + "noahowp_table".ljust(19) + "= 'MPTABLE.TBL'" + "                ! model param tables (includes veg)",
            "  " + "soil_class_name".ljust(19) + "= 'STAS'" + "                       ! soil class data source - 'STAS' or 'STAS-RUC'",
            "  " + "veg_class_name".ljust(19) + "= 'USGS'" + "                       ! vegetation class data source - 'MODIFIED_IGBP_MODIS_NOAH' or 'USGS'",

        ],
        'forcing': [
            "  " + "ZREF".ljust(19) + "= 10.0" + "                         ! measurement height for wind speed (m)",
            "  " + "rain_snow_thresh".ljust(19) + "= 0.5" + "                          ! rain-snow temperature threshold (degrees Celcius)",
        ],
        'model_options': [
            "  " + "precip_phase_option".ljust(34) + "= 6",
            "  " + "snow_albedo_option".ljust(34) + "= 1",
            "  " + "dynamic_veg_option".ljust(34) + "= 4",
            "  " + "runoff_option".ljust(34) + "= 3",
            "  " + "drainage_option".ljust(34) + "= 8",
            "  " + "frozen_soil_option".ljust(34) + "= 1",
            "  " + "dynamic_vic_option".ljust(34) + "= 1",
            "  " + "radiative_transfer_option".ljust(34) + "= 3",
            "  " + "sfc_drag_coeff_option".ljust(34) + "= 1",
            "  " + "canopy_stom_resist_option".ljust(34) + "= 1",
            "  " + "crop_model_option".ljust(34) + "= 0",
            "  " + "snowsoil_temp_time_option".ljust(34) + "= 3",
            "  " + "soil_temp_boundary_option".ljust(34) + "= 2",
            "  " + "supercooled_water_option".ljust(34) + "= 1",
            "  " + "stomatal_resistance_option".ljust(34) + "= 1",
            "  " + "evap_srfc_resistance_option".ljust(34) + "= 4",
            "  " + "subsurface_option".ljust(34) + "= 2",
        ],
        'structure': [
            "  " + "nsoil".ljust(17) + "= 4              ! number of soil levels",
            "  " + "nsnow".ljust(17) + "= 3              ! number of snow levels",
            "  " + "nveg".ljust(17) + "= 27             ! number of vegetation type",
            "  " + "croptype".ljust(17) + "= 0              ! crop type (0 = no crops; this option is currently inactive)",
            "  " + "soilcolor".ljust(17) + "= 4              ! soil color code",
        ],
        'initial_values': [
            "  " + "dzsnso".ljust(10) + "= 0.0, 0.0, 0.0, 0.1, 0.3, 0.6, 1.0      ! level thickness [m]",
            "  " + "sice".ljust(10) + "= 0.0, 0.0, 0.0, 0.0                     ! initial soil ice profile [m3/m3]",
            "  " + "sh2o".ljust(10) + "= 0.3, 0.3, 0.3, 0.3                     ! initial soil liquid profile [m3/m3]",
            "  " + "zwt".ljust(10) + "= -2.0                                   ! initial water table depth below surface [m]",
        ],
    }

    for run_name in run_list:
        if not time_period['run_time_period'][run_name][0] and time_period['run_time_period'][run_name][1]:
            continue

        # Parse dates
        startdate = datetime.datetime.strptime(time_period['run_time_period'][run_name][0], "%Y-%m-%d %H:%M:%S")
        startdate = (startdate + datetime.timedelta(hours=1)).strftime("%Y%m%d%H%M")  # TODO: Should NOAH have a start time + 1 hour?
        enddate = datetime.datetime.strptime(time_period['run_time_period'][run_name][1], "%Y-%m-%d %H:%M:%S").strftime("%Y%m%d%H%M")

        # Specify options for namelist file
        for catID in catids:
            # Get catchment attributes
            cat_attrs = divides_df.loc[catID]
            tslp = cat_attrs['slope250m_mean']
            azimuth = cat_attrs['aspect_circmean']
            lat = cat_attrs['lat']
            lon = cat_attrs['lon']
            isltype = int(cat_attrs['isltyp_mode'])
            vegtype = int(cat_attrs["ivgtyp_mode"])
            sfctype = 2 if vegtype == 16 else 1

            # Build catchment specific namelist file
            nom_lst = ['&timing']
            nom_lst.extend(base_namelist['timing'])
            nom_lst.extend([
                "  " + "startdate".ljust(19) + f"= '{startdate}'" + "               ! UTC time start of simulation (YYYYMMDDhhmm)",
                "  " + "enddate".ljust(19) + f"= '{enddate}'" + "               ! UTC time end of simulation (YYYYMMDDhhmm)",
            ])
            nom_lst.extend(['/', '', '&parameters'])
            nom_lst.extend(base_namelist['parameters'])
            nom_lst.extend(['/', '', '&location'])
            nom_lst.extend([
                "  " + "lat".ljust(19) + f"= {lat}" + "            ! latitude [degrees]  (-90 to 90)",
                "  " + "lon".ljust(19) + f"= {lon}" + "           ! longitude [degrees] (-180 to 180)",
                "  " + "terrain_slope".ljust(19) + f"= {tslp}" + "           ! terrain slope [degrees]",
                "  " + "azimuth".ljust(19) + f"= {azimuth}" + "           ! terrain azimuth or aspect [degrees clockwise from north]",

            ])
            nom_lst.extend(['/', '', '&forcing'])
            nom_lst.extend(base_namelist['forcing'])
            nom_lst.extend(['/', '', '&model_options'])
            nom_lst.extend(base_namelist['model_options'])
            nom_lst.extend(['/', '', '&structure'])
            nom_lst.extend([
                "  " + "isltyp".ljust(17) + f"= {isltype}" + "              ! soil texture class",
                "  " + "vegtyp".ljust(17) + f"= {vegtype}" + "             ! vegetation type",
                "  " + "sfctyp".ljust(17) + f"= {sfctype}" + "              ! land surface type, 1:soil, 2:lake",
            ])
            nom_lst.extend(base_namelist['structure'])
            nom_lst.extend(['/', '', '&initial_values'])
            nom_lst.extend(base_namelist['initial_values'])
            nom_lst.append('/')

            namelst = os.path.join(noah_input_dir, f'{catID}_{run_name}.input')
            with open(namelst, 'w') as outfile:
                outfile.write('\n'.join(nom_lst) + '\n')


def create_sft_smp_input(
        catids: List[str],
        modules: Union[List[str], List[List[str]]],
        divides_df: gpd.GeoDataFrame,
        sft_dir: Union[str, Path],
        smp_dir: Union[str, Path],
        run_type: str,
        sm_frac_depth: float = 0.4,
        sm_profile_depth: List[float] = [0.1, 0.4, 1.0, 2.0],
) -> None:
    """ Create BMI configuration file for soil freeze and thaw module, and soil moisture profiles

    Parameters
    ----------
    catids : catchment IDs in the basin
    modules: list of modules in the formulation
    divides_df: dataframe containing hydrofabric divides attributes
    sft_dir : directory for writing sft bmi configuration files
    smp_dir : directory for writing smp bmi configuration files
    sm_frac_depth: depth at which to output soil moisture fraction
    sm_profile_depth = list of soil moisture profile depths
    run_type: type of run (calib, regionalization, or default)

    Returns
    ----------
    None

    """
    os.makedirs(sft_dir, exist_ok=True)
    os.makedirs(smp_dir, exist_ok=True)

    # Set module list for non-regionalization run
    is_grouped = run_type == 'regionalization' or isinstance(modules[0], list)
    mods_list = None if is_grouped else modules

    # Shared configuration parameters
    sm_profile_str = ",".join(f"{float(depth):g}" for depth in sm_profile_depth)
    mtemp = 280.372  # TODO: Are we okay with a soil temp of 45 degrees for each layer
    soil_temp_str = ','.join([str(mtemp)] * 4)

    # Base SFT config template
    sft_base = [
        'verbosity=none',
        'soil_moisture_bmi=1',
        'end_time=1.[d]',
        'dt=1.0[h]',
    ]

    # Base SMP config template
    smp_base = [
        'verbosity=none',
    ]

    # SMP model-specific configurations
    smp_model_configs = {
        'cfe': ['soil_storage_model=conceptual', 'soil_storage_depth=2.0'],
        'sac': ['soil_storage_model=conceptual', 'soil_storage_depth=2.0'],
        'topmodel': ['soil_storage_model=TopModel', 'water_table_based_method=flux_based'],
        'lasam': ['soil_storage_model=layered', 'soil_moisture_profile_option=constant', 'soil_depth_layers=2.0', 'water_table_depth=10[m]'],
    }

    # Create bmi config files
    for i, catID in enumerate(catids):

        # Set module list for each catchment during regionalization
        mods = modules[i] if is_grouped else mods_list

        # Determine ice fraction scheme
        icefscheme = 'Xinanjiang' if 'cfex' in mods else 'Schaake'

        # Get catchment attributes
        cat_attrs = divides_df.loc[catID]

        # Build SFT config
        sft_config = sft_base.copy()
        sft_config.extend([
            f'soil_params.smcmax={cat_attrs["smcmax_mean"]}[m/m]',
            f'soil_params.b={cat_attrs["bexp_mode"]}[]',
            f'soil_params.satpsi={cat_attrs["psisat_geomean"]}[m]',
            f'soil_params.quartz={cat_attrs["quartz_mean"]}[m]',
            f'ice_fraction_scheme={icefscheme}',
            f'soil_z={sm_profile_str}[m]',
            f'soil_temperature={soil_temp_str}[K]',
        ])

        # Write SFT config
        sft_bmi_file = os.path.join(sft_dir, f'{catID}_bmi_config_sft.txt')
        with open(sft_bmi_file, "w") as f:
            f.write('\n'.join(sft_config))

        # Build SMP config
        smp_config = smp_base.copy()
        smp_config.extend([
            f'soil_params.smcmax={cat_attrs["smcmax_mean"]}[m/m]',
            f'soil_params.b={cat_attrs["bexp_mode"]}[]',
            f'soil_params.satpsi={cat_attrs["psisat_geomean"]}[m]',
            f'soil_z={sm_profile_str}[m]',
            f'soil_moisture_fraction_depth={sm_frac_depth}[m]',
        ])

        # Add model-specific parameters
        if 'cfes' in mods or 'cfex' in mods:
            smp_config.extend(smp_model_configs['cfe'])
        elif 'sac' in mods:
            smp_config.extend(smp_model_configs['sac'])
        elif 'topmodel' in mods:
            smp_config.extend(smp_model_configs['topmodel'])
        elif 'lasam' in mods:
            smp_config.extend(smp_model_configs['lasam'])

        # Write SMP config
        smp_bmi_file = os.path.join(smp_dir, f'{catID}_bmi_config_smp.txt')
        with open(smp_bmi_file, "w") as f:
            f.write('\n'.join(smp_config))


def create_snow17_input(
        catids: List[str],
        divides_df: gpd.GeoDataFrame,
        snow17_input_dir: str
) -> None:
    """ Create BMI configuration file for Snow17

    Parameters
    ----------
    catids : catchment IDs in the basin
    divides_df: dataframe containing hydrofabric divides attributes
    snow17_input_dir : directory for the snow17 bmi configuration files

    Returns
    ----------
    None

   """
    os.makedirs(snow17_input_dir, exist_ok=True)

    # Base parameter template
    param_base = [
        'scf 1.100',
        'si 500.00',
        'pxtemp 1.000',
        'nmf 0.150',
        'tipm 0.100',
        'mbase 0.000',
        'plwhc 0.030',
        'daygm 0.000',
        'adc1 0.050',
        'adc2 0.100',
        'adc3 0.200',
        'adc4 0.300',
        'adc5 0.400',
        'adc6 0.500',
        'adc7 0.600',
        'adc8 0.700',
        'adc9 0.800',
        'adc10 0.900',
        'adc11 1.000',

    ]

    # Base namelist template # TODO: Do we need to create a working standalone snow17 file
    namelist_base = [
        '&SNOW17_CONTROL',
        '! === run control file for snow17bmi v. 1.x ===',
        '',
        '! -- basin config and path information',
        'n_hrus              = 1            ! number of sub-areas in model',
        'forcing_root        = "extern/snow17/test_cases/ex1/input/forcing/forcing.snow17bmi."',
        'output_root         = "data/output/output.snow17bmi."',
        'output_hrus         = 1            ! output HRU results? (1=yes; 0=no)',
        '',
        '! -- run period information',
        'start_datehr        = 2017120101   ! start date time, backward looking (check)',
        'end_datehr          = 2017120123   ! end date time',
        'model_timestep      = 3600        ! in seconds (86400 seconds = 1 day)',
        '',
        '! -- state start/write flags and files',
        'warm_start_run      = 0  ! is this run started from a state file?  (no=0 yes=1)',
        "write_states        = 0  ! write restart/state files for 'warm_start' runs (no=0 yes=1)",
        '',
        '! -- filenames only needed if warm_start_run = 1',
        'snow_state_in_root  = "data/state/snow17_states."  ! input state filename root',
        '',
        '! -- filenames only needed if write_states = 1',
        'snow_state_out_root = "data/state/snow17_states."  ! output states filename root',
        '/',
        ''
    ]

    for catID in catids:

        # Get catchment attributes
        cat_attrs = divides_df.loc[catID]

        # Build catchment-specific snow17 config parameters
        param_list = [f'hru_id {catID}',
                      f'hru_area {cat_attrs["area_sqkm"]}',
                      f'latitude {cat_attrs["lat"]}',
                      f'elev {cat_attrs["elevation_mean"]}',
                      ]
        param_list.extend(param_base)
        param_list.extend([
            f'mfmax {cat_attrs["mfmax_mean"]}',
            f'mfmin {cat_attrs["mfmin_mean"]}',
            f'uadj {cat_attrs["uadj_mean"]}',
        ])

        # Write parameter file
        param_file = os.path.join(snow17_input_dir, f'snow17_params-{catID}.txt')
        with open(param_file, "w") as f:
            f.write('\n'.join(param_list))

        # Build namelist file
        input_list = namelist_base.copy()
        input_list.insert(4, f'main_id             = "{catID}"     ! basin label or gage id')
        input_list.insert(8, f'snow17_param_file   = "{param_file}"')

        # Write namelist file
        input_file = os.path.join(snow17_input_dir, f'snow17-init-{catID}.namelist.input')
        with open(input_file, "w") as f:
            f.write('\n'.join(input_list))


def create_ueb_input(
        catids: List[str],
        time_period: dict,
        divides_df: gpd.GeoDataFrame,
        param_dir_source: Union[str, Path],
        ueb_input_dir: str,
        run_type: str
) -> None:
    """ Create BMI configuration file for ueb

    Parameters
    ----------
    catids : catchment IDs in the basin
    time_period: simulation time period
    divides_df: dataframe containing hydrofabric divides attributes
    param_dir_source : directory containing UEB parameter files
    ueb_input_dir : directory for the UEB bmi configuration file
    run_type: type of run (calib, regionalization, or default)

    Returns
    ----------
    None

   """
    os.makedirs(ueb_input_dir, exist_ok=True)

    # Create symlink for constant parameter files
    const_file_str = ['inputctr', 'outputctr', 'params']
    const_files = {}
    for par in const_file_str:
        src = Path(param_dir_source, f'ueb_{par}.dat').absolute()
        if not os.path.exists(src):
            try:
                raise FileNotFoundError(src)
            except FileNotFoundError as e:
                logger.critical(e)
                raise
        dst = os.path.join(ueb_input_dir, f'ueb_{par}.dat')
        const_files[par] = dst

        # Remove existing file or symlink
        if os.path.exists(dst) or os.path.islink(dst):
            try:
                os.unlink(dst)
            except Exception as e:
                logger.critical(f"Failed to remove existing {dst}: {e}")
                raise

        # Create new symlink
        os.symlink(src, dst)
        logger.info(f'Creating symlink from {src} to {dst}')

    # Read template sitevars file
    temp_file = Path(param_dir_source, 'ueb_sitevars.dat').resolve(strict=True)
    with open(temp_file) as f:
        template_lines = f.readlines()

    # Temperature delta line mapping
    temp_delta_lines = {
        'temp_delta_jan_mean': 57,
        'temp_delta_feb_mean': 60,
        'temp_delta_mar_mean': 63,
        'temp_delta_apr_mean': 66,
        'temp_delta_may_mean': 69,
        'temp_delta_jun_mean': 72,
        'temp_delta_jul_mean': 75,
        'temp_delta_aug_mean': 78,
        'temp_delta_sep_mean': 81,
        'temp_delta_oct_mean': 84,
        'temp_delta_nov_mean': 87,
        'temp_delta_dec_mean': 90,
    }

    # Create sitevars files for each catchment
    for catID in catids:
        # Get catchment attributes
        cat_attrs = divides_df.loc[catID]
        tslp = cat_attrs['slope250m_mean']
        azimuth = cat_attrs['aspect_circmean']
        lat = cat_attrs['lat']
        lon = cat_attrs['lon']
        elevation = cat_attrs['elevation_mean']

        # Compute atmospheric pressure based on elevation
        std_atm_pressure = round(Atmosphere(elevation).pressure[0], 4)

        # Update template with catchment-specific values
        lines = template_lines.copy()
        lines[18] = f"{std_atm_pressure}\n"
        lines[39] = f'{tslp}\n'
        lines[42] = f'{azimuth}\n'
        lines[45] = f'{lat}\n'
        lines[96] = f'{lon}\n'

        # Update temperature delta values
        for col, line_idx in temp_delta_lines.items():
            lines[line_idx] = f"{cat_attrs[col]}\n"

        # Write sitevars file
        site_file = os.path.join(ueb_input_dir, 'ueb_sitevars-f{catID}.dat')
        with open(site_file, 'w') as outfile:
            outfile.writelines(lines)

    # Determine run list based on run type
    run_list_map = {
        'calibration': ['calib', 'valid'],
        'regionalization': ['region'],
        'default': ['default']
    }
    run_list = run_list_map.get(run_type)

    # Set base init file template
    init_base = ['UEBGrid Model Driver Test for TWDEF',  # TODO does this need to be updated?
                 '1.0',
                 '-7.0',
                 '0',
                 '1 15 16',  # TODO: Confirm time zone offset is correct
                 '1 1'
                 ]

    for run_name in run_list:
        if not time_period['run_time_period'][run_name][0] and time_period['run_time_period'][run_name][1]:
            continue

        # Parse dates
        startdate = datetime.datetime.strptime(time_period['run_time_period'][run_name][0], "%Y-%m-%d %H:%M:%S").strftime("%Y%m%d%H%M")
        enddate = datetime.datetime.strptime(time_period['run_time_period'][run_name][1], "%Y-%m-%d %H:%M:%S").strftime("%Y%m%d%H%M")

        for catID in catids:
            site_file = os.path.join(ueb_input_dir, f'ueb_sitevars-{catID}.dat')

            # Build init file
            input_list = [
                init_base[0],
                const_files['params'],
                site_file,
                const_files['inputctr'],
                const_files['outputctr'],
                f'{param_dir_source}/aggout.nc ',
                f'{param_dir_source}/watershed_onecell.nc',
                'watershed y x',
                f'{startdate[:4]} {startdate[4:6]} {startdate[6:8]} {startdate[8:10]}.0',
                f'{enddate[:4]} {enddate[4:6]} {enddate[6:8]} {enddate[8:10]}.0',
            ]
            input_list.extend(init_base[1:])

            # Write init file
            input_file = os.path.join(ueb_input_dir, f'ueb-init-{catID}_{run_name}.dat')
            with open(input_file, "w") as f:
                f.write('\n'.join(input_list))


def create_sac_input(
        catids: List[str],
        divides_df: gpd.GeoDataFrame,
        sac_input_dir: str
) -> None:
    """ Create BMI configuration file for sac-sma

    Parameters
    ----------
    catids : catchment IDs in the basin
    divides_df: dataframe containing hydrofabric divides attributes
    sac_input_dir : directory for the sac bmi configuration file

    Returns
    ----------
    None

    """
    os.makedirs(sac_input_dir, exist_ok=True)

    # Set base parameter template
    param_base = [
        'adimp 0.0000',
        'pctim 0.0000',
        'riva 0.000',
        'side 0.0000',
        'rserv 0.3000',
        'giuh_ordinates 0.06,0.51,0.28,0.12,0.03',
    ]

    # Set namelist template  # TODO: Do we need a working sac-sma standalone file?
    namelist_base = [
        '&SAC_CONTROL',
        '! === run control file for sacbmi v. 1.x ===',
        '',
        '! -- basin config and path information',
        'n_hrus              = 1            ! number of sub-areas in model',
        'forcing_root        = ""',
        'output_root         = ""',
        'output_hrus         = 0            ! output HRU results? (1=yes; 0=no)',
        '',
        '! -- run period information',
        'start_datehr        = 2015120112   ! start date time, backward looking (check)',
        'end_datehr          = 2015123012   ! end date time',
        'model_timestep      = 3600        ! in seconds (86400 seconds = 1 day)',
        '',
        '! -- state start/write flags and files',
        'warm_start_run      = 0  ! is this run started from a state file?  (no=0 yes=1)',
        "write_states        = 0  ! write restart/state files for 'warm_start' runs (no=0 yes=1)",
        '',
        '! -- filenames only needed if warm_start_run = 1',
        'sac_state_in_root  = "../state/sac_states."  ! input state filename root',
        '',
        '! -- filenames only needed if write_states = 1',
        'sac_state_out_root = "../state/sac_states."  ! output states filename root',
        '/',
        ''
    ]

    for catID in catids:
        # Get catchment attributes
        cat_attrs = divides_df.loc[catID]

        # Build parameter file
        param_list = [
            f'hru_id {catID}',
            f'hru_area {cat_attrs["area_sqkm"]}',
            f'uztwm {cat_attrs["uztwm_mean"]}',
            f'uzfwm {cat_attrs["uzfwm_mean"]}',
            f'lztwm {cat_attrs["lztwm_mean"]}',
            f'lzfpm {cat_attrs["lzfpm_mean"]}',
            f'lzfsm {cat_attrs["lzfsm_mean"]}',
            f'uzk {cat_attrs["uzk_mean"]}',
            f'lzpk {cat_attrs["lzpk_mean"]}',
            f'lzsk {cat_attrs["lzsk_mean"]}',
            f'zperc {cat_attrs["zperc_mean"]}',
            f'rexp {cat_attrs["rexp_mean"]}',
            f'pfree {cat_attrs["pfree_mean"]}',
        ]

        # Add static parameters
        param_list.extend(param_base)

        # Write parameter file
        param_file = os.path.join(sac_input_dir, f'sac_params-{catID}.txt')
        with open(param_file, "w") as f:
            f.write('\n'.join(param_list))

        # Build namelist file
        input_list = namelist_base.copy()
        input_list.insert(4, f'main_id             = "{catID}"     ! basin label or gage id')
        input_list.insert(8, f'sac_param_file   = "{param_file}"',)

        # Write namelist file
        input_file = os.path.join(sac_input_dir, f'sac-init-{catID}.namelist.input')
        with open(input_file, "w") as f:
            f.write('\n'.join(input_list))


def update_lstm_parameters(
    input_config_path: str,
    output_dir: str,
    params_to_remove=None,
    params_to_update=None
) -> None:

    """
    Reads a YAML config file, removes specified parameters, updates others,
    and writes the result to a new config.yaml in a given output directory.

    :param input_config_path: Path to the original config.yaml
    :param output_dir: Directory where the modified config will be saved
    :param params_to_remove: List of top-level parameters to remove
    :param params_to_update: Dict of parameters to update or add
    """
    import re
    from fnmatch import fnmatch

    params_to_remove = params_to_remove or []
    params_to_update = params_to_update or {}

    # Read the original config
    try:
        with open(input_config_path, 'r') as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        logger.critical(f"Error parsing LSTM yaml config at {input_config_path}: {e}")
        raise
    except FileNotFoundError:
        logger.critical(f"LSTM yaml config file not found: {input_config_path}")
        raise

    # Remove specified parameters
    keys_to_remove = set()
    for key in config:
        for pattern in params_to_remove:
            try:
                if fnmatch(key, pattern):
                    keys_to_remove.add(key)
                elif is_probably_regex(pattern) and re.fullmatch(pattern, key):
                    keys_to_remove.add(key)
            except re.error as regex_error:
                logger.info(f"Skipping invalid regex pattern: '{pattern}' - {regex_error}")
    for key in keys_to_remove:
        config.pop(key, None)

    # Update or add new parameters
    config.update(params_to_update)

    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    output_config_path = os.path.join(output_dir, "config.yml")

    # Write the modified config
    try:
        with open(output_config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False)
    except yaml.YAMLError as e:
        logger.critical(f"Error writing LSTM yaml to {output_config_path}: {e}")
        raise
    except OSError as e:
        logger.critical(f"Error writing LSTM yaml to {output_config_path}: {e}")
        raise

    logger.info(f"LSTM config written to: {output_config_path}")


def create_symlinks(src_file_list, src_dir, dst_dir):

    missing_input_files = list()

    for data_file in src_file_list:
        ffile = os.path.join(src_dir, data_file)
        # Make sure we have the file
        if not os.path.exists(ffile):
            logger.info(f'Input file {ffile} does not exist')
            missing_input_files.append(ffile)
        else:
            target = os.path.join(dst_dir, os.path.basename(ffile))
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

    if missing_input_files:
        try:
            raise Exception(f'Missing LSTM input files - {missing_input_files}')
        except Exception as e:
            logger.critical(e)
            raise


def create_lstm_config(
        param_dir_source: Union[str, Path],
        lstm_input_dir: Union[str, Path]
) -> None:
    """
    Create LSTM config yaml files from existing static files
    Parameters
    ----------
    param_dir_source: direcetory for static lstm files
    lstm_input_dir: directory for the existing lstm bmi configuration file

    Returns
    ----------
    None

    """
    # create the config files
    lstm_data_dir = os.path.join(param_dir_source, "ngen_files/data/lstm")
    lstm_train_dir = os.path.join(param_dir_source, "trained_neuralhydrology_models/nh_AORC_hourly_slope_elev_precip_temp_seq999_seed101_2801_191806")
    run_dir = lstm_input_dir
    lstm_train_data_dir = os.path.join(lstm_train_dir, 'train_data')
    train_data_dir = os.path.join(run_dir, 'train_data')
    if not os.path.isdir(lstm_train_data_dir):
        try:
            raise ValueError(f"LSTM source path '{lstm_train_data_dir}' must be an existing directory.")
        except Exception as e:
            logger.critical(e)
            raise

    if os.path.islink(train_data_dir) or os.path.exists(train_data_dir):
        try:
            os.unlink(train_data_dir)
        except Exception as e:
            logger.critical(f"Failed to remove existing {train_data_dir}: {e}")
            raise

    try:
        os.symlink(lstm_train_data_dir, train_data_dir, target_is_directory=True)
        logger.info("Created symlink to ngen executable")
    except OSError as e:
        logger.critical(f"Failed to create symlink: {lstm_train_data_dir} -> {train_data_dir}: {e}")
        raise

    # Create config.yml
    params_to_remove = ['test_*', 'train_*', 'validation_*', '*_dir']
    params_to_update = {
        "run_dir": run_dir
    }
    update_lstm_parameters(
        input_config_path=os.path.join(lstm_train_dir, 'config.yml'),
        output_dir=lstm_input_dir,
        params_to_remove=params_to_remove,
        params_to_update=params_to_update
    )

    data_files = ['initial_states.csv', 'input_scaling.csv', 'lstm_mean_std.csv', 'sugar_creek_trained.pt']
    create_symlinks(data_files, lstm_data_dir, lstm_input_dir)
    data_files = ['model_epoch009.pt', 'optimizer_state_epoch009.pt']
    create_symlinks(data_files, lstm_train_dir, lstm_input_dir)


def create_lstm_input(
        catids: List[str],
        divides_df: gpd.GeoDataFrame,
        param_dir_source: Union[str, Path],
        lstm_input_dir: Union[str, Path],
) -> None:

    """
    Create BMI configuration file for LSTM from existing EDFS files
    Parameters
    ----------
    catids: catchment IDs in the basin
    divides_df: dataframe containing hydrofabric divides attributes
    param_dir_source: direcetory for static lstm files
    lstm_input_dir: target directory for bmi configuration file output (lstm_input)

    Returns
    ----------
    None

    """
    # Create input directory
    os.makedirs(lstm_input_dir, exist_ok=True)

    # Create static LSTM config yaml files
    create_lstm_config(param_dir_source, lstm_input_dir)

    # Set base namelist template
    namelist_base = {
        'initial_state': 'zero',
        'timestep': '1 hour',
        'train_cfg_file': os.path.join(lstm_input_dir, 'config.yml'),
        'verbose': '1',
    }

    # Create catchment specific LSTM bmi config files from scratch
    for catID in catids:
        # Get catchment attributes
        cat_attrs = divides_df.loc[catID]

        # Build catchment-specific namelist
        namelist = namelist_base.copy()
        namelist.update({
            'area_sqkm': float(cat_attrs['area_sqkm']),
            'basin_id': catID,
            'basin_name': catID,
            'elev_mean': float(cat_attrs['elevation_mean']),
            'lat': float(cat_attrs['lat']),
            'lon': float(cat_attrs['lon']),
            'slope_mean': 1000 * math.tan(math.radians(float(cat_attrs['slope250m_mean']))),
        })

        # Write config to file
        input_file = os.path.join(lstm_input_dir, f'{catID}.yml')
        try:
            with open(input_file, "w") as f:
                yaml.dump(namelist, f, default_flow_style=False)
        except yaml.YAMLError as e:
            logger.critical(f"Error writing LSTM yaml to {input_file}: {e}")
            raise
        except OSError as e:
            logger.critical(f"Error writing LSTM yaml to {input_file}: {e}")
            raise


def create_pet_input(
        catids: List[str],
        divides_df: gpd.GeoDataFrame,
        pet_input_dir: str,
        pet_method: int | None = None,
) -> None:
    """ Create BMI configuration file for pet

    Parameters
    ----------
    catids : catchment IDs in the basin
    divides_df: dataframe containing hydrofabric divides attributes
    pet_input_dir : directory for the pet input files
    pet_method: integer (1-5) correponding to PET method to be used

    Returns
    ----------
    None

    """
    os.makedirs(pet_input_dir, exist_ok=True)

    # PET Methods
    # 1: energy balance method
    # 2: aerodynamic method
    # 3: combination method, which combines 1 & 2.
    # 4: Priestley-Taylor method, which assumes the ratio between 1 & 2, and only calculates 1.
    # 5: Penman-Monteith method, which requires a value of canopy resistance term, and does not rely on 1 or 2.

    # Set default pet_method
    if pet_method is None:
        pet_method = 5
        logger.info("No PET method supplied, defaulting to Penman-Monteith method")

    # Set PET parameters for catchment
    base_config = ['verbose=0',
                   f'pet_method={pet_method}',
                   'forcing_file=BMI',
                   'run_unit_tests=0',
                   'yes_aorc=1',
                   'yes_wrf=0',
                   'wind_speed_measurement_height_m=10.0',
                   'humidity_measurement_height_m=10.0',
                   'vegetation_height_m=0.12',
                   'zero_plane_displacement_height_m=0.0003',
                   'momentum_transfer_roughness_length=0.0',
                   'heat_transfer_roughness_length_m=0.1',
                   'surface_longwave_emissivity=1.0',
                   'surface_shortwave_albedo=0.22',
                   'time_step_size_s=3600',
                   'shortwave_radiation_provided=1']

    for catID in catids:

        # Get catchment attributes
        cat_attrs = divides_df.loc[catID]

        # Fill template with catchment-specific values
        config = base_config.copy()
        config.extend([
            f'latitude_degrees={cat_attrs["lat"]}',
            f'longitude_degrees={cat_attrs["lon"]}',
            f'site_elevation_m={cat_attrs["elevation_mean"]}',
        ])

        # Write PET bmi config files
        ini_file = os.path.join(pet_input_dir, f"{catID}_bmi_config.ini")
        with open(ini_file, "w") as f:
            f.writelines('\n'.join(config))


def create_lasam_input(
        catids: List[str],
        modules: Union[List[str], List[List[str]]],
        divides_df: gpd.GeoDataFrame,
        input_dir: Union[str, Path],
        param_dir: Union[str, Path],
        run_type: str
) -> None:
    """ Create BMI configuration file for Lumped Arid and Semi-arid Model

    Parameters
    ----------
    catids : catchment IDs in the basin
    modules: list of modules or a list of formulations for each catchment
    divides_df: dataframe containing hydrofabric divides attributes
    input_dir : directory for the lasam input configuration file
    param_dir: directory for static lasam parameter files
    run_type: type of run (calib, regionalization, or default)

    Returns
    ----------
    None

    """

    os.makedirs(input_dir, exist_ok=True)

    # Validate and retrieve param_dir and parameter files
    if param_dir and os.path.exists(param_dir):
        soil_param_file = os.path.join(param_dir, 'vG_default_params.dat')
        if not os.path.exists(soil_param_file):
            try:
                raise Exception(f'Soil params file does not exist: {soil_param_file}')
            except Exception as e:
                logger.critical(e)
                raise
        soil_class_file = os.path.join(param_dir, 'lasam_soil_class.txt')
        if not os.path.exists(soil_class_file):
            try:
                raise Exception(f'Soil class file does not exist: {soil_class_file}')
            except Exception as e:
                logger.critical(e)
                raise
    else:
        try:
            raise Exception(f'lasam_parameter_dir does not exist: {param_dir}')
        except Exception as e:
            logger.critical(e)
            raise

    # Create base LASAM config template
    max_soil_types = 16
    lasam_base = [
        'verbosity=none',
        f'soil_params_file={soil_param_file}',
        'layer_thickness=200.0[cm]',
        'initial_psi=2000.0[cm]',
        'timestep=300[sec]',  # TODO Where should this be supplied from?
        'endtime=1000[hr]',  # TODO Where should this be supplied from?
        'forcing_resolution=3600[sec]',
        'ponded_depth_max=1.1[cm]',
        'use_closed_form_G=false',
        'layer_soil_type=',
        f'max_valid_soil_types={max_soil_types}',
        'wilting_point_psi=15495.0[cm]',
        'field_capacity_psi=340.9[cm]',
        'giuh_ordinates=0.06,0.51,0.28,0.12,0.03',  # TODO: Should the LASAM giuh ordinates match those used by other modules?
        'calib_params=true',
        'adaptive_timestep=true',
        'sft_coupled=',
        'soil_z=10,30,100.0,200.0[cm]',  # TODO: Should this match soil moisture depths supplied by user?
    ]

    # Set module list based on grouping
    is_grouped = run_type == 'regionalization' or isinstance(modules[0], list)
    mods_list = None if is_grouped else modules

    # Create bmi config file
    for i, catID in enumerate(catids):
        # Set module list for each catchment during regionalization
        mods = modules[i] if is_grouped else mods_list

        # Get catchment attributes
        cat_attrs = divides_df.loc[catID]

        # Build catchment-specific configuration
        lasam_config = lasam_base.copy()
        isltyp = int(cat_attrs['isltyp_mode'])
        if isltyp > max_soil_types:
            msg = f"LASAM soil type value {isltyp} exceeds max_soil_types={max_soil_types}"
            logger.critical(msg)
            raise ValueError(msg)
        lasam_config[9] += str(isltyp)
        lasam_config[16] += 'true' if 'sft' in mods else 'false'

        # Write config file
        lasam_bmi_file = os.path.join(input_dir, f'{catID}_bmi_config_lasam.txt')
        with open(lasam_bmi_file, "w") as f:
            f.write('\n'.join(lasam_config))


def create_topoflow_glacier_input(
        catids: List[str],
        divides_df: gpd.GeoDataFrame,
        time_period: dict,
        topo_input_dir: str,
        run_type: str,
) -> None:
    """ Create BMI configuration file for ueb

    Parameters
    ----------
    catids : catchment IDs in the basin
    divides_df: dataframe containing hydrofabric divides attributes
    time_period: simulation time period
    topo_input_dir : directory for the bmi configuration file
    run_type: type of run (calib, regionalization, or default)

    Returns
    ----------
    None

    """
    os.makedirs(topo_input_dir, exist_ok=True)

    # Determine run list based on run type
    run_list_map = {
        'calibration': ['calib', 'valid'],
        'regionalization': ['region'],
        'default': ['default'],
    }
    run_list = run_list_map.get(run_type)

    # Set base parameter template
    param_base = {
        'forcing_file': '.',
        'dt': 1,
        'h_active_layer': 0.125,
        'h0_snow': 5,
        'h0_ice': 2,
        'h0_swe': 0.25,
        'h0_iwe': 1.834,
        'T_rain_snow': 0
    }

    for run_name in run_list:
        if not time_period['run_time_period'][run_name][0] and time_period['run_time_period'][run_name][1]:
            continue

        # Parse dates
        start_time = datetime.datetime.strptime(time_period['run_time_period'][run_name][0], "%Y-%m-%d %H:%M:%S").strftime("%Y%m%d%H")
        end_time = datetime.datetime.strptime(time_period['run_time_period'][run_name][1], "%Y-%m-%d %H:%M:%S").strftime("%Y%m%d%H")

        # Create topoflow-glacier parameter yaml file
        for catID in catids:
            # Get catchment attributes
            cat_attrs = divides_df.loc[catID]

            # Build catchment-specific dictionary
            param_dict = param_base.copy()
            param_dict.update({
                'site_prefix': str(catID),
                'start_time': start_time,
                'end_time': end_time,
                'da': float(cat_attrs["area_sqkm"]),
                'slope': 1000 * math.tan(math.radians(float(cat_attrs['slope250m_mean']))),
                'aspect': float(cat_attrs["aspect_circmean"]),
                'lat': float(cat_attrs["lat"]),
                'lon': float(cat_attrs["lon"]),
                'elev': float(cat_attrs["elevation_mean"]),
            })

            # Write bmi to file
            topo_bmi_file = os.path.join(topo_input_dir, f'{catID}_{run_name}.yaml')
            with open(topo_bmi_file, 'w') as f:
                yaml.dump(param_dict, f, default_flow_style=False, sort_keys=False)


def create_topmodel_input(
        catids: List[str],
        divides_df: gpd.GeoDataFrame,
        flowpaths_df: gpd.GeoDataFrame,
        input_dir: Union[str, Path],
) -> None:
    """ Create BMI configuration file for Topmodel

    Parameters
    ----------
    catids : catchment IDs in the basin
    divides_df: dataframe containing hydrofabric divides attributesF
    flowpaths_df: dataframe containing hydrofabric flowpaths attributes
    input_dir: directory for writing topmodel bmi configuration files

    Returns
    ----------
    None

    """

    os.makedirs(input_dir, exist_ok=True)

    # Create base topmodel parameters template
    params_base = OrderedDict([
        ('szm', '0.0125'),
        ('t0', '0.000075'),
        ('td', '20'),
        ('chv', '1000'),
        ('rv', '1000'),
        ('srmax', '0.04'),
        ('Q0', '0.0000328'),
        ('sr0', '0'),
        ('infex', '0'),
        ('xk0', '2'),
        ('hf', '0.1'),
        ('dth', '0.1'),
    ])

    # Set static topmodel parameters
    num_sub_catchments = 1
    imap = 1
    yes_print_output = 1
    area = 1
    num_topodex_values = 4
    num_channels = 1
    cum_dist_area_with_dist = 1
    stand_alone = '0\n'  # Set to false for BMI

    # Parent directory for forcing/output files
    parent_dir = os.path.dirname(os.path.dirname(input_dir))

    # Create topmodel configuration files
    for catID in catids:
        # Get catchment attributes
        cat_attrs_divides = divides_df.loc[catID]
        cat_attrs_flowpaths = flowpaths_df.loc[catID]

        # Calculate distance from outlet (convert km to m)
        dist_from_outlet = round(cat_attrs_flowpaths['length_km'] * 1000)

        # Create subcatchment file
        subcat_lines = [
            f"{num_sub_catchments} {imap} {yes_print_output} \n",
            f"Extracted study basin:  {catID} \n",
            f"{num_topodex_values} {area} \n",
            f"{0.25} {cat_attrs_divides['twi_q25']}",
            f"{0.25} {cat_attrs_divides['twi_q50']}",
            f"{0.25} {cat_attrs_divides['twi_q75']}",
            f"{0.25} {cat_attrs_divides['twi_q100']}",
            f"{num_channels}\n",
            f"{cum_dist_area_with_dist} {dist_from_outlet}\n"
        ]

        # Write subcat file
        subcat_file = os.path.join(input_dir, f'{catID}_topmodel_subcat.dat')
        with open(subcat_file, 'w') as f:
            f.writelines(subcat_lines)

        # Create and write parameters file
        params_values = " ".join([str(v) for v in params_base.values()])
        params_file = os.path.join(input_dir, f'{catID}_topmodel_params.dat')
        with open(params_file, 'w') as f:
            f.write(f'{catID}\n')
            f.write(params_values)

        # Create run configuration file
        run_config = [
            stand_alone,
            f'{catID}\n',
            f'{os.path.join(parent_dir, str(catID))}_forcing.csv\n',
            f'{subcat_file}\n',
            f'{params_file}\n',
            f'{os.path.join(parent_dir, str(catID))}_topmod.out\n',
            f'{os.path.join(parent_dir, str(catID))}_hyd.out\n',
        ]

        # Write run file
        run_file = os.path.join(input_dir, f'{catID}_topmodel.run')
        with open(run_file, 'w') as f:
            f.writelines(run_config)


def update_noah_ueb_topo_times(
        real_config: dict,
        input_dir: Path,
        basename_opt: str,
) -> dict:
    """
    For noah-owp-modular, Topoflow-Glacier, & UEB, create new BMI config files with adjusted start/end times, and then
        update path to BMI config files in realization file accordingly

    Arguments
    ---------
    real_config: dictionary containing the realization configuration
    input_dir: folder for the new BMI config files
    basename_opt: suffix for new BMI config files

    Returns
    -------
    dictionary containing adjusted realization config

    """
    # Check for format of realization file
    real_format = 'grouped' if 'formulation_groups' in real_config else 'uniform'

    # Retrieve times from realization
    try:
        start_time = real_config['time']['start_time']
        end_time = real_config['time']['end_time']
        startdate = pd.to_datetime(start_time, format="%Y-%m-%d %H:%M:%S").strftime("%Y%m%d%H%M")
        enddate = pd.to_datetime(end_time, format="%Y-%m-%d %H:%M:%S").strftime("%Y%m%d%H%M")
        startdate_topo = pd.to_datetime(start_time, format="%Y-%m-%d %H:%M:%S").strftime("%Y%m%d%H")
        enddate_topo = pd.to_datetime(end_time, format="%Y-%m-%d %H:%M:%S").strftime("%Y%m%d%H")
    except Exception as e:
        logger.critical(f"Error converting yaml config times: {real_config['time']}\n{e}")
        raise

    # Set modules to update
    mod_dict = {
        'NoahOWP': 'noah-owp-modular',
        'UEB': 'ueb',
        'BmiTopoflowGlacier': 'topoflow-glacier'}

    if real_format == 'uniform':
        modules_list = real_config['global']['formulations'][0]['params']['modules']
    else:
        modules_list = []
        for grp in real_config['formulation_groups'].values():
            for form in grp:
                modules_list.extend(form['params']['modules'])

    # Loop through modules and update start/end times
    for form in modules_list:
        mod_params = form.get('params')
        model_name = mod_params.get('model_type_name')

        if model_name not in mod_dict:
            continue

        # Get source files and create destination directory
        src0 = mod_params.get('init_config')
        src = Path(src0.replace('{{id}}', '*'))
        dst = Path(input_dir, f'{mod_dict[model_name]}_input')

        try:
            dst.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.critical(f"Failed to create directory: {dst}\n{e}")
            raise

        # Update times with line based editting for NoahOWP/UEB
        if model_name in ['NoahOWP', 'UEB']:
            for f1 in glob.glob(f'{src}'):
                with open(f1) as f:
                    lines = f.readlines()

                    # update start/end times
                    for i, line in enumerate(lines):
                        if model_name == 'NoahOWP':
                            if 'startdate' in line:
                                lines[i] = "  " + "startdate".ljust(19) + f"= '{startdate}'" + "               ! UTC time start of simulation (YYYYMMDDhhmm)\n"
                            elif 'enddate' in line:
                                lines[i] = "  " + "enddate".ljust(19) + f"= '{enddate}'" + "               ! UTC time end of simulation (YYYYMMDDhhmm)\n"
                        elif model_name == 'UEB':
                            if i == 8:
                                lines[i] = f'{startdate[:4]} {startdate[4:6]} {startdate[6:8]} {startdate[8:10]}.0\n'
                            elif i == 9:
                                lines[i] = f'{enddate[:4]} {enddate[4:6]} {enddate[6:8]} {enddate[8:10]}.0\n'

                    # Rename basename from _valid to basename_opt
                    src_basename = os.path.basename(f1)
                    new_basename = src_basename.replace('_valid', f'_{basename_opt}')

                    # write to new BMI config files
                    try:
                        with open(Path(dst, new_basename), 'w') as outfile:
                            outfile.writelines(lines)
                    except (FileNotFoundError, PermissionError, OSError) as e:
                        logger.critical(f"Error writing to {dst}\n{e}")
                        raise

                # replace path to BMI config file in realization file
                src_basename_init = os.path.basename(src0)
                new_basename_init = src_basename_init.replace('_valid', f'_{basename_opt}')
                mod_params['init_config'] = str(Path(dst, new_basename_init))

        # Update times with yaml-based editting for TopoflowGlacier
        elif model_name == 'BmiTopoflowGlacier':
            for f1 in glob.glob(f'{src}'):
                cfg_path = Path(dst, os.path.basename(f1))

                try:
                    with open(f1, 'r') as yaml_file:
                        cfg = yaml.safe_load(yaml_file)

                    cfg['start_time'] = startdate_topo
                    cfg['end_time'] = enddate_topo

                    with open(cfg_path, 'w') as yaml_file:
                        yaml.dump(cfg, yaml_file, default_flow_style=False, sort_keys=False)
                except (FileNotFoundError, PermissionError, OSError) as e:
                    logger.critical(f"Error updating Topoflow-glacier config at {cfg_path}: {e}")
                    raise

                # replace path to BMI config file in realization file
                src_basename_init = os.path.basename(src0)
                new_basename_init = src_basename_init.replace('_valid', f'_{basename_opt}')
                mod_params['init_config'] = str(Path(dst, new_basename_init))

    return real_config


def update_troute(
        real_config: dict,
        run_dir: Path,
        basename_opt: str
) -> dict:
    """
    For t-route, create new BMI config file with adjusted start/end times, and then
        update path to BMI config files in realization file accordingly

    Arguments
    ---------
    real_config: dictionary containing the realization configuration
    run_dir: folder for the new troute output file
    basename_opt: new file basename for forecast or cold start

    Returns
    -------
    dictionary containing adjusted realization config

    """

    # make sure the source t-route config exists
    src = Path(real_config['routing']['t_route_config_file_with_path']).absolute()
    if not src.exists():
        try:
            raise FileNotFoundError(src)
        except FileNotFoundError as e:
            logger.critical(e)
            raise

    try:
        with open(src) as fp1:
            rt_config = yaml.safe_load(fp1)
    except (FileNotFoundError, yaml.YAMLError) as e:
        logger.critical(f'Error loading config file: {src}\n{e}')
        raise
    except Exception as e:
        logger.critical(f"Unexpected error loading config at: {src}\n{e}")
        raise

    # compute number of time steps and max_loop_size
    try:
        start_time = pd.to_datetime(real_config['time']['start_time'], format="%Y-%m-%d %H:%M:%S") - pd.Timedelta(hours=1)
        end_time = pd.to_datetime(real_config['time']['end_time'], format="%Y-%m-%d %H:%M:%S")
        nts = len(pd.date_range(start=start_time, end=end_time, freq='5min')) - 1
        max_loop_size = divmod(nts * 300, 3600)[0] + 1
    except Exception as e:
        logger.critical(f"Error converting yaml config times: {real_config['time']}\n{e}")
        raise

    # update t-route config
    rt_config['compute_parameters']['restart_parameters']['start_datetime'] = str(start_time)
    rt_config['compute_parameters']['forcing_parameters']['nts'] = nts
    rt_config['compute_parameters']['forcing_parameters']['max_loop_size'] = max_loop_size
    rt_config['output_parameters']['stream_output']['stream_output_time'] = max_loop_size

    # write to new t-route config file
    new_basename = os.path.basename(src).replace("valid_best", basename_opt)

    try:
        new_file = Path(run_dir, new_basename)
        with open(new_file, 'w') as file:
            yaml.dump(rt_config, file, sort_keys=False, default_flow_style=False, indent=4)
    except yaml.YAMLError as e:
        logger.critical(f"YAML serialization error: {new_file}\n{e}")
        raise
    except TypeError as e:
        logger.critical(f"Non-serializable object passed to yaml.dump: {new_file}\n{e}")
        raise
    except OSError as e:
        logger.critical(f"Unexpected error while writing YAML file: {new_file}\n{e}")
        raise

    # update path to new t-route config in realization
    real_config['routing']['t_route_config_file_with_path'] = str(new_file)

    return real_config


def create_troute_config(
        gpkg_file: Union[str, Path],
        time_period: dict,
        rt_cfg_file: Union[str, Path],
        run_configs: List[str],
        run_type: str
) -> None:
    """ Create routing configuration YAML file

    Parameters
    ----------
    gpkg_file :  GeoPackage hydrofabric file
    time_period: simulation time period
    rt_cfg_file : t-route configuration YAML file
    run_configs: list of file name suffixes for varying run types
    run_type: type of run (calib, regionalization, or default)

    Returns
    ----------
    None

    """
    # Determine run names based on run type
    run_type_map = {
        'calibration': ['calib', 'valid', 'valid'],
        'regionalization': ['region'],
        'default': ['default'],
    }
    run_names = run_type_map.get(run_type)

    # Set base log parameters
    log_param = {
        "showtiming": True,
        "log_level": 'DEBUG'
    }

    # Set network topology parameters
    nwtopo_param = {
        "supernetwork_parameters": {
            "geo_file_path": str(gpkg_file),
            "network_type": "NHF",
        },
        "waterbody_parameters": {
            "break_network_at_waterbodies": True
        },
    }

    # Set base data assimilation parameters
    stream_da = {
        "streamflow_nudging": False,
        "diffusive_streamflow_nudging": False,
    }

    res_da = {
        "reservoir_persistence_da": {
            "reservoir_persistence_usgs": False,
        },
        "reservoir_rfc_da": {
            "reservoir_rfc_forecasts": False,
        },
    }

    for file_name, run_name in zip(run_configs, run_names):
        if not len(time_period['run_time_period'][run_name][0]) != 0 & len(time_period['run_time_period'][run_name][0]):
            continue

        # Parse time and compute time steps
        run_range = pd.to_datetime(time_period['run_time_period'][run_name])
        nts = len(pd.date_range(start=run_range[0], end=run_range[1], freq='5min')) - 1
        max_loop_size = divmod(nts * 300, 3600)[0] + 1

        # Set compute parameters
        comp_param = {
            "parallel_compute_method": "by-subnetwork-jit-clustered",
            "compute_kernel": "V02-structured",
            "assume_short_ts": True,
            "subnetwork_target_size": 10000,
            "cpu_pool": 16,  # TODO: Should this be set from info in the Parallel section?
            "restart_parameters": {
                "start_datetime": time_period['run_time_period'][run_name][0]
            },
            "forcing_parameters": {
                "qts_subdivisions": 12,
                "dt": 300,  # Timestep in seconds
                "qlat_input_folder": ".",
                "qlat_file_pattern_filter": "nex-*",  # TODO: Possibly update based on NHF ngen output names
                "nts": nts,
                "max_loop_size": max_loop_size
            },
            "data_assimilation_parameters": {
                "streamflow_da": stream_da,
                "reservoir_da": res_da
            },
        }

        # Set output_parameters
        output_param = {
            'stream_output': {
                'stream_output_directory': ".",
                'stream_output_time': max_loop_size,
                'stream_output_type': '.nc',
                'stream_output_internal_frequency': 60,
            },
        }

        # Combine all parameters
        config = {
            "log_parameters": log_param,
            "network_topology_parameters": nwtopo_param,
            "compute_parameters": comp_param,
            "output_parameters": output_param,
        }

        # Save configuration into yaml file
        routing_config_file = f'{rt_cfg_file}{file_name}'
        with open(routing_config_file, 'w') as file:
            yaml.dump(config, file, sort_keys=False, default_flow_style=False, indent=4)
        run_name1 = file_name.replace('_troute_config_', '').replace('.yaml', '')
        logger.info(f'troute config file for {run_name1} is created at: {routing_config_file}')


def create_fcst_times(
        forcing_template: dict,
        cycle_date: str,
        cycle_hour: str,
        use_cold_start: bool,
        use_warm_start: bool,
        hind_cycle: int = None,
        prev_hind_cycle: int = None,
        forcing_lag: int = None,
        cold_start_datetime: str = None,
        fcst_lookback: int = None
) -> Tuple[str, str]:
    """ Compute forecast start and end time based on selected forecast cycle, date, and hour

    Parameters
    ----------
    forecast_template: dictionary of forecast config file template
    cycle_date : date of forecast cycle
    cycle_hour : hour of forecast cycle (00z)
    use_cold_start : boolean flag for using cold start period
    use_warm_start: boolean flag for using warm start run
    hind_cycle: cycle (in hours) between first hindcast iteration (00) and current hindcast iteration
    prev_hind_cycle: cycle (in hours) from previous hindcast iteration, used to orchestrate warm start runs
    forcing_lag: number of hours forcing valid time is lagged from ngen start time in lagged ensemble run
    cold_start_datetime : datetime str of beginning of cold start period
    fcst_lookback : lookback time in hours of forecast configuration following cold start

    Returns
    ----------
    fcst_start: datetime of ngen start time for forecast
    fcst_end: datetime of ngen end time for forecast

    """

    # Convert cycle date and hour to datetime
    cycle_dt = datetime.datetime.strptime(cycle_date, "%Y-%m-%d").replace(hour=int(cycle_hour.replace("z", "")))
    cs_dt = datetime.datetime.strptime(cold_start_datetime, "%Y-%m-%d %H:%M:%S") if cold_start_datetime else None

    # Retrieve AnAFlag
    ana_flag = forcing_template['AnAFlag']

    # Construct start and end times for cold start period
    if use_cold_start:

        # fcst_lookback aligns cold start end with start of forecast start for AnA configurations
        fcst_start = datetime.datetime.strftime(cs_dt + datetime.timedelta(hours=1), "%Y-%m-%d %H:%M:%S")
        fcst_end = datetime.datetime.strftime(cycle_dt - datetime.timedelta(hours=fcst_lookback), "%Y-%m-%d %H:%M:%S")

    # Construct start and end times for warm start period
    elif use_warm_start:

        # Warm start begins at the start of the previous hindcast cycle and ends at the start of the current hindcast cycle
        # fcst_lookback shifts the warm start period to align with cold start for AnA configurations
        fcst_start = datetime.datetime.strftime(cycle_dt + datetime.timedelta(hours=prev_hind_cycle) - datetime.timedelta(hours=fcst_lookback) + datetime.timedelta(hours=1), "%Y-%m-%d %H:%M:%S")
        fcst_end = datetime.datetime.strftime(cycle_dt + datetime.timedelta(hours=hind_cycle) - datetime.timedelta(hours=fcst_lookback), "%Y-%m-%d %H:%M:%S")

    # Construct start and end times for warm start period
    elif use_warm_start:
        # Warm start begins at the start of the previous hindcast cycle and ends at the start of the current hindcast cycle
        fcst_start = datetime.datetime.strftime(cycle_dt + datetime.timedelta(hours=prev_hind_cycle), "%Y-%m-%d %H:%M:%S")
        fcst_end = datetime.datetime.strftime(cycle_dt + datetime.timedelta(hours=hind_cycle), "%Y-%m-%d %H:%M:%S")

    # Construct start and end times based on forecast cycle
    elif ana_flag == 0:

        # Retrieve forecast input horizon from config file
        forcing_horizon = int(forcing_template['ForecastInputHorizons'][0] / 60)
        start_delta = 1

        fcst_start = datetime.datetime.strftime(cycle_dt + datetime.timedelta(hours=hind_cycle) + datetime.timedelta(hours=start_delta), "%Y-%m-%d %H:%M:%S")
        fcst_end = datetime.datetime.strftime(cycle_dt + datetime.timedelta(hours=forcing_horizon) + datetime.timedelta(hours=hind_cycle) - datetime.timedelta(hours=forcing_lag), "%Y-%m-%d %H:%M:%S")

    # Construct start and end times based on analysis cycle
    elif ana_flag == 1:

        # Retrieve analysis lookback from config file
        forcing_lookback = int(forcing_template['LookBack'] / 60) - 1

        fcst_start = datetime.datetime.strftime(cycle_dt + datetime.timedelta(hours=hind_cycle) - datetime.timedelta(hours=forcing_lookback), "%Y-%m-%d %H:%M:%S")
        fcst_end = datetime.datetime.strftime(cycle_dt + datetime.timedelta(hours=hind_cycle), "%Y-%m-%d %H:%M:%S")

    return fcst_start, fcst_end


def replace_forcing_placeholders(
        obj: Any,
        vars: dict[str, str]
) -> Any:
    """
    Recursively replace root path or gage name in forcing engine yaml file
    """
    # Recurse through dictionary
    if isinstance(obj, dict):
        return {k: replace_forcing_placeholders(v, vars) for k, v in obj.items()}

    # Recurse through list
    if isinstance(obj, list):
        return [replace_forcing_placeholders(i, vars) for i in obj]

    # Replace placeholders if string contains format pattern
    elif isinstance(obj, str):
        for placeholder, value in vars.items():
            # only replace if value is not None
            if value is not None:
                obj = obj.replace(placeholder, str(value))
        return obj

    else:
        return obj


class NoForcingProductVersionMatchError(Exception):
    """Returned by get_forcing_dir_path_override when the forcing product basename
    does not have a match in the provided lookup dictionary"""


def get_forcing_dir_path_override(
    forcing_dir_path_provided: str,
    forcing_product_versions: dict[str, list[str, str]],
) -> tuple[str | None, Exception | None]:
    """
    Inspect the provided forcing directory path and return a copy of it
    that has been overridden using the provided dictionary.

    Parameters
    ----------
    forcing_dir_path_provided : str
        The forcing directory path as read from the forcing configuration yaml file.
    forcing_product_versions : dictionary of forcing product directories,
        keyed on product name,
        with value being a list of 2 elements:
            1. Directory path (with format parameter {vers}),
            2. A version string to use in the string replacement.

        These are used to override any paths found in InputForcingDirectories, SuppPcpDirectories, SuppPcpParamDir

        Example:
            {
                "HRRR":     ["/lfs/h1/ops/prod/com/hrrr/{vers}", "v4.1"],
                "HRRR_ANA": ["/lfs/h1/ops/prod/com/hrrr/{vers}", "v4.1"],
            }

    Returns
    -------
    str
        Path after applying override.
        If no override provided, then the original path is returned.
        If a problem is detected in the inputs, then None is returned.
    Exception | None
        If a problem is detected in the inputs, an exception will be returned, otherwise None will be returned.
    """
    # As written in the forcing config file
    forcing_product_name = os.path.basename(forcing_dir_path_provided)
    try:
        val = forcing_product_versions[forcing_product_name]
    except KeyError:
        return None, NoForcingProductVersionMatchError(
            f"Forcing product name {repr(forcing_product_name)} was derived from path {forcing_dir_path_provided}, but was not found in forcing_product_versions keys: {list(forcing_product_versions)}"
        )
    path_template, version = val
    dir_path_adjusted = path_template.format(vers=version)
    return dir_path_adjusted, None


def adjust_forcing_config_for_wcoss(
    forcing_template: dict[str, str],
    scratch_dir_override: str | None = None,
    forcing_product_versions: dict[str, str] | None = None,
) -> dict[str, str]:
    """Adjust the forcing config dictionary for WCOSS use case, if the optional parameters are provided.

    Parameters
    ----------
    forcing_template : dictionary of forcing bmi config template file
    scratch_dir_override (optional) : if provided, replaces entire value of key ScratchDir
    forcing_product_versions (optional) : dictionary of overrides for forcing product directories,
        keyed on product name,
        with value being a list of 2 elements:
            1. Directory path to use -- a "format" string with format parameter {vers} to be replaced,
            2. A version string to use in the string replacement.

        These are used to override any paths found in InputForcingDirectories, SuppPcpDirectories, SuppPcpParamDir

        SuppPcpParamDir is treated specially in that it is less strict -- if its input basename value (from config yml file)
        does not have a match in the provided forcing_product_versions dict, then it uses the value from the config yml file
        as is (does not raise an exception).

        InputForcingDirectories and SuppPcpDirectories are strict -- they raise an exception if they do not have a match in forcing_product_versions.

        Example:
            {
                "HRRR":     ["/lfs/h1/ops/prod/com/hrrr/{vers}", "v4.1"],
                "HRRR_ANA": ["/lfs/h1/ops/prod/com/hrrr/{vers}", "v4.1"],
            }

    Returns
    ----------
    A copy of forcing_template, modified if optional arguments were provided.
    """
    errors: list[Exception] = []

    d = copy.deepcopy(forcing_template)

    # For ScratchDir, replace the entire string if "scratch_dir_override" is provided.
    if scratch_dir_override:
        if "ScratchDir" not in d:
            raise KeyError(f"Key 'ScratchDir' not in forcing_template: {d}")
        d["ScratchDir"] = scratch_dir_override

    if forcing_product_versions:
        expected_keys = [
            "InputForcingDirectories",
            "SuppPcpDirectories",
            "SuppPcpParamDir",
        ]
        for k in expected_keys:
            if k not in d:
                raise KeyError(f"Missing key {repr(k)} in keys {list(d)}")

        all_forcing_dirs_lists = [d["InputForcingDirectories"], d["SuppPcpDirectories"]]
        for dirs_list in all_forcing_dirs_lists:
            if not dirs_list:
                continue

            for i, dir_path_orig in enumerate(dirs_list):
                forcing_dir_path_override, error = get_forcing_dir_path_override(
                    dir_path_orig,
                    forcing_product_versions,
                )
                if error:
                    errors.append(error)
                else:
                    dirs_list[i] = forcing_dir_path_override

        # This is a single value rather than a list
        if d["SuppPcpParamDir"]:
            forcing_dir_path_override, error = get_forcing_dir_path_override(
                d["SuppPcpParamDir"], forcing_product_versions
            )
            if error:
                # SuppPcpParamDir is treated differently, it is less strict.
                # If there is no product it just uses what was in the config file rather than raising an error.
                if isinstance(error, NoForcingProductVersionMatchError):
                    logger.warning(
                        f"No match for SuppPcpParamDir {repr(d['SuppPcpParamDir'])} in provided product version dictionary {list(forcing_product_versions)}. Not applying override."
                    )
                    pass
                else:
                    errors.append(error)
            else:
                d["SuppPcpParamDir"] = forcing_dir_path_override

    if errors:
        logger.critical(errors)
        raise RuntimeError(errors)

    return d


def update_fcst_forcing_config(
        cycle_date: str,
        cycle_hour: str,
        root_dir: str,
        forcing_template: dict,
        gpkg_file: str,
        forcing_config_dir: Path,
        forcing_config_file: Path,
        use_cold_start: bool,
        use_warm_start: bool,
        hind_cycle: int,
        prev_hind_cycle: int,
        forcing_lag: int,
        cold_start_datetime: str = None,
        fcst_lookback: int = None,
        scratch_dir_override: str | None = None,
        forcing_product_versions: dict[str, str] | None = None,
) -> None:
    """ update bmi forcing engine config yaml file for forecast forcing

    Parameters
    ----------
    cycle_date : date of forecast cycle
    cycle_hour : hour of forecast cycle (00z)
    root_dir : root directory for forcing engine paths
    forcing_template : dictionary of forcing bmi config template file
    gpkg_file: path to geopackage file
    forcing_config_dir: directory path for forcing config file
    forcing_config_dir: output path for forcing config file
    use_cold_start : boolean flag for using cold start period
    use_warm_start: boolean flag for using warm start period
    hind_cycle: cycle (in hours) between first hindcast iteration (00) and current hindcast iteration
    prev_hind_cycle: cycle (in hours) from previous hindcast iteration, used to orchestrate warm start runs
    forcing_lag: number of hours forcing valid time is lagged from ngen start time in lagged ensemble run
    cold_start_datetime : datetime str of beginning of cold start period
    fcst_lookback : lookback time in hours of forecast configuration following cold start
    scratch_dir_override (optional) : if provided, replaces entire value of key ScratchDir
    forcing_product_versions (optional) : see function update_fcst_config_for_wcoss

    Returns
    ----------
    None
    """

    # Create directory for storing config file
    os.makedirs(forcing_config_dir, exist_ok=True)

    ana_flag = forcing_template['AnAFlag']

    # Format cycle_date and hour for config file
    initial_cycle_dt = datetime.datetime.strptime(cycle_date, "%Y-%m-%d").replace(hour=int(cycle_hour.replace("z", "")))
    cycle_dt = initial_cycle_dt + datetime.timedelta(hours=hind_cycle) - datetime.timedelta(hours=forcing_lag)
    cycle_str = cycle_dt.strftime('%Y%m%d%H%M')

    # Set lookback minutes for cold start period
    if use_cold_start:
        cold_start_dt = datetime.datetime.strptime(cold_start_datetime, "%Y-%m-%d %H:%M:%S")
        lookback = int((cycle_dt - cold_start_dt).total_seconds() / 60)
        forcing_template['LookBack'] = lookback

    # Set lookback minutes for warm start period
    elif use_warm_start:
        lookback = int((hind_cycle - prev_hind_cycle) * 60)
        forcing_template['LookBack'] = lookback

    # Set geogrid file name
    gpkg_name = os.path.splitext(os.path.basename(gpkg_file))[0]

    # Replace {root_dir} and {gage} placeholders in forcing config
    vars = {"{root_dir}": root_dir,
            "{gage}": gpkg_name}
    forcing_template = replace_forcing_placeholders(forcing_template, vars)

    # Update forcing_template with dynamic variables
    if ana_flag:
        forcing_template['RefcstBDateProc'] = (cycle_dt - datetime.timedelta(hours=fcst_lookback) - datetime.timedelta(hours=1)).strftime('%Y%m%d%H%M')
    else:
        forcing_template['RefcstBDateProc'] = cycle_str
    forcing_template['Geopackage'] = gpkg_file

    forcing_template = adjust_forcing_config_for_wcoss(
        forcing_template,
        scratch_dir_override,
        forcing_product_versions,
    )
    # Write forcing config yaml file
    with open(forcing_config_file, "w", encoding="utf-8") as file:
        yaml.dump(forcing_template, file, Dumper=ForcingDumper, sort_keys=False, default_flow_style=False)


def update_hist_forcing_config(
        time_period: dict,
        root_dir: str,
        forcing_template: dict,
        gpkg_file: str,
        forcing_config_dir: Path,
        forcing_config_file: Path,
        run_type: str,
        domain: str,
        forcing_static_dir: str,
) -> None:
    """ update bmi forcing engine config yaml file for historical forcing

    Parameters
    ----------
    time_period: dictionary of run start and end time
    root_dir : root directory for forcing engine paths
    forcing_template : dictionary of forcing bmi config template file
    gpkg_file: path to geopackage file
    forcing_config_dir: directory path for forcing config file
    forcing_config_dir: output path for forcing config file
    run_type: type of run (calib, regionalization, or default)
    domain: domain name for historical runs
    forcing_static_dir: directory for static data files (e.g. geogrid) for historical runs

    Returns
    ----------
    None
    """

    # Create directory for storing config file
    os.makedirs(forcing_config_dir, exist_ok=True)

    # Retrieve start and end times
    start_times = []
    end_times = []
    if run_type == 'regionalization':
        start_times.append(datetime.datetime.strptime(time_period['run_time_period']['region'][0], '%Y-%m-%d %H:%M:%S'))
        end_times.append(datetime.datetime.strptime(time_period['run_time_period']['region'][1], '%Y-%m-%d %H:%M:%S'))
    elif run_type == 'default':
        start_times.append(datetime.datetime.strptime(time_period['run_time_period']['default'][0], '%Y-%m-%d %H:%M:%S'))
        end_times.append(datetime.datetime.strptime(time_period['run_time_period']['default'][1], '%Y-%m-%d %H:%M:%S'))
    elif run_type == 'calibration':
        start_times.append(datetime.datetime.strptime(time_period['run_time_period']['calib'][0], '%Y-%m-%d %H:%M:%S'))
        start_times.append(datetime.datetime.strptime(time_period['run_time_period']['valid'][0], '%Y-%m-%d %H:%M:%S'))
        end_times.append(datetime.datetime.strptime(time_period['run_time_period']['calib'][1], '%Y-%m-%d %H:%M:%S'))
        end_times.append(datetime.datetime.strptime(time_period['run_time_period']['valid'][1], '%Y-%m-%d %H:%M:%S'))

    file_suffix = ['', 'valid'] if run_type == 'calibration' else ['']

    # Set geogrid file name
    gpkg_name = os.path.splitext(os.path.basename(gpkg_file))[0]

    # Replace {root_dir} and {gage} placeholders in forcing config
    vars = {'{root_dir}': root_dir,
            '{gage}': gpkg_name,
            '{global_domain}': domain,
            '{forcing_static_dir}': forcing_static_dir,
            }
    forcing_template = replace_forcing_placeholders(forcing_template, vars)
    forcing_template['Geopackage'] = gpkg_file

    for i in range(len(start_times)):

        # Determine length of run in minutes
        diff_time = int((end_times[i] - start_times[i]).total_seconds() / 60)

        # Format start time for config file
        start_str = start_times[i].strftime('%Y%m%d%H%M')

        # Update forcing_template with dynamic variables
        forcing_template['RefcstBDateProc'] = start_str
        forcing_template['ForecastInputHorizons'] = [diff_time]

        # If creating validation run forcing engine config, append file suffix for valid
        if file_suffix[i] == 'valid':
            forcing_config_file = forcing_config_file.with_name(forcing_config_file.stem + '_' + file_suffix[i] + forcing_config_file.suffix)

        # Write forcing config yaml file
        with open(forcing_config_file, "w", encoding="utf-8") as file:
            yaml.dump(forcing_template, file, Dumper=ForcingDumper, sort_keys=False, default_flow_style=False)


def update_forcing_in_realization(
        real_config: dict,
        forcing_path: Path,
        forcing_config_file: Path,
        fcst_start: str,
        fcst_end: str,
        basename_opt: str
) -> dict:
    """
    Adjust the realization configuration with forecast or cold start information accordingly:
        1) update forcing information
        2) update start and end times

    Arguments
    ---------
    real_config: dictionary containing the realization configuration
    forcing_path: path to run /forcing/ folder
    forcing_config_file: path to forcing engine configuration yaml file
    fcst_start: cold_start or fcst ngen start time
    fcst_end: cold_start or fcst ngen end time
    basename_opt: new file basename for forecast or cold start

    Returns
    -------
    dictionary containing the adjusted realization config

    """

    # Check for format of realization file
    real_format = 'grouped' if 'formulation_groups' in real_config else 'uniform'

    # Update realization file for forcing
    forcing_update = {"path": str(forcing_path),
                      "provider": "ForcingsEngineLumpedDataProvider",
                      "params": {"init_config": str(forcing_config_file)}}
    if real_format == 'uniform':
        real_config['global']['forcing'] = forcing_update
    else:
        forcing_grp_key = next(iter(real_config['forcing_groups']))
        real_config['forcing_groups'][forcing_grp_key] = forcing_update

    # Update time period in realization file
    real_config['time']['start_time'] = fcst_start
    real_config['time']['end_time'] = fcst_end

    # Retrieve modules from realization
    if real_format == 'uniform':
        modules_list = real_config['global']['formulations'][0]['params']['modules']
    else:
        modules_list = []
        for grp in real_config['formulation_groups'].values():
            for form in grp:
                modules_list.extend(form['params']['modules'])

    # Update variable names map for forcing engine
    for mod in modules_list:

        # Retrieve module name and variable names map for module
        mod_params = mod.get('params')
        mod_var_names = mod_params.get('variables_names_map')

        # Map module variable names to new forcing engine names
        if mod_var_names is not None:
            mod['params']['variables_names_map'] = map_var_names_forcing_engine(mod_var_names)

    return real_config


def get_forcing_vars_map() -> dict:
    """
    Get CSDMS to forcing engine variable name mapping
    """
    return {
        "prcp": {
            "csv": "atmosphere_water__liquid_equivalent_precipitation_rate",
            "bmi": "RAINRATE_ELEMENT",
        },
        "Q2": {
            "csv": "atmosphere_air_water~vapor__relative_saturation",
            "bmi": "Q2D_ELEMENT",
        },
        "temp": {
            "csv": "land_surface_air__temperature",
            "bmi": "T2D_ELEMENT",
        },
        "xwind": {
            "csv": "land_surface_wind__x_component_of_velocity",
            "bmi": "U2D_ELEMENT",
        },
        "ywind": {
            "csv": "land_surface_wind__y_component_of_velocity",
            "bmi": "V2D_ELEMENT",
        },
        "lw": {
            "csv": "land_surface_radiation~incoming~longwave__energy_flux",
            "bmi": "LWDOWN_ELEMENT",
        },
        "sw": {
            "csv": "land_surface_radiation~incoming~shortwave__energy_flux",
            "bmi": "SWDOWN_ELEMENT",
        },
        "pressure": {
            "csv": "land_surface_air__pressure",
            "bmi": "PSFC_ELEMENT",
        },
    }


def map_var_names_forcing_engine(
        mod_var_names: dict
) -> Dict[str, str]:
    """
    Set realization variables_names_map for forcing engine based on module name
    """
    forcing_var_map = get_forcing_vars_map()

    # Set variable name mapping based on forcing provider
    name_dict = {forcing_var_map[key]["csv"]: forcing_var_map[key]["bmi"]
                 for key in forcing_var_map}

    return {key: name_dict.get(value, value) for key, value in mod_var_names.items()}


def var_mapping(
        modules: List[str],
        pet_in: str,
        pcp_in: str,
        pcp_forcing: str,
        output_dict: dict,
) -> Dict[str, str]:
    """ create variable name mapping based on modules

    Parameters
    ----------
    modules: list of modules in the formulation
    pet_in: module input variable name for evapotranspiration
    pcp_in: module input variable name for precipitation
    pcp_forcing: name of precipitation forcing variable
    output_dict: dictionary defining which output variables to write out

    Returns
    ----------
    Variable name mapping dictionary (for module inputs and outputs).
    Currently the following outputs are included:
        swe_out: output variable name for SWE (snow water equivalent)
        sm_out: output variable names for soil mositure fraction and soil moisture profile

    """
    var_maps = {'input': {}, 'output': {}}

    # only needed when CFE is not coupled to SFT/SMP
    if ('cfes' in modules or 'cfex' in modules) and ('sft' not in modules) and ('smp' not in modules):
        var_maps['input']["ice_fraction_schaake"] = "sloth_ice_fraction_schaake"
        var_maps['input']["ice_fraction_xinanjiang"] = "sloth_ice_fraction_xinanjiang"
        var_maps['input']["soil_moisture_profile"] = "sloth_smp"

    # PET
    if 'noah' in modules and 'pet' not in modules:
        var_maps['input'][pet_in] = "EVAPOTRANS"

    if 'pet' in modules and ('sac' in modules or 'lasam' in modules):
        var_maps['input'][pet_in] = "water_potential_evaporation_flux"

    # Map precipitation and swe output
    swe_precip_map = {
        'snow17': (pcp_in, 'raim', 'sneqv', 'SWE_mm', 'mm'),
        'ueb': (pcp_in, 'SWIT', 'SWE', 'SWE_m', 'm'),
        'noah': (pcp_in, 'QINSUR', 'SNEQV', 'SWE_mm', 'mm')
    }

    for mod, (pcp_key, pcp_var, swe_var, swe_hdr, swe_unit) in swe_precip_map.items():
        if mod in modules:
            # Only add precip input if pcp_var is not None
            if pcp_var is not None:
                var_maps['input'][pcp_key] = pcp_var
            if output_dict['output_swe']:
                var_maps['output']['swe_out'] = swe_var
                var_maps['output']['swe_out_header'] = swe_hdr
                var_maps['output']['swe_out_units'] = swe_unit
            else:
                var_maps['output']['swe_out'] = ''
            break
    else:
        # Assign precipitation forcing mapping if needed
        if pcp_in != pcp_forcing:
            var_maps['input'][pcp_in] = pcp_forcing
        # Default swe_out if module is not in swe_precip_map
        var_maps['output']['swe_out'] = ''

    # soil moisture fraction
    if 'smp' in modules and output_dict['output_sm']:
        sm_frac_depth = output_dict["sm_frac_depth"]
        depths = output_dict.get("sm_profile_depth", [])

        var_maps["output"]["sm_out"] = ["soil_moisture_fraction"]
        var_maps["output"]["sm_out_header"] = [f"sm_frac_{float(sm_frac_depth):g}m"]
        var_maps["output"]["sm_out_units"] = ["1"]
        var_maps["output"]["sm_out_index"] = ["0"]

        # Add soil moisture profile for each depth
        for i, d in enumerate(depths):
            var_maps["output"]["sm_out"].append("soil_moisture_profile")
            var_maps["output"]["sm_out_header"].append(f"sm_profile_{float(d):g}m")
            var_maps["output"]["sm_out_units"].append("1")
            var_maps["output"]["sm_out_index"].append(str(i))
    else:
        var_maps['output']['sm_out'] = ''

    return var_maps


def get_model_type_name(
        module: str
) -> str:
    return settings.modules_all.loc[settings.modules_all['module'] == module, 'name_config'].iloc[0]


def create_lib_symlinks(workdir: Union[str, Path], lib_file: dict) -> dict:
    """Create symlinks for model libraries."""
    lib_mod = {}
    for key, value in lib_file.items():
        lib_mod_link = os.path.join(workdir, 'Input/' + os.path.basename(value))
        lib_mod[key] = lib_mod_link

        if os.path.exists(lib_mod_link) or os.path.islink(lib_mod_link):
            try:
                os.unlink(lib_mod_link)
            except Exception as e:
                logger.error(f"Failed to remove existing {lib_mod_link}: {e}")
                raise
        try:
            os.symlink(value, lib_mod_link)
            logger.info(f"Created symlink to {lib_mod_link}")
        except OSError as e:
            logger.critical(f"Failed to create symlink: {value} -> {lib_mod_link}: {e}")
            raise

    return lib_mod


def get_sloth_params(modules: List[str], adapters: List[str] = None) -> dict:
    """Get SLOTH model parameters based on model configuration"""
    adapters = adapters or []
    smp_as_adapter = 'smp' in adapters
    sft_as_adapter = 'sft' in adapters

    if 'cfes' in modules or 'cfex' in modules or 'cfes' in adapters:
        if sft_as_adapter and smp_as_adapter:
            # smp/sft added as adapters: sloth must provide soil storage vars
            return {
                "sloth_soil_storage(1,double,m,node)": 1.0E-10,
                "sloth_soil_storage_change(1,double,m,node)": 0.0,
                "soil_moisture_wetting_fronts(1,double,1,node)": 0.0,
                "soil_thickness_layered(1,double,1,node)": 0.0,
                "soil_depth_wetting_fronts(1,double,m,node)": 0.0,
                "num_wetting_fronts(1,int,1,node)": 1.0,
                "Qb_topmodel(1,double,m h^-1,node)": 0.0,
                "Qv_topmodel(1,double,m h^-1,node)": 0.0,
                "global_deficit(1,double,m,node)": 0.0,
            }
        elif 'sft' not in modules:
            return {
                "sloth_ice_fraction_schaake(1,double,1,node)": 0.0,
                "sloth_ice_fraction_xinanjiang(1,double,1,node)": 0.0,
                "sloth_smp(1,double,1,node)": 0.0,
            }
        else:
            return {
                "soil_moisture_wetting_fronts(1,double,1,node)": 0.0,
                "soil_thickness_layered(1,double,1,node)": 0.0,
                "soil_depth_wetting_fronts(1,double,m,node)": 0.0,
                "num_wetting_fronts(1,int,1,node)": 1.0,
                "Qb_topmodel(1,double,m h^-1,node)": 0.0,
                "Qv_topmodel(1,double,m h^-1,node)": 0.0,
                "global_deficit(1,double,m,node)": 0.0,
            }
    elif 'topmodel' in modules:
        if 'smp' in modules:
            return {
                "sloth_soil_storage(1,double,m,node)": 1.0E-10,
                "sloth_soil_storage_change(1,double,m,node)": 0.0,
                "soil_moisture_wetting_fronts(1,double,1,node)": 0.0,
                "soil_depth_wetting_fronts(1,double,1,node)": 0.0,
                "num_wetting_fronts(1,int,1,node)": 1,
            }
        elif smp_as_adapter:
            return {
                "sloth_soil_storage(1,double,m,node)": 1.0E-10,
                "sloth_soil_storage_change(1,double,m,node)": 0.0,
                "soil_moisture_wetting_fronts(1,double,1,node)": 0.0,
                "soil_thickness_layered(1,double,1,node)": 0.0,
                "soil_depth_wetting_fronts(1,double,m,node)": 0.0,
                "num_wetting_fronts(1,int,1,node)": 1.0,
                "Qb_topmodel(1,double,m h^-1,node)": 0.0,
                "Qv_topmodel(1,double,m h^-1,node)": 0.0,
                "global_deficit(1,double,m,node)": 0.0,
            }
    elif 'sac' in modules:
        if 'smp' in modules:
            return {
                "soil_moisture_wetting_fronts(1,double,1,node)": 0.0,
                "soil_thickness_layered(1,double,1,node)": 0.0,
                "soil_depth_wetting_fronts(1,double,m,node)": 0.0,
                "num_wetting_fronts(1,int,1,node)": 1.0,
                "Qb_topmodel(1,double,m h^-1,node)": 0.0,
                "Qv_topmodel(1,double,m h^-1,node)": 0.0,
                "global_deficit(1,double,m,node)": 0.0
            }
        elif smp_as_adapter:
            return {
                "sloth_soil_storage(1,double,m,node)": 1.0E-10,
                "sloth_soil_storage_change(1,double,m,node)": 0.0,
                "soil_moisture_wetting_fronts(1,double,1,node)": 0.0,
                "soil_thickness_layered(1,double,1,node)": 0.0,
                "soil_depth_wetting_fronts(1,double,m,node)": 0.0,
                "num_wetting_fronts(1,int,1,node)": 1.0,
                "Qb_topmodel(1,double,m h^-1,node)": 0.0,
                "Qv_topmodel(1,double,m h^-1,node)": 0.0,
                "global_deficit(1,double,m,node)": 0.0,
            }
    elif 'lasam' in modules:
        if 'sft' not in modules and not sft_as_adapter:
            return {"soil_temperature_profile(1,double,K,node)": 275.15}
        elif smp_as_adapter:
            return {
                "sloth_soil_storage(1,double,m,node)": 1.0E-10,
                "sloth_soil_storage_change(1,double,m,node)": 0.0,
                "Qb_topmodel(1,double,m h^-1,node)": 0.0,
                "Qv_topmodel(1,double,m h^-1,node)": 0.0,
                "global_deficit(1,double,m,node)": 0.0,
                "num_wetting_fronts(1,int,1,node)": 1.0,
                "potential_evapotranspiration_rate(1,double,1,node)": 0.0
            }
        else:
            return {
                "sloth_soil_storage(1,double,m,node)": 1.0E-10,
                "sloth_soil_storage_change(1,double,m,node)": 0.0,
                "Qb_topmodel(1,double,m h^-1,node)": 0.0,
                "Qv_topmodel(1,double,m h^-1,node)": 0.0,
                "global_deficit(1,double,m,node)": 0.0,
                "potential_evapotranspiration_rate(1,double,1,node)": 0.0
            }
    return {}


def get_smp_var_map(modules: List) -> dict:
    """Get SMP variable mapping based on coupled modules"""
    base_map = {
        "soil_storage": "SOIL_STORAGE",
        "soil_storage_change": "SOIL_STORAGE_CHANGE",
    }

    if 'lasam' in modules:
        return {
            "soil_storage": "sloth_soil_storage",
            "soil_storage_change": "sloth_soil_storage_change",
            "soil_moisture_wetting_fronts": "soil_moisture_wetting_fronts",
            "soil_depth_wetting_fronts": "soil_depth_wetting_fronts",
            "num_wetting_fronts": "soil_num_wetting_fronts"
        }
    elif 'topmodel' in modules:
        return {
            "soil_storage": "sloth_soil_storage",
            "soil_storage_change": "sloth_soil_storage_change",
            "Qb_topmodel": "land_surface_water__baseflow_volume_flux",
            "Qv_topmodel": "soil_water_root-zone_unsat-zone_top__recharge_volume_flux",
            "global_deficit": "soil_water__domain_volume_deficit"
        }
    elif 'sac' in modules:
        return {
            "soil_storage": "uzsmc",
            "soil_storage_change": "uzsmc_ch"
        }
    return base_map


def build_base_config(module: str, lib_mod: dict, bmi_dir: dict, run_type_abbr: str, forcing_provider: str, forcing_vars: dict) -> dict:
    """Build module configuration templates for realization"""
    if module == 'noah':
        return {
            "name": "bmi_fortran",
            "model_type_name": get_model_type_name('noah'),
            "main_output_variable": "QINSUR",
            "library_file": lib_mod['noah'],
            "init_config": os.path.join(bmi_dir['noah'], '{{id}}_' + run_type_abbr + '.input'),
            "allow_exceed_end_time": True,
            "fixed_time_step": False,
            "uses_forcing_file": False,
            "variables_names_map": {"PRCPNONC": forcing_vars['prcp'].get(forcing_provider),
                                    "Q2": forcing_vars['Q2'].get(forcing_provider),
                                    "SFCTMP": forcing_vars['temp'].get(forcing_provider),
                                    "UU": forcing_vars['xwind'].get(forcing_provider),
                                    "VV": forcing_vars['ywind'].get(forcing_provider),
                                    "LWDN": forcing_vars['lw'].get(forcing_provider),
                                    "SOLDN": forcing_vars['sw'].get(forcing_provider),
                                    "SFCPRS": forcing_vars['pressure'].get(forcing_provider),
                                    },
        }
    elif module == 'cfes':
        return {
            "name": "bmi_c",
            "model_type_name": get_model_type_name('cfes'),
            "main_output_variable": "Q_OUT",
            "library_file": lib_mod['cfes'],
            "init_config": os.path.join(bmi_dir['cfes'], '{{id}}_bmi_config_cfe.txt'),
            "allow_exceed_end_time": True,
            "fixed_time_step": False,
            "uses_forcing_file": False,
            "registration_function": "register_bmi_cfe",
            "precip_output": "atmosphere_water__liquid_equivalent_precipitation_rate_out",
        }
    elif module == 'cfex':
        return {
            "name": "bmi_c",
            "model_type_name": get_model_type_name('cfex'),
            "main_output_variable": "Q_OUT",
            "library_file": lib_mod['cfex'],
            "init_config": os.path.join(bmi_dir['cfex'], '{{id}}_bmi_config_cfe.txt'),
            "allow_exceed_end_time": True,
            "fixed_time_step": False,
            "uses_forcing_file": False,
            "registration_function": "register_bmi_cfe",
            "precip_output": "atmosphere_water__liquid_equivalent_precipitation_rate_out",
        }
    elif module == 'topmodel':
        return {
            "name": "bmi_c",
            "model_type_name": get_model_type_name('topmodel'),
            "main_output_variable": "Qout",
            "library_file": lib_mod['topmodel'],
            "init_config": os.path.join(bmi_dir['topmodel'], '{{id}}_topmodel.run'),
            "allow_exceed_end_time": True,
            "fixed_time_step": False,
            "uses_forcing_file": False,
            "registration_function": "register_bmi_topmodel",
            "precip_output": "atmosphere_water__liquid_equivalent_precipitation_rate_out",
        }
    elif module == 'sac':
        return {
            "name": "bmi_fortran",
            "model_type_name": get_model_type_name('sac'),
            "main_output_variable": "tci_giuh",
            "library_file": lib_mod['sac'],
            "init_config": os.path.join(bmi_dir['sac'], 'sac-init-{{id}}.namelist.input'),
            "allow_exceed_end_time": True,
            "fixed_time_step": False,
            "uses_forcing_file": False,
            "registration_function": "register_bmi_sac",
            "precip_output": "precip_out",
        }
    elif module == 'snow17':
        return {
            "name": "bmi_fortran",
            "model_type_name": get_model_type_name('snow17'),
            "main_output_variable": "raim",
            "library_file": lib_mod['snow17'],
            "init_config": os.path.join(bmi_dir['snow17'], 'snow17-init-{{id}}.namelist.input'),
            "allow_exceed_end_time": True,
            "fixed_time_step": False,
            "uses_forcing_file": False,
            "variables_names_map": {
                "precip": forcing_vars['prcp'].get(forcing_provider),
                "tair": forcing_vars['temp'].get(forcing_provider)
            },
        }
    elif module == 'ueb':
        return {
            "name": "bmi_c++",
            "model_type_name": get_model_type_name('ueb'),
            "main_output_variable": "SWIT",
            "library_file": lib_mod['ueb'],
            "init_config": os.path.join(bmi_dir['ueb'], 'ueb-init-{{id}}_' + run_type_abbr + '.dat'),
            "allow_exceed_end_time": True,
            "fixed_time_step": False,
            "uses_forcing_file": False,
            "variables_names_map": {
                "Prec": forcing_vars['prcp'].get(forcing_provider),
                "Ta": forcing_vars['temp'].get(forcing_provider),
                "qair": forcing_vars['Q2'].get(forcing_provider),
                "uebu2d": forcing_vars['xwind'].get(forcing_provider),
                "uebv2d": forcing_vars['ywind'].get(forcing_provider),
                "Qli": forcing_vars['lw'].get(forcing_provider),
                "Qsi": forcing_vars['sw'].get(forcing_provider),
                "AP": forcing_vars['pressure'].get(forcing_provider)
            },
        }
    elif module == 'pet':
        return {
            "name": "bmi_c",
            "model_type_name": get_model_type_name('pet'),
            "main_output_variable": "water_potential_evaporation_flux",
            "library_file": lib_mod['pet'],
            "init_config": os.path.join(bmi_dir['pet'], '{{id}}_bmi_config.ini'),
            "allow_exceed_end_time": True,
            "fixed_time_step": False,
            "uses_forcing_file": False,
            "registration_function": "register_bmi_pet",
            "requires_all_bmi_forcing": True,
        }
    elif module == 'sloth':
        return {
            "name": "bmi_c++",
            "model_type_name": get_model_type_name('sloth'),
            "main_output_variable": "z",
            "library_file": lib_mod['sloth'],
            "init_config": '/dev/null',
            "allow_exceed_end_time": True,
            "fixed_time_step": False,
            "uses_forcing_file": False,
        }
    elif module == 'sft':
        return {
            "name": "bmi_c++",
            "model_type_name": get_model_type_name('sft'),
            "main_output_variable": "num_cells",
            "library_file": lib_mod['sft'],
            "init_config": os.path.join(bmi_dir['sft'], '{{id}}_bmi_config_sft.txt'),
            "allow_exceed_end_time": True,
            "fixed_time_step": False,
            "uses_forcing_file": False,
            "variables_names_map": {"ground_temperature": "TGS"},
        }
    elif module == 'smp':
        return {
            "name": "bmi_c++",
            "model_type_name": get_model_type_name('smp'),
            "main_output_variable": "soil_water_table",
            "library_file": lib_mod['smp'],
            "init_config": os.path.join(bmi_dir['smp'], '{{id}}_bmi_config_smp.txt'),
            "allow_exceed_end_time": True,
            "fixed_time_step": False,
            "uses_forcing_file": False,
        }
    elif module == 'lasam':
        return {
            "name": "bmi_c++",
            "model_type_name": get_model_type_name('lasam'),
            "main_output_variable": "total_discharge",
            "library_file": lib_mod['lasam'],
            "init_config": os.path.join(bmi_dir['lasam'], '{{id}}_bmi_config_lasam.txt'),
            "allow_exceed_end_time": True,
            "uses_forcing_file": False,
            "bmi_multi_output_var": "total_discharge",
            "precip_output": "precipitation_rate_out",
        }
    elif module == 'lstm':
        return {
            "name": "bmi_python",
            "python_type": "lstm.bmi_lstm.bmi_LSTM",
            "model_type_name": get_model_type_name('lstm'),
            "main_output_variable": "land_surface_water__runoff_depth",
            "init_config": os.path.join(bmi_dir['lstm'], '{{id}}.yml'),
            "allow_exceed_end_time": True,
            "uses_forcing_file": False,
            "variables_names_map": {
                "streamflow_cms": "land_surface_water__runoff_volume_flux",
                "pytorch_model_path": os.path.join(bmi_dir['lstm'], "sugar_creek_trained.pt"),
                "normalization_path": os.path.join(bmi_dir['lstm'], "input_scaling.csv"),
                "initial_state_path": os.path.join(bmi_dir['lstm'], "initial_states.csv"),
                "useGPU": False,
            },
            "precip_output": "precipitation_rate",
            "requires_all_bmi_forcing": True,
        }
    elif module == 'topoflow-glacier':
        return {
            "name": "bmi_python",
            "python_type": "topoflow_glacier.bmi.bmi_topoflow_glacier.BmiTopoflowGlacier",
            "model_type_name": get_model_type_name('topoflow-glacier'),
            "main_output_variable": "land_surface_water__runoff_depth",
            "init_config": os.path.join(bmi_dir['topoflow-glacier'], "{{id}}_" + run_type_abbr + ".yaml"),
            "allow_exceed_end_time": True,
            "uses_forcing_file": False,
            "variables_names_map": {
                'streamflow_cms': 'channel_water_x-section__volume_flow_rate'},
            "precip_output": "precipitation_rate",
            "requires_all_bmi_forcing": True,
        }


def build_module_config(mod: str, base: dict, modules: List[str], forcing_provider: str = 'csv', forcing_vars: dict = None) -> dict:
    """Build module realization configuration section from base templates"""
    config = {
        'name': base.get('name'),
        'params': {
            'name': base.get('name'),
            'model_type_name': base.get('model_type_name'),
            'main_output_variable': base.get('main_output_variable'),
            'library_file': base.get('library_file'),
            'init_config': base.get('init_config'),
        },
    }

    # Add optional fields only if present in template
    opt_fields = ['allow_exceed_end_time', 'fixed_time_step', 'uses_forcing_file', 'python_type', 'registration_function', 'variables_names_map']
    for field in opt_fields:
        if field in base:
            config['params'][field] = base[field]

    # Add SLOTH parameters
    if mod == 'sloth':
        config['params']['model_params'] = get_sloth_params(modules)

    # Add SMP variable mapping
    if mod == 'smp':
        config['params']['variables_names_map'] = get_smp_var_map(modules)

    # Add CSV to BMI forcing variables if module requires them lstm/topoflow-glacier
    if base.get('requires_all_bmi_forcing') and forcing_provider == 'bmi' and forcing_vars:
        # Initialize variables_names_map if it doesn't exist
        if 'variables_names_map' not in config['params']:
            config['params']['variables_names_map'] = {}

        # Add all forcing variable mappings
        config['params']['variables_names_map'].update({
            forcing_vars['lw'].get('csv'): forcing_vars['lw'].get('bmi'),
            forcing_vars['sw'].get('csv'): forcing_vars['sw'].get('bmi'),
            forcing_vars['pressure'].get('csv'): forcing_vars['pressure'].get('bmi'),
            forcing_vars['Q2'].get('csv'): forcing_vars['Q2'].get('bmi'),
            forcing_vars['temp'].get('csv'): forcing_vars['temp'].get('bmi'),
            forcing_vars['xwind'].get('csv'): forcing_vars['xwind'].get('bmi'),
            forcing_vars['ywind'].get('csv'): forcing_vars['ywind'].get('bmi'),
        })

    return config


def build_output_vars(var_maps: dict, output_dict: dict, precip_output: str) -> dict:
    """Build output variables dictionary for config"""
    output_vars = []

    # Add SWE output if requested
    if output_dict.get('output_swe') and var_maps['output'].get('swe_out'):
        entry = {
            'name': var_maps['output']['swe_out'],
            'header': var_maps['output'].get('swe_out_header', ''),
            'units': var_maps['output'].get('swe_out_units', ''),
        }
        if var_maps['output'].get('swe_out_index', ''):
            entry['index'] = var_maps['output']['swe_out_index']
        output_vars.append(entry)

    # Add precipitation output if requested
    if output_dict.get('output_sm') and var_maps['output'].get('sm_out'):
        for i, sm_var in enumerate(var_maps['output']['sm_out']):
            entry = {
                'name': sm_var,
                'header': var_maps['output']['sm_out_header'][i],
                'units': var_maps['output']['sm_out_units'][i],
                'index': var_maps['output']['sm_out_index'][i],
            }
            if var_maps['output']['sm_out_index'][i] != '0':
                entry['index'] = var_maps['output']['sm_out_index'][i]
            output_vars.append(entry)

    # Add precipitation output if requested
    if output_dict.get('output_precip') and precip_output:
        output_vars.append({
            'name': precip_output,
            'header': 'rainmelt',
            'units': 'mm/s'
        })

    return output_vars


def create_realization_file(
        workdir: Union[str, Path],
        lib_file: dict,
        bmi_dir: dict,
        forcing_provider: str,
        forcing_dir: Union[str, Path],
        forcing_config_file: Union[str, Path],
        modules: List[str],
        time_period: dict,
        rt_dict: dict,
        output_dict: dict,
        calib_output_vars: bool,
        run_type: str
) -> None:
    """
    Create realization file for the specified model and module

    Parameters
    ----------
    workdir : basin directory for storing all the files
    lib_file : library files for different modules
    bmi_dir : directory for different model or module to store BMI files
    forcing_provider: forcing provider option (csv or bmi)
    forcing_dir : directory to store forcing files
    forcing_config_file: path to forcing engine configuration file
    realization_file : model realization configuration file
    model: model and module combination
    time_period : simulation and evaluation time period
    rt_dict : routing model source file directory and configuration file
    output_dict: whether to output certain variables (currently SWE and soil moisture)
    calib_output_vars: boolean flag for writing calibration output variables
    run_type: type of run (calib, regionalization, or default)

    Returns
    ----------
    output_config: dictionary containing output variable configuration
    """

    # Create symlinks for libraries
    lib_mod = create_lib_symlinks(workdir, lib_file)

    # Normalize run_type abbreviation
    run_type_abbr = {'calibration': 'calib'}.get(run_type, run_type)

    # Retrieve forcing variable names
    forcing_vars = get_forcing_vars_map()

    # Build module configurations for each module in formulation
    model_configs = {}
    base_configs = {}
    for mod in modules:
        if mod == 'troute':
            continue

        # Build realization config section for requested module
        base_config = build_base_config(mod, lib_mod, bmi_dir, run_type_abbr, forcing_provider, forcing_vars)
        base_configs[mod] = base_config
        model_configs[mod] = build_module_config(mod, base_config, modules, forcing_provider, forcing_vars)

    # Determine rainfall-runoff module
    rr_mods = [m for m in modules if 'Rainfall_runoff' in settings.modules_all.loc[settings.modules_all['module'] == m, 'process'].values[0]]

    if len(rr_mods) != 1:
        err_msg = f'Expected 1 rainfall-runoff module, found {len(rr_mods)}: {rr_mods}'
        logger.critical(err_msg)
        raise Exception(err_msg)
    rr_mod = rr_mods[0]

    # Get PET and Precip variable mapping for RR module
    var_map_config = {
        'sac': ('pet', 'precip'),
        'lasam': ('potential_evapotranspiration_rate', 'precipitation_rate'),
    }

    if rr_mod in var_map_config:
        pet_in, pcp_in = var_map_config[rr_mod]
    else:
        # Used for CFE-S, CFE-X, Topmodel
        pet_in = 'water_potential_evaporation_flux'
        pcp_in = forcing_vars['prcp'].get('csv')

    var_maps = var_mapping(modules, pet_in, pcp_in, forcing_vars['prcp'].get(forcing_provider), output_dict)

    # Add extra mappings for specific modules
    if rr_mod == 'sac':
        var_maps['input']['tair'] = forcing_vars['temp'].get(forcing_provider)

    # Apply variable mapping to RR module
    if 'variables_names_map' not in model_configs[rr_mod]['params']:
        model_configs[rr_mod]['params']['variables_names_map'] = {}
    model_configs[rr_mod]['params']['variables_names_map'].update(var_maps['input'])

    # Retrieve precip_output from module that supplies it
    precip_suppliers = ['cfes', 'cfex', 'sac', 'topmodel', 'lasam', 'lstm', 'topoflow-glacier']
    precip_output = None
    for supplier in precip_suppliers:
        if supplier in modules:
            supplier_config = base_configs.get(supplier, {})
            precip_output = supplier_config.get('precip_output')
            if precip_output:
                break

    if not precip_output:
        err_msg = f'No precipitation output supplier found. Expected one of {precip_suppliers} in formulation.'
        logger.critical(err_msg)
        raise Exception(err_msg)

    # Build output variable dictionary
    output_vars = build_output_vars(var_maps, output_dict, precip_output)

    # Build main bmi_multi config
    # Set main_output_variable from bmi_multi_output_var if available, otherwise, use main_output_var from rr module
    rr_base_config = base_configs.get(rr_mod, {})
    bmi_multi_output = rr_base_config.get('bmi_multi_output_var') or model_configs[rr_mod]['params']['main_output_variable']
    gbmain = {
        'name': 'bmi_multi',
        'params': {
            'name': 'bmi_multi',
            'model_type_name': 'bmi_multi',
            'init_config': '',
            'allow_exceed_end_time': False,
            'fixed_time_step': False,
            'uses_forcing_file': False,
            'main_output_variable': bmi_multi_output,
            'output_variables': output_vars if (calib_output_vars or run_type_abbr != 'calib') else [],
            'modules': [model_configs[m] for m in modules if m != 'troute'],
        }
    }

    # Build output_config dict from output_vars for return (used in calibration)
    output_config = {
        'output_variables': [v['name'] for v in output_vars],
        'output_header_fields': [v['header'] for v in output_vars],
        'output_units': [v['units'] for v in output_vars],
        'output_index': [v.get('index', '0') for v in output_vars],
    }

    # Build global realization configuration
    g = {
        'global': {
            'formulations': [gbmain],
            'forcing': {},
        },
        'time': {
            'start_time': time_period['run_time_period'][run_type_abbr][0],
            'end_time': time_period['run_time_period'][run_type_abbr][1],
            'output_interval': 3600,
        },
    }

    # Forcing configuration
    forcing_map = {
        "csv": {"file_pattern": "{{id}}.csv", "path": forcing_dir, "provider": "CsvPerFeature"},
        "bmi": {"path": "", "provider": "ForcingsEngineLumpedDataProvider", "params": {"init_config": str(forcing_config_file)}}
    }

    g["global"]["forcing"] = forcing_map[forcing_provider]

    # Add routing section
    g.update(rt_dict)

    return g, output_config


def create_reg_realization_file(
        workdir: Union[str, Path],
        lib_file: dict,
        bmi_dir: dict,
        forcing_provider: str,
        forcing_dir: Union[str, Path],
        forcing_config_file: Union[str, Path],
        time_period: dict,
        rt_dict: dict,
        output_dict: dict,
        calib_output_vars: dict,
        run_type: str,
        cat_to_grp: dict,
        grp_to_form: dict,
        grp_params: dict
) -> None:
    """ Create realization file for regionalization for the specified modules by catchment

    Parameters
    ----------
    workdir : basin directory for storing all the files
    lib_file : library files for different modules
    bmi_dir : directory for different model or module to store BMI files
    forcing_provider: forcing provider option (csv or bmi)
    forcing_dir : directory to store forcing files
    forcing_config_file: path to forcing engine configuration file
    realization_file : model realization configuration file
    time_period : simulation and evaluation time period
    rt_dict : routing model source file directory and configuration file
    output_dict: whether to output certain variables (currently SWE and soil moisture)
    calib_output_vars: boolean flag for writing calibration output variables
    run_type: type of run (calib, regionalization, or default)
    cat_to_grp: dictionary mapping catchments to regionalization groups
    grp_to_form: dictionary mapping regionalization groups to formulations
    grp_params: dictionary mapping regionalization groups to modules and their corresponding parameters

    Returns
    ----------
    None
    """

    # Create symlinks for libraries
    lib_mod = create_lib_symlinks(workdir, lib_file)

    # Normalize run_type abbreviation
    run_type_abbr = {'calibration': 'calib', 'regionalization': 'region'}.get(run_type, run_type)

    # Retrieve forcing variable names
    forcing_vars = get_forcing_vars_map()

    # Initialize goutput tracking and main realization section
    output_config_grp = {}
    grp_main = {}

    # Process each regionalization group
    for grp, grp_mod in grp_to_form.items():

        model_configs = {}
        base_configs = {}

        # Build realization configurations for each module in group
        for mod in grp_mod:
            if mod == 'troute':
                continue

            # Build realization config section for requested module
            base_config = build_base_config(mod, lib_mod, bmi_dir, run_type_abbr, forcing_provider, forcing_vars)
            base_configs[mod] = base_config
            model_configs[mod] = build_module_config(mod, base_config, grp_mod, forcing_provider, forcing_vars)

            # Add group-specific parameters if available
            if grp_params.get(mod, {}).get(grp):
                model_configs[mod]['params']['model_params'] = grp_params[mod][grp]

        # Determine rainfall-runoff module
        rr_mods = [m for m in grp_mod if 'Rainfall_runoff' in settings.modules_all.loc[settings.modules_all['module'] == m, 'process'].values[0]]

        if len(rr_mods) != 1:
            err_msg = f'Expected 1 rainfall-runoff module in group {grp}, found {len(rr_mods)}: {rr_mods}'
            logger.critical(err_msg)
            raise Exception(err_msg)
        rr_mod = rr_mods[0]

        # Get PET and Precip variable mapping for RR module
        var_map_config = {
            'sac': ('pet', 'precip'),
            'lasam': ('potential_evapotranspiration_rate', 'precipitation_rate'),
        }

        if rr_mod in var_map_config:
            pet_in, pcp_in = var_map_config[rr_mod]
        else:
            pet_in = 'water_potential_evaporation_flux'
            pcp_in = forcing_vars['prcp'].get('csv')

        var_maps = var_mapping(grp_mod, pet_in, pcp_in, forcing_vars['prcp'].get(forcing_provider), output_dict)

        # Add extra mappings for specific modules
        if rr_mod == 'sac':
            var_maps['input']['tair'] = forcing_vars['temp'].get(forcing_provider)

        # Apply variable mapping to RR module
        if 'variables_names_map' not in model_configs[rr_mod]['params']:
            model_configs[rr_mod]['params']['variables_names_map'] = {}
        model_configs[rr_mod]['params']['variables_names_map'].update(var_maps['input'])

        # Retrieve precip_output from module that supplies it
        precip_suppliers = ['cfes', 'cfex', 'sac', 'topmodel', 'lasam', 'lstm', 'topoflow-glacier']
        precip_output = None
        for supplier in precip_suppliers:
            if supplier in grp_mod:
                supplier_config = base_configs.get(supplier, {})
                precip_output = supplier_config.get('precip_output')
                if precip_output:
                    break

        if not precip_output:
            err_msg = f'No precipitation output supplier found in group {grp}. Expected one of {precip_suppliers} in formulation.'
            logger.critical(err_msg)
            raise Exception(err_msg)

        # Build output variable dictionary
        output_vars = build_output_vars(var_maps, output_dict, precip_output)

        # Build main bmi_multi config
        # Set main_output_variable from bmi_multi_output_var if available, otherwise, use main_output_var from rr module
        rr_base_config = base_configs.get(rr_mod, {})
        bmi_multi_output = rr_base_config.get('bmi_multi_output_var') or model_configs[rr_mod]['params']['main_output_variable']
        grp_configs = {
            'name': 'bmi_multi',
            'params': {
                'name': 'bmi_multi',
                'model_type_name': 'bmi_multi',
                'init_config': '',
                'allow_exceed_end_time': False,
                'fixed_time_step': False,
                'uses_forcing_file': False,
                'main_output_variable': bmi_multi_output,
                'output_variables': output_vars if (calib_output_vars or run_type_abbr != 'calib') else [],
                'modules': [model_configs[m] for m in grp_mod if m != 'troute'],
            }
        }

        # Add group configs to group main section
        grp_main[grp] = [grp_configs]

        # Build output_config dict from output_vars for return (used in calibration)
        output_config = {
            'output_variables': [v['name'] for v in output_vars],
            'output_header_fields': [v['header'] for v in output_vars],
            'output_units': [v['units'] for v in output_vars],
            'output_index': [v.get('index', '0') for v in output_vars],
        }
        output_config_grp[grp] = output_config

    # Build global realization configuration
    g = {
        'time': {
            'start_time': time_period['run_time_period'][run_type_abbr][0],
            'end_time': time_period['run_time_period'][run_type_abbr][1],
            'output_interval': 3600,
        },
    }
    g.update(rt_dict)
    g['formulation_groups'] = grp_main

    # Forcing configuration
    forcing_map = {
        "csv": {"file_pattern": "{{id}}.csv", "path": forcing_dir, "provider": "CsvPerFeature"},
        "bmi": {"path": "", "provider": "ForcingsEngineLumpedDataProvider", "params": {"init_config": str(forcing_config_file)}}
    }

    g["forcing_groups"] = {"forcing_grp1": forcing_map[forcing_provider]}

    # Add catchment groups
    g['catchments'] = {cat: {"formulations": grp, "forcing": "forcing_grp1"} for cat, grp in cat_to_grp.items()}

    return g, output_config_grp


def find_module_index(real_modules: List[dict], module: str) -> int | None:
    """
    Find the index of a module in the real modules list by model_type_name
    """
    return next((i for i, m in enumerate(real_modules) if m['params'].get('model_type_name') == get_model_type_name(module)), None)


def update_realization_nwm_output(
        workdir: Union[str, Path],
        lib_file: dict,
        bmi_dir: dict,
        forcing_provider: str,
        adapters: List[str],
        modules: List[str],
        nwm_output_dicts: List[dict],
        output_dict: dict,
        real_config: dict,
        run_type: str,
        grp: str = None
) -> None:
    """
    Create realization file for the specified model and module

    Parameters
    ----------
    workdir : basin directory for storing all the files
    lib_file : library files for different modules
    bmi_dir : directory for different model or module to store BMI files
    forcing_provider: forcing provider option (csv or bmi)
    adapters : additional modules required to produce NWM output variables
    modules: model and module combination
    nwm_output_dicts : dictionaries containing NWM output variable information
    output_dict : whether to output certain variables (currently SWE and soil moisture)
    real_config : existing realization file as a dictionary
    run_type: type of run (calib, regionalization, or default, cold_start, forecast, hindcast, lagged_ens)
    grp: group name for regionalization realizations

    Returns
    ----------
    real_config: updated realization file as a dictionary
    """
    # Create local copy of modules to not affect self.modules
    base_modules = modules.copy()

    run_type_abbr = {'regionalization': 'region'}.get(run_type, run_type)

    # Retrieve forcing variable names
    forcing_vars = get_forcing_vars_map()

    # Create symlinks for adapter libraries
    adapter_lib_file = {k: v for k, v in lib_file.items() if k in adapters}
    lib_mod = create_lib_symlinks(workdir, adapter_lib_file)

    # Retrieve correct formulation section based on type of realization file
    if grp is not None:
        real_output = real_config['formulation_groups'][grp][0]['params']['output_variables']
        real_modules = real_config['formulation_groups'][grp][0]['params']['modules']
    else:
        real_output = real_config['global']['formulations'][0]['params']['output_variables']
        real_modules = real_config['global']['formulations'][0]['params']['modules']

    # Update output variable section with NWM output variables
    output_keys = set(item['header'] for item in real_output)
    for nwm_dict in nwm_output_dicts:
        if nwm_dict['nwm_name'] not in output_keys:
            real_output.append({'name': nwm_dict['provider_var'], 'header': nwm_dict['nwm_name'], 'units': nwm_dict['nwm_units']})

    # Combine modules and adapters
    mod_adapters = base_modules + adapters

    if 'sloth' in mod_adapters:
        sloth_params = get_sloth_params(base_modules, adapters)

        # If sloth already in formulation, add sloth module parameters to existing section
        if 'sloth' in base_modules:
            sloth_index = find_module_index(real_modules, 'sloth')
            # Remove soil_temperature profile if SFT is being added as an adapter
            real_modules[sloth_index]["params"]["model_params"].pop("soil_temperature_profile(1,double,K,node)", None)
            real_modules[sloth_index]["params"]["model_params"].update(sloth_params)
        else:
            # Add sloth section to realization
            modules.insert(0, 'sloth')
            base = build_base_config('sloth', lib_mod, bmi_dir, run_type_abbr, forcing_provider, forcing_vars)
            sloth_config = build_module_config('sloth', base, mod_adapters, forcing_provider, forcing_vars)
            sloth_config['params']['model_params'] = sloth_params
            real_modules.insert(0, sloth_config)

    if 'noah' in adapters:
        noah_index = 1 if 'sloth' in modules else 0
        modules.insert(noah_index, 'noah')
        base = build_base_config('noah', lib_mod, bmi_dir, run_type_abbr, forcing_provider, forcing_vars)
        noah_config = build_module_config('noah', base, mod_adapters, forcing_provider, forcing_vars)
        real_modules.insert(noah_index, noah_config)

    if 'smp' in adapters:
        noah_index = find_module_index(real_modules, 'noah')
        smp_index = noah_index + 1
        modules.insert(smp_index, 'smp')
        base = build_base_config('smp', lib_mod, bmi_dir, run_type_abbr, forcing_provider, forcing_vars)
        smp_config = build_module_config('smp', base, mod_adapters, forcing_provider, forcing_vars)
        # Enforce smp adapter variable name mapping
        smp_config['params']['variables_names_map'] = {
            "soil_storage": "sloth_soil_storage",
            "soil_storage_change": "sloth_soil_storage_change"
        }
        real_modules.insert(smp_index, smp_config)

    if 'sft' in adapters:
        smp_index = find_module_index(real_modules, 'smp')
        sft_index = smp_index + 1
        modules.insert(sft_index, 'sft')
        base = build_base_config('sft', lib_mod, bmi_dir, run_type_abbr, forcing_provider, forcing_vars)
        sft_config = build_module_config('sft', base, mod_adapters, forcing_provider, forcing_vars)
        real_modules.insert(sft_index, sft_config)

    if 'cfes' in adapters:
        sft_index = find_module_index(real_modules, 'sft')
        cfes_index = sft_index + 1
        modules.insert(cfes_index, 'cfes')
        base = build_base_config('cfes', lib_mod, bmi_dir, run_type_abbr, forcing_provider, forcing_vars)
        cfes_config = build_module_config('cfes', base, mod_adapters, forcing_provider, forcing_vars)
        var_maps = var_mapping(modules, "water_potential_evaporation_flux", forcing_vars['prcp'].get('csv'), forcing_vars['prcp'].get(forcing_provider), output_dict)
        cfes_config['params']['variables_names_map'] = var_maps['input']
        real_modules.insert(cfes_index, cfes_config)

    return real_config


def write_realization_to_file(
        real_config: dict,
        realization_file: Union[str, Path],
) -> None:
    """ Create configuration YAML file for calibration run

    Parameters
    ----------
    real_config : dictionary containing realization file schema
    realization_file: path to write realization file

    Returns
    ----------
    None
    """
    try:
        with open(realization_file, 'w') as outfile:
            json.dump(real_config, outfile, indent=4, separators=(", ", ": "), sort_keys=False)
    except TypeError as e:
        logger.critical(f"Failed to dump realization data to JSON: {realization_file}\n{e}")
        raise
    except OSError as e:
        logger.critical(f"Unexpected error while writing realization data to JSON: {realization_file}\n{e}")
        raise


def create_calib_config_file(
        par_file: Union[str, Path],
        modules: List[str],
        workdir: Union[str, Path],
        general_dict: dict,
        model_dict: dict,
        config_yaml_file: Union[str, Path],
) -> None:
    """ Create configuration YAML file for calibration run

    Parameters
    ----------
    par_file : file containing min, max and init values of calibration parameters
    modules: list of modules in the formulation
    workdir : basin directory for storing all the files
    general_dict : general settings
    model_dict : model settings
    config_yaml_file : configuration YAML file

    Returns
    ----------
    None

    """

    # Extract calibration params range
    # If par_file (which contains calibration parameters and its initial, min and max values) exists,
    # read from that file directly; otherwise gather this information from predefined calib_params files for
    # individual modules in the directory given by par_file
    calib_modules_config = list(settings.modules_all.loc[settings.modules_all['calibratable'], 'name_config'])
    if os.path.isfile(par_file):
        df_params = pd.read_fwf(par_file).copy()
        df_params = df_params.loc[df_params['model'].isin(calib_modules_config)]
    else:
        if os.path.isdir(par_file):
            df_params = pd.DataFrame()
            for m1 in modules:
                m_ui = settings.modules_all.loc[settings.modules_all['module'] == m1, 'name_ui'].iloc[0]
                m_config = settings.modules_all.loc[settings.modules_all['module'] == m1, 'name_config'].iloc[0]
                if m_config in calib_modules_config:
                    f1 = os.path.join(par_file, 'calib_params_' + m_ui + '.csv')
                    if not os.path.exists(f1):
                        logger.warning(f'Folder {par_file} does not contain calibration parameter file for {m_ui}')
                        continue
                    df_tmp = pd.read_csv(f1, sep=None, comment='#', engine='python')
                    df_tmp['model'] = m_config
                    df_params = pd.concat([df_params, df_tmp], ignore_index=True)
        else:
            try:
                raise Exception(f'{par_file} is not a valid file or folder with calibration parameter files for the chosen modules')
            except Exception as e:
                logger.critical(e)
                raise

    params_range_dict = {}
    # Create configuration
    basin_yaml = {'general': general_dict}

    if 'lstm' not in modules:
        if len(df_params) == 0:
            try:
                raise Exception(f'No calibratable parameters found for the list of modules: {modules}')
            except Exception as e:
                logger.critical(e)
                raise

        df_params.set_index('param', inplace=True)
        calib_params = df_params.groupby('model').groups

        params_range_dict = {}
        for k, v in calib_params.items():
            params_range = []
            for m in v:
                params_range.append({'name': m, 'min': float(df_params.query('model==@k').loc[m]['min']),
                                     'max': float(df_params.query('model==@k').loc[m]['max']),
                                     'init': float(df_params.query('model==@k').loc[m]['init'])})
            params_range_dict.update({k: params_range})

        # Create configuration
        basin_yaml = {'general': general_dict}
        basin_yaml.update(params_range_dict)

    # Create symlink for ngen executable
    ngen_file_link = os.path.join(workdir, 'Input/' + os.path.basename(model_dict['binary'])[0:4])
    if os.path.exists(ngen_file_link) or os.path.islink(ngen_file_link):
        try:
            os.unlink(ngen_file_link)
        except Exception as e:
            logger.critical(f"Failed to remove existing {ngen_file_link}: {e}")
            raise
    try:
        os.symlink(model_dict['binary'], ngen_file_link)
    except OSError as e:
        logger.critical(f"Failed to create symlink: {model_dict['binary']} -> {ngen_file_link}: {e}")
        raise

    model_dict['binary'] = ngen_file_link
    basin_yaml['model'] = model_dict
    if 'lstm' not in modules:
        basin_yaml['model']['params'] = params_range_dict
    else:
        basin_yaml['model']['type'] = 'nocalib'

    # Save configuration into yaml file
    with open(config_yaml_file, 'w') as file:
        yaml.dump(basin_yaml, file, sort_keys=False, default_flow_style=False, indent=2)
    logger.info(f'Calibration config file is created at: {config_yaml_file}')


def create_partition_file(
        partition_generator: str,
        gpkg_file: str,
        nprocs: int,
        work_dir: str,
        partition_config_basename_prefix: str,
        sub_dir_name: str = "Input") -> Union[str, Path]:
    """ Create partition file

    Parameters
    ----------
    partition_generator: partition config generator json file
    gpkg_file: GeoPackage hydrofabric file
    nprocs: number of processors
    work_dir : path to working directory.
        For non-forecasts this should be RealizationBuilder.work_dir.
        For forecasts this is the forecast realization directory.
    partition_config_basename_prefix : prefix of the basename used for the output partition configuration file
    sub_dir_name : subdirectory basename (direct child of work_dir) in which to write the partition file.  Default: "Input"

    Returns
    ----------
    Path of the partition file that was written

    """

    partition_file = os.path.join(
        work_dir,
        sub_dir_name,
        f"{partition_config_basename_prefix}{settings.PARTITION_CONFIG_FILE_NAME_SUFFIX}.json",
    )

    cmd = f"{partition_generator} {gpkg_file} {gpkg_file} {partition_file} {nprocs} '' ''"

    logger.info("Creating partition file for %s", partition_config_basename_prefix)
    logger.info(" - Partition generator: %s", partition_generator)
    logger.info(" - Hydrofabric file: %s", gpkg_file)
    logger.info(" - Partition file: %s", partition_file)
    logger.info(" - Number of processors: %s", nprocs)
    logger.info(" - Command: %s", cmd)

    # Run the command and capture output
    try:
        result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logger.info("Command output (stdout): %s", result.stdout.decode().strip())
        if result.stderr:
            logger.critical("Command error (stderr): %s", result.stderr.decode().strip())
        result.check_returncode()  # Will raise CalledProcessError if non-zero
    except subprocess.CalledProcessError as e:
        logger.critical("Partition generator command failed with exit code %s", e.returncode)
        raise
    except FileNotFoundError as e:
        logger.critical("Partition generator not found '%s': %s", partition_generator, e)
        raise

    return partition_file
