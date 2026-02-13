"""
Module Development Guide: Config, Logging, Translation, Database, Users, Conversations, LLM, Prompts & Settings

[agent]
## Core Systems

### Configuration System (`core/config.py`)
Centralized configuration management with dot-notation access. Automatically discovers and merges config.json files throughout the project directory structure. Supports test overrides when TEST_MODE is enabled.

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
- `llm_generate()` / `llm()`: Generate response from current LLM
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
"""



import streamlit as st
import os, sys
from typing import Optional, Dict, List, Tuple, Any, Callable
from core.logging import log as _log, configure_logging_from_dict as _configure_logging_from_dict
from core.translate import load_all_translations, get_translation
from core.config import load_all_configs, Config, _load_config
from core.database import Base as _Base, get_db_manager as _get_db_manager, init_database as _init_database
from .users import UserRole as _UserRole, get_user_manager as _get_user_manager
from .conversation import Message as _Message, get_conversation_manager as _get_conversation_manager
from .prompt_manager import get_prompt_manager as _get_prompt_manager, load_all_prompts as _load_all_prompts
from .prompt_manager import is_multilingual as _is_multilingual, set_default_language as _set_default_language
from .settings import UserSettingsManager
from .llm import LLMManager


# Translation ================================================================

@st.cache_resource
def _load_translations() -> dict[str, dict[str, str]]:
    """Load all translations once and cache them globally."""
    return load_all_translations()


def get_available_languages() -> list[str]:
    """Return sorted list of dynamic available language codes."""
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

# Configuration ================================================

@st.cache_resource
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


# Database =====================================================

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

# Conversations ================================================

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

# LLM ==========================================================

@st.cache_resource
def get_llm_manager():
    """Get or create the global LLMManager instance."""
    return LLMManager(get_config())

# Update public functions with backward compatibility
async def llm_generate(message: str,
                      stream_callback: Optional[Callable] = None,
                      conversation_history: Optional[List[Dict]] = None,
                      user_id: Optional[str] = None) -> str:  # Added user_id parameter
    """Simple interface to generate response from current LLM with conversation history."""
    manager = get_llm_manager()
    return await manager.generate(message, stream_callback, conversation_history, user_id)

def set_current_llm(llm_id: str) -> bool:
    """Set the current LLM to use."""
    manager = get_llm_manager()
    return manager.set_current_llm(llm_id)

def get_available_llms() -> List[Dict[str, Any]]:
    """Get list of available LLMs."""
    manager = get_llm_manager()
    return manager.get_available_llms()

def get_current_llm_info() -> Optional[Dict[str, Any]]:
    """Get information about the current LLM."""
    manager = get_llm_manager()
    return manager.get_current_llm_info()

def get_current_llm_id() -> str:
    """
    Get the ID of the currently configured LLM.

    Returns:
        str: The ID of the current LLM

    Raises:
        ValueError: If no LLM is configured or available
    """
    try:
        current_llm_info = get_current_llm_info()
        if current_llm_info:
            # Try to get ID from the info dictionary
            llm_id = current_llm_info.get('id')
            if llm_id:
                return str(llm_id)

        # Fallback: check the LLM manager directly
        manager = get_llm_manager()
        if manager.current_llm:
            return str(manager.current_llm)

    except Exception as e:
        raise ValueError(f"Failed to get current LLM ID: {e}")

    raise ValueError("No LLM is currently configured or available")

def get_llm_by_name(name: str) -> Optional[Dict[str, Any]]:
    """Get LLM information by name."""
    manager = get_llm_manager()
    return manager.get_llm_by_name(name)

def register_llm_callback(callback_func: Callable[[str, List[Dict]], str]):
    """Register a callback to add LLM context to LLM queries."""
    manager = get_llm_manager()
    manager.register_llm_callback(callback_func)

def unregister_llm_callback(callback_func: Callable[[str, List[Dict]], str]):
    """Unregister a LLM callback."""
    manager = get_llm_manager()
    manager.unregister_llm_callback(callback_func)

def register_llm_context_callback(callback_func: Callable[[str, List[Dict]], Tuple[str, str, str]]):
    """Register a callback to add LLM context to LLM queries.
    The callback should return a tuple: (context, role, position)
    where:
      - context: string to add as context
      - role: "system" or "user"
      - position: "top" or "bottom"""
    manager = get_llm_manager()
    manager.register_context_callback(callback_func)

def unregister_llm_context_callback(callback_func: Callable[[str, List[Dict]], Tuple[str, str, str]]):
    """Unregister a LLM callback."""
    manager = get_llm_manager()
    manager.unregister_context_callback(callback_func)

# Alias for backward compatibility - maintains old interface
llm = llm_generate


# Prompt Management ============================================

is_multilingual = _is_multilingual
set_default_language = _set_default_language

@st.cache_resource
def _init_prompt_manager():
    """Initialize and load all prompts."""
    shared_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(shared_dir)
    _load_all_prompts(root_dir)
    return _get_prompt_manager()

def get_prompt_manager():
    """Get the prompt manager instance."""
    return _init_prompt_manager()

def get_prompt(key: str, default: Any = None, language: Optional[str] = None) -> Any:
    """
    Get a prompt by key using dot notation.

    Args:
        key: Dot-separated key (e.g., 'rag_manager.search_prompt')
        default: Default value if key not found
        language: Language code for multilingual mode (e.g., 'en', 'fr')

    Returns:
        Prompt value or default
    """
    return get_prompt_manager().get_prompt(key, default, language)

def get_all_prompts(language: Optional[str] = None) -> Dict[str, Any]:
    """Get all loaded prompts."""
    return get_prompt_manager().get_all_prompts(language)

def get_module_prompts(module_prefix: str = "", language: Optional[str] = None) -> Dict[str, Any]:
    """Get prompts for a specific module."""
    return get_prompt_manager().get_module_prompts(module_prefix, language)

def list_modules_with_prompts(language: Optional[str] = None) -> List[str]:
    """List all module prefixes with prompts."""
    return get_prompt_manager().list_modules(language)

def get_available_prompt_languages() -> List[str]:
    """Get list of dynamic available languages."""
    return get_prompt_manager().get_available_languages()

# User Settings =============================================

@st.cache_resource
def get_user_settings_manager():
    """Get or create the user settings manager."""
    return UserSettingsManager()
