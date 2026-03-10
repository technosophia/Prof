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


@router.post("/stream")
async def stream_chat(payload: ChatRequest, current_user: dict = Depends(get_current_user)):
    conversation_manager = get_conversation_manager()
    llm_manager = get_llm_manager()

    conv = conversation_manager.get_conversation(payload.conversation_id, include_messages=True)
    if not conv or conv.user_id != current_user["id"]:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conversation_manager.add_message(payload.conversation_id, ChatMessage(role="user", content=payload.message))
    refreshed = conversation_manager.get_conversation(payload.conversation_id, include_messages=True)
    history = [{"role": m.role, "content": m.content} for m in refreshed.messages]

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def on_chunk(chunk: str):
        loop.call_soon_threadsafe(queue.put_nowait, chunk)

    async def runner() -> str:
        try:
            response = await llm_manager.generate(payload.message, on_chunk, history, current_user["id"])
            await queue.put(None)
            return response
        except Exception as exc:
            await queue.put({"error": str(exc)})
            await queue.put(None)
            return ""

    async def event_stream():
        task = asyncio.create_task(runner())
        chunks = []
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
            conversation_manager.add_message(payload.conversation_id, ChatMessage(role="assistant", content=assistant_text))
        yield f"data: {json.dumps({'type': 'done', 'content': ''})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
