# /shared/common.py

"""
[api]
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

### Module Handler (for service access)
- `get_module_handler()` - Get the global module handler instance
"""

from typing import Optional, Dict, List, Tuple, Any, Callable
from functools import wraps

from .users import UserRole as _UserRole
from .conversation import Message as _Message
from .conversation import UserMessageCallback
from .prompt_manager import is_multilingual as _is_multilingual, set_default_language as _set_default_language
from .module_handler import module_handler as _global_module_handler

# ---------------------------------------------------------------------------
# Service access via module handler
# ---------------------------------------------------------------------------

def get_module_handler():
    """Get the global module handler instance."""
    return _global_module_handler


def _get_services():
    """Get the ServiceLocator from the global module handler."""
    return _global_module_handler.get_services()


def _get_service(service_name: str, default=None):
    """Get a service from the module handler's service locator."""
    services = _get_services()
    if services and service_name in services:
        return services.get(service_name)
    return default


def _get_service_or_raise(service_name: str):
    """Get a service or raise an informative error."""
    service = _get_service(service_name)
    if service is None:
        services_available = "yes" if _get_services() is not None else "no"
        raise RuntimeError(
            f"Service '{service_name}' not available. "
            f"Services available: {services_available}. "
            f"Make sure the application has properly initialized and "
            f"called module_handler.set_services() with a ServiceLocator containing '{service_name}'."
        )
    return service


# ---------------------------------------------------------------------------
# Decorator to ensure services are initialized
# ---------------------------------------------------------------------------

def require_services(func):
    """Decorator to ensure services are initialized before calling a function."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if _get_services() is None:
            raise RuntimeError(
                f"Cannot call {func.__name__}(): services not initialized in module handler. "
                f"Call module_handler.set_services() first with a ServiceLocator instance."
            )
        return func(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

UserRole = _UserRole


@require_services
def get_user_manager():
    """Get the user manager instance from services."""
    return _get_service_or_raise("user_manager")


@require_services
def init_user_manager(create_default_users: bool = True):
    """Initialize the user manager."""
    user_manager = get_user_manager()
    if create_default_users and user_manager.db.is_initialized():
        user_manager.init_default_users()
    return user_manager


@require_services
def get_all_users() -> Dict[str, Dict[str, Any]]:
    """Backward compatibility alias."""
    return get_user_manager().get_all_users_dict()


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

from shared.conversation import ConversationTable, MessageTable

Message = _Message


@require_services
def get_conversation_manager():
    """Get the conversation manager instance from services."""
    return _get_service_or_raise("conversation_manager")


@require_services
def register_user_message_callback(callback: UserMessageCallback) -> None:
    """Register a callback to be triggered when a user message is added."""
    get_conversation_manager().register_user_message_callback(callback)


@require_services
def unregister_user_message_callback(callback: UserMessageCallback) -> bool:
    """Unregister a user message callback."""
    return get_conversation_manager().unregister_user_message_callback(callback)


@require_services
def clear_user_message_callbacks() -> None:
    """Remove all registered user message callbacks."""
    get_conversation_manager().clear_user_message_callbacks()


@require_services
def cleanup_user_conversations(user_id: str) -> bool:
    """Cleanup all conversations for a user before deletion."""
    try:
        conv_manager = get_conversation_manager()
        with conv_manager.db.get_session() as session:
            conversations = session.query(ConversationTable).filter_by(user_id=user_id).all()

            for conv in conversations:
                session.query(MessageTable).filter_by(conversation_id=conv.id).delete()

            session.query(ConversationTable).filter_by(user_id=user_id).delete()
            return True
    except Exception:
        return False


# Register cleanup callback with user manager if both are available
def _register_cleanup_callback():
    """Register the cleanup callback with user manager if both are available."""
    try:
        user_manager = _get_service("user_manager")
        if user_manager and hasattr(user_manager, 'register_before_delete_callback'):
            user_manager.register_before_delete_callback(cleanup_user_conversations)
    except Exception:
        pass  # Silently fail - this is optional


# Try to register cleanup callback if services are already available
if _get_services() is not None:
    _register_cleanup_callback()


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

@require_services
def get_llm_manager():
    """Get the LLM manager instance from services."""
    return _get_service_or_raise("llm_manager")


@require_services
async def llm_conversation_generate(
    message: str,
    stream_callback: Optional[Callable] = None,
    conversation_history: Optional[List[Dict]] = None,
    user_id: Optional[str] = None,
) -> str:
    """Simple interface to generate response from current LLM with conversation history."""
    manager = get_llm_manager()
    return await manager.generate(message, stream_callback, conversation_history, user_id)


@require_services
def set_current_llm(llm_id: str) -> bool:
    """Set the current LLM to use."""
    manager = get_llm_manager()
    return manager.set_current_llm(llm_id)


@require_services
def get_available_llms() -> List[Dict[str, Any]]:
    """Get list of available LLMs."""
    manager = get_llm_manager()
    return manager.get_available_llms()


@require_services
def get_current_llm_info() -> Optional[Dict[str, Any]]:
    """Get information about the current LLM."""
    manager = get_llm_manager()
    return manager.get_current_llm_info()


@require_services
def get_current_llm_id() -> str:
    """Get the ID of the currently configured LLM."""
    try:
        manager = get_llm_manager()
        current_llm_info = manager.get_current_llm_info()
        if current_llm_info:
            llm_id = current_llm_info.get('id')
            if llm_id:
                return str(llm_id)

        if manager.current_llm:
            return str(manager.current_llm)

    except Exception as e:
        raise ValueError(f"Failed to get current LLM ID: {e}")

    raise ValueError("No LLM is currently configured or available")


@require_services
def get_llm_by_name(name: str) -> Optional[Dict[str, Any]]:
    manager = get_llm_manager()
    return manager.get_llm_by_name(name)


@require_services
def get_embedding(text: str) -> List[float]:
    manager = get_llm_manager()
    return manager.get_embedding(text)


@require_services
def get_embeddings(texts: List[str]) -> List[List[float]]:
    manager = get_llm_manager()
    return manager.get_embeddings(texts)


@require_services
def register_llm_callback(callback_func: Callable[[str, List[Dict]], str]):
    manager = get_llm_manager()
    manager.register_llm_callback(callback_func)


@require_services
def unregister_llm_callback(callback_func: Callable[[str, List[Dict]], str]):
    manager = get_llm_manager()
    manager.unregister_llm_callback(callback_func)


@require_services
def register_llm_context_callback(callback_func: Callable[[str, List[Dict]], Tuple[str, str, str]]):
    manager = get_llm_manager()
    manager.register_context_callback(callback_func)


@require_services
def unregister_llm_context_callback(callback_func: Callable[[str, List[Dict]], Tuple[str, str, str]]):
    manager = get_llm_manager()
    manager.unregister_context_callback(callback_func)


# Alias for backward compatibility
llm = llm_conversation_generate


# ---------------------------------------------------------------------------
# Prompt Management
# ---------------------------------------------------------------------------

is_multilingual = _is_multilingual
set_default_language = _set_default_language


@require_services
def get_prompt_manager():
    """Get the prompt manager instance from services."""
    return _get_service_or_raise("prompt_manager")


@require_services
def get_prompt(key: str, default: Any = None, language: Optional[str] = None) -> Any:
    return get_prompt_manager().get_prompt(key, default, language)


@require_services
def set_prompt(key: str, value: Any, language: Optional[str] = None) -> bool:
    return get_prompt_manager().set_prompt(key, value, language)


@require_services
def save_prompt(key: str, new_value: Any, language: Optional[str] = None) -> bool:
    return get_prompt_manager().save_prompt(key, new_value, language)


@require_services
def reload_prompts():
    return get_prompt_manager().reload_prompts()


@require_services
def get_all_prompts(language: Optional[str] = None) -> Dict[str, Any]:
    manager = get_prompt_manager()
    return manager.get_all_prompts(language)


@require_services
def get_module_prompts(module_prefix: str = "", language: Optional[str] = None) -> Dict[str, Any]:
    manager = get_prompt_manager()
    return manager.get_module_prompts(module_prefix, language)


@require_services
def list_modules_with_prompts(language: Optional[str] = None) -> List[str]:
    manager = get_prompt_manager()
    return manager.list_modules(language)


@require_services
def get_available_prompt_languages() -> List[str]:
    manager = get_prompt_manager()
    return manager.get_available_languages()


# ---------------------------------------------------------------------------
# User Settings
# ---------------------------------------------------------------------------

@require_services
def get_user_settings_manager():
    """Get or create the user settings manager."""
    return _get_service_or_raise("user_settings_manager")


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

@require_services
def get_driver():
    """Get the driver instance from services."""
    return _get_service_or_raise("driver")


@require_services
def register_option(
    group: str,
    name: str,
    activate_fn: Callable[[], None],
    deactivate_fn: Callable[[], None],
    description: str = "",
) -> None:
    get_driver().register_option(group, name, activate_fn, deactivate_fn, description)


@require_services
def register_action(
    name: str,
    handler_fn: Callable[..., Dict],
    description: str = "",
    required_context: Optional[List[str]] = None,
) -> None:
    get_driver().register_action(name, handler_fn, description, required_context)




@require_services
def register_assertion(
    name: str,
    handler_fn: Callable[..., Dict],
    description: str = "",
) -> None:
    get_driver().register_assertion(name, handler_fn, description)

@require_services
def record_plugin_event(plugin_id: str, event: str, data: Optional[Dict] = None) -> None:
    get_driver().record_plugin_event(plugin_id, event, data or {})


# ---------------------------------------------------------------------------
# Streamlit-specific bridge (only imported when needed)
# ---------------------------------------------------------------------------

def _get_streamlit_cached_service(service_name: str):
    """
    Fallback function to get services from st_shared.cached when running in Streamlit.
    This should only be used by the application startup code, not by common.py directly.
    """
    from st_shared.cached import (
        get_user_manager as _cached_user_manager,
        get_conversation_manager as _cached_conversation_manager,
        get_llm_manager as _cached_llm_manager,
        get_prompt_manager as _cached_prompt_manager,
        get_user_settings_manager as _cached_user_settings_manager,
    )

    _CACHED_GETTERS = {
        "user_manager": _cached_user_manager,
        "conversation_manager": _cached_conversation_manager,
        "llm_manager": _cached_llm_manager,
        "prompt_manager": _cached_prompt_manager,
        "user_settings_manager": _cached_user_settings_manager,
    }

    getter = _CACHED_GETTERS.get(service_name)
    if getter:
        return getter()
    return None


def initialize_services_from_streamlit():
    """
    Initialize the module handler's service locator with services from st_shared.cached.
    This should be called ONCE at application startup in a Streamlit context.
    """
    from .module_handler import ServiceLocator
    from st_shared.cached import get_config

    services = ServiceLocator()

    # Register config
    services.register("config", get_config())

    # Register managers from st_shared.cached
    services.register("user_manager", _get_streamlit_cached_service("user_manager"))
    services.register("conversation_manager", _get_streamlit_cached_service("conversation_manager"))
    services.register("llm_manager", _get_streamlit_cached_service("llm_manager"))
    services.register("prompt_manager", _get_streamlit_cached_service("prompt_manager"))
    services.register("user_settings_manager", _get_streamlit_cached_service("user_settings_manager"))

    # Create and register driver
    from .driver import get_driver as _get_driver
    services.register("driver", _get_driver())

    # Set services on the global module handler
    _global_module_handler.set_services(services)

    # Register cleanup callback
    _register_cleanup_callback()

    return services
