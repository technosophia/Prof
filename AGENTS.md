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
- Training : follow user progression, learning path, level assessment through discussion rather than questionnaires.
- Additional Features:
- Retrieval of YouTube playlists and PDFs for importing RAG content.

## UI Injection Points

Modules can implement the following injection points by creating functions with the pattern `inject_ui_[injection_point]()` in a `*_ui.py` file:

### Core Application Flow
- `initialize`: Called once at app startup for initializing session state and module setup. No UI expected.
- `sidebar`: Content injected into the main sidebar. Use `st.*` functions to render UI elements.
- `main_header`: Content injected at the top of the main content area (chat page).
- `main_before_conversation`: Content injected before the conversation interface on chat page.
- `main_content`: Content injected when no user is logged in (fallback content).
- `main_after_conversation`: Content injected after the conversation interface on chat page.
- `main_footer`: Content injected at the bottom of the main content area.
- `settings_content`: Content injected into the user settings page when a user is logged in.

### Admin Interface
- `admin_tab`: Returns a tuple `(tab_name: str, render_function: callable)` to create admin tabs. The render function should contain `st.*` calls for the tab content.

### Usage Examples:
1. **For sidebar integration:**
   ```python
   def inject_ui_sidebar():
       st.subheader("My Module")
       if st.button("Do something"):
           st.write("Clicked!")
   ```

2. **For admin tab integration:**
   ```python
   def inject_ui_admin_tab():
       def render_my_admin_tab():
           st.header("My Admin Panel")
           st.write("Admin content here")
       return ("My Module", render_my_admin_tab)
   ```

3. **For settings integration:**
   ```python
   def inject_ui_settings_content():
       st.subheader("Module Settings")
       option = st.selectbox("Choose option", ["A", "B", "C"])
   ```

### Location Requirements:
- UI modules must be placed in `shared/` or `modules/[module_name]/` directories
- File names must end with `_ui.py` (e.g., `my_module_ui.py`)
- Functions must be named exactly `inject_ui_[injection_point]()`
- Functions should use Streamlit commands (`st.button`, `st.write`, etc.) to render content

### Notes:
- Each injection point can be implemented by multiple modules
- Modules can implement multiple injection points
- The registry automatically discovers and caches all UI modules
- Order of execution within an injection point is not guaranteed (use dependencies if needed)
- Modules only appear if their parent module is active (except shared modules which are always active)

<a id="core.database"></a>

# core.database

Unified database management with SQLAlchemy.
Supports both in-memory (for testing) and persistent storage.

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

[agent]
## Creating User-Linked Persistent Data
When adding new persistent data linked to users (e.g., user preferences, user history), follow this pattern:

### 1. Define Your Model
```python
from core.database import Base
from sqlalchemy import Column, String, ForeignKey, DateTime, JSON
from datetime import datetime

class UserPreferenceTable(Base):
    __tablename__ = 'user_preferences'

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey('users.id'), nullable=False, index=True)
    preference_type = Column(String, nullable=False)
    preference_data = Column(JSON, default={})
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

### 2. Register Cleanup Callback
To automatically clean up user data when a user is deleted, register a cleanup function:

```python
def cleanup_user_preferences(user_id: str) -> bool:
    try:
        with get_db_manager().get_session() as session:
            session.query(UserPreferenceTable).filter_by(user_id=user_id).delete()
            log("info", f"Cleaned up preferences for user {user_id}")
            return True
    except Exception as e:
        log("error", f"Failed to cleanup preferences: {e}")
        return False

# Register with user manager
get_user_manager().register_before_delete_callback(cleanup_user_preferences)
```

### 3. Access User-Linked Data
Always query by user_id to respect permission boundaries:

```python
with get_db_manager().get_session() as session:
    preferences = session.query(UserPreferenceTable).filter_by(user_id=current_user_id).all()
```

**Note**: Tables are automatically created via `Base.metadata.create_all()` when `init_database()` is called.

<a id="core.database.DatabaseManager"></a>

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
- empty_all_tables(): Remove all records from all tables (preserves table structure)

Usage:
    # In another module like users.py
    from core.database import db_manager

    if db_manager.is_initialized():
        with db_manager.get_session() as session:
            # Perform database operations

<a id="core.database.DatabaseManager.is_initialized"></a>

#### is\_initialized

```python
def is_initialized()
```

Check if database is initialized.

[agent]
Returns True if database is ready for use.

Returns:
    bool: True if database engine is initialized

<a id="core.database.DatabaseManager.dispose"></a>

#### dispose

```python
def dispose()
```

Dispose of database connections and reset manager state.

[agent]
Properly closes all database connections and resets the manager.
Critical for test isolation - call between tests to prevent file locks.

Usage:
    # Between tests
    if db_manager.is_initialized():
        db_manager.dispose()

<a id="core.database.DatabaseManager.get_session"></a>

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

<a id="core.database.DatabaseManager.empty_all_tables"></a>

#### empty\_all\_tables

```python
def empty_all_tables()
```

Remove all records from all tables while preserving table structure.

[agent]
Useful for testing or resetting application state. This method deletes all
data from every table but keeps the tables themselves intact.

Warning: This is a destructive operation and should be used with caution.
Not recommended for production use unless absolutely necessary.

Returns:
    bool: True if successful, False otherwise

Example:
    # Reset database for testing
    db_manager.empty_all_tables()

<a id="core.database.init_database"></a>

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

<a id="shared.common"></a>

# shared.common

Module Development Guide: Config, Logging, Translation & Database Systems

[agent]
## Configuration System (`core/config.py`)
Centralized configuration management with dot-notation access. Automatically discovers and merges config.json files throughout the project directory structure. Supports test overrides when TEST_MODE is enabled.

Key functions:
- `get_config()`: Access the global configuration object
- `get_section(prefix)`: Get module-specific configuration section
- `save_config(prefix, data)`: Save module configuration back to file

Usage:
```python
config = get_config()
db_path = config.get("database.path")
module_config = get_section("modules.my_module")
```

## Logging System (`core/logging.py`)
Simple, configurable logging with multiple severity levels and stack trace support. Integrates with the configuration system.

Key functions:
- `log(level, message, *args, exc_info=False)`: Main logging function
- Convenience functions: `debug()`, `info()`, `warning()`, `error()`, `critical()`
- `configure_logging_from_dict(config_dict)`: Apply logging configuration

Usage:
```python
log("info", "Module initialized")
error("Failed to connect: %s", error_msg, exc_info=True)
debug("Processing item %d", item_id)
```

## Translation System (`core/translate.py`)
Multi-language support with JSON-based translation files. Automatically loads all translation files from 'translations' directories throughout the project.

Key functions:
- `_(key, lang=None)`: Main translation function (uses session language)
- `get_available_languages()`: List all loaded language codes

Usage:
```python
# Uses current session language
title = _("welcome_message")
# Force specific language
title_en = _("welcome_message", "en")
```

## Database System (`core/database.py`)
SQLAlchemy-based database management with singleton pattern. Supports both in-memory (testing) and persistent SQLite databases.

Key imports:
- `Base`: SQLAlchemy declarative base for model definitions

Key functions:
- `init_database()`: Initialize database connection (use in-memory for tests)
- `get_db_manager()`: Access the global database manager
- `db_manager.get_session()`: Get database session (context manager)
- `db_manager.empty_all_tables()`: Clear all table data (preserves structure)

Usage:
```python
# Define models
class MyModel(Base):
    __tablename__ = "my_table"

# Initialize database
init_database()

# Use database session
with get_db_manager().get_session() as session:
    items = session.query(MyModel).all()
```

## User Management System (`shared/users.py`)
Built-in user authentication and role-based access control with database persistence. Supports hierarchical user relationships.

Key imports:
- `UserRole`: Enum for user permissions (ADMIN, MASTER, NORMAL)

Key functions:
- `get_user_manager()`: Access user management singleton
- `init_user_manager()`: Initialize with default users
- `get_all_users()`: Get all users as dictionary

User hierarchy:
- ADMIN: Full system access
- MASTER: Can manage their NORMAL users
- NORMAL: Regular users with parent MASTER

Usage:
```python
# Check user authentication
if get_user_manager().authenticate(username, password):
    user = get_user_manager().get_user(username)
    # Check permissions
    if user.role == UserRole.ADMIN:
        # Admin actions
```

## Conversation Management System (`shared/conversation.py`)
Stores and manages user conversations with LLM interactions. Supports multiple conversations per user with full message history.

Key imports:
- `Message`: Conversation message model with role, content, timestamp

Key functions:
- `get_conversation_manager()`: Access conversation management
- Automatic cleanup of user conversations when users are deleted

Usage:
```python
# Get user's conversations
manager = get_conversation_manager()
conversations = manager.get_user_conversations(user_id)

# Add new message
manager.add_message(conversation_id, Message(role="user", content="Hello"))
```

## Best Practices Quick Reference

1. **Import from common.py only**: Never import directly from core modules
2. **Initialize in order**: Config → Logging → Database → Other systems
3. **Use session state for language**: Translation uses `st.session_state.current_language`
4. **Always use db sessions as context managers**: `with get_db_manager().get_session() as session:`
5. **Log errors with tracebacks**: Use `exc_info=True` for error logs
6. **Test with in-memory database**: Use `init_database(use_memory=True)` in tests
7. **Cleanup test data**: Use `db_manager.empty_all_tables()` between tests

<a id="shared.llm"></a>

# shared.llm

LLM Manager using plugin-based engine system.

[agent]
## LLM System (`shared/llm.py`)

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

### Context injection
Any module can inject context in the current conversation. It will be added at the end of the history
```
 from shared.llm import register_llm_callback, unregister_llm_callback

def inject_current_time_context(user_id: str, messages: List[Dict]) -> str:
    from datetime import datetime
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"Current time: {current_time}"

# Register the callback (typically during initialization)
register_llm_callback(inject_current_time_context)
```

<a id="shared.module_handler"></a>

# shared.module\_handler

Module Handler

[agent]
Provides module discovery, activation, and management for the application.
Scans ./modules directory to detect modules and allows loading them or not,
depending on the configuration. Module activation status is stored in modules.json.

Key Features:
- Auto-discovers modules in the modules/ directory (cached for efficiency)
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

