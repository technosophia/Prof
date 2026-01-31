"""
User Management UI Module
=========================
"""

import streamlit as st
from shared.users import user_manager, UserRole
from shared.logging import log

def auto_login_first_user():
    """Automatically log in the first available user if none is logged in."""
    if st.session_state.user_manually_logged_out:
        log("debug", "Skipping auto-login: user manually logged out")
        return False

    if not st.session_state.current_user:
        try:
            # Get all users
            all_users = user_manager.get_all_users_dict()

            if all_users:
                # Try to find an admin first, then master, then any user
                admin_users = [u for u in all_users.values() if u.get('role') == UserRole.ADMIN.value]
                master_users = [u for u in all_users.values() if u.get('role') == UserRole.MASTER.value]

                if admin_users:
                    first_user = admin_users[0]
                elif master_users:
                    first_user = master_users[0]
                else:
                    first_user = list(all_users.values())[0]

                # Set as current user
                st.session_state.current_user = first_user

                # Update last login
                user_manager.update_last_login(first_user['id'])

                # Set the flag to show this was an auto-login
                st.session_state.just_auto_logged_in = True

                log("info", f"Auto-logged in user: {first_user['name']} ({first_user['role']})")
                return True
            else:
                log("warning", "No users available for auto-login")
                return False
        except Exception as e:
            log("error", f"Auto-login failed: {e}")
            return False
    return True

def inject_ui_sidebar():
    """Render user management section in the sidebar."""
    st.title("👤 User Management")

    # Current user info
    if st.session_state.current_user:
        current_user = st.session_state.current_user
        role = current_user.get('role', 'normal')
        role_emoji = "👑" if role == UserRole.ADMIN.value else "⭐" if role == UserRole.MASTER.value else "👤"

        st.info(f"**Current User:** {current_user['name']} {role_emoji}")
        col1, col2 = st.columns(2)
        col1.caption(f"Role: {role.capitalize()}")

        if current_user.get('parent_name'):
            col2.caption(f"Parent: {current_user['parent_name']}")

        # Switch user button
        if st.button("Switch User"):
            st.session_state.user_manually_logged_out = True
            st.session_state.current_user = None
            st.session_state.current_conversation_id = None
            st.session_state.conversation_messages = []
            st.rerun()
    else:
        st.warning("No user selected")

        # User selector
        all_users = user_manager.get_all_users_dict()
        if all_users:
            # Filter users based on hierarchy if needed
            filtered_users = all_users

            user_options = ["Select a user..."] + list(filtered_users.keys())
            user_display = ["Select a user..."] + [
                f"{user['name']} ({user.get('role', 'normal')})"
                for user_id, user in filtered_users.items()
            ]

            selected_user = st.selectbox(
                "Choose user",
                options=user_options,
                format_func=lambda x: user_display[user_options.index(x)] if x in user_options else x,
                key="user_selector"
            )

            if selected_user != "Select a user..." and selected_user:
                if st.button("Login as User"):
                    st.session_state.user_manually_logged_out = False
                    st.session_state.current_user = filtered_users[selected_user]

                    # Update last login
                    user_manager.update_last_login(selected_user)

                    log("info", f"User logged in: {st.session_state.current_user['name']}")
                    st.rerun()
        else:
            st.info("No users found. Please create a user first.")

    # Create new user button (only for admin and master)
    current_user = st.session_state.get('current_user')
    if current_user and current_user.get('role') in [UserRole.ADMIN.value, UserRole.MASTER.value]:
        if st.button("➕ Create New User", type="primary"):
            st.session_state.show_user_form = True
            st.session_state.edit_user_id = None

    return True

def inject_ui_main_header():
    """Render user info in the main header."""
    if "just_auto_logged_in" not in st.session_state:
        st.session_state.just_auto_logged_in = False

    if st.session_state.current_user:
        current_user = st.session_state.current_user
        role = current_user.get('role', 'normal')
        role_text = {
            UserRole.ADMIN.value: "Administrator",
            UserRole.MASTER.value: "Master",
            UserRole.NORMAL.value: "User"
        }.get(role, "User")

        if st.session_state.just_auto_logged_in:
            st.success(f"👋 Welcome, **{current_user['name']}**! ({role_text}) - Auto-logged in")
            st.session_state.just_auto_logged_in = False
        else:
            st.success(f"✅ Logged in as: **{current_user['name']}** ({role_text})")

        # Show parent info if applicable
        if current_user.get('parent_name'):
            st.caption(f"👨‍👦 Managed by: {current_user['parent_name']}")

        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            if st.button("👤 Profile", key="profile_header_btn"):
                st.session_state.edit_user_id = current_user['id']
                st.session_state.show_user_form = True
                st.rerun()
        with col2:
            if st.button("🔄 Switch User", key="switch_header_btn"):
                st.session_state.user_manually_logged_out = True
                st.session_state.current_user = None
                st.session_state.current_conversation_id = None
                st.session_state.conversation_messages = []
                st.rerun()
        with col3:
            if st.button("🚪 Logout", key="logout_header_btn"):
                st.session_state.user_manually_logged_out = True
                st.session_state.current_user = None
                st.session_state.current_conversation_id = None
                st.session_state.conversation_messages = []
                st.rerun()
        return True
    else:
        st.warning("👤 Please select or create a user from the sidebar to start conversations.")
        return True

def inject_ui_main_content():
    """Render content when no user is logged in."""
    if not st.session_state.current_user:
        if st.session_state.show_user_form:
            render_user_form()
            return True
    return False

def render_user_form():
    """Render the user creation/editing form."""
    current_user = st.session_state.get('current_user')
    can_create = current_user and current_user.get('role') in [UserRole.ADMIN.value, UserRole.MASTER.value]

    if not can_create and not st.session_state.edit_user_id:
        st.error("You don't have permission to create users.")
        return

    st.divider()
    is_editing = bool(st.session_state.edit_user_id)
    st.subheader("👤 " + ("Edit User Profile" if is_editing else "Create New User"))

    with st.form("user_form"):
        if is_editing:
            user = user_manager.get_user(st.session_state.edit_user_id)
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

        name = st.text_input("Name *", value=default_name)
        email = st.text_input("Email", value=default_email)

        # Role selection (only for admin creating users)
        if current_user and current_user.get('role') == UserRole.ADMIN.value and not is_editing:
            available_roles = [UserRole.MASTER.value, UserRole.NORMAL.value]
            role = st.selectbox("Role", available_roles)
        else:
            role = current_role
            st.caption(f"Role: {role}")

        # Parent selection for normal users
        if role == UserRole.NORMAL.value:
            if current_user:
                if current_user.get('role') == UserRole.ADMIN.value:
                    masters = user_manager.get_users_by_role(UserRole.MASTER.value)
                    parent_options = [("", "Select a master...")] + [(m["id"], m["name"]) for m in masters]
                else:  # Master
                    parent_options = [(current_user["id"], current_user["name"])]

                parent_options_dict = dict(parent_options)
                selected_parent = st.selectbox(
                    "Parent (Master) *",
                    options=list(parent_options_dict.keys()),
                    format_func=lambda x: parent_options_dict[x],
                    help="Normal users must have a master as parent"
                )
            else:
                selected_parent = None
        else:
            selected_parent = None

        # Profile preferences
        st.subheader("Profile Preferences")
        preference_schema = user_manager.get_profile_preferences_schema()

        # Language
        current_profile = user.get('profile', {}) if is_editing else {}
        current_lang = current_profile.get('language', 'en')
        language = st.selectbox(
            "Preferred Language",
            preference_schema["language"]["options"],
            index=preference_schema["language"]["options"].index(current_lang)
            if current_lang in preference_schema["language"]["options"] else 0
        )

        col1, col2 = st.columns(2)
        with col1:
            submit = st.form_submit_button("💾 Save", type="primary")
        with col2:
            cancel = st.form_submit_button("❌ Cancel")

        if submit:
            if not name.strip():
                st.error("Name is required")
            elif role == UserRole.NORMAL.value and not selected_parent:
                st.error("Normal users must have a parent!")
            else:
                try:
                    # Build profile
                    profile = {"language": language}

                    if is_editing:
                        # Update existing user
                        updates = {
                            "name": name.strip(),
                            "email": email.strip() if email else None,
                            "profile": profile
                        }

                        # Add role if admin editing
                        if current_user and current_user.get('role') == UserRole.ADMIN.value:
                            updates["role"] = role
                            if role == UserRole.NORMAL.value:
                                updates["parent_id"] = selected_parent

                        success = user_manager.update_user(
                            st.session_state.edit_user_id,
                            current_user['id'] if current_user else None,
                            **updates
                        )

                        if success:
                            st.success("✅ Profile updated successfully!")
                            # Update current user if editing self
                            if current_user and current_user['id'] == st.session_state.edit_user_id:
                                updated_user = user_manager.get_user(st.session_state.edit_user_id)
                                if updated_user:
                                    st.session_state.current_user = updated_user
                            log("info", f"User profile updated: {name}")
                        else:
                            st.error("❌ Failed to update user (permission denied)")
                    else:
                        # Create new user
                        user_id = user_manager.create_user(
                            name=name.strip(),
                            role=role,
                            email=email.strip() if email else None,
                            parent_id=selected_parent if selected_parent else None,
                            profile=profile
                        )
                        st.success(f"✅ User created successfully! ID: {user_id}")
                        log("info", f"User created: {name} (ID: {user_id})")

                        # Auto-login the newly created user if no user is logged in
                        if not st.session_state.current_user:
                            st.session_state.user_manually_logged_out = False
                            new_user = user_manager.get_user(user_id)
                            if new_user:
                                st.session_state.current_user = new_user
                                st.session_state.just_auto_logged_in = True
                                log("info", f"Auto-logged in newly created user: {name}")

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
