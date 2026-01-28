<a id="app"></a>

# app

[agent]
## Technical Specifications
The technical specifications are as follows:
- Code and comments are exclusively in English.
- The application is multilingual (French/English), managed via gettext.
- Function or class names are explicit.
- Standalone utility functions are grouped by theme in a "lib" directory.
- To determine if a function is a utility, ask the following question: Could it be useful in a completely different program, unrelated to the current specs? If yes, it's a utility function; if not, it belongs to a module.
- All configuration is stored in a JSON file separate from the code.
- Any value that can be changed without modifying the code and is not user data is placed in the configuration.
- All user data is stored in a database.
- Any key or information that should not be in the git repository is stored in a .env file, loaded at startup.
- Provide shell instructions for launching.
- All prompts are stored in a YAML file.
- The requirements.txt file does not contain version numbers.

Tests:
- Each main function from the specs has a non-regression test for its workflow.
- An initialization function creates a starting test dataset that is reset before running tests.

Modules:
- Every module is designed to be scalable and plug-and-play: the application must be able to run, even if diminished, if the module is absent.
- A module is a directory containing ALL files necessary for its operation (tests, configuration, prompts).
- A module injects into the application through injection points what allows it to function.
- The architecture is modular and scalable; all modules are in a "modules" directory.
- A module groups what is needed to code a semantic unit or a functional unit that uses semantic units.
- Each module contains a specification in its header.
- Each module has associated unit tests.
- A module contains: its translations (JSON), its prompts (YAML), its configuration (JSON), its tests (pytest), its display, its business logic, its libraries. Files are always the same from one module to another.
- A module must be independent of other modules, except for common functionalities.
- A module can have sub-modules and its own injection points, but the only dependencies are the parent module and the application's common functionalities. There must be no module that depends on multiple modules. It is a tree structure.

Common:
- Shared modules are in a dedicated "shared" directory to clearly separate them from removable modules; these modules cannot be disabled.
- The application provides injection points for modules for: translations, prompts and LLM calls, configuration, tests, display (side bar, main page, settings tab, user config).
- Everything common comes with a Mock for tests.

Planned Features:
- Base: multi-user, multilingual, multi-LLM, multi-conversation.
- MVP Features:
- RAG with different RAG engines, means to compare and debug them.
- Token stats: monitoring token usage per user.
- Learning path, level assessment through discussion rather than questionnaires.
- Additional Features:
- Retrieval of YouTube playlists and PDFs for importing RAG content.
- Metadata for RAG if necessary for the learning path.

<a id="shared.__init__"></a>

# shared.\_\_init\_\_

Module Development Guide: Config, Logging, Translation & LLM Systems

[agent]

## Overview

This application provides four core utilities that all modules can use: **configuration management**, **logging**, **translation**, and **LLM integration**. Each system is designed for simple one-line initialization and easy use throughout your modules.

## Important Initialization Order

**CRITICAL**: Always load configuration **BEFORE** importing other modules that depend on it:

```python
# CORRECT ORDER:
from shared.config import init_config, get_config
config = init_config("config.json")  # MUST BE FIRST

# Then import other modules
from shared.logging import log, configure_logging_from_dict
from shared.translate import init_translations_streamlit, _
from shared.llm import llm_generate, set_current_llm, get_available_llms

# Configure other systems
configure_logging_from_dict(config.get("logging", {}))
```

## 1. Configuration System (`shared/config.py`)

### Purpose
Centralized configuration management with module injection support. Loads from JSON files and supports nested configurations with duplicate checking.

### Key Functions

#### Initialization (in your module)
```python
from shared.config import init_config, inject_module_config, get_config

# Initialize main config (usually done once in app.py)
config = init_config("config.json")

# Inject module-specific config (one line)
inject_module_config("your_module_name", "path/to/your/config.json")
```

#### Using Configuration
```python
from shared.config import get_config

config = get_config()

# Get values with dot notation
log_level = config.get("logging.level", "INFO")
app_name = config.get("app.name")

# Set values
config.set("your_module.some_key", "value")

# Check if key exists
if "your_module.enabled" in config:
    # Do something
```

### Module Configuration File Example
Create `your_module/config.json`:
```json
{
    "your_module": {
        "enabled": true,
        "api_key": "your_key_here",
        "endpoint": "https://api.example.com"
    },
    "logging": {
        "your_module_level": "DEBUG"
    }
}
```

## 2. Logging System (`shared/logging.py`)

### Purpose
Simple, configurable logging with multiple levels and stack trace support. All logs are in English (not translated). Integrates with configuration system.

### Key Functions

#### Simple Logging (main way to log)
```python
from shared.logging import log

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

# Or use convenience functions
from shared.logging import debug, info, warning, error
info("Module started")
debug("Detailed debug info: %s", data)
```

#### Connecting to Configuration
```python
from shared.config import get_config
from shared.logging import configure_logging_from_dict

# Configure logging from config
config = get_config()
configure_logging_from_dict(config.get("logging", {}))
```

### Log Levels (from most to least verbose)
- `debug` - Detailed information for debugging
- `info` - General information about program execution
- `warning` - Potential issues that don't stop execution
- `error` - Serious problems that affect functionality
- `critical` - Critical errors that may cause program termination

### Configuration Example
```json
{
  "logging": {
    "level": "INFO",
    "format": "[{level}] {timestamp} - {message}",
    "include_traceback": true
  }
}
```

## 3. Translation System (`shared/translate.py`)

### Purpose
Multilingual support with module-specific translations. Uses simple `_()` function for translation lookups.

### Key Functions

#### For Regular Modules
```python
from shared.translate import _

# Simple translation
title = _("module_title")
description = _("module_description")

# Translation with parameters (use string formatting)
message = _("welcome_user").format(username=user_name)
```

#### For Streamlit Modules
```python
from shared.translate import init_translations_streamlit, _

# Initialize with Streamlit session support
translator = init_translations_streamlit("en", "translations")

# Use in Streamlit components
st.title(_("module_title"))
st.write(_("description"))
```

#### Adding Module Translations
```python
from shared.translate import get_translator

translator = get_translator()

# Method 1: Direct dictionary injection
translator.add_module_translations("your_module", {
    "en": {
        "module_title": "Your Module",
        "welcome": "Welcome to the module"
    },
    "fr": {
        "module_title": "Votre Module",
        "welcome": "Bienvenue dans le module"
    }
})

# Method 2: Load from directory structure
translator.inject_module_translations("your_module", "translations/your_module/")
```

### Translation File Structure
```
translations/
├── en.json
├── fr.json
└── your_module/
    ├── en.json
    └── fr.json
```

**`translations/en.json`:**
```json
{
    "hello_world": "Hello World!",
    "description": "Welcome to the application",
    "button_text": "Click here"
}
```

**`translations/fr.json`:**
```json
{
    "hello_world": "Bonjour le monde!",
    "description": "Bienvenue dans l'application",
    "button_text": "Cliquez ici"
}
```

## 4. LLM System (`shared/llm.py`)

### Purpose
Unified interface for multiple Large Language Models (Ollama, Gemini, Groq) with streaming support and configuration-based management.

### Key Functions

#### Initialization and Setup
```python
from shared.llm import llm_generate, set_current_llm, get_available_llms, get_current_llm_info

# LLM manager is automatically initialized with app config
# No manual initialization needed
```

#### Generating Responses
```python
import asyncio

# Simple text generation
response = await llm_generate("Hello, how are you?")
print(response)

# With streaming (real-time response)
def stream_callback(chunk):
    print(chunk, end="", flush=True)

response = await llm_generate("Tell me a story", stream_callback)
```

#### Managing LLMs
```python
# Get available LLMs
available_llms = get_available_llms()
for llm_info in available_llms:
    print(f"{llm_info['name']}: {llm_info['description']}")

# Switch LLM
success = set_current_llm("ollama_qwen")
if success:
    print("LLM switched successfully")

# Get current LLM info
current_llm = get_current_llm_info()
if current_llm:
    print(f"Current LLM: {current_llm['name']}")
```

### Configuration Example (`config.json`)
```json
{
  "app": {
    "name": "My App",
    "default_llm": "Qwen 3 4B",
    "version": "1.0.0"
  },
  "llms": {
    "ollama_qwen": {
      "type": "ollama",
      "model": "qwen3:4b",
      "name": "Qwen 3 4B",
      "enabled": true,
      "description": "Local Qwen model via Ollama",
      "requires_api_key": false
    },
    "gemini": {
      "type": "gemini",
      "model": "gemini-2.5-flash",
      "name": "Google Gemini",
      "enabled": true,
      "description": "Google's fast multimodal model",
      "requires_api_key": true
    },
    "groq": {
      "type": "groq",
      "model": "llama-3.3-70b-versatile",
      "name": "Groq Llama 3",
      "enabled": true,
      "description": "Fast inference via Groq",
      "requires_api_key": true
    }
  }
}
```

### Environment Variables
Create a `.env` file in your project root:
```bash
# Required for Gemini
GEMINI_API_KEY=your_gemini_api_key_here

# Required for Groq
GROQ_API_KEY=your_groq_api_key_here

# Optional: Custom Ollama URL
OLLAMA_BASE_URL=http://localhost:11434
```

## Best Practices

1. **Initialize in correct order**: Always load config first, then other systems
2. **Use async for LLM calls**: Always use `asyncio.run()` or async context for LLM operations
3. **Handle streaming properly**: Use callbacks for real-time response display
4. **Log errors with tracebacks**: Use `exc_info=True` for error logs to get stack traces
5. **Check LLM availability**: Verify `llm_info["available"]` before trying to use an LLM
6. **Use environment variables**: Keep API keys in `.env` file, not in code
7. **Validate configurations**: Ensure your `config.json` has all required fields
8. **Graceful error handling**: Always wrap LLM calls in try-except blocks

## Quick Reference

```python
# Most common imports
from shared.config import get_config
from shared.logging import log
from shared.translate import _
from shared.llm import llm_generate, set_current_llm

# Most common patterns
config = get_config()
log("info", "Message here")
translated_text = _("translation_key")
response = await llm_generate("Your prompt")
```

## Troubleshooting

### Common Issues

1. **"No available LLMs found"**: Check your `.env` file for missing API keys
2. **"cannot access local variable 'llm'"**: Avoid using `llm` as variable name in loops
3. **Configuration errors**: Ensure config is loaded before importing other modules
4. **Streaming not working**: Verify the LLM supports streaming and callback is defined
5. **Translation errors**: Check that translation files exist and keys match

### Debug Tips

1. Enable traceback in logging config: `"include_traceback": true`
2. Check LLM availability: `get_available_llms()` returns detailed status
3. Verify environment variables: Use debug section in Streamlit app
4. Monitor logs: All system operations are logged with appropriate levels

This integrated system allows each module to be self-contained with its own configuration, translations, logging, and LLM capabilities while seamlessly integrating with the main application.

<a id="shared.translate"></a>

# shared.translate

Translate helper function

[agent]
Streamlit-safe translation function.
Works with the translator in session state.
Must be imported like this : from shared.translate import _streamlit as _

<a id="shared.database"></a>

# shared.database

Unified database management with SQLAlchemy.
Supports both in-memory (for testing) and persistent storage.

[agent]
This module provides a singleton DatabaseManager for database operations.
Modules like users.py should inject this service rather than creating their own connections.

Public interface:
- db_manager: Global DatabaseManager instance
- Base: SQLAlchemy declarative base for models
- init_database(): Initialize database connection
- DatabaseManager.get_session(): Get database session (context manager)
- DatabaseManager.is_initialized(): Check if database is ready

Typical usage:
1. Call init_database() at application startup
2. Use db_manager.get_session() for database operations
3. Define models using Base as base class

<a id="shared.database.DatabaseManager"></a>

## DatabaseManager Objects

```python
class DatabaseManager()
```

Manages database connections and operations.

[agent]
Singleton class providing database services. Use the global db_manager instance.
Other modules should inject this service rather than creating their own connections.

Public methods:
- get_session(): Primary method for database access
- is_initialized(): Check if database is ready

Usage:
    # In another module like users.py
    from shared.database import db_manager

    if db_manager.is_initialized():
        with db_manager.get_session() as session:
            # Perform database operations

<a id="shared.database.DatabaseManager.is_initialized"></a>

#### is\_initialized

```python
def is_initialized()
```

Check if database is initialized.

[agent]
Returns True if database is ready for use.

Returns:
    bool: True if database engine is initialized

<a id="shared.database.DatabaseManager.get_session"></a>

#### get\_session

```python
@contextmanager
def get_session() -> Session
```

Get a database session with context manager.

[agent]
Primary method for database access. Provides automatic session management.
Commits on success, rolls back on exception.

Yields:
    sqlalchemy.orm.Session: Database session

Raises:
    RuntimeError: If database not initialized

Example (from users.py):
    with db_manager.get_session() as session:
        user = session.query(UserTable).filter_by(id=user_id).first()

<a id="shared.database.init_database"></a>

#### init\_database

```python
def init_database(use_memory: bool = False, db_path: Optional[str] = None)
```

Initialize the database.

[agent]
Initialize database connection. Must be called before any database operations.

Args:
    use_memory: Use in-memory database for testing (default: False)
    db_path: Path to database file (default: from config or "data/app.db")

Returns:
    DatabaseManager: Initialized database manager

Example:
    # At application startup
    init_database(use_memory=False, db_path="data/myapp.db")

<a id="shared.ui_registry"></a>

# shared.ui\_registry

UI Registry System

[agent]

Provides a modular UI injection system for Streamlit applications. UI modules
can register render functions that are automatically discovered and injected
into predefined injection points.

Module Discovery:
- Discovers UI modules from shared/*_ui.py files
- Discovers UI modules from modules/*/*_ui.py files (subdirectories within modules)

Naming Conventions:
- Module files must end with _ui.py
- Render functions can use either pattern:
  1. Direct injection point names: sidebar(), main_header(), etc.
  2. Namespaced pattern: modulename_render_injectionpoint()

Injection Points:
- sidebar: Content injected into the sidebar
- main_header: Content injected into the main header area
- main_before_conversation: Content injected before conversation interface
- main_content: Content injected when no user is logged in
- main_after_conversation: Content injected after conversation interface

Module Requirements:
1. Must be placed in shared/ or modules/*/ directories
2. Must have filename ending with _ui.py
3. Must define at least one render function matching an injection point
4. Render functions must be callable and return a value

Registry Initialization:
Automatically initialized and cached in Streamlit session state.
No manual initialization required in modules.

<a id="shared.module_handler"></a>

# shared.module\_handler

Module Handler

[agent]
Provides module discovery, activation, and management for the application.
Scans ./modules directory to detect modules and allows loading them or not,
depending on the configuration. Module activation status is stored in modules.json.

Key Features:
- Auto-discovers modules in the modules/ directory
- Loads module configuration from module.json files
- Manages activation status in modules.json
- Provides toggle functionality for modules
- Integrates with UI registry for selective module loading

Module Requirements:
1. Must be placed in modules/ directory as a subdirectory
2. Must contain a module.json file with metadata
3. UI modules should follow *_ui.py naming convention
4. Can include config.json for module-specific configuration

Module JSON Structure:
```json
{
    "name": "module_name",
    "version": "1.0.0",
    "description": "Module description",
    "author": "Author name",
    "enabled_by_default": true,
    "category": "category",
    "dependencies": []
}
```
