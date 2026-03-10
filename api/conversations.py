from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import get_current_user
from shared.common import get_conversation_manager

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class ConversationCreateRequest(BaseModel):
    title: str


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
