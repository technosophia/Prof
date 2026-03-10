import asyncio
import json

from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.deps import get_current_user
from shared.common import get_conversation_manager, get_llm_manager


router = APIRouter(prefix="/api/chat", tags=["chat"])


@dataclass
class ChatMessage:
    role: str
    content: str
    timestamp: str | None = None
    tokens: int | None = None
    metadata: dict | None = None
    llm_id: str | None = None


class ChatRequest(BaseModel):
    conversation_id: str
    message: str


class RegenerateRequest(BaseModel):
    conversation_id: str


def _build_history(messages):
    return [{"role": m.role, "content": m.content} for m in messages]


def _streaming_headers():
    return {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
        "X-Content-Type-Options": "nosniff",
    }


async def _stream_llm_response(conversation_id: str, user_id: str, message: str, history, save_user_message: bool):
    conversation_manager = get_conversation_manager()
    llm_manager = get_llm_manager()

    if save_user_message:
        conversation_manager.add_message(conversation_id, ChatMessage(role="user", content=message))

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def on_chunk(chunk: str):
        loop.call_soon_threadsafe(queue.put_nowait, chunk)

    async def runner() -> str:
        try:
            response = await llm_manager.generate(message, on_chunk, history, user_id)
            await queue.put(None)
            return response
        except Exception as exc:
            await queue.put({"error": str(exc)})
            await queue.put(None)
            return ""

    async def event_stream():
        task = asyncio.create_task(runner())
        chunks = []

        # Send initial event to help clients/proxies flush stream quickly.
        yield f"data: {json.dumps({'type': 'start', 'content': ''})}\n\n"

        while True:
            item = await queue.get()
            if item is None:
                break
            if isinstance(item, dict) and item.get("error"):
                yield f"data: {json.dumps({'type': 'error', 'content': item['error']})}\n\n"
                continue
            text = str(item)
            chunks.append(text)
            yield f"data: {json.dumps({'type': 'chunk', 'content': text})}\n\n"

        response = await task
        assistant_text = response if response else "".join(chunks)
        if assistant_text:
            conversation_manager.add_message(conversation_id, ChatMessage(role="assistant", content=assistant_text))
        yield f"data: {json.dumps({'type': 'done', 'content': ''})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_streaming_headers())


@router.post("/stream")
async def stream_chat(payload: ChatRequest, current_user: dict = Depends(get_current_user)):
    conversation_manager = get_conversation_manager()

    conv = conversation_manager.get_conversation(payload.conversation_id, include_messages=True)
    if not conv or conv.user_id != current_user["id"]:
        raise HTTPException(status_code=404, detail="Conversation not found")

    refreshed = conversation_manager.get_conversation(payload.conversation_id, include_messages=True)
    history = _build_history(refreshed.messages + [ChatMessage(role="user", content=payload.message)])
    return await _stream_llm_response(payload.conversation_id, current_user["id"], payload.message, history, save_user_message=True)


@router.post("/regenerate-stream")
async def regenerate_last_response(payload: RegenerateRequest, current_user: dict = Depends(get_current_user)):
    conversation_manager = get_conversation_manager()
    conv = conversation_manager.get_conversation(payload.conversation_id, include_messages=True)
    if not conv or conv.user_id != current_user["id"]:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not conv.messages:
        raise HTTPException(status_code=400, detail="No messages to regenerate")

    last_user_idx = next((idx for idx in range(len(conv.messages) - 1, -1, -1) if conv.messages[idx].role == "user"), None)
    if last_user_idx is None:
        raise HTTPException(status_code=400, detail="No user message found")

    last_user_message = conv.messages[last_user_idx].content
    truncated_history = _build_history(conv.messages[: last_user_idx + 1])

    return await _stream_llm_response(
        payload.conversation_id,
        current_user["id"],
        last_user_message,
        truncated_history,
        save_user_message=False,
    )
