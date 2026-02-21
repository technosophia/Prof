"""
Core scenario actions registered by the benchmarker.

These actions drive fundamental app interactions (conversations, messaging)
that are not owned by any specific app module.
They are registered via the driver at benchmarker initialize() time.
"""

import asyncio
from typing import Dict

from shared.conversation import Message
from shared.driver import DriverContext, DriverContextError
from shared.common import (
    get_conversation_manager,
    get_current_llm_id,
    llm_conversation_generate,
    save_prompt,
)


def _run_async(coro):
    """Run a coroutine from sync code."""
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def action_create_conversation(context: DriverContext, **params) -> Dict:
    """Create a new conversation for the current student."""
    title = params.get("title", "Benchmark conversation")
    manager = get_conversation_manager()
    conversation_id = manager.create_conversation(user_id=context.student_id, title=title)

    context.conversation_id = conversation_id

    return {"conversation_id": conversation_id, "created": True}


def action_user_send_message(context: DriverContext, **params) -> Dict:
    """Send a message as the current student and get the LLM response."""
    content = params.get("content")
    if not content:
        raise ValueError("Parameter 'content' is required")
    if not context.conversation_id:
        raise DriverContextError("Missing required context field(s) for action 'user_send_message': conversation_id")

    manager = get_conversation_manager()
    manager.add_message(context.conversation_id, Message(role="user", content=content, metadata={}))

    conversation = manager.get_conversation(context.conversation_id, include_messages=True)
    history = [message.to_dict() for message in conversation.messages] if conversation else []

    llm_response = _run_async(
        llm_conversation_generate(
            message=content,
            conversation_history=history,
            user_id=context.student_id,
        )
    )

    llm_id = context.llm_id or get_current_llm_id()
    manager.add_message(
        context.conversation_id,
        Message(role="assistant", content=llm_response, llm_id=llm_id, metadata={}),
    )

    return {
        "user_message": content,
        "llm_response": llm_response,
        "tokens_used": len(llm_response.split()),
        "conversation_id": context.conversation_id,
    }


def action_teacher_send_message(context: DriverContext, **params) -> Dict:
    """Inject a teacher message in a student conversation without LLM call."""
    content = params.get("content")
    if not content:
        raise ValueError("Parameter 'content' is required")

    manager = get_conversation_manager()
    manager.add_message(
        context.conversation_id,
        Message(role="system", content=content, metadata={"sender": "teacher", "trainer_id": context.trainer_id}),
    )

    return {"teacher_message": content, "conversation_id": context.conversation_id}


def action_set_training_program(context: DriverContext, **params) -> Dict:
    """Set trainer training program prompt used by memory/RAG actions."""
    content = params.get("content")
    if not content:
        raise ValueError("Parameter 'content' is required")

    save_prompt("trainer.teacher.training_program", content)
    return {"saved": True}
