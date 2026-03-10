from datetime import datetime, timedelta, timezone
import os

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


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserDTO


def _to_user_dto(user: dict) -> UserDTO:
    profile = user.get("profile") or {}
    return UserDTO(
        id=user["id"],
        name=user.get("name") or user["id"],
        role=user.get("role", "normal"),
        language=profile.get("language", "en"),
    )


def _create_token(user: dict) -> str:
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise HTTPException(status_code=500, detail="JWT secret unavailable")

    exp = datetime.now(timezone.utc) + timedelta(hours=24)
    payload = {"sub": user["id"], "role": user.get("role", "normal"), "exp": int(exp.timestamp())}
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
