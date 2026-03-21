Here's the updated `API.md` with documentation for the new log capture functionality:

```markdown
<!-- /core/API.md -->

# Configuration System (`core/config.py`)

Centralized configuration management with dot-notation access. Automatically discovers and loads `config.json` files throughout the project directory structure, with keys prefixed by their relative path (e.g., `modules/rag/config.json` becomes accessible under `modules.rag`).

Configuration merging follows this priority order (highest last):
1. Base `config.json` files
2. `local_config.json` files (override base)
3. `tests/test_config.json` files (override both, only when `TEST_MODE=true` or running with pytest)

**Exported functions:**
- `get_config()`: Access the global configuration object
- `get_section(prefix)`: Get module-specific configuration section
- `save_config(prefix, data)`: Save module configuration back to its original file

# Logging System (`core/logging.py`)

Simple, configurable logging with multiple severity levels and stack trace support. Integrates with the configuration system. Supports both global and per-module log levels. Automatically displays the caller function name in parentheses after the log level. Includes intelligent filtering that can suppress DEBUG and INFO logs from specific functions while always showing WARNING, ERROR, and CRITICAL logs.

## Key Features:
- **Caller function display**: Each log entry shows the function name that generated it: `[INFO(my_function)] 2024-01-01 12:34:56 - message`
- **Intelligent filtering**: Suppress noisy DEBUG/INFO logs from specific functions while always preserving WARNING, ERROR, and CRITICAL logs
- **Module-specific log levels**: Set different log levels for different modules
- **Stack trace support**: Optional exception traceback inclusion for ERROR and CRITICAL logs
- **Colored console output**: Different colors for different log levels
- **Customizable format**: Configurable log message format
- **Log capture**: Temporarily capture logs in memory or to file for testing/debugging

## Core Logging Functions

**Exported functions:**
- `log(level, message, *args, stacktrace=False)`: Main logging function
- `debug()`, `info()`, `warning()`, `error()`, `critical()`: Level-specific shortcuts
- `set_level(level, module=None)`: Set global or module-specific log level
- `set_log_module_level(level)`: Enable debug for current module (auto-detects module name)
- `log_filter_out_caller(function_names)`: Suppress DEBUG/INFO logs from specified functions (cumulative)
- `configure_logging_from_dict(config_dict)`: Apply logging configuration

**Environment Variables:**
- `FORCE_LOG=true` or `FORCE_LOG=DEBUG`: Force logging from outside (useful for GitHub Actions)
- `FILTER_LOG=pattern`: Highlight logs matching a pattern with bold magenta on white background. The pattern can be a simple string (case insensitive) or a regex pattern. Useful for quickly spotting specific log messages in noisy output.

**Example:**
```python
import logging

# Filter out DEBUG/INFO logs from verbose functions
logging.log_filter_out_caller(["debug_helper", "verbose_printer"])

def debug_helper():
    logging.debug("This DEBUG will be filtered out")
    logging.info("This INFO will be filtered out")
    logging.warning("This WARNING will still appear")
    logging.error("This ERROR will still appear")
```

## Log Capture System

The log capture system allows you to temporarily intercept and collect log messages for analysis, testing, or display in UI components. Captured logs are stored in memory by default for maximum performance, with optional file persistence.

### Capture Functions

- **`capture_log_start(level, max_messages=0, capture_file=None)`**: Start capturing logs at or above the specified level
  - `level`: Minimum log level to capture (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`)
  - `max_messages`: Maximum number of messages to keep in memory (0 for unlimited)
  - `capture_file`: Optional file path to persist captured logs (if not provided, logs are only kept in memory)

- **`capture_log_end()`**: Stop the current log capture and return all captured messages as a list of strings

- **`is_log_capturing()`**: Check if a log capture session is currently active

### Capture Behavior

- **Memory-first**: Captured logs are stored in RAM for instant access (ideal for Streamlit apps)
- **FIFO rotation**: When `max_messages` is set, oldest messages are automatically removed when limit is reached
- **Unlimited capture warnings**: When capturing without a limit, warnings are issued at 1000 messages and every 1000 thereafter
- **Level filtering**: Only logs at or above the specified capture level are collected
- **Respects existing filters**: Logs that would be filtered out by `log_filter_out_caller()` are also excluded from capture
- **Concurrent sessions**: Only one capture session can be active at a time (starting a new capture automatically ends the previous one)

### File Persistence

When a `capture_file` is specified:
- The file is automatically created/cleared when capture starts
- Each captured log is appended to the file as it occurs
- File writing errors are caught and logged (capture continues in memory)
- The file path is returned via `get_capture_file()` if needed

### Configuration

You can specify a default capture file in your `config.json`:

```json
{
  "logging": {
    "level": "INFO",
    "format": "[{level}({function})] {timestamp} - {message}",
    "include_traceback": true,
    "use_filtering": true,
    "capture_file": "logs/captured_output.txt",
    "filtered_functions": [...]
  }
}
```

# Translation System (`core/translate.py`)
Multi-language support with JSON-based translation files. Automatically loads all translation files from 'translations' directories throughout the project.

**Exported functions:**
- `_(key, lang=None)`: Main translation function (uses session language)
- `get_available_languages()`: List all loaded language codes

# Database System (`core/database.py`)
The goal is to have : 
- same code for mysql / sqlite  (sqlalchemy)
- same simple tool to upgrade database structure (alembic)

SQLAlchemy-based database management with singleton pattern. Supports both in-memory (testing) and persistent SQLite databases.

**Exported components:**
- `Base`: SQLAlchemy declarative base for model definitions
- `init_database()`: Initialize database connection
- `get_db_manager()`: Access the global database manager
- `db_manager.get_session()`: Get database session (context manager)
- `db_manager.empty_all_tables()`: Clear all table data
```

The documentation now includes:
- A new "Log Capture System" section with comprehensive details
- Capture functions and their parameters
- Capture behavior and limitations
- File persistence options
- Configuration example
- Multiple usage examples including basic capture, Streamlit integration, and testing
- Streamlit-specific considerations
