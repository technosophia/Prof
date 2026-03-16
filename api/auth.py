from datetime import datetime, timedelta, timezone
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
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



class RegisterRequest(BaseModel):
    email: str
    password: str
    confirm_password: str
    suggested_id: Optional[str] = None


class PendingRegistrationResponse(BaseModel):
    status: str

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




def _sanitize_user_id(raw_user_id: str) -> str:
    candidate = (raw_user_id or "").strip().lower().replace(" ", "_").replace(".", "_")
    while "__" in candidate:
        candidate = candidate.replace("__", "_")
    return candidate.strip("_")

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
    user_manager = get_user_manager()
    user, auth_status = user_manager.authenticate_user_with_status(payload.user_id, payload.password)
    if auth_status == "pending_approval":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="pending_approval")
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = _create_token(user)
    return TokenResponse(access_token=token, user=_to_user_dto(user))


@router.post(
    "/register",
    response_model=TokenResponse | PendingRegistrationResponse,
)
async def register(payload: RegisterRequest):
    if payload.password != payload.confirm_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="password_mismatch")

    email = payload.email.strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_email")

    derived_id_source = payload.suggested_id or email.split("@", 1)[0]
    derived_user_id = _sanitize_user_id(derived_id_source)
    if not derived_user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_user_id")

    user_manager = get_user_manager()
    registration_status = "approved" if user_manager.is_email_preregistered(email) else "pending"


    if user_manager.get_user(derived_user_id):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "user_id_conflict", "conflicting_user_id": derived_user_id},
        )

    try:
        user_manager.create_user(
            name=derived_user_id,
            role="normal",
            email=email,
            parent_id=None,
            password=payload.password,
            user_id=derived_user_id,
            allow_orphan_normal=True,
            registration_status=registration_status,
        )
    except ValueError as error:
        if "already exists" in str(error):
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={"detail": "user_id_conflict", "conflicting_user_id": derived_user_id},
            )
        raise

    if registration_status == "pending":
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content={"status": "pending"})

    user = user_manager.authenticate_user(derived_user_id, payload.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unable to authenticate user")

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
