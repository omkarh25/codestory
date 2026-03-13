"""
Logging configuration for codeStory.

Provides centralized logging setup with configurable levels,
formatting, and file output.
"""

import logging
import sys
from pathlib import Path
from typing import Optional


# Default format for all log messages
DEFAULT_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def setup_logging(
    level: int = logging.WARNING,
    log_file: Optional[Path] = None,
    format_string: str = DEFAULT_FORMAT,
) -> logging.Logger:
    """
    Configure logging for the entire application.

    Args:
        level: Logging level (e.g., logging.DEBUG, logging.INFO).
        log_file: Optional path to write logs to file.
        format_string: Custom format string for log messages.

    Returns:
        Configured root logger.
    """
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter(format_string))
    root_logger.addHandler(console_handler)

    # File handler (if specified)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(level)
        file_handler.setFormatter(logging.Formatter(format_string))
        root_logger.addHandler(file_handler)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a specific module.

    Args:
        name: Logger name (typically __name__ of the module).

    Returns:
        Logger instance.
    """
    return logging.getLogger(name)


# Pre-configure common loggers
LOGGER = get_logger("codestory")
