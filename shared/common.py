# /shared/common.py

import os, sys
from typing import Optional, Dict, List, Tuple, Any, Callable
import streamlit as st
from core.logging import log as _log, configure_logging_from_dict as _configure_logging_from_dict
from core.translate import get_translation
from core.config import load_all_configs
from core.database import Base as _Base, init_database as _init_database
from .users import UserRole as _UserRole
from .conversation import Message as _Message
from .conversation import UserMessageCallback
from .prompt_manager import load_all_prompts as _load_all_prompts
from .prompt_manager import is_multilingual as _is_multilingual, set_default_language as _set_default_language
from .cached import (
    _load_translations,
    get_config,
    get_db_manager,
    get_user_manager,
    get_conversation_manager,
    get_llm_manager,
    get_prompt_manager,
    get_user_settings_manager,
)


# Translation ================================================================

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

def get_section(prefix: str = "") -> dict:
    """Convenient wrapper for module-specific sections."""
    return get_config().get_section(prefix)


def save_config(prefix: str = "", data: dict | None = None) -> bool:
    """Convenient wrapper to save a module/section back to its CONFIG_FILE."""
    if data is None:
        raise ValueError("save_config requires the data dict to save")
    return get_config().save_section(prefix, data)


# Database =====================================================

Base = _Base
UserRole = _UserRole
init_database = _init_database

# Users

def init_user_manager(create_default_users: bool = True):
    """Initialize the user manager."""
    if create_default_users and get_user_manager().db.is_initialized():
        get_user_manager().init_default_users()
    return get_user_manager()


def get_all_users() -> Dict[str, Dict[str, Any]]:
    """Backward compatibility alias."""
    return get_user_manager().get_all_users_dict()

# Conversations ================================================

from shared.conversation import ConversationTable, MessageTable

Message = _Message

def register_user_message_callback(callback: UserMessageCallback) -> None:
    """Register a callback to be triggered when a user message is added."""
    get_conversation_manager().register_user_message_callback(callback)

def unregister_user_message_callback(callback: UserMessageCallback) -> bool:
    """Unregister a user message callback."""
    return get_conversation_manager().unregister_user_message_callback(callback)

def clear_user_message_callbacks() -> None:
    """Remove all registered user message callbacks."""
    get_conversation_manager().clear_user_message_callbacks()

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

# Update public functions with backward compatibility
async def llm_conversation_generate(message: str,
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

def get_embedding(text: str) -> List[float]:
    """Embed a single string. Returns a float vector."""
    manager = get_llm_manager()
    return manager.get_embedding(text)

def get_embeddings(texts: List[str]) -> List[List[float]]:
    """Embed a list of strings. Returns a list of float vectors."""
    manager = get_llm_manager()
    return manager.get_embeddings(texts)

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
llm = llm_conversation_generate


# Prompt Management ============================================

is_multilingual = _is_multilingual
set_default_language = _set_default_language

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

def save_prompt(key: str, new_value: Any, language: Optional[str] = None) -> bool:
    """
    Convenience function to save a modified prompt.

    Args:
        key: Dot-separated key (e.g., 'rag_manager.search_prompt')
        new_value: New value for the prompt
        language: Language code for multilingual mode

    Returns:
        bool: True if saved successfully, False otherwise
    """
    return get_prompt_manager().save_prompt(key, new_value, language)

def reload_prompts():
    """Reload all prompts from files."""
    return get_prompt_manager().reload_prompts()

def get_all_prompts(language: Optional[str] = None) -> Dict[str, Any]:
    """Get all loaded prompts."""
    manager = get_prompt_manager()
    return manager.get_all_prompts(language)

def get_module_prompts(module_prefix: str = "", language: Optional[str] = None) -> Dict[str, Any]:
    """Get prompts for a specific module."""
    manager = get_prompt_manager()
    return manager.get_module_prompts(module_prefix, language)

def list_modules_with_prompts(language: Optional[str] = None) -> List[str]:
    """List all module prefixes with prompts."""
    manager = get_prompt_manager()

    # Force multilingual detection
    if not manager._is_multilingual and manager._multilingual_prompts:
        manager._is_multilingual = True
        manager._available_languages = set(manager._multilingual_prompts.keys())

    return manager.list_modules(language)

def get_available_prompt_languages() -> List[str]:
    """Get list of dynamic available languages."""
    manager = get_prompt_manager()

    # Force multilingual detection
    if manager._multilingual_prompts:
        manager._is_multilingual = True
        manager._available_languages = set(manager._multilingual_prompts.keys())
        return sorted(manager._available_languages)

    return manager.get_available_languages()

# User Settings =============================================


# Driver =======================================================

def get_driver():
    """Get or create the global AppDriver instance."""
    from shared.driver import get_driver as _get_driver

    return _get_driver()


def register_option(
    group: str,
    name: str,
    activate_fn: Callable[[], None],
    deactivate_fn: Callable[[], None],
    description: str = "",
) -> None:
    """Register a switchable option in the app driver."""
    get_driver().register_option(group, name, activate_fn, deactivate_fn, description)


def register_action(
    name: str,
    handler_fn: Callable[..., Dict],
    description: str = "",
    required_context: Optional[List[str]] = None,
) -> None:
    """Register a driveable action in the app driver."""
    get_driver().register_action(name, handler_fn, description, required_context)


def record_plugin_event(plugin_id: str, event: str, data: Optional[Dict] = None) -> None:
    """Record a plugin event in the app driver session log."""
    get_driver().record_plugin_event(plugin_id, event, data or {})
