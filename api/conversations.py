from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import get_current_user
from shared.common import get_conversation_manager, get_user_manager

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class ConversationCreateRequest(BaseModel):
    title: str


class ConversationRenameRequest(BaseModel):
    title: str


def _get_effective_power_user(current_user: dict):
    user_manager = get_user_manager()
    if current_user.get("role") in {"admin", "master"}:
        return current_user

    masquerader_id = current_user.get("masquerader_id")
    if not masquerader_id:
        return None

    masquerader = user_manager.get_user(masquerader_id)
    if masquerader and masquerader.get("role") in {"admin", "master"}:
        return masquerader
    return None


@router.get("/stats/users")
async def users_stats(current_user: dict = Depends(get_current_user)):
    power_user = _get_effective_power_user(current_user)
    if not power_user:
        raise HTTPException(status_code=403, detail="Forbidden")

    user_manager = get_user_manager()
    conv_manager = get_conversation_manager()

    if power_user.get("role") == "admin":
        users = list(user_manager.get_all_users_dict().values())
    else:
        users = [power_user]
        users.extend(
            user
            for user in user_manager.get_all_users_dict().values()
            if user.get("parent_id") == power_user["id"]
        )

    stats = []
    for user in users:
        convs = conv_manager.get_user_conversations(user["id"], include_inactive=True)
        total_messages = sum(conv.get("message_count", 0) for conv in convs)
        last_message_at = None
        for conv in convs:
            ts = conv.get("last_message_at")
            if ts and (not last_message_at or ts > last_message_at):
                last_message_at = ts

        stats.append(
            {
                "user_id": user["id"],
                "name": user.get("name") or user["id"],
                "role": user.get("role", "normal"),
                "conversation_count": len(convs),
                "total_messages": total_messages,
                "last_message_at": last_message_at,
            }
        )

    stats.sort(key=lambda item: item["name"].lower())
    return stats


@router.get("")
async def list_conversations(current_user: dict = Depends(get_current_user)):
    convs = get_conversation_manager().get_user_conversations(current_user["id"])
    return [
        {
            "id": c["id"],
            "title": c["title"],
            "created_at": c["created_at"],
            "updated_at": c["updated_at"],
            "message_count": c.get("message_count", 0),
        }
        for c in convs
    ]


@router.post("")
async def create_conversation(payload: ConversationCreateRequest, current_user: dict = Depends(get_current_user)):
    conv_id = get_conversation_manager().create_conversation(current_user["id"], payload.title)
    conv = get_conversation_manager().get_conversation(conv_id, include_messages=False)
    return {
        "id": conv.id,
        "title": conv.title,
        "created_at": conv.created_at.isoformat(),
        "updated_at": conv.updated_at.isoformat(),
        "message_count": 0,
    }


@router.delete("/{conversation_id}")
async def delete_conversation(conversation_id: str, current_user: dict = Depends(get_current_user)):
    conv = get_conversation_manager().get_conversation(conversation_id, include_messages=False)
    if not conv or conv.user_id != current_user["id"]:
        raise HTTPException(status_code=404, detail="Conversation not found")

    get_conversation_manager().delete_conversation(conversation_id)
    return {"ok": True}


@router.get("/{conversation_id}/messages")
async def conversation_messages(conversation_id: str, current_user: dict = Depends(get_current_user)):
    conv = get_conversation_manager().get_conversation(conversation_id, include_messages=True)
    if not conv or conv.user_id != current_user["id"]:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return [
        {
            "role": message.role,
            "content": message.content,
            "timestamp": (message.timestamp.isoformat() if message.timestamp else None),
        }
        for message in conv.messages
    ]


@router.patch("/{conversation_id}")
async def rename_conversation(
    conversation_id: str,
    payload: ConversationRenameRequest,
    current_user: dict = Depends(get_current_user),
):
    conv_manager = get_conversation_manager()
    conv = conv_manager.get_conversation(conversation_id, include_messages=False)
    if not conv or conv.user_id != current_user["id"]:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conv_manager.update_conversation_title(conversation_id, payload.title)
    updated = conv_manager.get_conversation(conversation_id, include_messages=False)
    details = next((c for c in conv_manager.get_user_conversations(current_user["id"]) if c["id"] == conversation_id), None)
    return {
        "id": updated.id,
        "title": updated.title,
        "created_at": updated.created_at.isoformat(),
        "updated_at": updated.updated_at.isoformat(),
        "message_count": details.get("message_count", 0) if details else 0,
    }


@router.get("/{conversation_id}/messages/{message_index}/context")
async def message_context(
    conversation_id: str,
    message_index: int,
    timestamp: str | None = None,
    current_user: dict = Depends(get_current_user),
):
    if not _get_effective_power_user(current_user):
        raise HTTPException(status_code=403, detail="Forbidden")

    conv = get_conversation_manager().get_conversation(conversation_id, include_messages=True)
    if not conv or conv.user_id != current_user["id"]:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if message_index < 0 or message_index >= len(conv.messages):
        return {"found": False, "debug": "message index out of range"}

    try:
        from modules.llm_monitor.llm_monitor_factory import get_llm_monitor
        from core.config import get_config
        from core.database import get_db_manager

        llm_monitor = get_llm_monitor(config=get_config(), db_manager=get_db_manager())
    except Exception:
        return {"found": False, "debug": "llm_monitor unavailable"}

    calls = llm_monitor.get_llm_calls(conversation_id=conversation_id, limit=200)
    if not calls:
        return {"found": False, "debug": "no llm call for conversation"}

    target_ts = None
    if timestamp:
        try:
            target_ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            target_ts = None

    selected_call = None
    if target_ts is not None:
        closest_delta = None
        for call in calls:
            call_timestamp = call.get("timestamp")
            if not call_timestamp:
                continue
            try:
                call_ts = datetime.fromisoformat(call_timestamp.replace("Z", "+00:00"))
            except ValueError:
                continue
            delta = abs((call_ts - target_ts).total_seconds())
            if closest_delta is None or delta < closest_delta:
                closest_delta = delta
                selected_call = call

    if selected_call is None:
        assistant_turn = -1
        for idx, message in enumerate(conv.messages):
            if idx > message_index:
                break
            if message.role == "assistant":
                assistant_turn += 1

        assistant_calls = [call for call in reversed(calls)]
        if 0 <= assistant_turn < len(assistant_calls):
            selected_call = assistant_calls[assistant_turn]

    if selected_call is None:
        return {"found": False, "debug": "no matching llm call"}

    return {
        "found": True,
        "input_tokens": selected_call.get("input_tokens"),
        "output_tokens": selected_call.get("output_tokens"),
        "total_tokens": selected_call.get("total_tokens"),
        "total_cost": selected_call.get("total_cost"),
        "model": selected_call.get("model"),
        "llm_type": selected_call.get("llm_type"),
        "no_thinking": selected_call.get("no_thinking"),
        "messages": selected_call.get("messages") or [],
        "context_messages": selected_call.get("context_messages") or [],
    }
