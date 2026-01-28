"""
User Management UI Module
=========================

This module provides UI components for user management that can be injected
into the main application through the UI registry system.
"""

import streamlit as st
from shared.users import user_manager
from shared.logging import log

def inject_ui_sidebar():
    """Render user management section in the sidebar."""
    st.title("👤 User Management")

    # Current user info
    if st.session_state.current_user:
        st.info(f"**Current User:** {st.session_state.current_user['name']}")

        # Switch user button
        if st.button("Switch User"):
            st.session_state.current_user = None
            st.session_state.current_conversation_id = None
            st.session_state.conversation_messages = []
            st.rerun()
    else:
        st.warning("No user selected")

        # User selector - USING get_all_users_dict() instead of get_all_users()
        all_users = user_manager.get_all_users_dict()
        if all_users:
            user_options = ["Select a user..."] + list(all_users.keys())
            user_display = ["Select a user..."] + [f"{user['name']} ({user_id})" for user_id, user in all_users.items()]

            selected_user = st.selectbox(
                "Choose user",
                options=user_options,
                format_func=lambda x: user_display[user_options.index(x)] if x in user_options else x,
                key="user_selector"
            )

            if selected_user != "Select a user..." and selected_user:
                if st.button("Login as User"):
                    st.session_state.current_user = all_users[selected_user]
                    log("info", f"User logged in: {st.session_state.current_user['name']}")
                    st.rerun()

    # Create new user button
    if st.button("➕ Create New User", type="primary"):
        st.session_state.show_user_form = True
        st.session_state.edit_user_id = None

    return True  # Return value indicates content was rendered

def inject_ui_main_header():
    """Render user info in the main header."""
    if st.session_state.current_user:
        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            st.success(f"✅ Logged in as: **{st.session_state.current_user['name']}**")
        with col2:
            if st.button("👤 Profile", key="profile_header_btn"):
                st.session_state.edit_user_id = st.session_state.current_user['id']
                st.session_state.show_user_form = True
                st.rerun()
        with col3:
            if st.button("🚪 Logout", key="logout_header_btn"):
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
        # User form if triggered
        if st.session_state.show_user_form:
            render_user_form()
            return True
    return False

def render_user_form():
    """Render the user creation/editing form."""
    st.divider()
    st.subheader("👤 " + ("Edit User" if st.session_state.edit_user_id else "Create New User"))

    with st.form("user_form"):
        if st.session_state.edit_user_id:
            # Editing existing user
            user = user_manager.get_user(st.session_state.edit_user_id)
            default_name = user["name"] if user else ""
            default_email = user["email"] if user else ""
        else:
            # Creating new user
            default_name = ""
            default_email = ""

        name = st.text_input("Name *", value=default_name)
        email = st.text_input("Email", value=default_email)

        col1, col2 = st.columns(2)
        with col1:
            submit = st.form_submit_button("💾 Save User", type="primary")
        with col2:
            cancel = st.form_submit_button("❌ Cancel")

        if submit:
            if not name.strip():
                st.error("Name is required")
            else:
                try:
                    if st.session_state.edit_user_id:
                        # Update existing user
                        success = user_manager.update_user(
                            st.session_state.edit_user_id,
                            name=name.strip(),
                            email=email.strip() if email else None
                        )
                        if success:
                            st.success("User updated successfully!")
                            # Update current user if editing self
                            if (st.session_state.current_user and
                                st.session_state.current_user['id'] == st.session_state.edit_user_id):
                                st.session_state.current_user = user_manager.get_user(st.session_state.edit_user_id)
                            log("info", f"User updated: {name}")
                        else:
                            st.error("Failed to update user")
                    else:
                        # Create new user
                        user_id = user_manager.create_user(
                            name=name.strip(),
                            email=email.strip() if email else None
                        )
                        st.success(f"User created successfully! ID: {user_id}")
                        log("info", f"User created: {name} (ID: {user_id})")

                    # Reset form state
                    st.session_state.show_user_form = False
                    st.session_state.edit_user_id = None
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {str(e)}")
                    log("error", f"User form error: {str(e)}")

        if cancel:
            st.session_state.show_user_form = False
            st.session_state.edit_user_id = None
            st.rerun()
