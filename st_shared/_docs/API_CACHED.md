<!-- st_shared/_docs/API_CACHED.md -->

<!-- GENERATED FILE - do not edit manually -->
<!-- Source: st_shared/cached.py -->

# API — cached

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
