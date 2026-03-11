from datetime import datetime, timedelta, timezone
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from jose import jwt
from pydantic import BaseModel

from api.deps import get_current_user
from shared.common import get_user_manager

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    user_id: str
    password: str


class InitPasswordRequest(BaseModel):
    user_id: str
    reset_code: str
    new_password: str


class UserDTO(BaseModel):
    id: str
    name: str
    role: str
    language: str = "en"
    masquerader_id: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserDTO


class MasqueradeRequest(BaseModel):
    target_user_id: str


def _get_masquerade_targets(current_user: dict, user_manager) -> list[dict]:
    actor_id = current_user.get("masquerader_id") or current_user["id"]
    actor = user_manager.get_user(actor_id) if actor_id != current_user.get("id") else current_user
    if not actor:
        return []

    actor_role = actor.get("role", "normal")
    users_dict = user_manager.get_all_users_dict()

    if actor_role == "admin":
        return [user for user in users_dict.values() if user.get("id") != current_user.get("id")]

    if actor_role == "master":
        return [
            user
            for user in users_dict.values()
            if user.get("parent_id") == actor["id"] and user.get("id") != current_user.get("id")
        ]

    return []


def _to_user_dto(user: dict) -> UserDTO:
    profile = user.get("profile") or {}
    return UserDTO(
        id=user["id"],
        name=user.get("name") or user["id"],
        role=user.get("role", "normal"),
        language=profile.get("language", "en"),
        masquerader_id=user.get("masquerader_id"),
    )


def _create_token(user: dict, masquerader_id: Optional[str] = None) -> str:
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise HTTPException(status_code=500, detail="JWT secret unavailable")

    exp = datetime.now(timezone.utc) + timedelta(hours=24)
    payload = {"sub": user["id"], "role": user.get("role", "normal"), "exp": int(exp.timestamp())}
    if masquerader_id:
        payload["masquerader_id"] = masquerader_id
    return jwt.encode(payload, secret, algorithm="HS256")


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest):
    user = get_user_manager().authenticate_user(payload.user_id, payload.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = _create_token(user)
    return TokenResponse(access_token=token, user=_to_user_dto(user))


@router.post("/init-password", response_model=TokenResponse)
async def init_password(payload: InitPasswordRequest):
    ok = get_user_manager().reset_password_with_code(
        payload.user_id,
        payload.reset_code,
        payload.new_password,
    )
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid reset code")

    user = get_user_manager().authenticate_user(payload.user_id, payload.new_password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unable to authenticate user")

    token = _create_token(user)
    return TokenResponse(access_token=token, user=_to_user_dto(user))


@router.get("/me", response_model=UserDTO)
async def me(current_user: dict = Depends(get_current_user)):
    return _to_user_dto(current_user)


@router.get("/masquerade-targets", response_model=list[UserDTO])
async def masquerade_targets(current_user: dict = Depends(get_current_user)):
    user_manager = get_user_manager()
    targets = _get_masquerade_targets(current_user, user_manager)
    return [_to_user_dto(user) for user in targets]


@router.post("/masquerade", response_model=TokenResponse)
async def masquerade(payload: MasqueradeRequest, current_user: dict = Depends(get_current_user)):
    user_manager = get_user_manager()
    targets = _get_masquerade_targets(current_user, user_manager)
    effective_masquerader_id = current_user.get("masquerader_id") or current_user["id"]
    allowed_target_ids = {user.get("id") for user in targets}
    if current_user.get("masquerader_id"):
        allowed_target_ids.add(current_user["masquerader_id"])
    if payload.target_user_id not in allowed_target_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    target_user = user_manager.get_user(payload.target_user_id)
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target user not found")

    token = _create_token(target_user, masquerader_id=effective_masquerader_id)
    return TokenResponse(access_token=token, user=_to_user_dto(target_user))
