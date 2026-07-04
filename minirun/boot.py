from __future__ import annotations

import logging
import os

from minirun.config import load_env
from minirun.config.loader import load_settings
from minirun.log import configure_logging


def init(log_level: int | None = None, verbose: int = 0) -> None:
    if log_level is not None:
        # Explicit log level provided (from parameter)
        final_level = log_level
    elif verbose >= 2:
        # -vv or more: DEBUG level
        final_level = logging.DEBUG
    elif verbose >= 1:
        # -v: INFO level
        final_level = logging.INFO
    else:
        # No verbose flag: WARNING and above only (quiet by default)
        final_level = logging.WARNING
    configure_logging(level=final_level)
    load_env()
    load_settings()
