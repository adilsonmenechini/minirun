from __future__ import annotations

import logging
import os

from minirun.config import load_env
from minirun.config.loader import load_settings
from minirun.log import configure_logging


def init(log_level: int | None = None) -> None:
    if log_level is not None:
        configure_logging(level=log_level)
    else:
        raw = os.environ.get("LOG_LEVEL", "INFO")
        level = getattr(logging, raw.upper(), logging.INFO)
        configure_logging(level=level)
    load_env()
    load_settings()
