import logging
import os
from logging.handlers import RotatingFileHandler

from utils import asset_path

LOG_DIR = asset_path()          # resolves to <project>/assets/ or installed assets/
LOG_FILE = asset_path("vpnswitcher.log")

_logger = None


def get_logger() -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger

    os.makedirs(LOG_DIR, exist_ok=True)

    logger = logging.getLogger("VPNSwitcher")
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:
        handler = RotatingFileHandler(
            LOG_FILE, maxBytes=500_000, backupCount=1, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(handler)

    _logger = logger
    return logger
