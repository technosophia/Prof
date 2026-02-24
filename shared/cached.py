# /shared/cached.py

import os
import streamlit as st

from core.config import Config, _load_config
from core.translate import get_translation
from core.database import get_db_manager as _get_db_manager
from core.translate import load_all_translations
from .conversation import get_conversation_manager as _get_conversation_manager
from .llm import LLMManager
from .settings import UserSettingsManager
from .users import get_user_manager as _get_user_manager


@st.cache_resource
def _load_translations() -> dict[str, dict[str, str]]:
    """Load all translations once and cache them globally."""
    return load_all_translations()


@st.cache_resource
def get_config() -> Config:
    """Primary way to access configuration from anywhere."""
    return _load_config()


def get_section(prefix: str = "") -> dict:
    """Convenient wrapper for module-specific sections."""
    return get_config().get_section(prefix)


def save_config(prefix: str = "", data: dict | None = None) -> bool:
    """Convenient wrapper to save a module/section back to its CONFIG_FILE."""
    if data is None:
        raise ValueError("save_config requires the data dict to save")
    return get_config().save_section(prefix, data)


@st.cache_resource
def get_db_manager():
    return _get_db_manager()


@st.cache_resource
def get_user_manager():
    return _get_user_manager()


@st.cache_resource
def get_conversation_manager():
    return _get_conversation_manager()


@st.cache_resource
def get_llm_manager():
    """Get or create the global LLMManager instance."""
    return LLMManager(get_config())


def _init_prompt_manager():
    """Initialize and load all prompts."""
    shared_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(shared_dir)

    # IMPORTANT: Get fresh instance and force reload
    import importlib
    from shared import prompt_manager

    # Reload the module to ensure fresh state
    importlib.reload(prompt_manager)

    # Get fresh prompt manager
    prompt_manager_instance = prompt_manager.get_prompt_manager()

    # Load prompts
    prompt_manager.load_all_prompts(root_dir)

    # Double-check multilingual status
    if prompt_manager_instance._multilingual_prompts:
        prompt_manager_instance._is_multilingual = True
        prompt_manager_instance._available_languages = set(prompt_manager_instance._multilingual_prompts.keys())

    return prompt_manager_instance


@st.cache_resource
def get_prompt_manager():
    """Get the prompt manager instance."""
    return _init_prompt_manager()


@st.cache_resource
def get_user_settings_manager():
    """Get or create the user settings manager."""
    return UserSettingsManager()


def get_available_languages() -> list[str]:
    """Return sorted list of dynamic available language codes."""
    return sorted(_load_translations().keys())


def _(key: str, lang: str | None = None) -> str:
    """Central translation function using cached translation resources."""
    if lang is None:
        if "current_language" not in st.session_state:
            st.session_state.current_language = "en"
        lang = st.session_state.current_language
    return get_translation(key, lang, _load_translations())
