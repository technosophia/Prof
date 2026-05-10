"""
User Management UI Module
=========================
"""

import streamlit as st
from shared.common import UserRole
from st_shared.cached import get_user_manager

from st_shared.cached import get_config
from shared.common import set_current_llm, get_current_llm_info
from datetime import datetime, timedelta

from core.logging import log, set_log_module_level
from st_shared.cached import _, get_available_languages


def is_production_mode() -> bool:
    """Check if we're in production mode (not local and not test)."""
    config = get_config()
    prod_mode = config.get("app.prod_mode", False)
    test_mode = config.get("app.test_mode", False) or "pytest" in str(st.__file__)

    # Production mode = not local and not test
    return prod_mode and not test_mode


def apply_user_preferences(user):
    """Apply user's saved preferences to the current session.

    Args:
        user: User dictionary from user manager

    Returns:
        bool: True if any preferences were applied, False otherwise
    """
    if not user:
        return False

    # Import settings manager
    try:
        from st_shared.settings_ui import get_user_settings_manager

        settings_manager = get_user_settings_manager()
    except Exception as e:
        log(
            "warning",
            f"Settings UI module not available for applying preferences: {e}",
            stacktrace=True,
        )
        return False

    applied = False

    # Get user preferences
    preferred_lang, preferred_llm = settings_manager.get_user_preferences(user)

    # Apply language preference
    if preferred_lang and preferred_lang != st.session_state.current_language:
        available_langs = get_available_languages()
        if preferred_lang in available_langs:
            st.session_state.current_language = preferred_lang
            log("info", f"Applied user's preferred language: {preferred_lang}")
            applied = True

    # Apply LLM preference
    if preferred_llm:
        current_llm_info = get_current_llm_info()
        current_llm_id = current_llm_info.get("id") if current_llm_info else None

        if preferred_llm != current_llm_id:
            if set_current_llm(preferred_llm):
                log("info", f"Applied user's preferred LLM: {preferred_llm}")
                applied = True
            else:
                log("warning", f"Failed to apply user's preferred LLM: {preferred_llm}")

    return applied


def auto_login_first_user():
    """Automatically log in the first available user if none is logged in."""
    if st.session_state.user_manually_logged_out:
        log("debug", "Skipping auto-login: user manually logged out")
        return False

    # In production mode, auto-login is disabled
    if is_production_mode():
        log("debug", "Production mode: auto-login disabled")
        return False

    if not st.session_state.current_user:
        try:
            # Check if auto-login is enabled in config
            if not get_config().get("app.auto_login", False):
                log("debug", "Auto-login disabled in configuration")
                return False

            # Get the specified auto-login user from config
            auto_login_user_id = get_config().get("app.auto_login_user")

            if not auto_login_user_id:
                log("warning", "Auto-login enabled but no user specified in config")
                return False

            # Get user manager
            user_manager = get_user_manager()

            # Try to find the specified user
            target_user = user_manager.get_user(auto_login_user_id)

            if not target_user:
                log("warning", f"Auto-login user '{auto_login_user_id}' not found")

                # Fallback: try to find any user (original behavior)
                all_users = user_manager.get_all_users_dict()
                if all_users:
                    # Try to find an admin first, then master, then any user
                    admin_users = [
                        u
                        for u in all_users.values()
                        if u.get("role") == UserRole.ADMIN.value
                    ]
                    master_users = [
                        u
                        for u in all_users.values()
                        if u.get("role") == UserRole.MASTER.value
                    ]

                    if admin_users:
                        target_user = admin_users[0]
                    elif master_users:
                        target_user = master_users[0]
                    else:
                        target_user = list(all_users.values())[0]

                    log(
                        "info",
                        f"Falling back to auto-login with user: {target_user['name']}",
                    )
                else:
                    log("warning", "No users available for auto-login")
                    return False

            # Set as current user
            st.session_state.current_user = target_user

            # Apply user preferences
            apply_user_preferences(target_user)

            # Update last login
            user_manager.update_last_login(target_user["id"])

            # Set the flag to show this was an auto-login
            st.session_state.just_auto_logged_in = True

            log(
                "info",
                f"Auto-logged in user: {target_user['name']} ({target_user['role']})",
            )
            return True

        except Exception as e:
            log("error", f"Auto-login failed: {e}")
            return False
    else:
        log("debug", "User already logged in, skipping auto-login")
        return False


def render_login_form(form_key="login_form"):
    """Render login form for production mode."""
    st.subheader("🔐 Login")

    user_manager = get_user_manager()

    with st.form(key=form_key):
        # Text input for username
        username = st.text_input(
            "Username", key=f"{form_key}_username", placeholder="Enter username"
        )

        password = st.text_input(
            "Password", type="password", key=f"{form_key}_password"
        )

        col1, col2 = st.columns(2)
        with col1:
            login_submit = st.form_submit_button(
                "Login", type="primary", width="stretch"
            )
        with col2:
            reset_request = st.form_submit_button("Forgot Password?", width="stretch")

        if login_submit:
            if username and password:
                # Authenticate with username (not ID)
                user = user_manager.authenticate_user(username, password)

                if user:
                    st.session_state.user_manually_logged_out = False
                    st.session_state.current_user = user

                    # Apply user preferences when logging in
                    apply_user_preferences(user)

                    log("info", f"User logged in: {user['name']}")
                    st.rerun()
                else:
                    st.error("❌ Invalid username or password")
            else:
                st.warning("Please enter both username and password")

        if reset_request:
            st.session_state.show_reset_password_form = True
            st.rerun()


def render_reset_password_form(form_key="reset_form"):
    """Render password reset form."""
    st.subheader("🔑 Reset Password")

    with st.form(key=form_key):
        username = st.text_input("Username", key=f"{form_key}_username")
        reset_code_input = st.text_input("Reset Code", key=f"{form_key}_code")
        new_password = st.text_input(
            "New Password", type="password", key=f"{form_key}_new_pw"
        )
        confirm_password = st.text_input(
            "Confirm New Password", type="password", key=f"{form_key}_confirm_pw"
        )

        col1, col2 = st.columns(2)
        with col1:
            reset_submit = st.form_submit_button(
                "Reset Password", type="primary", use_container_width=True
            )
        with col2:
            back_to_login = st.form_submit_button(
                "Back to Login", use_container_width=True
            )

        if reset_submit:
            if not username or not new_password:
                st.warning("Please fill in username and new password")
            elif new_password != confirm_password:
                st.warning("Passwords do not match")
            else:
                user_manager = get_user_manager()

                # Special handling for admin username
                if username.lower() == "admin":
                    # If user provided a reset code, use it directly
                    if reset_code_input:
                        code_to_use = reset_code_input
                    else:
                        # No code provided - generate a new one for admin
                        try:
                            import os
                            from datetime import datetime

                            # Find the admin user
                            admin_user = user_manager.get_user_by_name("admin")
                            if not admin_user:
                                # Try to find any admin user
                                admin_users = user_manager.get_users_by_role(
                                    UserRole.ADMIN.value
                                )
                                if admin_users:
                                    admin_user = admin_users[0]

                            if not admin_user:
                                st.error("❌ No admin user found in the system")
                                return

                            # Generate a new reset code
                            new_code = user_manager.generate_reset_code(
                                admin_user["id"], admin_user["id"]
                            )

                            if new_code:
                                # Save to file in root directory
                                reset_code_file = "reset_code.txt"
                                try:
                                    with open(reset_code_file, "w") as f:
                                        f.write(new_code)

                                    st.success(
                                        "✅ A new reset code has been generated!"
                                    )
                                    st.info(
                                        f"📁 Reset code saved to: {os.path.abspath(reset_code_file)}"
                                    )
                                    st.info(
                                        "🔑 Please check this file and enter the code in the 'Reset Code' field above."
                                    )

                                    # Don't auto-fill the code - user needs to enter it manually
                                    # This is intentional for security

                                except Exception as e:
                                    st.error(
                                        f"❌ Failed to save reset code to file: {str(e)}"
                                    )
                                    # Still show the code as fallback (only in non-prod?)
                                    st.info(f"🔑 Reset code: {new_code}")

                                # Don't proceed with reset yet - user needs to submit again with the code
                                st.warning(
                                    "⚠️ Please copy the reset code from the file and submit the form again."
                                )
                                return
                            else:
                                st.error("❌ Failed to generate reset code for admin")
                                return

                        except Exception as e:
                            st.error(f"❌ Error in admin recovery: {str(e)}")
                            return
                else:
                    # Non-admin user - must provide reset code
                    if not reset_code_input:
                        st.warning("Please enter a reset code")
                        return
                    code_to_use = reset_code_input

                # If we get here, we have a code to use (either from input or from admin flow with code provided)
                if username.lower() == "admin" and reset_code_input:
                    code_to_use = reset_code_input

                # Attempt to reset password
                success = user_manager.reset_password_with_code(
                    username, code_to_use, new_password
                )

                if success:
                    st.success("✅ Password reset successfully! You can now login.")

                    # Clean up reset code file for admin after successful reset
                    if username.lower() == "admin":
                        try:
                            reset_code_file = "reset_code.txt"
                            if os.path.exists(reset_code_file):
                                os.remove(reset_code_file)
                        except Exception:
                            pass

                    st.session_state.show_reset_password_form = False
                    st.rerun()
                else:
                    st.error(
                        "❌ Invalid username or reset code. Please check and try again."
                    )

        if back_to_login:
            st.session_state.show_reset_password_form = False
            st.rerun()


def inject_ui_sidebar():
    """Render user management section in the sidebar."""
    st.title("👤 User Management")

    production_mode = is_production_mode()

    if production_mode:
        # Production mode - show login if no user
        if not st.session_state.current_user:
            if st.button("🔐 Login", type="primary", width="stretch"):
                st.session_state.show_login_form = True
                st.rerun()
            return True

    # Current user info
    if st.session_state.current_user:
        current_user = st.session_state.current_user
        role = current_user.get("role", "normal")
        role_emoji = (
            "👑"
            if role == UserRole.ADMIN.value
            else "⭐"
            if role == UserRole.MASTER.value
            else "👤"
        )

        st.info(f"**Current User:** {current_user['name']} {role_emoji}")
        col1, col2 = st.columns(2)
        col1.caption(f"Role: {role.capitalize()}")

        if current_user.get("parent_name"):
            col2.caption(f"Parent: {current_user['parent_name']}")

        # Training switcher — only for normal users enrolled in multiple masters
        if role == UserRole.NORMAL.value:
            enrollments = get_user_manager().get_user_enrollments(current_user["id"])
            if len(enrollments) > 1:
                profile = current_user.get("profile") or {}
                active_master_id = profile.get("active_master_id") or current_user.get("parent_id")
                master_ids = [e["master_id"] for e in enrollments]
                master_names = {e["master_id"]: e["master_name"] for e in enrollments}
                current_idx = master_ids.index(active_master_id) if active_master_id in master_ids else 0

                selected = st.selectbox(
                    "🎓 Training",
                    options=master_ids,
                    format_func=lambda x: master_names.get(x, x),
                    index=current_idx,
                    key="training_switcher",
                )
                if selected != active_master_id:
                    get_user_manager().set_active_master(current_user["id"], selected)
                    updated = get_user_manager().get_user(current_user["id"])
                    if updated:
                        st.session_state.current_user = updated
                    st.rerun()

        # Logout button
        if st.button("🚪 Logout", width="stretch"):
            user_manager = get_user_manager()
            user_manager.log_user_action(user_id=current_user["id"], action="logout")
            st.session_state.user_manually_logged_out = True
            st.session_state.current_user = None
            st.session_state.current_conversation_id = None
            st.session_state.conversation_messages = []
            st.rerun()

    else:
        if production_mode:
            # In production mode, no user is logged in - show nothing
            st.warning("Please log in to continue")
        else:
            # Local/test mode - user selector
            st.warning("No user selected")

            # User selector for local/test mode
            all_users = get_user_manager().get_all_users_dict()
            if all_users:
                user_options = ["Select a user..."] + list(all_users.keys())
                user_display = ["Select a user..."] + [
                    f"{user['name']} ({user.get('role', 'normal')})"
                    for user_id, user in all_users.items()
                ]

                selected_user = st.selectbox(
                    "Choose user",
                    options=user_options,
                    format_func=lambda x: user_display[user_options.index(x)]
                    if x in user_options
                    else x,
                    key="user_selector",
                )

                if selected_user != "Select a user..." and selected_user:
                    if st.button("Login as User", width="stretch"):
                        st.session_state.user_manually_logged_out = False
                        st.session_state.current_user = all_users[selected_user]
                        apply_user_preferences(st.session_state.current_user)
                        get_user_manager().update_last_login(selected_user)
                        log(
                            "info",
                            f"User logged in: {st.session_state.current_user['name']}",
                        )
                        st.rerun()

    return True


def render_user_form():
    """Render the user creation/editing form."""
    current_user = st.session_state.get("current_user")
    production_mode = is_production_mode()

    if production_mode and not current_user:
        st.error("You must be logged in to create users.")
        return

    can_create = False
    if production_mode:
        # In production mode, only admin and master can create users
        can_create = current_user and current_user.get("role") in [
            UserRole.ADMIN.value,
            UserRole.MASTER.value,
        ]
    else:
        # In local/test mode, anyone with admin/master role can create
        can_create = current_user and current_user.get("role") in [
            UserRole.ADMIN.value,
            UserRole.MASTER.value,
        ]

    if not can_create and not st.session_state.edit_user_id:
        st.error("You don't have permission to create users.")
        return

    st.divider()
    is_editing = bool(st.session_state.edit_user_id)
    st.subheader("👤 " + ("Edit User Profile" if is_editing else "Create New User"))

    # Use a unique form key
    form_key = f"user_form_{st.session_state.edit_user_id if is_editing else 'new'}"

    with st.form(key=form_key):
        if is_editing:
            user = get_user_manager().get_user(st.session_state.edit_user_id)
            if not user:
                st.error("User not found")
                return
            default_name = user["name"]
            default_email = user.get("email", "")
            current_role = user.get("role", UserRole.NORMAL.value)
        else:
            default_name = ""
            default_email = ""
            current_role = UserRole.NORMAL.value

        name = st.text_input("Username *", value=default_name)
        email = st.text_input("Email", value=default_email)

        # Password handling for new users in production mode
        set_password = None
        generate_reset = False

        if production_mode and not is_editing:
            st.write("**Password Setup**")
            col_pw1, col_pw2 = st.columns(2)
            with col_pw1:
                set_password = st.text_input(
                    "Set Password (optional)",
                    type="password",
                    help="Leave empty to generate a reset code",
                )
            with col_pw2:
                confirm_password = st.text_input("Confirm Password", type="password")
        elif (
            production_mode
            and is_editing
            and current_user.get("role") == UserRole.ADMIN.value
        ):
            # Admin can reset password for users
            if st.checkbox("Reset user's password", key=f"reset_pw_check_{user['id']}"):
                col_reset1, col_reset2 = st.columns(2)
                with col_reset1:
                    new_pw = st.text_input(
                        "New Password",
                        type="password",
                        key=f"admin_new_pw_{user['id']}",
                    )
                with col_reset2:
                    confirm_new_pw = st.text_input(
                        "Confirm New Password",
                        type="password",
                        key=f"admin_confirm_pw_{user['id']}",
                    )

        # Role selection
        if current_user and current_user.get("role") == UserRole.ADMIN.value:
            if is_editing:
                # Can change role for any user except maybe themselves?
                available_roles = [
                    UserRole.ADMIN.value,
                    UserRole.MASTER.value,
                    UserRole.NORMAL.value,
                ]
                role = st.selectbox(
                    "Role",
                    available_roles,
                    index=available_roles.index(current_role)
                    if current_role in available_roles
                    else 0,
                )
            else:
                # For new users, admin can choose any role
                available_roles = [
                    UserRole.ADMIN.value,
                    UserRole.MASTER.value,
                    UserRole.NORMAL.value,
                ]
                role = st.selectbox("Role", available_roles)
        elif current_user and current_user.get("role") == UserRole.MASTER.value:
            # Master can only create normal users
            role = UserRole.NORMAL.value
            if is_editing and current_role != UserRole.NORMAL.value:
                # Can't edit role of non-normal users
                st.caption(f"Role: {current_role} (cannot change)")
            else:
                st.caption(f"Role: {role}")
        else:
            role = current_role
            st.caption(f"Role: {role}")

        # Parent selection for normal users
        selected_parent = None
        if role == UserRole.NORMAL.value or (
            is_editing and current_role == UserRole.NORMAL.value
        ):
            if current_user:
                if current_user.get("role") == UserRole.ADMIN.value:
                    masters = get_user_manager().get_users_by_role(
                        UserRole.MASTER.value
                    )
                    parent_options = [("", "Select a master...")] + [
                        (m["id"], m["name"]) for m in masters
                    ]
                elif current_user.get("role") == UserRole.MASTER.value:
                    parent_options = [(current_user["id"], current_user["name"])]
                else:
                    parent_options = []

                if parent_options:
                    parent_options_dict = dict(parent_options)
                    default_parent = user.get("parent_id", "") if is_editing else ""
                    selected_parent = st.selectbox(
                        "Parent (Master) *",
                        options=list(parent_options_dict.keys()),
                        format_func=lambda x: parent_options_dict[x],
                        index=list(parent_options_dict.keys()).index(default_parent)
                        if default_parent in parent_options_dict
                        else 0,
                        help="Normal users must have a master as parent",
                    )
                else:
                    st.error("No masters available to be parent")
                    selected_parent = None

        # Profile preferences
        st.subheader("Profile Preferences")
        preference_schema = get_user_manager().get_profile_preferences_schema()

        # Language
        current_profile = user.get("profile", {}) if is_editing else {}
        current_lang = current_profile.get("language", "en")
        language = st.selectbox(
            "Preferred Language",
            preference_schema["language"]["options"],
            index=preference_schema["language"]["options"].index(current_lang)
            if current_lang in preference_schema["language"]["options"]
            else 0,
        )

        col1, col2 = st.columns(2)
        with col1:
            submit = st.form_submit_button("💾 Save", type="primary", width="stretch")
        with col2:
            cancel = st.form_submit_button("❌ Cancel", width="stretch")

        if submit:
            if not name.strip():
                st.error("Username is required")
            elif role == UserRole.NORMAL.value and not selected_parent:
                st.error("Normal users must have a parent!")
            else:
                try:
                    # Build profile
                    profile = {"language": language}

                    user_manager = get_user_manager()

                    if is_editing:
                        # Update existing user
                        updates = {
                            "name": name.strip(),
                            "email": email.strip() if email else None,
                            "profile": profile,
                        }

                        # Add role if admin editing
                        if (
                            current_user
                            and current_user.get("role") == UserRole.ADMIN.value
                        ):
                            updates["role"] = role
                            if role == UserRole.NORMAL.value:
                                updates["parent_id"] = selected_parent
                            else:
                                updates["parent_id"] = None

                        # Handle password reset by admin
                        if (
                            production_mode
                            and current_user.get("role") == UserRole.ADMIN.value
                        ):
                            if st.session_state.get(
                                f"reset_pw_check_{user['id']}", False
                            ):
                                if new_pw and new_pw == confirm_new_pw:
                                    user_manager.set_password(
                                        st.session_state.edit_user_id,
                                        new_pw,
                                        current_user["id"],
                                    )
                                    st.success("✅ Password updated!")

                        success = user_manager.update_user(
                            st.session_state.edit_user_id,
                            current_user["id"] if current_user else None,
                            **updates,
                        )

                        if success:
                            st.success("✅ Profile updated successfully!")
                            # Update current user if editing self
                            if (
                                current_user
                                and current_user["id"] == st.session_state.edit_user_id
                            ):
                                updated_user = user_manager.get_user(
                                    st.session_state.edit_user_id
                                )
                                if updated_user:
                                    st.session_state.current_user = updated_user
                                    # Apply updated preferences
                                    apply_user_preferences(updated_user)
                            log("info", f"User profile updated: {name}")
                        else:
                            st.error("❌ Failed to update user (permission denied)")
                    else:
                        # Create new user
                        password_to_set = (
                            set_password if production_mode and set_password else None
                        )

                        user_id, reset_code = user_manager.create_user(
                            name=name.strip(),
                            role=role,
                            email=email.strip() if email else None,
                            parent_id=selected_parent if selected_parent else None,
                            profile=profile,
                            password=password_to_set,
                            requesting_user_id=current_user["id"]
                            if current_user
                            else None,
                        )

                        if production_mode and not password_to_set and reset_code:
                            st.success(f"✅ User created successfully!")
                            # Save reset code to file instead of displaying it
                            try:
                                with open(f"reset_code_{name.strip()}.txt", "w") as f:
                                    f.write(reset_code)
                                st.info(
                                    f"🔑 A reset code has been saved to reset_code_{name.strip()}.txt"
                                )
                            except Exception as e:
                                st.error(f"Failed to save reset code: {e}")
                            st.warning("⚠️ This code will expire in 24 hours.")

                        log("info", f"User created: {name} (ID: {user_id})")

                    # Reset form state
                    st.session_state.show_user_form = False
                    st.session_state.edit_user_id = None
                    st.rerun()
                except ValueError as e:
                    st.error(f"❌ Validation error: {str(e)}")
                except Exception as e:
                    st.error(f"❌ Error: {str(e)}")
                    log("error", f"User form error: {str(e)}")

        if cancel:
            st.session_state.show_user_form = False
            st.session_state.edit_user_id = None
            st.rerun()


def inject_ui_main_header():
    """Render user info in the main header."""
    production_mode = is_production_mode()

    # Only show header content if user is logged in
    if st.session_state.current_user:
        if "just_auto_logged_in" not in st.session_state:
            st.session_state.just_auto_logged_in = False

        current_user = st.session_state.current_user
        role = current_user.get("role", "normal")
        role_text = {
            UserRole.ADMIN.value: "Administrator",
            UserRole.MASTER.value: "Master",
            UserRole.NORMAL.value: "User",
        }.get(role, "User")

        if st.session_state.just_auto_logged_in:
            st.success(
                f"👋 Welcome, **{current_user['name']}**! ({role_text}) - Auto-logged in"
            )
            st.session_state.just_auto_logged_in = False
        else:
            st.success(f"✅ Logged in as: **{current_user['name']}** ({role_text})")

        # Show parent info if applicable
        if current_user.get("parent_name"):
            st.caption(f"👨‍👦 Managed by: {current_user['parent_name']}")

        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            if st.button("👤 Profile", key="profile_header_btn", width="stretch"):
                st.session_state.edit_user_id = current_user["id"]
                st.session_state.show_user_form = True
                st.rerun()
        with col2:
            if st.button("⚙️ Settings", key="settings_header_btn", width="stretch"):
                st.session_state.current_page = "settings"
                st.rerun()
        with col3:
            if st.button("🚪 Logout", key="logout_header_btn", width="stretch"):
                user_manager = get_user_manager()
                user_manager.log_user_action(
                    user_id=current_user["id"], action="logout"
                )
                st.session_state.user_manually_logged_out = True
                st.session_state.current_user = None
                st.session_state.current_conversation_id = None
                st.session_state.conversation_messages = []
                st.rerun()
        return True
    else:
        if not production_mode:
            st.warning(
                "👤 Please select or create a user from the sidebar to start conversations."
            )
        return True


def inject_ui_main_content():
    """Render content when no user is logged in."""
    production_mode = is_production_mode()

    if production_mode and not st.session_state.current_user:
        # Render login or reset form in main content area
        if st.session_state.get("show_reset_password_form", False):
            render_reset_password_form("main_reset_form")
        else:
            render_login_form("main_login_form")
        return True

    if not st.session_state.current_user and st.session_state.show_user_form:
        render_user_form()
        return True

    return False


def inject_ui_initialize():
    """Initialize session state for user management."""
    if "current_user" not in st.session_state:
        st.session_state.current_user = None
    if "show_user_form" not in st.session_state:
        st.session_state.show_user_form = False
    if "edit_user_id" not in st.session_state:
        st.session_state.edit_user_id = None
    if "just_auto_logged_in" not in st.session_state:
        st.session_state.just_auto_logged_in = False
    if "user_manually_logged_out" not in st.session_state:
        st.session_state.user_manually_logged_out = False
    if "show_login_form" not in st.session_state:
        st.session_state.show_login_form = True
    if "show_reset_password_form" not in st.session_state:
        st.session_state.show_reset_password_form = False

    log("debug", "Users UI module initialized")
