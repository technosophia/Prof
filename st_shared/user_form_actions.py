"""Persistence handlers for the user creation / edit form."""

import streamlit as st
from typing import Any, Dict, Optional, Tuple

from core.logging import log
from shared.common import UserRole
from st_shared.cached import get_user_manager


def _handle_user_update(
    name: str,
    email: str,
    role: str,
    selected_parent: Optional[str],
    language: str,
    edit_user_id: str,
    current_user: Dict[str, Any],
    production_mode: bool,
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Persist changes to an existing user. Returns (success, updated_user_if_self)."""
    user_manager = get_user_manager()
    updates: Dict[str, Any] = {
        "name": name.strip(),
        "email": email.strip() if email else None,
        "profile": {"language": language},
    }
    if current_user and current_user.get("role") == UserRole.ADMIN.value:
        updates["role"] = role
        updates["parent_id"] = selected_parent if role == UserRole.NORMAL.value else None

    if production_mode and current_user.get("role") == UserRole.ADMIN.value:
        if st.session_state.get(f"reset_pw_check_{edit_user_id}", False):
            new_pw = st.session_state.get(f"admin_new_pw_{edit_user_id}", "")
            confirm_new_pw = st.session_state.get(f"admin_confirm_pw_{edit_user_id}", "")
            if new_pw and new_pw == confirm_new_pw:
                user_manager.set_password(edit_user_id, new_pw, current_user["id"])
                st.success("✅ Password updated!")

    success = user_manager.update_user(
        edit_user_id, current_user["id"] if current_user else None, **updates
    )
    if not success:
        st.error("❌ Failed to update user (permission denied)")
        return False, None

    st.success("✅ Profile updated successfully!")
    log("info", f"User profile updated: {name}")
    if current_user and current_user["id"] == edit_user_id:
        return True, user_manager.get_user(edit_user_id)
    return True, None


def _handle_user_create(
    name: str,
    email: str,
    role: str,
    selected_parent: Optional[str],
    language: str,
    set_password: Optional[str],
    current_user: Dict[str, Any],
    production_mode: bool,
) -> None:
    """Create a new user and display confirmation / reset-code info."""
    user_manager = get_user_manager()
    password_to_set = set_password if production_mode and set_password else None
    user_id, reset_code = user_manager.create_user(
        name=name.strip(),
        role=role,
        email=email.strip() if email else None,
        parent_id=selected_parent or None,
        profile={"language": language},
        password=password_to_set,
        requesting_user_id=current_user["id"] if current_user else None,
    )
    if production_mode and not password_to_set and reset_code:
        st.success("✅ User created successfully!")
        try:
            with open(f"reset_code_{name.strip()}.txt", "w") as f:
                f.write(reset_code)
            st.info(f"🔑 A reset code has been saved to reset_code_{name.strip()}.txt")
        except Exception as e:
            st.error(f"Failed to save reset code: {e}")
        st.warning("⚠️ This code will expire in 24 hours.")
    log("info", f"User created: {name} (ID: {user_id})")
