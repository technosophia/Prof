# /st_shared/cached.py

"""
[api]
Streamlit-cached singletons and the cache service.

This is the ONLY file in the codebase that imports streamlit directly for
caching purposes. Everything else receives the cache primitive via the
ServiceLocator ("cache" key) so that:
  - modules stay Streamlit-free and headless-compatible
  - swapping the cache backend (st.cache_resource → lru_cache, no-op, etc.)
    requires changing exactly ONE line: `_CACHE = ...`

### Cache primitive
- `_CACHE` - The active cache decorator. Currently `st.cache_resource`.
             Registered in the ServiceLocator as "cache" by register_all_services().
             Inject via services.get("cache") — never import this directly.

### Public API

#### Configuration
- `get_config() -> Config` - Primary way to access configuration (cached)
- `get_section(prefix: str = "") -> dict` - Get a module-specific config section
- `save_config(prefix: str = "", data: dict | None = None) -> bool` - Save a section back to its config file

#### Cache
- `get_cache()` - The active cache decorator (registered as "cache" in the ServiceLocator)

#### Managers (cached singletons)
- `get_db_manager()` - Database manager instance
- `get_user_manager()` - User manager instance
- `get_conversation_manager()` - Conversation manager instance
- `get_llm_manager()` - LLMManager instance
- `get_prompt_manager()` - Prompt manager instance (multilingual)
- `get_user_settings_manager()` - User settings manager instance
- `get_driver()` - App driver instance

#### Language / i18n
- `get_language_service()` - LanguageService instance (cached)
- `get_current_language() -> str` - Current language from Streamlit session state
- `get_available_languages() -> list[str]` - Sorted list of available language codes
- `_(key: str, lang: str | None = None) -> str` - Translate a key using cached translations

#### Module system
- `get_active_modules() -> list[str]` - Cached list of active module names

#### Startup
- `register_all_services(module_handler_instance=None) -> ServiceLocator`
    Builds and populates the ServiceLocator with all cached singletons,
    including the "cache" service. Call once at app startup (prof.py)
    and once in conftest.py before any module is activated.

### Internal (not for external use)
- `_CACHE` - The cache decorator (st.cache_resource by default)
- `_load_translations()` - Load all translation files once
- `_get_language_service()` - Cached factory for LanguageService
- `_init_prompt_manager()` - Initialize and load all prompts
- `_discover_ui_modules(active_modules_tuple)` - Cached UI module discovery
"""

import os
import streamlit as st

from core.service import ServiceLocator
from core.config import Config, _load_config
from core.translate import get_translation
from core.translate import LanguageService
from core.database import get_db_manager as _get_db_manager
from core.translate import load_all_translations
from shared.conversation import get_conversation_manager as _get_conversation_manager
from shared.llm import LLMManager
from shared.settings import UserSettingsManager
from shared.users import get_user_manager as _get_user_manager
from shared.module_handler import module_handler as global_module_handler
from shared.semantic_eval import SemanticEvaluator

# ---------------------------------------------------------------------------
# Cache service
# ---------------------------------------------------------------------------
# This is the single place in the codebase that decides WHAT the cache is.
# Everything else receives it via the ServiceLocator — no direct st import needed.
#
# To swap the cache backend for the entire application, change this one line:
#   e.g. import functools; _CACHE = functools.cache
#        or: _CACHE = lambda f: f   (no-op, for tests / headless)
_CACHE = st.cache_resource


# ---------------------------------------------------------------------------
# Cache service accessor
# ---------------------------------------------------------------------------

def get_cache():
    """Return the active cache decorator.

    Use this to retrieve the cache primitive when you don't have access to a
    ServiceLocator but are already in an st_shared context. Prefer injecting
    via services.get("cache") in modules that must stay Streamlit-free.

    Example:
        cache = get_cache()
        cached_fn = cache(my_expensive_fn)
    """
    return _CACHE


# ---------------------------------------------------------------------------
# Cached helpers
# ---------------------------------------------------------------------------

@_CACHE
def _load_translations() -> dict[str, dict[str, str]]:
    """Load all translations once and cache them globally."""
    return load_all_translations()


@_CACHE
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


@_CACHE
def _get_language_service():
    """Create a language service that knows about Streamlit's session state."""
    return LanguageService()


def get_language_service():
    """Get the language service instance (cached)."""
    return _get_language_service()


def get_current_language() -> str:
    """Get the current language from Streamlit session state."""
    service = get_language_service()
    return service.get_current_language()


@_CACHE
def get_db_manager():
    return _get_db_manager()


@_CACHE
def get_user_manager():
    return _get_user_manager()


@_CACHE
def get_conversation_manager():
    return _get_conversation_manager()


@_CACHE
def get_llm_manager():
    """Get or create the global LLMManager instance."""
    return LLMManager(get_config())


def _init_prompt_manager():
    """Initialize and load all prompts."""
    shared_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(shared_dir)

    import importlib
    from shared import prompt_manager

    importlib.reload(prompt_manager)

    prompt_manager_instance = prompt_manager.get_prompt_manager()
    prompt_manager.load_all_prompts(root_dir)

    if prompt_manager_instance._multilingual_prompts:
        prompt_manager_instance._is_multilingual = True
        prompt_manager_instance._available_languages = set(prompt_manager_instance._multilingual_prompts.keys())

    return prompt_manager_instance


@_CACHE
def get_prompt_manager():
    """Get the prompt manager instance."""
    return _init_prompt_manager()


@_CACHE
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


@_CACHE
def get_active_modules() -> list[str]:
    """Cached proxy for shared.module_handler.get_active_modules."""
    from shared.module_handler import get_active_modules as _get_active_modules
    return _get_active_modules()


@_CACHE
def _discover_ui_modules(active_modules_tuple: tuple[str, ...]):
    """Cached proxy for shared.ui_registry._discover_ui_modules."""
    from shared.ui_registry import _discover_ui_modules as _registry_discover
    shared_ui_dir = get_config().get("ui.shared_dir", None)
    return _registry_discover(active_modules_tuple, shared_ui_dir)


@_CACHE
def get_driver():
    """Cached proxy for shared.driver.get_driver."""
    from shared.driver import get_driver as _get_driver
    return _get_driver()

@_CACHE
def get_semantic_evaluator():
    """Get or create the global SemanticEvaluator instance."""
    return SemanticEvaluator(get_llm_manager())

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
    handler = module_handler_instance or global_module_handler

    services = ServiceLocator()
    services.register("cache", get_cache())
    services.register("config", get_config())
    services.register("user_manager", get_user_manager())
    services.register("db_manager", get_db_manager())
    services.register("conversation_manager", get_conversation_manager())
    services.register("prompt_manager", get_prompt_manager())
    services.register("llm_manager", get_llm_manager())
    services.register("user_settings_manager", get_user_settings_manager())
    services.register("driver", get_driver())
    services.register("language_service", get_language_service())
    services.register("semantic_eval", get_semantic_evaluator())

    handler.set_services(services)

    return services
