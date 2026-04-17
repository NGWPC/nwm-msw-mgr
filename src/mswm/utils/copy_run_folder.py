"""
Module to copy a run folder to a new path, updating all internal path references
from the original run folder to the destination path
"""
import os
import shutil
import argparse
from pathlib import Path

class LoggerLike(Protocol):
    def debug(self, msg: str, *args, **kwargs) -> object: ...
    def info(self, msg: str, *args, **kwargs) -> object: ...
    def warning(self, msg: str, *args, **kwargs) -> object: ...
    def error(self, msg: str, *args, **kwargs) -> object: ...
    def critical(self, msg: str, *args, **kwargs) -> object: ...


def _resolve_logger(logger: LoggerLike | None) -> LoggerLike:
    # Your desired behavior
    if logger is None:
        return logging.getLogger(__name__)

    # No strict type checking — trust duck typing
    return logger


def copy_run_folder(src_path: str, dst_path: str, ignore_forcing_config: bool = False, logger: LoggerLike | None = None) -> None:
    """
    Copy a run folder to a new path, replacing internal path references

    Parameters
    ----------
    src_path: str
        Path to the existing run folder
    dst_path: str
        Path to the destination folder
    ignore_forcing_config: bool
        If True, exlcude forcing_config directory from copy (default: False)
        Should be set to True for update_fcst_run
        Should be set to False for checkpoint_restart
    """
    logger = _resolve_logger(logger)
    src = Path(src_path).resolve()
    dst = Path(dst_path).resolve()

    # Validate source exists
    if not src.exists():
        raise FileNotFoundError(f"Source run folder does not exist: {src}")

    if not src.is_dir():
        raise ValueError(f"Source path is not a directory: {src}")

    # Raise error if destination directory already exists
    if dst.exists():
        raise FileExistsError(f"Destination directory already exists: {dst}")

    # Build ignore patterns
    ignore_patterns = ['*.log', 'Output', 'state_save']
    if ignore_forcing_config:
        ignore_patterns.append('forcing_config')

    # Copy full directory tree, ignoring existing log files, Output folder, and state_save folder
    shutil.copytree(src, dst, symlinks=True, ignore=shutil.ignore_patterns(*ignore_patterns))

    # File extensions to serach for path references
    file_extensions = {
        '.json', '.yaml', '.yml', '.input', '.run', '.dat'
    }

    # Iterate through files in destination and replace path reference
    src_str = str(src)
    dst_str = str(dst)

    for root, dirs, files in os.walk(dst):
        for filename in files:
            filepath = Path(root) / filename

            # Skip files not in file_extensions set
            if filepath.suffix.lower() not in file_extensions:
                continue

            # Read files that match file extensions
            try:
                content = filepath.read_text(encoding='utf-8')
            except UnicodeDecodeError as e:
                raise UnicodeDecodeError(f"Unicode decode error reading file: {filepath}") from e
            except PermissionError as e:
                raise PermissionError(f"Permission error reading file: {filepath}") from e

            # Update file path if contained within file
            if src_str in content:
                updated_content = content.replace(src_str, dst_str)
                filepath.write_text(updated_content, encoding='utf-8')

def parse_args():
    parser = argparse.ArgumentParser(
        description="Copy a run folder to a new path, updating all internal path references"
    )
    parser.add_argument(
        "src_path",
        type=str,
        help="Path to existing run folder"
    )
    parser.add_argument(
        "dst_path",
        type=str,
        help="Path to destination run folder"
    )
    parser.add_argument(
        "--ignore_forcing_config",
        action="store_true",
        default=False,
        help="Exclude forcing_config directory from copy (default: False)"
    )
    return parser.parse_args()

def main():
    args = parse_args()
    copy_run_folder(
        src_path=args.src_path,
        dst_path=args.dst_path,
        ignore_forcing_config=args.ignore_forcing_config
    )

if __name__ == "__main__":
    main()
