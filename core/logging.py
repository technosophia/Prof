"""
    This is a simple logging system with configurable levels.

## Logging System (`shared/logging.py`)

BECAREFUL : internal module. Use shared.common for imports, not core.logging

### Purpose
Simple, configurable logging with multiple levels and stack trace support. All logs are in English (not translated). Integrates with configuration system.

### Key Functions

#### Simple Logging (main way to log)
```python
from core.logging import log

# One-line logging
log("info", "Module initialized successfully")
log("debug", "Processing item %d", item_id)
log("warning", "Deprecated function called")
log("error", "Failed to connect: %s", error_msg)

# With stack trace for errors
try:
    risky_operation()
except Exception as e:
    log("error", "Operation failed: %s", str(e), exc_info=True)

"""

import sys
import traceback
import time
from enum import IntEnum
from typing import Optional, Callable, Any
from datetime import datetime

class LogLevel(IntEnum):
    """Log levels in increasing order of severity."""
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50

class Logger:
    """Simple logging system with configurable levels."""

    def __init__(self, name: str = "app"):
        """
        Initialize logger.

        Args:
            name: Logger name
        """
        self.name = name
        self._level = LogLevel.INFO  # Default level
        self._format = "[{level}] {timestamp} - {message}"  # Default format
        self._handlers = []
        self._include_traceback = False  # Whether to include traceback in errors

        # Add default console handler
        self.add_handler(self._console_handler)

    def set_level(self, level: str):
        """
        Set log level.

        Args:
            level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        """
        try:
            self._level = LogLevel[level.upper()]
        except KeyError:
            self._level = LogLevel.INFO

    def set_format(self, format_str: str):
        """
        Set log message format.

        Args:
            format_str: Format string with placeholders
        """
        self._format = format_str

    def include_traceback(self, include: bool = True):
        """
        Enable or disable traceback inclusion in error logs.

        Args:
            include: Whether to include traceback
        """
        self._include_traceback = include

    def _format_message(self, level: str, message: str, include_traceback: bool = False) -> str:
        """Format log message according to current format."""
        base_message = self._format.format(
            level=level.upper(),
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            message=message,
            logger=self.name
        )

        if include_traceback and level.upper() in ["ERROR", "CRITICAL"]:
            # Add traceback information
            tb_lines = traceback.format_exc().strip().split('\n')
            if tb_lines and tb_lines[-1] and not tb_lines[-1].startswith("Traceback"):
                # We have a real traceback
                tb_str = "\n".join(tb_lines)
                return f"{base_message}\nTraceback: {tb_str}"

        return base_message

    def _console_handler(self, level: str, formatted_message: str):
        """Default console output handler."""
        # Color codes for different levels
        colors = {
            "DEBUG": "\033[36m",    # Cyan
            "INFO": "\033[32m",     # Green
            "WARNING": "\033[33m",  # Yellow
            "ERROR": "\033[31m",    # Red
            "CRITICAL": "\033[41m"  # Red background
        }
        reset = "\033[0m"

        color = colors.get(level.upper(), "")
        full_message = f"{color}{formatted_message}{reset}"

        try:
            print(full_message)
        except (BrokenPipeError, OSError, IOError):
            # Silently ignore pipe errors in test/headless environments
            # Streamlit reruns often close stdout/stderr pipes
            pass

    def add_handler(self, handler: Callable[[str, str], None]):
        """
        Add a custom log handler.

        Args:
            handler: Function that accepts (level, formatted_message)
        """
        self._handlers.append(handler)

    def _log(self, level: LogLevel, level_name: str, message: str, *args: Any, include_traceback: bool = False):
        """Internal logging method."""
        # Check if this level should be logged
        if level < self._level:
            return

        # Format the message
        formatted_msg = message
        if args:
            formatted_msg = message % args

        # Format according to configuration
        formatted_output = self._format_message(level_name, formatted_msg, include_traceback)

        # Send to all handlers
        for handler in self._handlers:
            try:
                handler(level_name, formatted_output)
            except Exception as e:
                # Don't crash if a handler fails
                print(f"Log handler error: {e}")

    def debug(self, message: str, *args: Any):
        """Log debug message."""
        self._log(LogLevel.DEBUG, "DEBUG", message, *args)

    def info(self, message: str, *args: Any):
        """Log info message."""
        self._log(LogLevel.INFO, "INFO", message, *args)

    def warning(self, message: str, *args: Any):
        """Log warning message."""
        self._log(LogLevel.WARNING, "WARNING", message, *args)

    def error(self, message: str, *args: Any, exc_info: bool = False):
        """Log error message with optional exception info."""
        self._log(LogLevel.ERROR, "ERROR", message, *args, include_traceback=exc_info)

    def critical(self, message: str, *args: Any, exc_info: bool = False):
        """Log critical message with optional exception info."""
        self._log(LogLevel.CRITICAL, "CRITICAL", message, *args, include_traceback=exc_info)

    def log(self, level: str, message: str, *args: Any, exc_info: bool = False):
        """
        Generic log method with string level.

        Args:
            level: Log level as string (debug, info, warning, error, critical)
            message: Log message
            *args: Format arguments
            exc_info: Whether to include exception traceback
        """
        level_upper = level.upper()

        if level_upper == "DEBUG":
            self.debug(message, *args)
        elif level_upper == "INFO":
            self.info(message, *args)
        elif level_upper == "WARNING":
            self.warning(message, *args)
        elif level_upper == "ERROR":
            self.error(message, *args, exc_info=exc_info)
        elif level_upper == "CRITICAL":
            self.critical(message, *args, exc_info=exc_info)
        else:
            self.warning(f"Unknown log level '{level}', logging as INFO")
            self.info(message, *args)

# Global logger instance
_logger_instance = None

def get_logger(name: str = "app") -> Logger:
    """
    Get or create a logger instance.

    Args:
        name: Logger name

    Returns:
        Logger: Logger instance
    """
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = Logger(name)
    return _logger_instance

def log(level: str, message: str, *args: Any, exc_info: bool = False):
    """
    Convenience function for logging.
    This is the main function that modules should use.

    Args:
        level: Log level (debug, info, warning, error, critical)
        message: Log message
        *args: Format arguments
        exc_info: Whether to include exception traceback
    """
    logger = get_logger()
    logger.log(level, message, *args, exc_info=exc_info)

def debug(message: str, *args: Any):
    """Convenience function for debug logging."""
    log("DEBUG", message, *args)

def info(message: str, *args: Any):
    """Convenience function for info logging."""
    log("INFO", message, *args)

def warning(message: str, *args: Any):
    """Convenience function for warning logging."""
    log("WARNING", message, *args)

def error(message: str, *args: Any, exc_info: bool = False):
    """Convenience function for error logging."""
    log("ERROR", message, *args, exc_info=exc_info)

def critical(message: str, *args: Any, exc_info: bool = False):
    """Convenience function for critical logging."""
    log("CRITICAL", message, *args, exc_info=exc_info)

# Configuration helper functions
def configure_logging_from_dict(config_dict: dict):
    """
    Configure logging from a dictionary.

    Args:
        config_dict: Dictionary with logging configuration
    """
    logger = get_logger()

    if "level" in config_dict:
        logger.set_level(config_dict["level"])

    if "format" in config_dict:
        logger.set_format(config_dict["format"])

    if "include_traceback" in config_dict:
        logger.include_traceback(config_dict["include_traceback"])
