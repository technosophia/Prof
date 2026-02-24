"""Built-in scenario actions for benchmarker."""

import asyncio
from typing import Dict, List

from core.logging import log, set_module_level
from st_shared.cached import get_config
from shared.common import (
    Message,
    get_conversation_manager,
    get_driver,
    llm_conversation_generate,
    set_current_llm,
)


def _run_async(coro):
    """Run coroutine in sync context."""
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def action_create_conversation(context, **params) -> Dict:
    """Create a new conversation and set driver context conversation_id."""
    title = params.get("title", "Benchmark conversation")
    conversation_id = get_conversation_manager().create_conversation(
        user_id=context.student_id,
        title=title,
        metadata={"created_via": "benchmarker"},
    )
    get_driver().set_context(conversation_id=conversation_id)
    return {"conversation_id": conversation_id, "created": True}


def action_user_send_message(context, **params) -> Dict:
    """Send a student message and generate assistant response through LLM stack."""
    content = params.get("content")
    if not content:
        raise ValueError("content is required")

    if context.llm_id:
        set_current_llm(context.llm_id)

    conversation = get_conversation_manager().get_conversation(context.conversation_id, include_messages=True)
    if conversation is None:
        raise ValueError(f"Conversation not found: {context.conversation_id}")

    get_conversation_manager().add_message(
        context.conversation_id,
        Message(role="user", content=content, metadata={"source": "benchmarker"}),
    )
    history = [msg.to_dict() for msg in conversation.messages]
    from shared.common import get_llm_manager

    captured_contexts: List[Dict] = []
    def _capture_context(monitor_data: Dict) -> None:
        for msg in monitor_data.get("messages", []):
            if "source" in msg:
                captured_contexts.append(
                    {
                        "source": msg.get("source", "unknown"),
                        "role": msg.get("role", "system"),
                        "content": msg.get("content", ""),
                    }
                )

    llm_manager = get_llm_manager()
    llm_manager.register_monitor_callback(_capture_context)
    try:
        llm_response = _run_async(
            llm_conversation_generate(
                content,
                conversation_history=history,
                user_id=context.student_id,
            )
        )
    finally:
        llm_manager.unregister_monitor_callback(_capture_context)

    get_conversation_manager().add_message(
        context.conversation_id,
        Message(role="assistant", content=llm_response, llm_id=context.llm_id, metadata={"source": "benchmarker"}),
    )

    return {
        "user_message": content,
        "llm_response": llm_response,
        "conversation_id": context.conversation_id,
        "injected_contexts": captured_contexts,
    }


def action_teacher_send_message(context, **params) -> Dict:
    """Inject a teacher/system message into the conversation without LLM call."""
    content = params.get("content")
    if not content:
        raise ValueError("content is required")

    get_conversation_manager().add_message(
        context.conversation_id,
        Message(
            role="system",
            content=f"[Teacher:{context.trainer_id}] {content}",
            metadata={"source": "benchmarker", "trainer_id": context.trainer_id},
        ),
    )
    return {"teacher_message": content, "conversation_id": context.conversation_id}



def action_switch_option(context, **params) -> Dict:
    """Switch an option through the driver."""
    group = params.get("group")
    name = params.get("name")
    if not group or not name:
        raise ValueError("group and name are required")

    driver = get_driver()
    previous = driver.get_active_option(group)
    driver.switch_option(group, name)
    return {"group": group, "activated": name, "previous": previous}
