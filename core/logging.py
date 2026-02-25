import sys
import traceback
import time
import inspect
from enum import IntEnum
from typing import Optional, Callable, Any, Dict, List, Set
from datetime import datetime

class LogLevel(IntEnum):
    """Log levels in increasing order of severity."""
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50

class Logger:
    """Simple logging system with configurable levels and per-module configuration."""

    def __init__(self, name: str = "app"):
        """
        Initialize logger.

        Args:
            name: Logger name
        """
        self.name = name
        self._level = LogLevel.INFO  # Default global level
        self._module_levels = {}  # Per-module level overrides
        self._format = "[{level}({function})] {timestamp} - {message}"  # Default format with function name
        self._handlers = []
        self._include_traceback = False
        self._filtered_functions: Set[str] = set()  # Set of function names to filter out

        # Add default console handler
        self.add_handler(self._console_handler)

    def get_calling_info(self, skip_frames: int = 0) -> tuple:
        """
        Determine the module and function that called the logging function.

        Args:
            skip_frames: Number of additional frames to skip

        Returns:
            tuple: (module_name, function_name) of the caller
        """
        # Get the call stack
        stack = inspect.stack()

        # Find the first frame outside of logging.py
        # Start from frame 1 to skip get_calling_info itself
        start_frame = 1 + skip_frames
        for frame_info in stack[start_frame:]:
            module = inspect.getmodule(frame_info.frame)
            if module and module.__name__ != __name__:  # Not this module
                function_name = frame_info.function
                return module.__name__, function_name

        return "unknown", "unknown"

    def set_level(self, level: str, module: Optional[str] = None):
        """
        Set log level.

        Args:
            level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            module: Optional module name to set level for specific module.
                   If None, sets global level.
        """
        try:
            level_enum = LogLevel[level.upper()]
        except KeyError:
            level_enum = LogLevel.INFO

        if module:
            self._module_levels[module] = level_enum
        else:
            self._level = level_enum

    def set_log_module_level(self, level: str):
        """
        Set log level for the module that calls this function.
        Automatically detects the calling module.

        Args:
            level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        """
        # Skip 1 frame to get the caller of set_log_module_level
        module, _ = self.get_calling_info(skip_frames=1)
        self.set_level(level, module)

    def log_filter_out_caller(self, function_names: List[str]):
        """
        Add function names to be filtered out from logging output for DEBUG and INFO levels.
        WARNING, ERROR, and CRITICAL logs are NEVER filtered out regardless of function name.
        Calls to this function are cumulative.

        Args:
            function_names: List of function names (strings) to exclude from DEBUG and INFO logging
        """
        self._filtered_functions.update(function_names)

    def is_function_filtered(self, function_name: str, level: LogLevel) -> bool:
        """
        Check if a function should be filtered based on its name and log level.
        Only filters DEBUG and INFO levels. WARNING, ERROR, and CRITICAL are never filtered.

        Args:
            function_name: Name of the function to check
            level: The log level being attempted

        Returns:
            bool: True if the log should be filtered out
        """
        # Never filter out WARNING, ERROR, or CRITICAL levels
        if level >= LogLevel.WARNING:
            return False

        # Only filter DEBUG and INFO levels
        return function_name in self._filtered_functions

    def get_effective_level(self, module: str) -> LogLevel:
        """
        Get the effective log level for a module.
        Returns module-specific level if set, otherwise global level.

        Args:
            module: Module name

        Returns:
            LogLevel: Effective level for the module
        """
        return self._module_levels.get(module, self._level)

    def set_format(self, format_str: str):
        """Set log message format."""
        self._format = format_str

    def include_traceback(self, include: bool = True):
        """Enable or disable traceback inclusion."""
        self._include_traceback = include

    def _format_message(self, level: str, message: str, module: str, function: str, include_traceback: bool = False) -> str:
        """Format log message according to current format."""
        base_message = self._format.format(
            level=level.upper(),
            function=function,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            message=message,
            logger=self.name,
            module=module  # Add module to format options
        )

        if include_traceback and level.upper() in ["ERROR", "CRITICAL"]:
            tb_lines = traceback.format_exc().strip().split('\n')
            if tb_lines and tb_lines[-1] and not tb_lines[-1].startswith("Traceback"):
                tb_str = "\n".join(tb_lines)
                return f"{base_message}\nTraceback: {tb_str}"

        return base_message

    def _console_handler(self, level: str, formatted_message: str):
        """Default console output handler."""
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
            pass

    def add_handler(self, handler: Callable[[str, str], None]):
        """Add a custom log handler."""
        self._handlers.append(handler)

    def _log(self, level: LogLevel, level_name: str, message: str, *args: Any, include_traceback: bool = False):
        """Internal logging method."""
        # Get calling module and function
        module, function = self.get_calling_info()

        # Check if this function should be filtered out based on level
        if self.is_function_filtered(function, level):
            return

        # Check if this level should be logged for this module
        effective_level = self.get_effective_level(module)
        if level < effective_level:
            return

        # Format the message
        formatted_msg = message
        if args:
            formatted_msg = message % args

        # Format according to configuration
        formatted_output = self._format_message(level_name, formatted_msg, module, function, include_traceback)

        # Send to all handlers
        for handler in self._handlers:
            try:
                handler(level_name, formatted_output)
            except Exception as e:
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
    """Get or create a logger instance."""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = Logger(name)
    return _logger_instance

def log(level: str, message: str, *args: Any, exc_info: bool = False):
    """
    Convenience function for logging.
    This is the main function that modules should use.
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

def set_level(level: str, module: Optional[str] = None):
    """
    Set log level globally or for a specific module.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        module: Optional module name. If provided, sets level only for that module.
    """
    logger = get_logger()
    logger.set_level(level, module)

def set_log_module_level(level: str):
    """
    Set log level for the module that calls this function.
    Automatically detects the calling module.

    This is the recommended way to enable debug logging for a specific module.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL)

    Example:
        # In your module, just call:
        set_log_module_level("DEBUG")
        # This will enable DEBUG logging only for this module
    """
    logger = get_logger()
    logger.set_log_module_level(level)

def log_filter_out_caller(function_names: List[str]):
    """
    Add function names to be filtered out from logging output for DEBUG and INFO levels.
    WARNING, ERROR, and CRITICAL logs are NEVER filtered out regardless of function name.
    Calls to this function are cumulative.

    This is a convenience function that operates on the global logger instance.

    Args:
        function_names: List of function names (strings) to exclude from DEBUG and INFO logging

    Example:
        # Filter out DEBUG and INFO logs from internal_helper and _private_func
        log_filter_out_caller(["internal_helper", "_private_func"])

        # Add more functions to filter (cumulative)
        log_filter_out_caller(["another_function"])

        # WARNING and ERROR logs from these functions will still appear
    """
    logger = get_logger()
    logger.log_filter_out_caller(function_names)

def configure_logging_from_dict(config_dict: dict):
    """
    Configure logging from a dictionary.

    Args:
        config_dict: Dictionary with logging configuration
    """
    logger = get_logger()

    if "level" in config_dict:
        logger.set_level(config_dict["level"])

    if "module_levels" in config_dict and isinstance(config_dict["module_levels"], dict):
        for module, level in config_dict["module_levels"].items():
            logger.set_level(level, module)

    if "format" in config_dict:
        logger.set_format(config_dict["format"])

    if "include_traceback" in config_dict:
        logger.include_traceback(config_dict["include_traceback"])

    if "filtered_functions" in config_dict and isinstance(config_dict["filtered_functions"], list):
        logger.log_filter_out_caller(config_dict["filtered_functions"])
