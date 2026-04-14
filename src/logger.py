import logging
import os
from logging.handlers import RotatingFileHandler

LOCALAPPDATA = os.getenv("LOCALAPPDATA", os.path.expanduser("~"))
LOG_DIR = os.path.join(LOCALAPPDATA, "VPNSwitcher", "assets")
LOG_FILE = os.path.join(LOG_DIR, "vpnswitcher.log")

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
