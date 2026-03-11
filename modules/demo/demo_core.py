# modules/demo/demo_core.py
"""
Demo module — core business logic.

Streamlit-free. Runs headless (tests, CLI, background tasks).
Functions accept their dependencies as arguments (manager objects) rather than
fetching them via shared.common — this makes them directly testable without patching.

Organized by the demo module's own sections, not by shared service structure.
"""

import asyncio
import os, sys
from typing import Any, Optional
from core.logging import log


# ─── Infrastructure: config, translations, prompts ───────────────────────────

def get_demo_config_value(config) -> str:
    """
    Read a value from this module's config.json.
    config.json in modules/demo/ auto-loads under the prefix 'modules.demo.*'.
    Returns a recognizable sentinel if the key is absent (visual check in UI).
    """
    return config.get("greeting", "⚠ CONFIG NOT LOADED")


def get_demo_translation(translate_fn, key: str = "demo.section_title") -> str:
    """
    Call the translation function with a dot-notation key.
    In UI: from st_shared.cached import _  →  _("demo.my_key")
    Translations live in translations/en.json nested under the module name.
    The translation system returns "[key]" for missing keys — that's the sentinel.
    """
    return translate_fn(key)


def get_demo_prompt(prompt_manager, language: str = "en") -> str:
    """
    Read a prompt from prompt.en.yml (or .fr.yml for French).
    Prompts are nested under the module name: system, demo.welcome, etc.
    Returns a recognizable sentinel if the prompt file is not loaded.
    """
    return prompt_manager.get_prompt("system", "⚠ PROMPT NOT LOADED", language)


# ─── Users ───────────────────────────────────────────────────────────────────

def list_users(user_manager) -> list[dict]:
    """
    Return all users as plain dicts.
    user_manager.get_all_users_dict() → {user_id: user_dict}
    Per the API: user dict has keys "id", "name", "role" (string: "admin"/"master"/"normal"),
    "email", "is_active", etc.
    """
    users = user_manager.get_all_users_dict()
    return [
        {
            "id": uid,
            # API returns "name" not "username"; fall back to id if missing
            "username": u.get("name", uid) if isinstance(u, dict) else getattr(u, "name", getattr(u, "username", str(uid))),
            # Role is a string value: "admin", "master", "normal"
            "role": u.get("role", "?") if isinstance(u, dict) else str(getattr(u, "role", "?")),
        }
        for uid, u in users.items()
    ]


def get_user(user_manager, user_id: str) -> Optional[dict]:
    """Get a single user by id. Returns None if not found."""
    user = user_manager.get_user(user_id)
    if user is None:
        return None
    if isinstance(user, dict):
        return {
            "id": user_id,
            "username": user.get("name", str(user_id)),
            "role": user.get("role", "?"),
        }
    return {
        "id": user_id,
        "username": getattr(user, "name", getattr(user, "username", str(user_id))),
        "role": str(getattr(user, "role", "?")),
    }


# ─── Conversations ────────────────────────────────────────────────────────────

def list_user_conversations(conversation_manager, user_id: str) -> list[dict]:
    """
    Return all conversations for a user as plain dicts.
    get_user_conversations(user_id) → list of dicts, each already containing:
      "id", "title", "message_count", "created_at", "updated_at", "is_active", etc.
    message_count is precomputed by the manager — no need to fetch messages.
    """
    try:
        convs = conversation_manager.get_user_conversations(user_id)
        if not convs:
            return []
        return [
            {
                "id": c["id"],
                "title": c["title"],
                "message_count": c.get("message_count", 0),
            }
            for c in convs
        ]
    except Exception as e:
        log("error", f"list_user_conversations: {e}")
        return []


def get_conversation_messages(conversation_manager, conv_id: str) -> list[dict]:
    """
    Return messages for a conversation as plain dicts (role, content).
    Uses get_conversation(id, include_messages=True) which returns a Conversation
    dataclass. Messages are Message dataclass objects with .role and .content.
    There is no standalone get_messages() method.
    """
    try:
        conv = conversation_manager.get_conversation(conv_id, include_messages=True)
        if conv is None:
            return []
        return [{"role": m.role, "content": m.content} for m in conv.messages]
    except Exception as e:
        log("error", f"get_conversation_messages: {e}")
        return []


def create_conversation(conversation_manager, user_id: str, title: str = "Demo") -> Optional[str]:
    """
    Create a new conversation, return its id string.
    create_conversation(user_id, title) returns the UUID string of the new conversation.
    """
    try:
        return str(conversation_manager.create_conversation(user_id, title=title))
    except Exception as e:
        log("error", f"create_conversation: {e}")
        return None


def send_user_message(conversation_manager, conv_id: str, content: str) -> Optional[str]:
    """
    Add a user message to a conversation.
    add_message(conversation_id, message: Message) → message_id (str).
    Triggers all registered user message callbacks.
    """
    from shared.conversation import Message
    try:
        return conversation_manager.add_message(conv_id, Message(role="user", content=content))
    except Exception as e:
        log("error", f"send_user_message: {e}")
        return None


# ─── LLM ──────────────────────────────────────────────────────────────────────

def generate_response(
    llm_manager,
    message: str,
    history: Optional[list] = None,
    user_id: Optional[str] = None,
) -> str:
    """
    Generate an LLM response synchronously (wraps async for Streamlit).
    For async contexts, await llm_manager.generate() directly.

    Context injection (RAG, memory, system prompts) is handled by callbacks
    registered via register_llm_context_callback() — see demo_on_module_activated().
    """
    try:
        return asyncio.run(
            llm_manager.generate(
                message=message,
                stream_callback=None,
                conversation_history=history or [],
                user_id=user_id,
            )
        )
    except Exception as e:
        log("error", f"generate_response: {e}")
        return f"[LLM error: {e}]"


def get_available_llms(llm_manager) -> list[dict]:
    """List available LLMs for a UI selector."""
    try:
        return llm_manager.get_available_llms()
    except Exception as e:
        log("error", f"get_available_llms: {e}")
        return []


# ─── Services introspection ───────────────────────────────────────────────────

EXPECTED_SERVICES = [
    "config", "user_manager", "db_manager", "conversation_manager",
    "llm_manager", "prompt_manager", "user_settings_manager",
    "driver", "language_service",
]


def check_services(services) -> dict[str, bool]:
    """
    Return {service_name: available} for each expected service.
    Drives the visual health check in the Services UI tab.
    """
    return {
        name: (name in services and services.get(name) is not None)
        for name in EXPECTED_SERVICES
    }


# ─── Module lifecycle ─────────────────────────────────────────────────────────

_PLUGIN_ID = "demo"


def _demo_context_provider(message: str, history: list) -> tuple[str, str, str]:
    """
    LLM context callback — runs before every LLM generation.
    Returns (system_addition, before_message, after_message).
    This is the injection point for RAG chunks, memory summaries, etc.
    """
    return ("You are a helpful demo assistant.", "", "")


def _demo_on_user_message(conversation_id: str, messages: list) -> None:
    """
    User message callback — runs when any user message is added.
    Signature: (conversation_id: str, messages: List[Message]) → None
    'messages' is the full conversation history including the new message.
    Use this to trigger RAG indexing, memory updates, analytics, etc.
    """
    last = messages[-1] if messages else None
    content = getattr(last, "content", "") if last else ""
    log("debug", f"[demo] user message in {conversation_id}: {content[:60]}")


def demo_on_module_activated(services) -> None:
    """
    Called by module_handler when this module is activated.
    Headless-safe: no Streamlit calls here.
    All callbacks and driver registrations go here, never at import time.
    """
    from shared.common import (
        register_llm_context_callback,
        register_user_message_callback,
        register_option,
        register_action,
        record_plugin_event,
    )

    test_mode = os.getenv("TEST_MODE") == "true" or "pytest" in sys.modules
    if test_mode:
        register_llm_context_callback(_demo_context_provider)
        register_user_message_callback(_demo_on_user_message)

    register_option(
        group=_PLUGIN_ID,
        name="demo_feature",
        activate_fn=lambda: record_plugin_event(_PLUGIN_ID, "demo_feature_activated"),
        deactivate_fn=lambda: record_plugin_event(_PLUGIN_ID, "demo_feature_deactivated"),
        description="Toggle the demo feature",
    )

    def _hello_action(name: str = "world") -> dict:
        return {"greeting": f"Hello, {name}!"}

    register_action(
        name=f"{_PLUGIN_ID}.hello",
        handler_fn=_hello_action,
        description="Demo greeting action. Params: name (str)",
    )

    log("debug", "[demo] module activated")


def demo_on_module_deactivated() -> None:
    """
    Called by module_handler when this module is deactivated.
    Must mirror demo_on_module_activated — unregister everything registered there.
    """
    from shared.common import (
        unregister_llm_context_callback,
        unregister_user_message_callback,
    )
    test_mode = os.getenv("TEST_MODE") == "true" or "pytest" in sys.modules
    if test_mode:
        unregister_llm_context_callback(_demo_context_provider)
        unregister_user_message_callback(_demo_on_user_message)
    log("info", "[demo] module deactivated")
