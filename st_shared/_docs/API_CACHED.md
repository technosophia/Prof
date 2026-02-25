<!-- st_shared/_docs/API_CACHED.md -->

<!-- GENERATED FILE - do not edit manually -->
<!-- Source: st_shared/cached.py -->

# API — cached

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
