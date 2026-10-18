"""
Centralized logging configuration for the El-Sharnouby BI Platform.
Every module should use: logger = setup_logger(__name__)
Every function should be decorated with: @log_function
"""
import logging
import functools
import time
from typing import Callable, Any

from app.settings import settings


def setup_logger(name: str) -> logging.Logger:
    """Create and configure a logger for the given module name."""
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(getattr(logging, str(settings.LOG_LEVEL).upper(), logging.INFO))

    return logger


def log_function(func: Callable) -> Callable:
    """Decorator that logs function entry, exit, and execution time."""
    logger = logging.getLogger(func.__module__)

    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        func_name = func.__qualname__
        logger.debug(f"→ {func_name}() called")
        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            elapsed = (time.perf_counter() - start) * 1000
            logger.info(f"{func_name}() completed in {elapsed:.1f}ms")
            return result
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error(f"✗ {func_name}() failed after {elapsed:.1f}ms: {e}")
            raise

    return wrapper
