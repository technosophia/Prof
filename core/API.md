<!-- /core/API.md -->

# Configuration System (`core/config.py`)
Centralized configuration management with dot-notation access. Automatically discovers and merges CONFIG_FILE files throughout the project directory structure. Supports test overrides when TEST_MODE is enabled.

**Exported functions:**
- `get_config()`: Access the global configuration object
- `get_section(prefix)`: Get module-specific configuration section
- `save_config(prefix, data)`: Save module configuration back to file

# Logging System (`core/logging.py`)
Simple, configurable logging with multiple severity levels and stack trace support. Integrates with the configuration system.

**Exported functions:**
- `log(level, message, *args, exc_info=False)`: Main logging function
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
