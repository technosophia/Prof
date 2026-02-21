# /shared/cached.py

import os
import streamlit as st

from core.config import Config, _load_config
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
