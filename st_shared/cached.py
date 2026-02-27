# /shared/cached.py

"""
[api]
All API are described in their API_xxx.md file but they are EXPOSED in a single module : common.py

Here is the list of exportable public functions from `shared/common.py`:

- `get_config()` - Primary way to access configuration (cached)
- `get_section(prefix: str = "")` - Get module-specific configuration sections
- `save_config(prefix: str = "", data: dict | None = None)` - Save a module section back to its config file
- `get_db_manager()` - Get the database manager instance (cached)
- `get_user_manager()` - Get the user manager instance (cached)
- `get_conversation_manager()` - Get the conversation manager instance (cached)
- `get_llm_manager()` - Get or create the global LLMManager instance (cached)
- `get_prompt_manager()` - Get the prompt manager instance with multilingual support (cached)
- `get_user_settings_manager()` - Get or create the user settings manager (cached)
- `get_available_languages() -> list[str]` - Get sorted list of available language codes
- `_(key: str, lang: str | None = None) -> str` - Central translation function using cached resources

### Internal cached functions (not exported)
- `_load_translations()` - Load all translations once and cache them globally
- `_init_prompt_manager()` - Initialize and load all prompts with multilingual support
"""

import os
import streamlit as st

from core.service import ServiceLocator
from core.config import Config, _load_config
from core.translate import get_translation
from core.database import get_db_manager as _get_db_manager
from core.translate import load_all_translations
from shared.conversation import get_conversation_manager as _get_conversation_manager
from shared.llm import LLMManager
from shared.settings import UserSettingsManager
from shared.users import get_user_manager as _get_user_manager
from shared.module_handler import module_handler as global_module_handler

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


@st.cache_resource
def get_active_modules() -> list[str]:
    """Cached proxy for shared.module_handler.get_active_modules."""
    from shared.module_handler import get_active_modules as _get_active_modules
    return _get_active_modules()


@st.cache_resource
def _discover_ui_modules(active_modules_tuple: tuple[str, ...]):
    """Cached proxy for shared.ui_registry._discover_ui_modules."""
    from shared.ui_registry import _discover_ui_modules as _registry_discover
    shared_ui_dir = get_config().get("ui.shared_dir", None)
    return _registry_discover(active_modules_tuple, shared_ui_dir)


@st.cache_resource
def get_driver():
    """Cached proxy for shared.driver.get_driver."""
    from shared.driver import get_driver as _get_driver
    return _get_driver()


def register_all_services(module_handler_instance=None):
    """
    Register all cached services with the module handler's ServiceLocator.

    This function should be called once at application startup (in prof.py and conftest.py)
    to set up the ServiceLocator with all available services from st_shared.cached.

    Args:
        module_handler_instance: Optional module handler instance. If not provided,
                                 uses the global module_handler.

    Returns:
        The ServiceLocator instance that was registered.
    """

    # Use provided module handler or global one
    handler = module_handler_instance or global_module_handler

    # Create and populate ServiceLocator
    services = ServiceLocator()
    services.register("config", get_config())
    services.register("user_manager", get_user_manager())
    services.register("db_manager", get_db_manager())
    services.register("conversation_manager", get_conversation_manager())
    services.register("prompt_manager", get_prompt_manager())
    services.register("llm_manager", get_llm_manager())
    services.register("user_settings_manager", get_user_settings_manager())
    services.register("driver", get_driver())
    # Add other services as needed

    # Register with module handler
    handler.set_services(services)

    return services
