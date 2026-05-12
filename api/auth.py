from datetime import datetime, timedelta, timezone
import os
import secrets
from typing import List, Optional

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
    new_name: Optional[str] = None


class CheckEmailRequest(BaseModel):
    email: str


class RequestActivationRequest(BaseModel):
    email: str


class RequestPasswordResetRequest(BaseModel):
    user_id: str


class RegisterRequest(BaseModel):
    email: str
    password: str
    confirm_password: str
    suggested_id: Optional[str] = None


class PendingRegistrationResponse(BaseModel):
    status: str


class WaitlistRequest(BaseModel):
    email: str
    list_id: Optional[str] = None


class WaitlistListRequest(BaseModel):
    name: str


class WaitlistListUpdateRequest(BaseModel):
    name: str


class BulkApproveRequest(BaseModel):
    entry_ids: List[str]
    master_id: str


class BulkRejectRequest(BaseModel):
    entry_ids: List[str]


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
    actor = (
        user_manager.get_user(actor_id)
        if actor_id != current_user.get("id")
        else current_user
    )
    if not actor:
        return []

    actor_role = actor.get("role", "normal")
    users_dict = user_manager.get_all_users_dict()

    if actor_role == "admin":
        return [
            user
            for user in users_dict.values()
            if user.get("id") != current_user.get("id")
        ]

    if actor_role == "master":
        student_ids = user_manager.get_master_students(actor["id"])
        return [
            user
            for user in users_dict.values()
            if user.get("id") in student_ids
            and user.get("id") != current_user.get("id")
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
    payload = {
        "sub": user["id"],
        "role": user.get("role", "normal"),
        "exp": int(exp.timestamp()),
    }
    if masquerader_id:
        payload["masquerader_id"] = masquerader_id
    return jwt.encode(payload, secret, algorithm="HS256")


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest):
    user_manager = get_user_manager()
    user, auth_status = user_manager.authenticate_user_with_status(
        payload.user_id, payload.password
    )
    if auth_status == "pending_approval":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="pending_approval"
        )
    if auth_status.startswith("deadline_expired::"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=auth_status)
    if auth_status == "enrollment_expired":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="enrollment_expired")
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    user_manager.update_last_login(user["id"])
    token = _create_token(user)
    return TokenResponse(access_token=token, user=_to_user_dto(user))


@router.post(
    "/register",
    response_model=TokenResponse | PendingRegistrationResponse,
)
async def register(payload: RegisterRequest):
    if payload.password != payload.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="password_mismatch"
        )

    email = payload.email.strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_email"
        )

    derived_id_source = payload.suggested_id or email.split("@", 1)[0]
    derived_user_id = _sanitize_user_id(derived_id_source)
    if not derived_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_user_id"
        )

    user_manager = get_user_manager()

    if user_manager.is_email_registered(email):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "email_already_registered"},
        )

    preregistered = user_manager.is_email_preregistered(email)
    registration_status = "approved" if preregistered else "pending"
    parent_id = (
        user_manager.get_preregistered_email_owner(email) if preregistered else None
    )
    prereg_policy = user_manager.get_preregistered_email_policy(email)

    if user_manager.get_user(derived_user_id):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": "user_id_conflict",
                "conflicting_user_id": derived_user_id,
            },
        )

    try:
        user_metadata = {}
        if preregistered:
            deadline_months = prereg_policy.get("deadline_months", 6)
            user_metadata = {
                "preregistered": True,
                "preregistered_deadline_months": deadline_months,
                "preregistered_deadline_at": user_manager.compute_deadline_at(
                    deadline_months
                ),
                "preregistered_expiry_message": prereg_policy.get("expiry_message"),
            }
        user_manager.create_user(
            name=derived_user_id,
            role="normal",
            email=email,
            parent_id=parent_id,
            password=payload.password,
            user_id=derived_user_id,
            allow_orphan_normal=True,
            registration_status=registration_status,
            user_metadata=user_metadata,
        )
    except ValueError as error:
        if "already exists" in str(error):
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={
                    "detail": "user_id_conflict",
                    "conflicting_user_id": derived_user_id,
                },
            )
        raise

    if parent_id:
        user_manager.add_enrollment(derived_user_id, parent_id)

    if registration_status == "pending":
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED, content={"status": "pending"}
        )

    user = user_manager.authenticate_user(derived_user_id, payload.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unable to authenticate user",
        )

    token = _create_token(user)
    return TokenResponse(access_token=token, user=_to_user_dto(user))


@router.get("/waitlist/lists")
async def get_waitlist_lists():
    """Get all waitlist lists (public - for frontend to show in waitlist form)."""
    user_manager = get_user_manager()
    lists = user_manager.get_all_waitlist_lists()
    return lists


@router.post("/waitlist/lists")
async def create_waitlist_list(
    payload: WaitlistListRequest,
    current_user: dict = Depends(get_current_user),
):
    """Create a new waitlist list (admin/master only)."""
    user_manager = get_user_manager()
    user_role = current_user.get("role")
    if user_role not in ["admin", "master"]:
        raise HTTPException(status_code=403, detail="Forbidden")

    list_id = user_manager.create_waitlist_list(
        payload.name,
        created_by=current_user.get("id"),
    )
    if not list_id:
        raise HTTPException(
            status_code=400, detail="List name already exists or invalid"
        )

    return {"id": list_id, "name": payload.name}


@router.put("/waitlist/lists/{list_id}")
async def update_waitlist_list(
    list_id: str,
    payload: WaitlistListUpdateRequest,
    current_user: dict = Depends(get_current_user),
):
    """Rename a waitlist list (admin/master only)."""
    user_manager = get_user_manager()
    user_role = current_user.get("role")
    if user_role not in ["admin", "master"]:
        raise HTTPException(status_code=403, detail="Forbidden")

    success = user_manager.rename_waitlist_list(list_id, payload.name)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to rename list")

    return {"success": True}


@router.delete("/waitlist/lists/{list_id}")
async def delete_waitlist_list(
    list_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Delete a waitlist list and all its entries (admin/master only)."""
    user_manager = get_user_manager()
    user_role = current_user.get("role")
    if user_role not in ["admin", "master"]:
        raise HTTPException(status_code=403, detail="Forbidden")

    success = user_manager.delete_waitlist_list(list_id)
    if not success:
        raise HTTPException(status_code=404, detail="List not found")

    return {"success": True}


@router.get("/waitlist/entries")
async def get_waitlist_entries(
    list_id: Optional[str] = None,
    status: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """Get waitlist entries (admin/master only)."""
    user_manager = get_user_manager()
    user_role = current_user.get("role")
    if user_role not in ["admin", "master"]:
        raise HTTPException(status_code=403, detail="Forbidden")

    entries = user_manager.get_waitlist_entries(list_id=list_id, status=status)
    return entries


@router.post("/waitlist", response_model=PendingRegistrationResponse)
async def waitlist(payload: WaitlistRequest):
    """Register an email to a waitlist list."""
    email = payload.email.strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_email"
        )

    user_manager = get_user_manager()

    if payload.list_id:
        entry_id = user_manager.add_waitlist_entry(email, payload.list_id)
        if not entry_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already in this list or list not found",
            )
        return PendingRegistrationResponse(status="pending")

    if user_manager.is_email_registered(email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="email_already_registered"
        )

    lists = user_manager.get_all_waitlist_lists()
    if not lists:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No waitlist lists available. Please contact support.",
        )

    default_list = lists[0]
    entry_id = user_manager.add_waitlist_entry(email, default_list["id"])
    if not entry_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already in this list",
        )

    return PendingRegistrationResponse(status="pending")


@router.post("/waitlist/bulk-approve")
async def bulk_approve_waitlist(
    payload: BulkApproveRequest,
    current_user: dict = Depends(get_current_user),
):
    """Approve multiple waitlist entries (admin/master only)."""
    user_manager = get_user_manager()
    user_role = current_user.get("role")
    if user_role not in ["admin", "master"]:
        raise HTTPException(status_code=403, detail="Forbidden")

    created_users = user_manager.bulk_approve_waitlist_entries(
        payload.entry_ids, payload.master_id
    )
    return {"approved": len(created_users), "user_ids": created_users}


@router.post("/waitlist/bulk-reject")
async def bulk_reject_waitlist(
    payload: BulkRejectRequest,
    current_user: dict = Depends(get_current_user),
):
    """Reject multiple waitlist entries (admin/master only)."""
    user_manager = get_user_manager()
    user_role = current_user.get("role")
    if user_role not in ["admin", "master"]:
        raise HTTPException(status_code=403, detail="Forbidden")

    rejected_count = user_manager.bulk_reject_waitlist_entries(payload.entry_ids)
    return {"rejected": rejected_count}


@router.delete("/waitlist/{entry_id}")
async def delete_waitlist_entry(
    entry_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Delete a waitlist entry (admin/master only)."""
    user_manager = get_user_manager()
    user_role = current_user.get("role")
    if user_role not in ["admin", "master"]:
        raise HTTPException(status_code=403, detail="Forbidden")

    success = user_manager.delete_waitlist_entry(entry_id)
    if not success:
        raise HTTPException(status_code=404, detail="Entry not found")

    return {"success": True}


@router.post("/check-email")
async def check_email(payload: CheckEmailRequest):
    """Check whether an email is registered and whether it's a first-time login."""
    email = payload.email.strip().lower()
    user_manager = get_user_manager()
    user = user_manager.get_user_by_email(email)
    if not user:
        return {"status": "not_found"}
    has_password = user.get("has_password", False)
    if has_password:
        return {"status": "normal"}
    reset_info = user.get("reset_code_info", {})
    if reset_info.get("is_valid"):
        return {
            "status": "first_time",
            "user_id": user["id"],
            "suggested_name": user.get("name") or user["id"],
        }
    return {"status": "activation_expired"}


@router.post("/request-activation")
async def request_activation(payload: RequestActivationRequest):
    """Resend activation email with a fresh 7-day reset code.

    Only works for accounts that have no password yet.
    Always returns {"status": "sent"} to avoid user enumeration.
    """
    email = payload.email.strip().lower()
    user_manager = get_user_manager()
    user = user_manager.get_user_by_email(email)

    if not user or user.get("has_password"):
        return {"status": "sent"}

    user_id = user["id"]
    lang = (user.get("profile") or {}).get("language", "en")
    reset_code = user_manager.generate_reset_code(user_id, expiry_days=7)
    if not reset_code:
        return {"status": "sent"}

    from shared.transactional_email import send_welcome_reset_code, _is_configured
    if _is_configured():
        send_welcome_reset_code(email, user.get("name") or user_id, reset_code, lang=lang)

    return {"status": "sent"}


@router.post("/init-password", response_model=TokenResponse)
async def init_password(payload: InitPasswordRequest):
    user_manager = get_user_manager()
    ok = user_manager.reset_password_with_code(
        payload.user_id,
        payload.reset_code,
        payload.new_password,
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid reset code"
        )

    user = user_manager.authenticate_user(payload.user_id, payload.new_password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unable to authenticate user",
        )

    if payload.new_name:
        new_name = payload.new_name.strip()
        if new_name and new_name != user.get("name"):
            existing = user_manager.get_user_by_name(new_name)
            if existing and existing["id"] != user["id"]:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="name_conflict")
            user_manager.update_user(user["id"], name=new_name)
            user = user_manager.get_user(user["id"]) or user

    token = _create_token(user)
    return TokenResponse(access_token=token, user=_to_user_dto(user))


@router.post("/request-password-reset")
async def request_password_reset(payload: RequestPasswordResetRequest):
    user_manager = get_user_manager()
    user = user_manager.get_user(payload.user_id)
    if not user:
        return {"message": "If the user exists, a reset code has been sent"}
    reset_code = user_manager.generate_reset_code(payload.user_id, payload.user_id)
    if not reset_code:
        return {"message": "If the user exists, a reset code has been sent"}
    return {"message": "Reset code generated", "reset_code": reset_code}


@router.get("/me", response_model=UserDTO)
async def me(current_user: dict = Depends(get_current_user)):
    return _to_user_dto(current_user)


class SelectTrainingRequest(BaseModel):
    master_id: str


class EnrollRequest(BaseModel):
    user_id: str
    master_id: Optional[str] = None


@router.get("/enrollments")
async def get_enrollments(current_user: dict = Depends(get_current_user)):
    """Return the list of trainings (masters) the current user is enrolled in."""
    user_manager = get_user_manager()
    enrollments = user_manager.get_user_enrollments(current_user["id"])
    active_master_id = (current_user.get("profile") or {}).get("active_master_id")
    return {"enrollments": enrollments, "active_master_id": active_master_id}


@router.post("/select-training")
async def select_training(
    payload: SelectTrainingRequest,
    current_user: dict = Depends(get_current_user),
):
    """Persist the user's active training (master) choice."""
    user_manager = get_user_manager()
    enrollments = user_manager.get_user_enrollments(current_user["id"])
    enrolled_master_ids = {e["master_id"] for e in enrollments}

    if payload.master_id not in enrolled_master_ids:
        raise HTTPException(status_code=403, detail="Not enrolled in this training")

    success = user_manager.set_active_master(current_user["id"], payload.master_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update active training")

    return {"active_master_id": payload.master_id}


@router.post("/enroll")
async def enroll_user(
    payload: EnrollRequest,
    current_user: dict = Depends(get_current_user),
):
    """Master (or admin) adds an existing normal user to their student roster."""
    user_manager = get_user_manager()
    caller_role = current_user.get("role")

    if caller_role not in ["admin", "master"]:
        raise HTTPException(status_code=403, detail="Forbidden")

    if caller_role == "master":
        master_id = current_user["id"]
        if payload.master_id and payload.master_id != master_id:
            raise HTTPException(status_code=403, detail="Forbidden")
    else:
        if not payload.master_id:
            raise HTTPException(status_code=400, detail="master_id required for admin")
        master = user_manager.get_user(payload.master_id)
        if not master or master.get("role") != "master":
            raise HTTPException(status_code=404, detail="Master not found")
        master_id = payload.master_id

    target = user_manager.get_user(payload.user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.get("role") != "normal":
        raise HTTPException(status_code=400, detail="Can only enroll normal users")

    user_manager.add_enrollment(payload.user_id, master_id)
    return {"user_id": payload.user_id, "master_id": master_id}


@router.get("/masquerade-targets", response_model=list[UserDTO])
async def masquerade_targets(current_user: dict = Depends(get_current_user)):
    user_manager = get_user_manager()
    targets = _get_masquerade_targets(current_user, user_manager)
    return [_to_user_dto(user) for user in targets]


@router.post("/masquerade", response_model=TokenResponse)
async def masquerade(
    payload: MasqueradeRequest, current_user: dict = Depends(get_current_user)
):
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Target user not found"
        )

    token = _create_token(target_user, masquerader_id=effective_masquerader_id)
    return TokenResponse(access_token=token, user=_to_user_dto(target_user))
