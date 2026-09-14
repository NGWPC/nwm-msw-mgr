"""
Shared helpers for making EWTS optional across the mswm package.

Per program directive: when EWTS is unavailable, log output goes to the given
log_dir/log_file_name if both are provided, or to stdout only if they are not.
No default log directory or filename is ever invented when one is not given.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

__all__ = [
    "EWTS_AVAILABLE",
    "MSW_MGR_ID",
    "MODNM",
    "Status",
    "STATUS_LEVEL",
    "MSG_PAYLOAD_SENTINEL_START",
    "MSG_PAYLOAD_SENTINEL_END",
    "StdoutStyleFormatter",
    "configure_stdout_logging",
    "get_msw_mgr_logger",
    "initialize_msw_mgr_logger",
    "log_status",
]

try:
    import ewts
    from ewts import Payload, Status
    from ewts.modules import ModuleKey
    EWTS_AVAILABLE = True
    MSW_MGR_ID = ewts.MSW_MGR_ID
    MODNM = ModuleKey.MSW_MGR.value
except ImportError:
    EWTS_AVAILABLE = False
    MSW_MGR_ID = "MSWMGR"
    MODNM = "msw-mgr"

    class Status:
        """Stand-in for ewts.data_payloads.Status so status names still resolve
        as attributes when EWTS is unavailable. Values mirror the real
        ewts.Status StrEnum wire values exactly."""
        NULL = "NULL"
        INITTING = "INITIALIZING"
        INITTED = "INITIALIZED"
        STARTING = "STARTING"
        INPROG = "IN_PROGRESS"
        COMPLETE = "COMPLETE"
        ERROR = "ERROR"

# Matches the "STATUS" custom level EWTS registers via logging.addLevelName(60, "STATUS")
# in ewts/logger.py. Defined here (not just conditionally) so StdoutStyleFormatter can
# treat STATUS records like INFO records regardless of whether EWTS itself already
# registered the level name.
STATUS_LEVEL = 60

if not EWTS_AVAILABLE:
    logging.addLevelName(STATUS_LEVEL, "STATUS")

MSG_PAYLOAD_SENTINEL_START = "<MSG_DATA>"
MSG_PAYLOAD_SENTINEL_END = "</MSG_DATA>"


class StdoutStyleFormatter(logging.Formatter):

    INFO_FORMAT = (
        "%(asctime)s %(name)-8s %(levelname)-7s %(message)s"
    )

    DETAILED_FORMAT = (
        "%(asctime)s %(name)-8s %(levelname)-7s "
        "%(message)s "
        "[%(filename)s.%(funcName)s(L%(lineno)s)]"
    )

    def format(self, record):
        if record.levelno in (logging.INFO, STATUS_LEVEL):
            self._style._fmt = self.INFO_FORMAT
        else:
            self._style._fmt = self.DETAILED_FORMAT

        return super().format(record)

    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def configure_stdout_logging(logger: logging.Logger) -> None:
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.INFO)
        handler.setFormatter(StdoutStyleFormatter())
        logger.addHandler(handler)

    logger.propagate = False


def _attach_file_handler(logger: logging.Logger, full_log_path: Path, log_level: str = "INFO") -> None:
    """Add/replace a FileHandler on an already-configured logger without touching
    its existing handlers (e.g. the stdout StreamHandler set up before this call)."""
    for handler in list(logger.handlers):
        if isinstance(handler, logging.FileHandler):
            logger.removeHandler(handler)
            handler.close()

    file_handler = logging.FileHandler(full_log_path)
    file_handler.setLevel(log_level)
    for handler in logger.handlers:
        if handler.formatter is not None:
            file_handler.setFormatter(handler.formatter)
            break
    logger.addHandler(file_handler)


def _remove_console_handlers(logger: logging.Logger) -> None:
    """Remove handlers that write to a stream (e.g. stdout/stderr) but are not
    file handlers. FileHandler is itself a StreamHandler subclass, so this
    excludes FileHandler instances explicitly rather than relying on isinstance."""
    for handler in list(logger.handlers):
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
            logger.removeHandler(handler)


def get_msw_mgr_logger() -> ewts.EwtsLogger | logging.Logger:
    if EWTS_AVAILABLE:
        return ewts.get_logger(MSW_MGR_ID)
    return logging.getLogger(MSW_MGR_ID)


def initialize_msw_mgr_logger(log_dir: str | Path | None = None, log_file_name: str | None = None) -> ewts.EwtsLogger | logging.Logger:
    '''
    Set up the MSWM named logger.

    Arguments
    ---------
    log_dir: optional directory to write the log file to. If not provided (along with
        log_file_name), no default directory is invented -- logging goes to stdout only
        (or, if EWTS is available, whatever EWTS itself does for log_dir=None).
    log_file_name: optional log file name. Only used when log_dir is also provided.

    Returns
    -------
    ewts.EwtsLogger | logging.Logger
        Instance of the EWTS logger; or, if EWTS is unavailable, a plain Python
        logger writing to log_dir/log_file_name if both are provided, or to
        stdout only if they are not.
    '''
    if log_dir is not None and log_file_name is not None:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file_path = log_dir / log_file_name
    else:
        log_dir = None
        log_file_name = None
        log_file_path = None

    if EWTS_AVAILABLE:
        # In case the logger was previously setup for bootstrapping
        ewts.logger.reset_logger(MSW_MGR_ID)

        return ewts.logger.setup_logger(
            MSW_MGR_ID,
            level="INFO",
            log_dir=log_dir,
            log_file_name=log_file_name,
            running_in_ngen=False,
            enabled=True,
        )

    logger = logging.getLogger(MSW_MGR_ID)
    configure_stdout_logging(logger)
    if log_file_path is not None:
        _attach_file_handler(logger, log_file_path, "INFO")
        _remove_console_handlers(logger)
    return logger


def log_status(logger: logging.Logger, status, msg: str | None = None, prog: float | None = None, modnm: str | None = MODNM) -> None:
    """Emit an EWTS status payload when available; otherwise log an equivalent
    <MSG_DATA> JSON payload at the STATUS level, byte-matching the format
    produced by ewts.data_payloads.Payload.json_wrapped (json.dumps(asdict(self)),
    which always includes all four fields, defaulting to null where unset)."""
    if EWTS_AVAILABLE:
        logger.status(Payload(status, msg=msg, prog=prog, modnm=modnm))
        return

    payload = {"status": str(status), "prog": prog, "msg": msg, "modnm": modnm}
    logger.log(
        STATUS_LEVEL,
        f"{MSG_PAYLOAD_SENTINEL_START}{json.dumps(payload)}{MSG_PAYLOAD_SENTINEL_END}",
    )
