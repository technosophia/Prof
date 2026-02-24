# /shared/common.py

from typing import Optional, Dict, List, Tuple, Any, Callable

from .users import UserRole as _UserRole
from .conversation import Message as _Message
from .conversation import UserMessageCallback
from .prompt_manager import is_multilingual as _is_multilingual, set_default_language as _set_default_language
from .cached import (
    get_user_manager,
    get_conversation_manager,
    get_llm_manager,
    get_prompt_manager,
    get_user_settings_manager,
)


UserRole = _UserRole

# Users ========================================================

def init_user_manager(create_default_users: bool = True):
    """Initialize the user manager."""
    if create_default_users and get_user_manager().db.is_initialized():
        get_user_manager().init_default_users()
    return get_user_manager()


def get_all_users() -> Dict[str, Dict[str, Any]]:
    """Backward compatibility alias."""
    return get_user_manager().get_all_users_dict()

# Conversations ================================================

from shared.conversation import ConversationTable, MessageTable

Message = _Message


def register_user_message_callback(callback: UserMessageCallback) -> None:
    """Register a callback to be triggered when a user message is added."""
    get_conversation_manager().register_user_message_callback(callback)


def unregister_user_message_callback(callback: UserMessageCallback) -> bool:
    """Unregister a user message callback."""
    return get_conversation_manager().unregister_user_message_callback(callback)


def clear_user_message_callbacks() -> None:
    """Remove all registered user message callbacks."""
    get_conversation_manager().clear_user_message_callbacks()


def cleanup_user_conversations(user_id: str) -> bool:
    """Cleanup all conversations for a user before deletion."""
    try:
        with get_conversation_manager().db.get_session() as session:
            conversations = session.query(ConversationTable).filter_by(user_id=user_id).all()

            for conv in conversations:
                session.query(MessageTable).filter_by(conversation_id=conv.id).delete()

            session.query(ConversationTable).filter_by(user_id=user_id).delete()
            return True
    except Exception:
        return False


get_user_manager().register_before_delete_callback(cleanup_user_conversations)

# LLM ==========================================================

async def llm_conversation_generate(
    message: str,
    stream_callback: Optional[Callable] = None,
    conversation_history: Optional[List[Dict]] = None,
    user_id: Optional[str] = None,
) -> str:
    """Simple interface to generate response from current LLM with conversation history."""
    manager = get_llm_manager()
    return await manager.generate(message, stream_callback, conversation_history, user_id)


def set_current_llm(llm_id: str) -> bool:
    """Set the current LLM to use."""
    manager = get_llm_manager()
    return manager.set_current_llm(llm_id)


def get_available_llms() -> List[Dict[str, Any]]:
    """Get list of available LLMs."""
    manager = get_llm_manager()
    return manager.get_available_llms()


def get_current_llm_info() -> Optional[Dict[str, Any]]:
    """Get information about the current LLM."""
    manager = get_llm_manager()
    return manager.get_current_llm_info()


def get_current_llm_id() -> str:
    """Get the ID of the currently configured LLM."""
    try:
        current_llm_info = get_current_llm_info()
        if current_llm_info:
            llm_id = current_llm_info.get('id')
            if llm_id:
                return str(llm_id)

        manager = get_llm_manager()
        if manager.current_llm:
            return str(manager.current_llm)

    except Exception as e:
        raise ValueError(f"Failed to get current LLM ID: {e}")

    raise ValueError("No LLM is currently configured or available")


def get_llm_by_name(name: str) -> Optional[Dict[str, Any]]:
    manager = get_llm_manager()
    return manager.get_llm_by_name(name)


def get_embedding(text: str) -> List[float]:
    manager = get_llm_manager()
    return manager.get_embedding(text)


def get_embeddings(texts: List[str]) -> List[List[float]]:
    manager = get_llm_manager()
    return manager.get_embeddings(texts)


def register_llm_callback(callback_func: Callable[[str, List[Dict]], str]):
    manager = get_llm_manager()
    manager.register_llm_callback(callback_func)


def unregister_llm_callback(callback_func: Callable[[str, List[Dict]], str]):
    manager = get_llm_manager()
    manager.unregister_llm_callback(callback_func)


def register_llm_context_callback(callback_func: Callable[[str, List[Dict]], Tuple[str, str, str]]):
    manager = get_llm_manager()
    manager.register_context_callback(callback_func)


def unregister_llm_context_callback(callback_func: Callable[[str, List[Dict]], Tuple[str, str, str]]):
    manager = get_llm_manager()
    manager.unregister_context_callback(callback_func)


llm = llm_conversation_generate

# Prompt Management ============================================

is_multilingual = _is_multilingual
set_default_language = _set_default_language


def get_prompt(key: str, default: Any = None, language: Optional[str] = None) -> Any:
    return get_prompt_manager().get_prompt(key, default, language)


def set_prompt(key: str, value: Any, language: Optional[str] = None) -> bool:
    return get_prompt_manager().set_prompt(key, value, language)


def save_prompt(key: str, new_value: Any, language: Optional[str] = None) -> bool:
    return get_prompt_manager().save_prompt(key, new_value, language)


def reload_prompts():
    return get_prompt_manager().reload_prompts()


def get_all_prompts(language: Optional[str] = None) -> Dict[str, Any]:
    manager = get_prompt_manager()
    return manager.get_all_prompts(language)


def get_module_prompts(module_prefix: str = "", language: Optional[str] = None) -> Dict[str, Any]:
    manager = get_prompt_manager()
    return manager.get_module_prompts(module_prefix, language)


def list_modules_with_prompts(language: Optional[str] = None) -> List[str]:
    manager = get_prompt_manager()
    if not manager._is_multilingual and manager._multilingual_prompts:
        manager._is_multilingual = True
        manager._available_languages = set(manager._multilingual_prompts.keys())
    return manager.list_modules(language)


def get_available_prompt_languages() -> List[str]:
    manager = get_prompt_manager()
    if manager._multilingual_prompts:
        manager._is_multilingual = True
        manager._available_languages = set(manager._multilingual_prompts.keys())
        return sorted(manager._available_languages)
    return manager.get_available_languages()


# Driver =======================================================

def get_driver():
    from shared.driver import get_driver as _get_driver
    return _get_driver()


def register_option(
    group: str,
    name: str,
    activate_fn: Callable[[], None],
    deactivate_fn: Callable[[], None],
    description: str = "",
) -> None:
    get_driver().register_option(group, name, activate_fn, deactivate_fn, description)


def register_action(
    name: str,
    handler_fn: Callable[..., Dict],
    description: str = "",
    required_context: Optional[List[str]] = None,
) -> None:
    get_driver().register_action(name, handler_fn, description, required_context)


def record_plugin_event(plugin_id: str, event: str, data: Optional[Dict] = None) -> None:
    get_driver().record_plugin_event(plugin_id, event, data or {})
