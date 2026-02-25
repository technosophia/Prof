<!-- shared/_docs/API_COMMON.md -->

<!-- GENERATED FILE - do not edit manually -->
<!-- Source: shared/common.py -->

# API — common

All API are described in their API_xxx.md file but they are EXPOSED in a single module : common.py

Here is the list of exportable public functions from `shared/common.py`:

### Users
- `get_user_manager()` - Get the user manager instance
- `init_user_manager(create_default_users: bool = True)` - Initialize the user manager
- `get_all_users()` - Get all users as a dictionary (backward compatibility alias)

### Conversations
- `get_conversation_manager()` - Get the conversation manager instance
- `register_user_message_callback(callback: UserMessageCallback)` - Register callback for user messages
- `unregister_user_message_callback(callback: UserMessageCallback) -> bool` - Unregister a user message callback
- `clear_user_message_callbacks()` - Remove all registered user message callbacks
- `cleanup_user_conversations(user_id: str) -> bool` - Cleanup all conversations for a user before deletion

### LLM
- `get_llm_manager()` - Get or create the global LLMManager instance
- `llm_conversation_generate(message: str, ...) -> str` - Generate response from current LLM
- `set_current_llm(llm_id: str) -> bool` - Set the current LLM to use
- `get_available_llms() -> List[Dict[str, Any]]` - Get list of available LLMs
- `get_current_llm_info() -> Optional[Dict[str, Any]]` - Get information about the current LLM
- `get_current_llm_id() -> str` - Get the ID of the currently configured LLM
- `get_llm_by_name(name: str) -> Optional[Dict[str, Any]]` - Get LLM information by name
- `get_embedding(text: str) -> List[float]` - Get embedding for a single text
- `get_embeddings(texts: List[str]) -> List[List[float]]` - Get embeddings for multiple texts
- `register_llm_callback(callback_func)` - Register callback to add LLM context
- `unregister_llm_callback(callback_func)` - Unregister an LLM callback
- `register_llm_context_callback(callback_func)` - Register callback for LLM context
- `unregister_llm_context_callback(callback_func)` - Unregister an LLM context callback
- `llm` - Alias for `llm_conversation_generate` (backward compatibility)

### Prompt Management
- `get_prompt_manager()` - Get the prompt manager instance
- `get_prompt(key: str, default: Any = None, language: Optional[str] = None) -> Any` - Get a prompt by key
- `set_prompt(key: str, value: Any, language: Optional[str] = None) -> bool` - Set a prompt value
- `save_prompt(key: str, new_value: Any, language: Optional[str] = None) -> bool` - Save a modified prompt
- `reload_prompts()` - Reload all prompts from files
- `get_all_prompts(language: Optional[str] = None) -> Dict[str, Any]` - Get all loaded prompts
- `get_module_prompts(module_prefix: str = "", language: Optional[str] = None) -> Dict[str, Any]` - Get prompts for a specific module
- `list_modules_with_prompts(language: Optional[str] = None) -> List[str]` - List all module prefixes with prompts
- `get_available_prompt_languages() -> List[str]` - Get list of available languages for prompts
- `is_multilingual()` - Check if multilingual mode is enabled
- `set_default_language(language: str)` - Set the default language for prompts

### User Settings
- `get_user_settings_manager()` - Get or create the user settings manager

### Driver
- `get_driver()` - Get or create the global AppDriver singleton
- `register_option(...)` - Register a switchable driver option
- `register_action(...)` - Register a driveable action
- `record_plugin_event(...)` - Record plugin-level events in the driver session log
