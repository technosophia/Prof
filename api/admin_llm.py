from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import get_current_user
from shared.common import get_llm_manager, get_user_manager
from core.config import get_config

router = APIRouter(prefix="/api/admin/llm", tags=["admin-llm"])


class SetLLMRequest(BaseModel):
    llm_id: str


class LLMStatusResponse(BaseModel):
    current_llm: dict | None
    config_default: str | None
    available_llms: list[dict]
    can_change: bool


@router.get("", response_model=LLMStatusResponse)
async def get_llm_status(current_user: dict = Depends(get_current_user)):
    llm_manager = get_llm_manager()
    config = get_config()

    current_llm_info = llm_manager.get_current_llm_info()
    if current_llm_info:
        current_llm_info = {k: v for k, v in current_llm_info.items() if k != "engine"}

    config_default = config.get("app.default_llm")
    available_llms = llm_manager.get_available_llms()

    # Strip non-serializable engine attribute
    for llm in available_llms:
        llm.pop("engine", None)

    user_manager = get_user_manager()
    masquerader_id = current_user.get("masquerader_id")

    if masquerader_id:
        masquerader = user_manager.get_user(masquerader_id)
        effective_role = masquerader.get("role", "normal") if masquerader else "normal"
    else:
        effective_role = current_user.get("role", "normal")

    can_change = effective_role in {"admin", "master"}

    return LLMStatusResponse(
        current_llm=current_llm_info,
        config_default=config_default,
        available_llms=available_llms,
        can_change=can_change,
    )


@router.post("")
async def set_default_llm(
    payload: SetLLMRequest,
    current_user: dict = Depends(get_current_user),
):
    user_manager = get_user_manager()
    masquerader_id = current_user.get("masquerader_id")

    if masquerader_id:
        masquerader = user_manager.get_user(masquerader_id)
        effective_role = masquerader.get("role", "normal") if masquerader else "normal"
    else:
        effective_role = current_user.get("role", "normal")

    if effective_role not in {"admin", "master"}:
        raise HTTPException(
            status_code=403, detail="Forbidden: admin or master role required"
        )

    llm_manager = get_llm_manager()
    config = get_config()

    # Validate the LLM exists
    available_llms = llm_manager.get_available_llms()
    valid_llm_ids = {llm["id"] for llm in available_llms}

    if payload.llm_id not in valid_llm_ids:
        raise HTTPException(status_code=400, detail=f"Invalid LLM ID: {payload.llm_id}")

    # Save to local_config.json
    if not config.save_key("app.default_llm", payload.llm_id):
        raise HTTPException(status_code=500, detail="Failed to save config")

    # Update runtime LLM
    if not llm_manager.set_current_llm(payload.llm_id):
        raise HTTPException(status_code=500, detail="Failed to set current LLM")

    return {"ok": True, "llm_id": payload.llm_id}
