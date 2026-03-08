"""
utils/logger.py — Centralized logging configuration.
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(log_file: str, log_level: str = "INFO") -> None:
    """
    Configure root logger with a rotating file handler and a stdout handler.
    Call once at the start of main.py before any other module is used.

    Args:
        log_file: Path to the log file (will be created with parent dirs if needed).
        log_level: Logging level string (DEBUG, INFO, WARNING, ERROR).
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    fmt = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handlers: list[logging.Handler] = [
        RotatingFileHandler(
            log_path,
            maxBytes=5_000_000,  # 5 MB per file
            backupCount=5,
            encoding="utf-8",
        ),
        logging.StreamHandler(sys.stdout),
    ]

    logging.basicConfig(level=level, format=fmt, datefmt=datefmt, handlers=handlers)
