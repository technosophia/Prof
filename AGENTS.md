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

Common & Core:
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

Modules that ends with *_ui.py can implement the following injection points by creating functions with the pattern `inject_ui_[injection_point]()` in a `*_ui.py` file:

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

Unified database management with SQLAlchemy and Alembic migrations.
Supports both in-memory (for testing) and persistent storage with automatic schema migrations.

This module provides a singleton DatabaseManager for database operations.
Now with integrated Alembic migration support.

Public interface:
- db_manager: Global DatabaseManager instance
- Base: SQLAlchemy declarative base for models
- init_database(): Initialize database connection and run migrations
- DatabaseManager.get_session(): Get database session (context manager)
- DatabaseManager.check_and_upgrade_schema(): Run pending migrations

[agent]
Unified database management with SQLAlchemy.
BECAREFUL : internal module. Use shared.common for imports, not core.database

This module provides a singleton DatabaseManager and SQLAlchemy declarative Base
for applications to define their own database models that integrate with the main
database system.

===========================================================================
DEFINING CUSTOM TABLES
===========================================================================

1. Import the Base class from this module:

   from core.database import Base

2. Define your model class inheriting from Base:

   class MyTable(Base):
       __tablename__ = 'my_table'

       id = Column(String, primary_key=True)
       name = Column(String, nullable=False)
       # ... other columns

3. Tables are automatically created on application startup via init_database().
   No manual creation or migration handling is needed.

===========================================================================
DATABASE ACCESS
===========================================================================

Get the global database manager and use session context manager:

   from core.database import get_db_manager

   db = get_db_manager()
   with db.get_session() as session:
       result = session.query(MyTable).all()
       session.add(my_object)

The session automatically commits on success, rolls back on error.

===========================================================================
PUBLIC INTERFACE
===========================================================================

- Base: SQLAlchemy declarative base - inherit this for all custom tables
- get_db_manager(): Returns the singleton DatabaseManager instance
- init_database(): Initialize database connection (called by app startup)
- DatabaseManager.get_session(): Context manager for database sessions

===========================================================================
NOTE
===========================================================================

- All tables inheriting from Base are automatically detected and created
- For persistent databases, schema changes are handled via Alembic migrations
- In-memory database (:memory:) is automatically used for testing
- Always use get_session() context manager - never manage sessions manually

<a id="shared.common"></a>

# shared.common

Module Development Guide: Config, Logging, Translation, Database, Users, Conversations, LLM, Prompts & Settings

[agent]
## Core Systems

### Configuration System (`core/config.py`)
Centralized configuration management with dot-notation access. Automatically discovers and merges CONFIG_FILE files throughout the project directory structure. Supports test overrides when TEST_MODE is enabled.

**Exported functions:**
- `get_config()`: Access the global configuration object
- `get_section(prefix)`: Get module-specific configuration section
- `save_config(prefix, data)`: Save module configuration back to file

### Logging System (`core/logging.py`)
Simple, configurable logging with multiple severity levels and stack trace support. Integrates with the configuration system.

**Exported functions:**
- `log(level, message, *args, exc_info=False)`: Main logging function
- `configure_logging_from_dict(config_dict)`: Apply logging configuration

### Translation System (`core/translate.py`)
Multi-language support with JSON-based translation files. Automatically loads all translation files from 'translations' directories throughout the project.

**Exported functions:**
- `_(key, lang=None)`: Main translation function (uses session language)
- `get_available_languages()`: List all loaded language codes

### Database System (`core/database.py`)
SQLAlchemy-based database management with singleton pattern. Supports both in-memory (testing) and persistent SQLite databases.

**Exported components:**
- `Base`: SQLAlchemy declarative base for model definitions
- `init_database()`: Initialize database connection
- `get_db_manager()`: Access the global database manager
- `db_manager.get_session()`: Get database session (context manager)
- `db_manager.empty_all_tables()`: Clear all table data

## Shared Systems

### User Management System (`shared/users.py`)
Built-in user authentication and role-based access control with database persistence. Supports hierarchical user relationships (ADMIN, MASTER, NORMAL).

**Exported components:**
- `UserRole`: Enum for user permissions
- `get_user_manager()`: Access user management singleton
- `init_user_manager()`: Initialize with default users
- `get_all_users()`: Get all users as dictionary
- Automatic cleanup callbacks for user deletion

### Conversation Management System (`shared/conversation.py`)
Stores and manages user conversations with LLM interactions. Supports multiple conversations per user with full message history.

**Exported components:**
- `Message`: Conversation message model
- `get_conversation_manager()`: Access conversation management
- `cleanup_user_conversations()`: Cleanup conversations before user deletion
- Automatic cleanup when users are deleted

### LLM Management System (`shared/llm.py`)
Manages multiple LLM providers and models with unified interface. Supports streaming, conversation history, and context injection.

**Exported functions:**
- `get_llm_manager()`: Get global LLM manager instance
- `llm_conversation_generate()` / `llm()`: Generate response from current LLM
- `set_current_llm()`: Switch active LLM
- `get_available_llms()`: List all configured LLMs
- `get_current_llm_info()`: Get current LLM details
- `get_current_llm_id()`: Get current LLM identifier
- `get_llm_by_name()`: Find LLM by name
- `register_llm_callback()`: Register context generation callback - legacy
- `unregister_llm_callback()`: Remove context callback - legacy
- `register_llm_context_callback()`: Register structured context callback
- `unregister_llm_context_callback()`: Remove structured context callback

### Prompt Management System (`shared/prompt_manager.py`)
Centralized prompt management with dot-notation access. Automatically discovers and merges prompts.yaml files throughout the project. Supports multilingual prompts.

**Exported functions:**
- `get_prompt()`: Get prompt by key using dot notation
- `get_all_prompts()`: Get all loaded prompts
- `get_module_prompts()`: Get prompts for a specific module
- `list_modules_with_prompts()`: List all modules with prompts
- `get_available_prompt_languages()`: List dynamic available languages
- `is_multilingual()`: Check if multilingual mode is enabled
- `set_default_language()`: Set default prompt language
- `get_prompt_manager()`: Access prompt manager instance

### User Settings System (`shared/settings.py`)
Manages user-specific configuration and preferences with database persistence.

**Exported functions:**
- `get_user_settings_manager()`: Access user settings manager

## Best Practices Quick Reference

1. **Import from common.py only**: Never import directly from core/shared modules
2. **Initialize in order**: Config → Logging → Database → Other systems
3. **Use session state for language**: Translation uses `st.session_state.current_language`
4. **Always use db sessions as context managers**: `with get_db_manager().get_session() as session:`
5. **Log errors with tracebacks**: Use `exc_info=True` for error logs
6. **Test with in-memory database**: Use `init_database(use_memory=True)` in tests
7. **Cleanup test data**: Use `db_manager.empty_all_tables()` between tests
8. **Cache singletons**: All managers use `@st.cache_resource` for global state

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
from shared.common import llm_conversation_generate, set_current_llm, get_available_llms, get_current_llm_info

# LLM manager is automatically initialized with app config
# No manual initialization needed
```

#### Generating Responses
```python
import asyncio

# Simple text generation
response = await llm_conversation_generate("Hello, how are you?")
print(response)

# With streaming (real-time response)
def stream_callback(chunk):
    print(chunk, end="", flush=True)

response = await llm_conversation_generate("Tell me a story", stream_callback)
```

### Context injection
Any module can inject context in the current conversation. It will be added at the end of the history
```
 from shared.common import register_llm_callback, unregister_llm_callback

def inject_current_time_context(user_id: str, messages: List[Dict]) -> str:
    from datetime import datetime
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"Current time: {current_time}"

# Register the callback (typically during initialization)
register_llm_callback(inject_current_time_context)
```

### Enhanced Context Injection
Any module can inject context with more control over placement and role
```
from shared.common import register_context_callback, unregister_context_callback

def inject_weather_context(user_id: str, messages: List[Dict]) -> tuple:
    weather = get_current_weather()
    return weather, "system", "top"  # context, role, position

# Register the enhanced callback
register_context_callback(inject_weather_context)
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
- Auto-discovery of translations and prompts
- Auto-discovery of injection points for UI integration with main App

Module Requirements:
1. Must be placed in modules/ directory as a subdirectory
2. Must contain a module.json file with metadata
3. UI modules should follow *_ui.py naming convention and inject_ui_xxx for UI integration with main App
4. Can include CONFIG_FILE for module-specific configuration
5. Can include translation/xx.json for language-specific translations
6. Can include prompts.xx.json for language-specific prompts
7. Can include tests in the test/ directory for pytest automatic testing

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

<a id="shared.users"></a>

# shared.users

User management with database backend.

[agent]

## User objets
User object structure returned by UserManager.get_user() and similar methods:

{
    "id": str,                          # Unique user identifier (UUID or predefined)
    "name": str,                        # Full name, must not be empty
    "email": Optional[str],             # Email address, can be null
    "role": str,                       # One of: "admin", "master", "normal"
    "parent_id": Optional[str],        # ID of parent user (required for normal users, must be master)
    "created_at": Optional[str],       # ISO 8601 datetime string, null if not set
    "last_login": Optional[str],       # ISO 8601 datetime string, null if never logged in
    "is_active": bool,                # Whether user account is active (default: True)
    "profile": Dict[str, Any],        # User preferences (includes language: str with 2-letter code)
    "metadata": Dict[str, Any],       # System metadata (creation source, defaults, etc.)
    "parent_name": Optional[str],     # Display name of parent user, null if no parent
    "children": Optional[List[Dict]]  # Only when include_children=True: recursive list of child users
}

Role hierarchy:
- ADMIN: System administrators, can manage all users
- MASTER: Can manage themselves and their direct children (normal users)
- NORMAL: Regular users, must have a master as parent, can only see themselves

This structure is JSON-serializable and used consistently across get_user(),
get_all_users(), search_users(), and similar methods.

<a id="shared.conversation"></a>

# shared.conversation

Conversation management with database backend.
Handles multiple conversations per user with LLM interactions.

[agent]

## Conversation objects
Conversation object structure returned by ConversationManager.get_conversation():

{
    "id": str,                          # Unique conversation identifier (UUID)
    "user_id": str,                     # ID of the user who owns the conversation
    "title": str,                      # Conversation title, cannot be empty
    "created_at": str,                 # ISO 8601 datetime string of creation
    "updated_at": str,                # ISO 8601 datetime string of last update
    "is_active": bool,               # Whether conversation is active (soft delete flag)
    "metadata": Dict[str, Any],      # Conversation metadata (created_via, etc.)
    "system_prompt": Optional[str],  # Custom system prompt for this conversation
    "llm_config": Dict[str, Any],   # LLM configuration used (model, temperature, etc.)
    "messages": List[Dict]          # Array of message objects (empty if include_messages=False)
}

Message object structure within the messages array:

{
    "role": str,                    # One of: "user", "assistant", "system"
    "content": str,                # Message content/body
    "timestamp": str,             # ISO 8601 datetime string
    "tokens": Optional[int],      # Token count for this message (if tracked)
    "llm_id": Optional[str],     # ID of the LLM that generated this message (assistant only)
    "metadata": Dict[str, Any]   # Message metadata (empty dict if none)
}

Related conversation summary (get_conversation_summary()):
{
    "id": str,                    # Conversation ID
    "title": str,               # Conversation title
    "message_count": int,       # Total number of messages
    "total_tokens": int,       # Sum of tokens across all messages
    "created_at": str,        # ISO 8601 creation timestamp
    "updated_at": str,        # ISO 8601 last update timestamp
    "llm_usage": Dict[str, int],  # Map of LLM IDs to message counts
    "last_user_message": Optional[str],  # Content of most recent user message
    "metadata": Dict[str, Any]  # Conversation metadata
}

User conversations list (get_user_conversations()):
{
    "id": str,                    # Conversation ID
    "user_id": str,             # Owner user ID
    "title": str,              # Conversation title
    "created_at": str,        # ISO 8601 creation timestamp
    "updated_at": str,        # ISO 8601 last update timestamp
    "is_active": bool,       # Active status
    "message_count": int,    # Number of messages in conversation
    "last_message_at": Optional[str],  # ISO 8601 of most recent message
    "system_prompt": Optional[str],    # Custom system prompt
    "llm_config": Dict[str, Any],      # LLM configuration
    "metadata": Dict[str, Any]         # Conversation metadata
}
