"""
User Management UI Module
=========================

This module provides UI components for user management that can be injected
into the main application through the UI registry system.
"""

import streamlit as st
from shared.users import user_manager
from shared.logging import log

def auto_login_first_user():
    """Automatically log in the first available user if none is logged in AND user hasn't manually logged out."""

    # Don't auto-login if user has manually logged out/switched
    if st.session_state.user_manually_logged_out:
        log("debug", "Skipping auto-login: user manually logged out")
        return False

    if not st.session_state.current_user:
        try:
            # Get all users
            all_users = user_manager.get_all_users_dict()

            if all_users:
                # Get the first user (sorted by ID for consistency)
                first_user_id = sorted(all_users.keys())[0]
                first_user = all_users[first_user_id]

                # Set as current user
                st.session_state.current_user = first_user

                # Update last login
                user_manager.update_last_login(first_user_id)

                # Set the flag to show this was an auto-login
                st.session_state.just_auto_logged_in = True

                log("info", f"Auto-logged in user: {first_user['name']}")
                return True
            else:
                log("warning", "No users available for auto-login")
                return False
        except Exception as e:
            log("error", f"Auto-login failed: {e}")
            return False
    return True  # Already logged in

def inject_ui_sidebar():
    """Render user management section in the sidebar."""
    st.title("👤 User Management")

    # Current user info
    if st.session_state.current_user:
        st.info(f"**Current User:** {st.session_state.current_user['name']}")

        # Switch user button
        if st.button("Switch User"):
            # Set the manual logout flag to prevent auto-login
            st.session_state.user_manually_logged_out = True
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
                    # Clear the manual logout flag when manually logging in
                    st.session_state.user_manually_logged_out = False
                    st.session_state.current_user = all_users[selected_user]
                    log("info", f"User logged in: {st.session_state.current_user['name']}")
                    st.rerun()
        else:
            st.info("No users found. Please create a user first.")

    # Create new user button
    if st.button("➕ Create New User", type="primary"):
        st.session_state.show_user_form = True
        st.session_state.edit_user_id = None

    return True  # Return value indicates content was rendered

def inject_ui_main_header():
    """Render user info in the main header."""
    # NEW: Check if we just auto-logged in
    if "just_auto_logged_in" not in st.session_state:
        st.session_state.just_auto_logged_in = False

    if st.session_state.current_user:
        # NEW: Show welcome message if just auto-logged in
        if st.session_state.just_auto_logged_in:
            st.success(f"👋 Welcome, **{st.session_state.current_user['name']}**! You've been automatically logged in.")
            # Clear the flag
            st.session_state.just_auto_logged_in = False
        else:
            st.success(f"✅ Logged in as: **{st.session_state.current_user['name']}**")

        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            if st.button("👤 Profile", key="profile_header_btn"):
                st.session_state.edit_user_id = st.session_state.current_user['id']
                st.session_state.show_user_form = True
                st.rerun()
        with col2:
            if st.button("🔄 Switch User", key="switch_header_btn"):
                # Set the manual logout flag
                st.session_state.user_manually_logged_out = True
                st.session_state.current_user = None
                st.session_state.current_conversation_id = None
                st.session_state.conversation_messages = []
                st.rerun()
        with col3:
            if st.button("🚪 Logout", key="logout_header_btn"):
                # Set the manual logout flag
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

                        # NEW: Auto-login the newly created user if no user is logged in
                        if not st.session_state.current_user:
                            # Clear the manual logout flag since we're creating a new user
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
                except Exception as e:
                    st.error(f"Error: {str(e)}")
                    log("error", f"User form error: {str(e)}")

        if cancel:
            st.session_state.show_user_form = False
            st.session_state.edit_user_id = None
            st.rerun()

def inject_ui_initialize():
    """Initialize session state for user management."""
    # Initialize session state for user management
    if "current_user" not in st.session_state:
        st.session_state.current_user = None
    if "show_user_form" not in st.session_state:
        st.session_state.show_user_form = False
    if "edit_user_id" not in st.session_state:
        st.session_state.edit_user_id = None
    # NEW: Flag for auto-login notification
    if "just_auto_logged_in" not in st.session_state:
        st.session_state.just_auto_logged_in = False
    # NEW: Flag to track manual logout/switch (initialize to False for first launch)
    if "user_manually_logged_out" not in st.session_state:
        st.session_state.user_manually_logged_out = False
