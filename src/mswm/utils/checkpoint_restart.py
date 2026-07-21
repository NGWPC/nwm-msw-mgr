"""
Module to restart a run from a saved checkpoint, copying a run folder to a new path and configuring checkpoint restart
"""
import os
import json
import argparse
from pathlib import Path
import ewts
from mswm.utils.copy_run_folder import copy_run_folder

logger = None


def checkpoint_restart(
        src_path: str,
        dst_path: str,
        checkpoint_dir: str | None = None,
) -> None:
    """
    Copy a run folder to a new path and configure it to load from a checkpoint state
    The checkpoint state copied to the new run folder and is inferred from the destination path at <dst_path>/checkpoint/.

    Parameters
    ----------
    src_path: str
        Path to the existing run folder
    dst_path: str
        Path to the destination run folder
    checkpoint_dir: str
        Path to the existing checkpointing state folder
    """

    # Copy existing run folder to new path
    copy_run_folder(src_path, dst_path)
    dst = Path(dst_path).resolve()

    # Initialize logging to dst logs directory
    global logger
    log_path = os.path.join(dst, 'logs')
    ewts.logger.reset_logger(ewts.MSW_MGR_ID)
    logger = ewts.logger.setup_logger(
        ewts.MSW_MGR_ID,
        level="INFO",
        log_dir=log_path,
        log_file_name="msw_mgr_checkpoint.log",
        running_in_ngen=False,
        enabled=True
    )

    logger.info(f"Copied run folder from {src_path} to {dst_path}")

    # Infer checkpoint state path from destination folder or use provided path
    checkpoint_state = Path(checkpoint_dir).resolve() if checkpoint_dir else dst / "checkpoint"
    if not checkpoint_state.exists():
        msg = f"Checkpoint state path does not exist: {checkpoint_state}"
        logger.critical(msg)
        raise FileNotFoundError(msg)

    # Confirm checkpoint state folder contains files
    checkpoint_files = list(checkpoint_state.iterdir())
    if not checkpoint_files:
        msg = f"Checkpoint state folder is empty: {checkpoint_state}"
        logger.critical(msg)
        raise FileNotFoundError(msg)

    # Fild realization file in the destination folder
    realization_files = list(dst.rglob("*realization*.json"))
    if not realization_files:
        msg = f"No realization file found in destination folder: {dst}"
        logger.critical(msg)
        raise FileNotFoundError(msg)
    if len(realization_files) > 1:
        logger.warning("More than one realization file found in source folder")
    realization_file = realization_files[0]

    # Read realization file
    try:
        with open(realization_file) as f:
            real_config = json.load(f)
    except json.JSONDecodeError as e:
        msg = f"Error parsing realization file: {realization_file}\n{e}"
        logger.critical(msg)
        raise ValueError(msg) from e

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
        msg = f"Error writing realization file: {realization_file}\n{e}"
        logger.critical(msg)
        raise OSError(msg) from e

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
        "--checkpoint_dir",
        type=str,
        default=None,
        help="Path to checkpoint state directory. Defaults to <dst_path>/checkpoint/."
    )
    return parser.parse_args()


def main():
    args = parse_args()
    checkpoint_restart(args.src_path, args.dst_path, checkpoint_dir=args.checkpoint_dir)


if __name__ == "__main__":
    main()
