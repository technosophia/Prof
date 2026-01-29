"""
Users Admin UI Module
====================

Provides admin interface for user management including:
- View all users
- Create new users
- Delete users (with conversation cleanup via callbacks)
- Edit user profiles

Uses the new UI injection mechanism with admin_tab injection point.
"""

import streamlit as st
from datetime import datetime
from typing import Dict, Any, List
from shared.users import user_manager
from shared.logging import log


def show_users_admin_content():
    """Display the Users Admin content."""
    st.header("👥 User Administration")

    # Section 1: Create New User
    st.subheader("➕ Create New User")

    with st.form("create_user_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            new_name = st.text_input("Username *",
                                   help="Required. This will be the display name.")
        with col2:
            new_email = st.text_input("Email",
                                    help="Optional email address")

        # Profile configuration
        st.subheader("Profile Configuration", help="Optional user profile settings")

        col3, col4 = st.columns(2)
        with col3:
            profile_role = st.selectbox(
                "Role",
                ["user", "admin", "viewer", "editor"],
                index=0,
                help="User role for access control"
            )
        with col4:
            available_rights = ["read", "write", "delete", "execute", "admin"]
            selected_rights = st.multiselect(
                "Rights",
                available_rights,
                default=["read"],
                help="User permissions"
            )

        # Submit button
        col_btn1, col_btn2 = st.columns([1, 3])
        with col_btn1:
            submit_create = st.form_submit_button("Create User", type="primary")

        if submit_create:
            if not new_name or not new_name.strip():
                st.error("Username is required!")
            else:
                try:
                    # Create profile
                    profile = {
                        "role": profile_role,
                        "rights": selected_rights
                    }

                    # Create user
                    user_id = user_manager.create_user(
                        name=new_name.strip(),
                        email=new_email.strip() if new_email else None,
                        profile=profile
                    )

                    st.success(f"✅ User '{new_name.strip()}' created successfully! (ID: {user_id})")
                    log("info", f"Admin created user: {new_name} (ID: {user_id})")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error creating user: {str(e)}")
                    log("error", f"Failed to create user via admin: {e}")

    st.divider()

    # Section 2: Manage Existing Users
    st.subheader("📋 User List")

    try:
        # Get all users
        all_users = user_manager.get_all_users()

        if not all_users:
            st.info("No users found. Create your first user above.")
            return

        # Display users in a table with actions
        for user in all_users:
            # Create a container for each user
            with st.container():
                col1, col2, col3, col4 = st.columns([3, 2, 1, 1])

                with col1:
                    st.write(f"**{user['name']}**")
                    if user.get('email'):
                        st.caption(f"📧 {user['email']}")
                    st.caption(f"🆔 {user['id']}")

                with col2:
                    status = "🟢 Active" if user.get('is_active', True) else "🔴 Inactive"
                    st.write(status)

                    # Show role if available
                    profile = user.get('profile', {})
                    role = profile.get('role', 'user')
                    st.caption(f"👤 {role}")

                    # Created date
                    if user.get('created_at'):
                        try:
                            created_date = datetime.fromisoformat(user['created_at'].replace('Z', '+00:00'))
                            st.caption(f"📅 {created_date.strftime('%Y-%m-%d')}")
                        except:
                            pass

                with col3:
                    # Edit button
                    if st.button("✏️ Edit",
                               key=f"edit_{user['id']}",
                               help=f"Edit user {user['name']}",
                               use_container_width=True):
                        st.session_state.editing_user_id = user['id']
                        st.session_state.editing_user_data = user
                        st.rerun()

                with col4:
                    # Delete button with confirmation
                    delete_key = f"delete_{user['id']}"

                    # Check if this is the current logged in user
                    is_current_user = (st.session_state.get('current_user') and
                                     st.session_state.current_user.get('id') == user['id'])

                    if is_current_user:
                        st.button("❌ Delete",
                                key=delete_key,
                                help="Cannot delete currently logged in user",
                                disabled=True,
                                use_container_width=True)
                    else:
                        if st.button("❌ Delete",
                                   key=delete_key,
                                   help=f"Delete user {user['name']}",
                                   use_container_width=True,
                                   type="secondary"):
                            # Set the user to delete and show confirmation
                            st.session_state.user_to_delete = user
                            st.session_state.show_delete_confirm = True
                            st.rerun()

                # Separator
                st.divider()

        # Check if we need to show delete confirmation
        if st.session_state.get('show_delete_confirm') and st.session_state.get('user_to_delete'):
            user_to_delete = st.session_state.user_to_delete

            st.warning(f"⚠️ **Confirm Deletion**")
            st.error(f"Are you sure you want to delete user **{user_to_delete['name']}**?")
            st.warning("This will also delete ALL conversations and messages for this user!")

            col_confirm1, col_confirm2 = st.columns(2)
            with col_confirm1:
                if st.button("✅ Yes, Delete User", type="primary", use_container_width=True):
                    try:
                        success = user_manager.delete_user(user_to_delete['id'])
                        if success:
                            st.success(f"✅ User '{user_to_delete['name']}' deleted successfully!")
                            log("info", f"Admin deleted user: {user_to_delete['name']} (ID: {user_to_delete['id']})")
                        else:
                            st.error(f"❌ Failed to delete user '{user_to_delete['name']}'")
                    except Exception as e:
                        st.error(f"❌ Error deleting user: {str(e)}")
                        log("error", f"Error deleting user {user_to_delete['id']}: {e}")

                    # Clear delete state
                    st.session_state.show_delete_confirm = False
                    st.session_state.user_to_delete = None
                    st.rerun()

            with col_confirm2:
                if st.button("❌ Cancel", use_container_width=True):
                    st.session_state.show_delete_confirm = False
                    st.session_state.user_to_delete = None
                    st.rerun()

        # Check if we need to show edit form
        if st.session_state.get('editing_user_id') and st.session_state.get('editing_user_data'):
            user_data = st.session_state.editing_user_data
            st.divider()
            st.subheader(f"✏️ Edit User: {user_data['name']}")

            with st.form("edit_user_form"):
                col_e1, col_e2 = st.columns(2)
                with col_e1:
                    edit_name = st.text_input("Username *",
                                            value=user_data['name'])
                with col_e2:
                    edit_email = st.text_input("Email",
                                             value=user_data.get('email', ''))

                # Profile editing
                current_profile = user_data.get('profile', {})
                current_role = current_profile.get('role', 'user')
                current_rights = current_profile.get('rights', ['read'])

                st.subheader("Profile", help="Edit user profile")

                col_e3, col_e4 = st.columns(2)
                with col_e3:
                    edit_role = st.selectbox(
                        "Role",
                        ["user", "admin", "viewer", "editor"],
                        index=["user", "admin", "viewer", "editor"].index(current_role)
                               if current_role in ["user", "admin", "viewer", "editor"] else 0
                    )
                with col_e4:
                    available_rights = ["read", "write", "delete", "execute", "admin"]
                    edit_rights = st.multiselect(
                        "Rights",
                        available_rights,
                        default=current_rights
                    )

                # Status toggle
                edit_active = st.toggle("Active",
                                      value=user_data.get('is_active', True),
                                      help="Deactivate to prevent user from logging in")

                col_ebtn1, col_ebtn2, col_ebtn3 = st.columns([1, 1, 2])
                with col_ebtn1:
                    submit_edit = st.form_submit_button("💾 Save Changes", type="primary")
                with col_ebtn2:
                    cancel_edit = st.form_submit_button("❌ Cancel")

                if submit_edit:
                    if not edit_name or not edit_name.strip():
                        st.error("Username is required!")
                    else:
                        try:
                            # Prepare updates
                            updates = {
                                "name": edit_name.strip(),
                                "email": edit_email.strip() if edit_email else None,
                                "is_active": edit_active,
                                "profile": {
                                    "role": edit_role,
                                    "rights": edit_rights
                                }
                            }

                            # Update user
                            success = user_manager.update_user(user_data['id'], **updates)

                            if success:
                                st.success(f"✅ User '{edit_name.strip()}' updated successfully!")

                                # If editing current user, update session state
                                if (st.session_state.get('current_user') and
                                    st.session_state.current_user.get('id') == user_data['id']):
                                    updated_user = user_manager.get_user(user_data['id'])
                                    if updated_user:
                                        st.session_state.current_user = updated_user

                                log("info", f"Admin updated user: {user_data['name']} (ID: {user_data['id']})")

                                # Clear edit state
                                st.session_state.editing_user_id = None
                                st.session_state.editing_user_data = None
                                st.rerun()
                            else:
                                st.error("❌ Failed to update user")
                        except Exception as e:
                            st.error(f"❌ Error updating user: {str(e)}")
                            log("error", f"Error updating user {user_data['id']}: {e}")

                if cancel_edit:
                    st.session_state.editing_user_id = None
                    st.session_state.editing_user_data = None
                    st.rerun()

    except Exception as e:
        st.error(f"❌ Error loading users: {str(e)}")
        log("error", f"Error in users admin UI: {e}")


def inject_ui_admin_tab():
    """Register the Users admin tab using the new injection mechanism.
    Returns: (tab_name, render_function) tuple."""
    return ("Users", show_users_admin_content)


def inject_ui_initialize():
    """Initialize the users admin UI module."""
    # Initialize session state variables
    if "editing_user_id" not in st.session_state:
        st.session_state.editing_user_id = None
    if "editing_user_data" not in st.session_state:
        st.session_state.editing_user_data = None
    if "user_to_delete" not in st.session_state:
        st.session_state.user_to_delete = None
    if "show_delete_confirm" not in st.session_state:
        st.session_state.show_delete_confirm = False
