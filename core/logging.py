import sys
import traceback
import time
import inspect
import os
import json
from enum import IntEnum
from typing import Optional, Callable, Any, Dict, List, Set, Tuple
from datetime import datetime
from pathlib import Path

class LogLevel(IntEnum):
    """Log levels in increasing order of severity."""
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50

class LogCapture:
    """Handles log capture functionality for a logger instance."""

    def __init__(self, level: LogLevel, max_messages: int = 0, capture_file: Optional[str] = None):
        """
        Initialize a log capture session.

        Args:
            level: Minimum log level to capture
            max_messages: Maximum number of messages to keep (0 for unlimited)
            capture_file: Optional file path to persist captured logs
        """
        self.level = level
        self.max_messages = max_messages
        self.capture_file = capture_file
        self.captured_logs: List[str] = []
        self.warning_count = 0
        self.warning_threshold = 1000
        self.active = True
        self.file_handle = None

        # Initialize capture file if specified
        if capture_file:
            self._init_capture_file()

    def _init_capture_file(self):
        """Initialize the capture file for writing."""
        try:
            # Ensure directory exists
            file_path = Path(self.capture_file)
            file_path.parent.mkdir(parents=True, exist_ok=True)

            # Open file handle for writing (append mode)
            # Using 'a' mode with explicit encoding
            self.file_handle = open(file_path, 'a', encoding='utf-8')

            # Write header to indicate capture start
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.file_handle.write(f"--- Log capture started at {timestamp} ---\n")
            self.file_handle.flush()  # Ensure it's written
            print(f"Log capture file initialized: {file_path.absolute()}")
        except Exception as e:
            print(f"Warning: Could not initialize capture file {self.capture_file}: {e}")
            self.capture_file = None
            self.file_handle = None

    def add_log(self, formatted_message: str, level: LogLevel):
        """
        Add a log message to the capture if it meets the level requirement.
        This bypasses the normal logging level checks.

        Args:
            formatted_message: The formatted log message
            level: The log level of the message
        """
        if not self.active:
            return

        # Check if this message meets the capture level requirement
        # This is independent of the normal logging level
        if level < self.level:
            return

        # Add to memory
        self.captured_logs.append(formatted_message)

        # Check size limits
        if self.max_messages > 0 and len(self.captured_logs) > self.max_messages:
            self.captured_logs.pop(0)  # Remove oldest

        # Warning for large captures
        if self.max_messages == 0:  # Unlimited
            current_size = len(self.captured_logs)
            if current_size >= self.warning_threshold and current_size % self.warning_threshold == 0:
                if current_size > self.warning_count * self.warning_threshold:
                    self.warning_count = current_size // self.warning_threshold
                    print(f"Warning: Log capture has reached {current_size} messages. "
                          f"Consider setting a max_messages limit.")

        # Write to file if configured
        self._write_to_file(formatted_message)

    def _write_to_file(self, formatted_message: str):
        """Write a log message to the capture file."""
        if self.file_handle and not self.file_handle.closed:
            try:
                self.file_handle.write(formatted_message + '\n')
                self.file_handle.flush()  # Ensure it's written immediately
            except Exception as e:
                print(f"Warning: Could not write to capture file: {e}")
        elif self.capture_file and not self.file_handle:
            # Try to reopen if file handle was lost
            self._init_capture_file()
            if self.file_handle:
                self.file_handle.write(formatted_message + '\n')
                self.file_handle.flush()

    def stop(self) -> Tuple[List[str], Optional[str]]:
        """
        Stop the capture session and return captured logs and file path.

        Returns:
            Tuple of (captured_logs, capture_file_path)
        """
        self.active = False

        # Close file handle if open
        if self.file_handle:
            try:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.file_handle.write(f"--- Log capture ended at {timestamp} - Total messages: {len(self.captured_logs)} ---\n")
                self.file_handle.close()
            except Exception as e:
                print(f"Warning: Error closing capture file: {e}")
            finally:
                self.file_handle = None

        return self.captured_logs.copy(), self.capture_file


class LogCaptureHandler:
    """Handler that sends logs to a LogCapture instance."""

    def __init__(self, capture: LogCapture):
        self.capture = capture

    def __call__(self, level_name: str, formatted_message: str):
        """Handle a log message by sending it to the capture."""
        if self.capture and self.capture.active:
            # Convert level name to LogLevel enum
            try:
                level = LogLevel[level_name.upper()]
            except KeyError:
                level = LogLevel.INFO
            self.capture.add_log(formatted_message, level)


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
        self._use_filtering = True
        self._capture_handler: Optional[LogCaptureHandler] = None  # Current capture handler
        self._capture: Optional[LogCapture] = None  # Current capture instance
        self._default_capture_file: Optional[str] = None

        # Check FORCE_LOG environment variable
        self._force_log = os.environ.get('FORCE_LOG', '').upper()
        if self._force_log:
            # If FORCE_LOG is set to any value, disable filtering
            self._use_filtering = False
            # If FORCE_LOG is set to a specific level, override the global level
            if self._force_log in ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']:
                try:
                    self._level = LogLevel[self._force_log]
                except KeyError:
                    pass  # Keep existing level if invalid

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
        # If FORCE_LOG is set to a level, ignore attempts to change the global level
        if module is None and self._force_log in ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']:
            return  # Global level is locked by FORCE_LOG environment variable

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

    def set_use_filtering(self, use_filtering: bool):
        """
        Enable or disable function name filtering.
        When disabled, all DEBUG and INFO logs will be shown regardless of function name.

        Args:
            use_filtering: True to enable filtering, False to disable
        """
        # If FORCE_LOG is set, ignore attempts to change filtering
        if not self._force_log:
            self._use_filtering = use_filtering

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

        # If FORCE_LOG is set, disable all filtering
        if self._force_log:
            return False

        # If filtering is disabled, don't filter anything
        if not self._use_filtering:
            return False

        # Only filter DEBUG and INFO levels when filtering is enabled
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

    def remove_handler(self, handler: Callable[[str, str], None]):
        """Remove a custom log handler."""
        if handler in self._handlers:
            self._handlers.remove(handler)

    def _log(self, level: LogLevel, level_name: str, message: str, *args: Any, include_traceback: bool = False):
        """Internal logging method."""
        # Get calling module and function
        module, function = self.get_calling_info()

        # Check if this function should be filtered out based on level
        if self.is_function_filtered(function, level):
            return

        # Format the message (always format even if not printed, for capture)
        formatted_msg = message
        if args:
            formatted_msg = message % args

        # Format according to configuration
        formatted_output = self._format_message(level_name, formatted_msg, module, function, include_traceback)

        # ALWAYS send to capture handler if active - this bypasses normal level checks
        # The capture handler itself will filter based on its own level
        if self._capture_handler:
            try:
                self._capture_handler(level_name, formatted_output)
            except Exception as e:
                print(f"Capture handler error: {e}")

        # Check if this level should be logged for this module (for normal output)
        effective_level = self.get_effective_level(module)
        if level >= effective_level:
            # Send to all regular handlers
            for handler in self._handlers:
                # Skip the capture handler in regular handlers to avoid double processing
                if handler is self._capture_handler:
                    continue
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

    def error(self, message: str, *args: Any, stacktrace: bool = False):
        """Log error message with optional exception info."""
        self._log(LogLevel.ERROR, "ERROR", message, *args, include_traceback=stacktrace)

    def critical(self, message: str, *args: Any, stacktrace: bool = False):
        """Log critical message with optional exception info."""
        self._log(LogLevel.CRITICAL, "CRITICAL", message, *args, include_traceback=stacktrace)

    def log(self, level: str, message: str, *args: Any, stacktrace: bool = False):
        """
        Generic log method with string level.

        Args:
            level: Log level as string (debug, info, warning, error, critical)
            message: Log message
            *args: Format arguments
            stacktrace: Whether to include exception traceback
        """
        level_upper = level.upper()

        if level_upper == "DEBUG":
            self.debug(message, *args)
        elif level_upper == "INFO":
            self.info(message, *args)
        elif level_upper == "WARNING":
            self.warning(message, *args)
        elif level_upper == "ERROR":
            self.error(message, *args, stacktrace=stacktrace)
        elif level_upper == "CRITICAL":
            self.critical(message, *args, stacktrace=stacktrace)
        else:
            self.warning(f"Unknown log level '{level}', logging as INFO")
            self.info(message, *args)

    # New methods for log capture
    def capture_start(self, level: str, max_messages: int = 0, capture_file: Optional[str] = None):
        """
        Start capturing logs above a certain level.
        Capture works independently of the normal logging level.

        Args:
            level: Minimum log level to capture (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            max_messages: Maximum number of messages to keep in memory (0 for unlimited)
            capture_file: Optional file path to persist captured logs
                         If not provided, uses config setting or keeps only in memory

        Returns:
            The logger instance for chaining
        """
        # Stop any existing capture
        if self._capture and self._capture.active:
            self.capture_end()

        # Use default capture file from config if not provided
        if capture_file is None and self._default_capture_file:
            capture_file = self._default_capture_file

        # Convert level string to LogLevel
        try:
            level_enum = LogLevel[level.upper()]
        except KeyError:
            level_enum = LogLevel.INFO
            print(f"Warning: Invalid capture level '{level}', using INFO")

        # Start new capture
        self._capture = LogCapture(level_enum, max_messages, capture_file)
        self._capture_handler = LogCaptureHandler(self._capture)

        file_info = f", File: {capture_file}" if capture_file else ""
        print(f"Log capture started - Level: {level}, Max messages: {'unlimited' if max_messages == 0 else max_messages}{file_info}")

        return self

    def capture_end(self) -> Tuple[List[str], Optional[str]]:
        """
        Stop the current log capture and return captured logs and file path.

        Returns:
            Tuple of (captured_logs, capture_file_path)
        """
        if not self._capture or not self._capture.active:
            print("Warning: No active log capture to end")
            return [], None

        captured_logs, capture_file = self._capture.stop()
        print(f"Log capture ended - Captured {len(captured_logs)} messages")

        if capture_file:
            abs_path = str(Path(capture_file).absolute())
            print(f"Captured logs written to: {abs_path}")

        # Clear the capture references
        self._capture = None
        self._capture_handler = None

        return captured_logs, capture_file

    def is_capturing(self) -> bool:
        """Check if log capture is currently active."""
        return self._capture is not None and self._capture.active

    def get_capture_file(self) -> Optional[str]:
        """Get the current capture file path if one is being used."""
        return self._capture.capture_file if self._capture else None


# Global logger instance
_logger_instance = None

def get_logger(name: str = "app") -> Logger:
    """Get or create a logger instance."""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = Logger(name)
    return _logger_instance

def log(level: str, message: str, *args: Any, stacktrace: bool = False):
    """
    Convenience function for logging.
    This is the main function that modules should use.
    """
    logger = get_logger()
    logger.log(level, message, *args, stacktrace=stacktrace)

def debug(message: str, *args: Any):
    """Convenience function for debug logging."""
    log("DEBUG", message, *args)

def info(message: str, *args: Any):
    """Convenience function for info logging."""
    log("INFO", message, *args)

def warning(message: str, *args: Any):
    """Convenience function for warning logging."""
    log("WARNING", message, *args)

def error(message: str, *args: Any, stacktrace: bool = False):
    """Convenience function for error logging."""
    log("ERROR", message, *args, stacktrace=stacktrace)

def critical(message: str, *args: Any, stacktrace: bool = False):
    """Convenience function for critical logging."""
    log("CRITICAL", message, *args, stacktrace=stacktrace)

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

    # Handle use_filtering configuration
    if "use_filtering" in config_dict:
        logger.set_use_filtering(config_dict["use_filtering"])

    # Handle capture_file configuration (for default capture file)
    if "capture_file" in config_dict:
        # Store as an attribute for later use if needed
        logger._default_capture_file = config_dict["capture_file"]


# New convenience functions for log capture
def capture_log_start(level: str, max_messages: int = 0, capture_file: Optional[str] = None):
    """
    Start capturing logs above a certain level.
    Capture works independently of the normal logging level.

    Args:
        level: Minimum log level to capture (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        max_messages: Maximum number of messages to keep in memory (0 for unlimited)
        capture_file: Optional file path to persist captured logs
                     If not provided, logs are kept only in memory
    """
    logger = get_logger()
    return logger.capture_start(level, max_messages, capture_file)

def capture_log_end() -> Tuple[List[str], Optional[str]]:
    """
    Stop the current log capture and return captured logs and file path.

    Returns:
        Tuple of (captured_logs, capture_file_path)
    """
    logger = get_logger()
    return logger.capture_end()

def is_log_capturing() -> bool:
    """Check if log capture is currently active."""
    logger = get_logger()
    return logger.is_capturing()
