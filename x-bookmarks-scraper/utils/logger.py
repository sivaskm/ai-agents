"""
Structured logging configuration using Loguru.

Provides a pre-configured logger instance that writes to both console and file.
Console output uses colorized formatting for readability during development,
while file output uses structured format for production log analysis.
"""

import sys
from pathlib import Path

from loguru import logger


def setup_logger(log_level: str = "INFO", log_dir: str = "logs") -> None:
    """
    Configure the global Loguru logger with console and file sinks.

    Args:
        log_level: Minimum log level to capture (DEBUG, INFO, WARNING, ERROR).
        log_dir: Directory where log files will be stored.
    """
    # Remove default Loguru handler to prevent duplicate output
    logger.remove()

    # Console sink — colorized, human-readable
    logger.add(
        sys.stderr,
        level=log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> — "
            "<level>{message}</level>"
        ),
        colorize=True,
    )

    # File sink — structured, rotated daily, retained for 7 days
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    logger.add(
        log_path / "scraper_{time:YYYY-MM-DD}.log",
        level="DEBUG",  # Always capture full detail in files
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} — {message}",
        rotation="1 day",
        retention="7 days",
        compression="zip",
        encoding="utf-8",
    )

    logger.info("Logger initialized (console={}, file=DEBUG)", log_level)
