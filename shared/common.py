"""Common shared resources (Streamlit-aware)"""

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
