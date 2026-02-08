"""
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
"""



import streamlit as st
import os, sys
from typing import Optional, Dict, List, Tuple, Any
from core.logging import log as _log, configure_logging_from_dict as _configure_logging_from_dict
from core.translate import load_all_translations, get_translation
from core.config import load_all_configs, Config
from core.database import Base as _Base, get_db_manager as _get_db_manager, init_database as _init_database
from .users import UserRole as _UserRole, get_user_manager as _get_user_manager
from .conversation import Message as _Message, get_conversation_manager as _get_conversation_manager


# Translation

@st.cache_resource
def _load_translations() -> dict[str, dict[str, str]]:
    """Load all translations once and cache them globally."""
    return load_all_translations()


def get_available_languages() -> list[str]:
    """Return sorted list of available language codes."""
    translations = _load_translations()
    return sorted(translations.keys())


def _(key: str, lang: str | None = None) -> str:
    """
    Central translation function.
    Uses per-session current language from st.session_state.
    """
    if lang is None:
        # Ensure a language is always set in session state
        if "current_language" not in st.session_state:
            st.session_state.current_language = "en"
        lang = st.session_state.current_language

    translations = _load_translations()
    return get_translation(key, lang, translations)

# logging

log = _log
configure_logging_from_dict = _configure_logging_from_dict

# Configuration

@st.cache_resource
def _load_config() -> Config:
    """Cached loading of the full configuration."""
    # Determine project root (shared/common.py → shared → root)
    shared_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(shared_dir)

    test_mode = os.getenv("TEST_MODE") == "true" or "pytest" in sys.modules
    return load_all_configs(root_dir, test_mode)


def get_config() -> Config:
    """Primary way to access configuration from anywhere."""
    return _load_config()


def get_section(prefix: str = "") -> dict:
    """Convenient wrapper for module-specific sections."""
    return get_config().get_section(prefix)


def save_config(prefix: str = "", data: dict | None = None) -> bool:
    """Convenient wrapper to save a module/section back to its config.json."""
    if data is None:
        raise ValueError("save_config requires the data dict to save")
    return get_config().save_section(prefix, data)


# Database

Base = _Base
UserRole = _UserRole
init_database = _init_database

@st.cache_resource
def get_db_manager():
    return _get_db_manager()

# Users

@st.cache_resource
def get_user_manager():
    return _get_user_manager()

def init_user_manager(create_default_users: bool = True):
    """Initialize the user manager."""
    if create_default_users and get_user_manager().db.is_initialized():
        get_user_manager().init_default_users()
    return get_user_manager()


def get_all_users() -> Dict[str, Dict[str, Any]]:
    """Backward compatibility alias."""
    return get_user_manager().get_all_users_dict()

# Conversations

Message = _Message

@st.cache_resource
def get_conversation_manager():
    return _get_conversation_manager()

def cleanup_user_conversations(user_id: str) -> bool:
    """Cleanup all conversations for a user before deletion."""
    try:
        # Get all conversations for this user
        with get_conversation_manager().db.get_session() as session:
            # Delete all messages from user's conversations
            conversations = session.query(ConversationTable).filter_by(user_id=user_id).all()

            for conv in conversations:
                # Delete all messages in this conversation
                session.query(MessageTable).filter_by(conversation_id=conv.id).delete()

            # Delete all conversations for this user
            session.query(ConversationTable).filter_by(user_id=user_id).delete()

            log("info", f"Cleaned up conversations for user {user_id}: "
                       f"{len(conversations)} conversations deleted")
            return True
    except Exception as e:
        log("error", f"Failed to cleanup conversations for user {user_id}: {e}")
        return False

# Register the cleanup callback with user_manager
get_user_manager().register_before_delete_callback(cleanup_user_conversations)
