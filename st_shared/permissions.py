"""Pure permission functions for role-based access control in the admin UI.

Each function returns a bool (or a structured result) given only plain dicts —
no Streamlit state, no DB calls, no side effects.
"""

from typing import Any, Dict, List

from shared.users import UserRole


def can_access_admin_tab(user: Dict[str, Any]) -> bool:
    if not user:
        return False
    return user.get("role") in [UserRole.ADMIN.value, UserRole.MASTER.value]


def can_see_admin_only_tabs(user: Dict[str, Any]) -> bool:
    """Import/Export and Email Templates tabs are visible only to admins."""
    if not user:
        return False
    return user.get("role") == UserRole.ADMIN.value


def can_delete_user(
    current_user: Dict[str, Any], target_user: Dict[str, Any]
) -> tuple[bool, str]:
    """Return (allowed, reason) for deleting target_user."""
    if target_user["id"] == current_user["id"]:
        return False, "Cannot delete yourself"
    if (
        target_user["role"] == UserRole.ADMIN.value
        and current_user["role"] != UserRole.ADMIN.value
    ):
        return False, "Only admin can delete other admins"
    return True, f"Delete user {target_user['name']}"


def can_generate_reset_code(
    current_user: Dict[str, Any], target_user: Dict[str, Any]
) -> bool:
    """Admin can reset anyone; master only resets their own normal children."""
    role = current_user.get("role")
    if role == UserRole.ADMIN.value:
        return True
    if role == UserRole.MASTER.value:
        return (
            target_user.get("role") == UserRole.NORMAL.value
            and target_user.get("parent_id") == current_user["id"]
        )
    return False


def can_remove_enrollment(
    current_user: Dict[str, Any], enrollment: Dict[str, Any]
) -> bool:
    """Admin can remove any enrollment; master can only remove their own."""
    role = current_user.get("role")
    if role == UserRole.ADMIN.value:
        return True
    if role == UserRole.MASTER.value:
        return enrollment.get("master_id") == current_user["id"]
    return False


def get_enrollable_masters(
    current_user: Dict[str, Any],
    all_masters: List[Dict[str, Any]],
    already_enrolled_ids: set,
) -> List[Dict[str, Any]]:
    """Masters available to be added to an enrollment, filtered by caller role."""
    role = current_user.get("role")
    if role == UserRole.ADMIN.value:
        return [m for m in all_masters if m["id"] not in already_enrolled_ids]
    if role == UserRole.MASTER.value:
        return [
            m
            for m in all_masters
            if m["id"] == current_user["id"] and m["id"] not in already_enrolled_ids
        ]
    return []


def can_edit_role_and_id(
    current_user: Dict[str, Any], target_user: Dict[str, Any]
) -> bool:
    """Only admin can change another user's role or ID; never on self."""
    return (
        current_user.get("role") == UserRole.ADMIN.value
        and target_user["id"] != current_user["id"]
    )


def can_toggle_active_status(
    current_user: Dict[str, Any], target_user: Dict[str, Any]
) -> bool:
    """Admin and master can toggle active status, but not on themselves."""
    return current_user.get("role") in [
        UserRole.ADMIN.value,
        UserRole.MASTER.value,
    ] and target_user["id"] != current_user["id"]
