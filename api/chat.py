import asyncio
import json
import uuid  # Add this import
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.deps import get_current_user
from shared.common import get_conversation_manager, get_llm_manager
from modules.rag_manager import get_rag_manager, set_query_override, clear_query_override


router = APIRouter(prefix="/api/chat", tags=["chat"])

# Dedicated thread pool for blocking LLM calls (Groq/Ollama use sync I/O internally)
_llm_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="llm-worker")


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
    result_limit: int | None = None  # NEW: Optional result limit for RAG context


class RegenerateRequest(BaseModel):
    conversation_id: str
    result_limit: int | None = None  # NEW: Also add to regenerate request


def _build_history(messages):
    return [{"role": m.role, "content": m.content} for m in messages]


def _streaming_headers():
    return {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
        "X-Content-Type-Options": "nosniff",
    }


async def _stream_llm_response(
    conversation_id: str,
    user_id: str,
    message: str,
    history,
    save_user_message: bool,
    result_limit: int | None = None,  # NEW parameter
):
    conversation_manager = get_conversation_manager()
    llm_manager = get_llm_manager()

    # NEW: Set query override for RAG if result_limit is provided
    query_id = None
    if result_limit is not None:
        try:
            rag_manager = get_rag_manager()
            # Generate a unique ID for this query
            query_id = f"chat_{conversation_id}_{uuid.uuid4().hex[:8]}"
            # Set temporary override (5 minutes TTL)
            rag_manager.limit_manager.set_query_override(query_id, result_limit, ttl_seconds=300)
        except Exception as e:
            # Log but don't fail if RAG is not available
            print(f"Could not set RAG query override: {e}")

    if save_user_message:
        conversation_manager.add_message(conversation_id, ChatMessage(role="user", content=message))

    queue: asyncio.Queue = asyncio.Queue()
    outer_loop = asyncio.get_running_loop()

    # on_chunk is invoked from whatever thread/loop the LLM engine runs in.
    # call_soon_threadsafe safely bridges back to the outer event loop.
    def on_chunk(chunk: str):
        outer_loop.call_soon_threadsafe(queue.put_nowait, chunk)

    def _run_llm_sync() -> str:
        """
        Run the async LLM generate() call in a *new* event loop on a worker
        thread.  This is necessary because the LLM engines (Groq, Ollama, xAI)
        use synchronous blocking I/O inside their async wrappers, which would
        stall the main asyncio event loop and prevent SSE chunks from being
        flushed in real-time if awaited directly.
        """
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        try:
            # NEW: Pass query_id to generate method
            return new_loop.run_until_complete(
                llm_manager.generate(
                    message,
                    on_chunk,
                    history,
                    user_id,
                    conversation_id=conversation_id,
                    query_id=query_id  # Pass query_id for RAG context limit
                )
            )
        finally:
            new_loop.close()

    async def runner() -> str:
        try:
            response = await outer_loop.run_in_executor(_llm_executor, _run_llm_sync)
            await queue.put(None)  # sentinel: generation finished
            return response
        except Exception as exc:
            await queue.put({"error": str(exc)})
            await queue.put(None)
            return ""

    async def event_stream():
        task = asyncio.create_task(runner())
        chunks = []

        # Initial event helps clients/proxies detect the stream immediately.
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
            conversation_manager.add_message(
                conversation_id, ChatMessage(role="assistant", content=assistant_text)
            )
        yield f"data: {json.dumps({'type': 'done', 'content': ''})}\n\n"

    return StreamingResponse(
        event_stream(), media_type="text/event-stream", headers=_streaming_headers()
    )


@router.post("/stream")
async def stream_chat(payload: ChatRequest, current_user: dict = Depends(get_current_user)):
    conversation_manager = get_conversation_manager()

    conv = conversation_manager.get_conversation(payload.conversation_id, include_messages=True)
    if not conv or conv.user_id != current_user["id"]:
        raise HTTPException(status_code=404, detail="Conversation not found")

    refreshed = conversation_manager.get_conversation(payload.conversation_id, include_messages=True)
    history = _build_history(
        refreshed.messages + [ChatMessage(role="user", content=payload.message)]
    )

    # NEW: Pass result_limit to _stream_llm_response
    return await _stream_llm_response(
        payload.conversation_id,
        current_user["id"],
        payload.message,
        history,
        save_user_message=True,
        result_limit=payload.result_limit,  # Pass the limit
    )


@router.post("/regenerate-stream")
async def regenerate_last_response(
    payload: RegenerateRequest, current_user: dict = Depends(get_current_user)
):
    conversation_manager = get_conversation_manager()
    conv = conversation_manager.get_conversation(payload.conversation_id, include_messages=True)
    if not conv or conv.user_id != current_user["id"]:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not conv.messages:
        raise HTTPException(status_code=400, detail="No messages to regenerate")

    last_user_idx = next(
        (idx for idx in range(len(conv.messages) - 1, -1, -1) if conv.messages[idx].role == "user"),
        None,
    )
    if last_user_idx is None:
        raise HTTPException(status_code=400, detail="No user message found")

    last_user_message = conv.messages[last_user_idx].content

    # This logic should replace, not append
    if last_user_idx < len(conv.messages) - 1:
        preserved_messages = conv.messages[: last_user_idx + 1]
        conversation_manager.clear_conversation_messages(payload.conversation_id)
        for message in preserved_messages:
            conversation_manager.add_message(payload.conversation_id, message)

    truncated_history = _build_history(conv.messages[: last_user_idx + 1])

    # NEW: Pass result_limit to _stream_llm_response
    return await _stream_llm_response(
        payload.conversation_id,
        current_user["id"],
        last_user_message,
        truncated_history,
        save_user_message=False,  # This should be False to avoid duplicating the user message
        result_limit=payload.result_limit,  # Pass the limit
    )
