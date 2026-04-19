"""Settings API for user and system settings."""

from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from api.deps import get_current_user
from modules.rag_manager.rag_factory import get_rag_manager

router = APIRouter(prefix="/settings", tags=["settings"])


class RAGEngineResponse(BaseModel):
    engine_id: str
    available_engines: list


class RAGEngineUpdate(BaseModel):
    engine_id: str
    target: Optional[str] = None


@router.get("/rag-engine", response_model=RAGEngineResponse)
def get_rag_engine(current_user: dict = Depends(get_current_user)):
    """Get the current default RAG engine for the user."""
    rag_manager = get_rag_manager()
    if not rag_manager:
        raise HTTPException(status_code=500, detail="RAG manager not available")

    default_engine = rag_manager.get_default_engine_id(current_user["id"])
    available = list(rag_manager.engines.keys())

    return RAGEngineResponse(engine_id=default_engine, available_engines=available)


@router.put("/rag-engine", response_model=RAGEngineResponse)
def set_rag_engine(
    update: RAGEngineUpdate,
    current_user: dict = Depends(get_current_user),
):
    """Set the default RAG engine for system or a specific target."""
    rag_manager = get_rag_manager()
    if not rag_manager:
        raise HTTPException(status_code=500, detail="RAG manager not available")

    if update.target and update.target != current_user["id"]:
        user_info = rag_manager._user_manager.get_user(current_user["id"])
        if user_info and user_info.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Cannot set engine for other users")

    success = rag_manager.set_default_engine_id(update.engine_id, update.target)
    if not success:
        raise HTTPException(status_code=400, detail=f"Invalid engine: {update.engine_id}")

    default_engine = rag_manager.get_default_engine_id(update.target)
    available = list(rag_manager.engines.keys())

    return RAGEngineResponse(engine_id=default_engine, available_engines=available)