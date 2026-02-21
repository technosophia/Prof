<!-- /shared/AGENTS.md -->

# Shared code

This code implements functionnalities shared across the app. No other module have meaning without it. It would have no purpose.

/shared contains common functionnalities of the app : users, conversations, llm, prompts, settings, and module handling.

It gives "managers", which are singletons objects that handle the app's data and logic.
Managers are python classes, but they are cached in common.py as a streamlit resource.
If needed in strategic points, the shared code provide callbacks (internal), and special callbacks for UI : injection points.

/shared/API.md describe the API that other modules can use to interact with the shared code.
/shared/CODE.md describe the coding rules

See : 
- /shared/API_CONVERSATION.md for conversations
- /shared/API_LLM.md for LLM and prompts
- /shared/API_USERS.md for users and user settings
- /shared/API_DRIVER.md for programmatic app driving API (context, options, actions, session log)
Special : 
- /shared/API_MODULE_HANDLER.md for module handling (main app only)
- MODULE.md to get the list of injection points aviable for modules and directory structure

If needed (only special cases, should be avoided unless strictly necessary to access some internals) : 
/core/API.md for logging, database, configuration, translation
This API is replicated in /shared/common.py and this one

# Special case : common.py

All API are described in their API_xxx.md file but they are EXPOSED in a single module : common.py

Here is the list of exportable public functions from `shared/common.py`, sorted by module:

### from shared.common import ...  # Configuration
- `get_config()` - Primary way to access configuration
- `get_section(prefix: str = "")` - Get module-specific configuration sections
- `save_config(prefix: str = "", data: dict | None = None)` - Save a module section back to its config file

### from shared.common import ...  # Database
- `init_database()` - Initialize the database
- `get_db_manager()` - Get the database manager instance

### from shared.common import ...  # Users
- `get_user_manager()` - Get the user manager instance
- `init_user_manager(create_default_users: bool = True)` - Initialize the user manager
- `get_all_users()` - Get all users as a dictionary (backward compatibility alias)

### from shared.common import ...  # Conversations
- `get_conversation_manager()` - Get the conversation manager instance
- `register_user_message_callback(callback: UserMessageCallback)` - Register callback for user messages
- `unregister_user_message_callback(callback: UserMessageCallback) -> bool` - Unregister a user message callback
- `clear_user_message_callbacks()` - Remove all registered user message callbacks
- `cleanup_user_conversations(user_id: str) -> bool` - Cleanup all conversations for a user before deletion

### from shared.common import ...  # LLM
- `get_llm_manager()` - Get or create the global LLMManager instance
- `llm_conversation_generate(message: str, stream_callback: Optional[Callable] = None, conversation_history: Optional[List[Dict]] = None, user_id: Optional[str] = None) -> str` - Generate response from current LLM
- `set_current_llm(llm_id: str) -> bool` - Set the current LLM to use
- `get_available_llms() -> List[Dict[str, Any]]` - Get list of available LLMs
- `get_current_llm_info() -> Optional[Dict[str, Any]]` - Get information about the current LLM
- `get_current_llm_id() -> str` - Get the ID of the currently configured LLM
- `get_llm_by_name(name: str) -> Optional[Dict[str, Any]]` - Get LLM information by name
- `register_llm_callback(callback_func: Callable[[str, List[Dict]], str])` - Register callback to add LLM context
- `unregister_llm_callback(callback_func: Callable[[str, List[Dict]], str])` - Unregister an LLM callback
- `register_llm_context_callback(callback_func: Callable[[str, List[Dict]], Tuple[str, str, str]])` - Register callback for LLM context
- `unregister_llm_context_callback(callback_func: Callable[[str, List[Dict]], Tuple[str, str, str]])` - Unregister an LLM context callback
- `llm` - Alias for `llm_conversation_generate` (backward compatibility)

### from shared.common import ...  # Prompt Management
- `get_prompt_manager()` - Get the prompt manager instance
- `get_prompt(key: str, default: Any = None, language: Optional[str] = None) -> Any` - Get a prompt by key
- `save_prompt(key: str, new_value: Any, language: Optional[str] = None) -> bool` - Save a modified prompt
- `reload_prompts()` - Reload all prompts from files
- `get_all_prompts(language: Optional[str] = None) -> Dict[str, Any]` - Get all loaded prompts
- `get_module_prompts(module_prefix: str = "", language: Optional[str] = None) -> Dict[str, Any]` - Get prompts for a specific module
- `list_modules_with_prompts(language: Optional[str] = None) -> List[str]` - List all module prefixes with prompts
- `get_available_prompt_languages() -> List[str]` - Get list of available languages for prompts
- `is_multilingual()` - Check if multilingual mode is enabled
- `set_default_language(language: str)` - Set the default language for prompts

### from shared.common import ...  # User Settings
- `get_user_settings_manager()` - Get or create the user settings manager

### from shared.common import ...  # Driver
- `get_driver()` - Get or create the global AppDriver singleton
- `register_option(...)` - Register a switchable driver option
- `register_action(...)` - Register a driveable action
- `record_plugin_event(...)` - Record plugin-level events in the driver session log

### from shared.common import ...  # Translation/Internationalization
- `get_available_languages() -> list[str]` - Get sorted list of available language codes
- `_(key: str, lang: str | None = None) -> str` - Central translation function

### from shared.common import ...  # Logging
- `log()` - Logging function
- `configure_logging_from_dict()` - Configure logging from a dictionary
