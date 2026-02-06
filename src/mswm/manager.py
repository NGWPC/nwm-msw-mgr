"""
This module creates a Setup Manager to manage the modification of configuration files for individual ngen runs

@author: Jeffrey Wade
"""

import argparse
from mswm.build_inputs import RealizationBuilder, validate_topoflow_glacier


def build_default(input_path: str, use_cold_start: bool = False):
    """
    Call RealizationBuilder class to generate realization and config files with default parameters
    """
    rb = RealizationBuilder(input_path=input_path, use_cold_start=use_cold_start)
    real_path = rb.build_default_realization()
    return real_path


def build_calib(input_path: str):
    """
    Call RealizationBuilder class to generate initial calibration realization and config files
    """
    rb = RealizationBuilder(input_path=input_path)
    real_path = rb.build_calib_realization()
    return real_path


def build_fcst(input_path: str, valid_yaml: str, fcst_run_name: str, use_cold_start: bool = False, use_warm_start: bool = False,
               use_hindcast: bool = False, use_lagged_ens: bool = False, hind_cycle: int | None = None, prev_hind_cycle: int | None = None,
               lagged_ens_mem: str | None = None, forcing_lag: int | None = None, load_state_from: str = None, save_state: bool = False):
    """
    Call RealizationBuilder class to generate forecast realization and config files
    """
    rb = RealizationBuilder(use_cold_start=use_cold_start, use_warm_start=use_warm_start, use_lagged_ens=use_lagged_ens,
                            use_hindcast=use_hindcast, hind_cycle=hind_cycle, prev_hind_cycle=prev_hind_cycle,
                            lagged_ens_mem=lagged_ens_mem, forcing_lag=forcing_lag,
                            load_state_from=load_state_from, save_state=save_state)
    real_path = rb.build_fcst_realization()
    return real_path


def build_region(input_path: str):
    """
    Call RealizationBuilder class to generate realization and config files for regionalization
    """
    rb = RealizationBuilder(input_path=input_path)
    real_path = rb.build_region_realization()
    return real_path


def validate_topo(gpkg_file: str):
    """
    Validate Topoflow-Glacier applicability by checking glacier coverage in basin catchments
    """
    result = validate_topoflow_glacier(gpkg_file)
    print(result)


def main():
    # Create command line parser
    parser = argparse.ArgumentParser(prog="mswm",
                                     description="Model Setup Workflow Manager command-line")
    subparser = parser.add_subparsers(dest="command", required=True, help="Available commands")

    # subcommand: build_default
    build_default_sub = subparser.add_parser("build_default", help="Create default realization")
    build_default_sub.add_argument("input_path", help="Input configuration file")
    build_default_sub.add_argument("--use_cold_start", action="store_true", help="Enable cold start flag when passed")

    # subcommand: build_calib
    build_calib_sub = subparser.add_parser("build_calib", help="Create calibration realization")
    build_calib_sub.add_argument("input_path", help="Input configuration file")

    # subcommand: build_region
    build_region_sub = subparser.add_parser("build_region", help="Create regionalization realization")
    build_region_sub.add_argument("input_path", help="Input configuration file")

    # subcommand: build_fcst
    build_fcst_sub = subparser.add_parser("build_fcst", help="Create forecast realization")
    build_fcst_sub.add_argument("input_path", help="Input configuration file")
    build_fcst_sub.add_argument("valid_yaml", help="Path to the config yaml file for a validation run")
    build_fcst_sub.add_argument("fcst_run_name", help="Name of the folder to be created for storing inputs/outputs from running ngen")
    build_fcst_sub.add_argument("--use_cold_start", action="store_true", help="Enable cold start flag when passed")
    build_fcst_sub.add_argument("--use_warm_start", action="store_true", help="Enable warm start flag when passed")
    build_fcst_sub.add_argument("--use_hindcast", action="store_true", help="Enable hindcast flag when passed")
    build_fcst_sub.add_argument("--use_lagged_ens", action="store_true", help="Enable lagged ensemble flag when passed")
    build_fcst_sub.add_argument("--hind_cycle", type=int, default=None, help="Cycle interval (in hours) between hindcast start and current hindcast run")
    build_fcst_sub.add_argument("--prev_hind_cycle", type=int, default=None, help="Previous hindcast cycle interval (in hours) used to coordinate warm start runs")
    build_fcst_sub.add_argument("--lagged_ens_mem", type=str, default=None, help="Name of medium range lagged ensemble member (mem1-mem6, no_da)")
    build_fcst_sub.add_argument("--forcing_lag", type=int, default=None, help="Number of hours lagged ensemble forcing valid time is lagged from start of ngen run")
    build_fcst_sub.add_argument("--load_state_from", type=str, default=None, help="Path to directory containing model states to load at beginning of run")
    build_fcst_sub.add_argument("--save_state", action="store_true", help="Enable save state at end of run flag when passed")

    # subcomman: validate_topoflow
    validate_topo_sub = subparser.add_parser("validate_topoflow_glacier", help="Validate Topoflow-Glacier applicability for a basin")
    validate_topo_sub.add_argument("gpkg_file", help="Path to geopackage file")

    args = parser.parse_args()

    # Parser logic
    if args.command == "build_default":
        build_default(args.input_path, args.use_cold_start)
    elif args.command == "build_calib":
        build_calib(args.input_path)
    elif args.command == "build_region":
        build_region(args.input_path)
    elif args.command == "build_fcst":
        build_fcst(args.input_path, args.valid_yaml, args.fcst_run_name, args.use_cold_start, args.use_warm_start, args.use_hindcast, args.use_lagged_ens,
                   args.hind_cycle, args.prev_hind_cycle, args.lagged_ens_mem, args.forcing_lag,
                   args.load_state_from, args.save_state)
    elif args.command == "validate_topoflow_glacier":
        validate_topo(args.gpkg_file)
    else:
        raise ValueError(f"Unexpected mswm command: {args.command}")


if __name__ == "__main__":
    main()
