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

Simple, configurable logging with multiple severity levels and stack trace support. Integrates with the configuration system. Supports both global and per-module log levels.

**Exported functions:**
- `log(level, message, *args, exc_info=False)`: Main logging function
- `debug()`, `info()`, `warning()`, `error()`, `critical()`: Level-specific shortcuts
- `set_level(level, module=None)`: Set global or module-specific log level
- `set_module_level(level)`: Enable debug for current module (auto-detects module name)
- `configure_logging_from_dict(config_dict)`: Apply logging configuration

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
