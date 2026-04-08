"""
Module to restart a run from a saved checkpoint, copying a run folder to a new path and configuring checkpoint restart
"""

import logging
import os
import json
import argparse
from pathlib import Path

from mswm.utils.copy_run_folder import copy_run_folder
from mswm.utils.log_level import log_level_set, MODULE_NAME

logger = logging.getLogger(MODULE_NAME)


def checkpoint_restart(
        src_path: str,
        dst_path: str,
        checkpoint_state_path: str,
) -> None:
    """
    Copy a run folder to a new path and configure it to load from a checkpoint state

    Parameters
    ----------
    src_path: str
        Path to the existing run folder
    dst_path: str
        Path to the destination run folder
    checkpoint_state_path: str
        Path to the checkpoint state folder to load
    """

    # Copy existing run folder to new path
    copy_run_folder(src_path, dst_path)

    dst = Path(dst_path).resolve()
    checkpoint_state = Path(checkpoint_state_path).resolve()

    # Initialize logging to dst logs directory
    log_path = os.path.join(dst, 'logs')
    log_level_set(log_path)

    # Validate checkpoint state path exists
    if not checkpoint_state.exists():
        msg = f"Checkpoint state path does not exist: {checkpoint_state}"
        logger.critical(msg)
        raise FileNotFoundError(msg)

    # Fild realization file in the destination folder
    realization_files = list(dst.rglob("*realization*.json"))
    if not realization_files:
        msg = f"No realization file found in destination folder: {dst}"
        logger.critical(msg)
        raise FileNotFoundError(msg)
    realization_file = realization_files[0]

    # Read realization file
    try:
        with open(realization_file) as f:
            real_config = json.load(f)
    except json.JSONDecodeError as e:
        logger.critical(f"Error parsing realization file: {realization_file}\n{e}")
        raise

    # Build checkpoint state loading configuration
    load_config = {
        "direction": "load",
        "label": "Load from checkpoint",
        "path": str(checkpoint_state),
        "type": "FilePerUnit",
        "when": "Checkpoint"
    }

    # Add or append to state_saving section
    if "state_saving" not in real_config:
        real_config["state_saving"] = []

    # Remove any existing checkpoint load configs and replace with new one
    real_config["state_saving"] = [
        s for s in real_config["state_saving"]
        if not (s.get("direction") == "load" and s.get("when") == "Checkpoint")
    ]
    real_config["state_saving"].append(load_config)

    # Write updated realization file
    try:
        with open(realization_file, 'w') as f:
            json.dump(real_config, f, indent=4, separators=(", ", ": "), sort_keys=False)
    except OSError as e:
        logger.critical(f"Error writing realization file: {realization_file}\n{e}")
        raise

    logger.info(f"Checkpointing restart state configured in realization file: {realization_file}")
    logger.info(f"Loading state from: {checkpoint_state}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Copy a run folder to a new path and configure checkpoint restart"
    )
    parser.add_argument(
        "src_path",
        type=str,
        help="Path to existing run folder"
    )
    parser.add_argument(
        "dst_path",
        type=str,
        help="Path to the destination run folder"
    )
    parser.add_argument(
        "checkpoint_state_path",
        type=str,
        help="Path to the checkpoint state folder to load"
    )
    return parser.parse_args()


def main():
    args = parse_args()
    checkpoint_restart(args.src_path, args.dst_path, args.checkpoint_state_path)


if __name__ == "__main__":
    main()
