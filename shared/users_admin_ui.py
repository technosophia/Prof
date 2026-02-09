"""
Users Admin UI Module
====================

Provides admin interface for user management with hierarchical roles:
- Admin: Can view and manage all users
- Master: Can view and manage only themselves and their children
- Normal: No access to admin tab
"""

import streamlit as st
from datetime import datetime
from typing import Dict, Any, List
from shared.common import _, log, get_config, get_user_manager, UserRole



def can_access_admin_tab(user: Dict[str, Any]) -> bool:
    """Check if user can access the admin tab."""
    if not user:
        return False
    return user.get("role") in [UserRole.ADMIN.value, UserRole.MASTER.value]


def show_users_admin_content():
    """Display the Users Admin content based on user role."""
    current_user = st.session_state.get("current_user")

    if not current_user:
        st.error("Please log in to access user administration.")
        return

    if not can_access_admin_tab(current_user):
        st.error("You don't have permission to access user administration.")
        return

    user_role = current_user.get("role")
    user_id = current_user.get("id")

    st.header("👥 User Administration")
    st.caption(f"Role: {user_role.capitalize()} | Viewing users you can manage")

    # Get manageable users based on role
    manageable_users = get_user_manager().get_manageable_users(user_id)

    # Section 1: Create New User (only for admin and master)
    if user_role in [UserRole.ADMIN.value, UserRole.MASTER.value]:
        st.subheader("➕ Create New User")

        with st.form("create_user_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                new_name = st.text_input("Username *",
                                       help="Required. This will be the display name.")
            with col2:
                new_email = st.text_input("Email",
                                        help="Optional email address")

            # Role selection
            col_role, col_parent = st.columns(2)
            with col_role:
                if user_role == UserRole.ADMIN.value:
                    available_roles = [UserRole.ADMIN.value, UserRole.MASTER.value, UserRole.NORMAL.value]
                else:  # Master can only create normal users
                    available_roles = [UserRole.NORMAL.value]

                new_role = st.selectbox(
                    "Role *",
                    available_roles,
                    index=0,
                    help="User role"
                )

            with col_parent:
                # Parent selection (only for normal users)
                if new_role == UserRole.NORMAL.value:
                    # For admin: all masters, for master: only themselves
                    if user_role == UserRole.ADMIN.value:
                        masters = get_user_manager().get_users_by_role(UserRole.MASTER.value)
                        parent_options = [("", "Select a master...")] + [(m["id"], m["name"]) for m in masters]
                    else:  # Master
                        parent_options = [(user_id, current_user["name"])]

                    parent_options_dict = dict(parent_options)
                    selected_parent = st.selectbox(
                        "Parent (Master) *",
                        options=list(parent_options_dict.keys()),
                        format_func=lambda x: parent_options_dict[x],
                        help="Normal users must have a master as parent"
                    )
                else:
                    selected_parent = None
                    st.selectbox(
                        "Parent",
                        [""],
                        disabled=True,
                        help="Only normal users have parents"
                    )

            # Profile configuration
            st.subheader("Profile Configuration", help="User profile settings")

            # Get preference schema
            preference_schema = get_user_manager().get_profile_preferences_schema()

            # Language preference (always available)
            language = st.selectbox(
                "Preferred Language",
                preference_schema["language"]["options"],
                index=preference_schema["language"]["options"].index(
                    preference_schema["language"].get("default", "en")
                ),
                help="User's preferred language"
            )

            # Custom preferences from other modules
            custom_preferences = {}
            for field_name, field_config in preference_schema.items():
                if field_name != "language":  # Already handled
                    label = field_config.get("label", field_name.replace("_", " ").title())

                    if field_config.get("type") == "select":
                        default_idx = 0
                        if "default" in field_config and field_config["default"] in field_config["options"]:
                            default_idx = field_config["options"].index(field_config["default"])
                        value = st.selectbox(
                            label,
                            field_config["options"],
                            index=default_idx,
                            key=f"pref_{field_name}_create"
                        )
                        custom_preferences[field_name] = value
                    elif field_config.get("type") == "checkbox":
                        value = st.checkbox(
                            label,
                            value=field_config.get("default", False),
                            key=f"pref_{field_name}_create"
                        )
                        custom_preferences[field_name] = value
                    else:  # text input
                        value = st.text_input(
                            label,
                            value=field_config.get("default", ""),
                            key=f"pref_{field_name}_create"
                        )
                        custom_preferences[field_name] = value

            # Build profile
            profile = {"language": language}
            profile.update(custom_preferences)

            # Submit button
            col_btn1, col_btn2 = st.columns([1, 3])
            with col_btn1:
                submit_create = st.form_submit_button("Create User", type="primary")

            if submit_create:
                if not new_name or not new_name.strip():
                    st.error("Username is required!")
                elif new_role == UserRole.NORMAL.value and not selected_parent:
                    st.error("Normal users must have a parent!")
                else:
                    try:
                        user_id = get_user_manager().create_user(
                            name=new_name.strip(),
                            role=new_role,
                            email=new_email.strip() if new_email else None,
                            parent_id=selected_parent if selected_parent else None,
                            profile=profile
                        )

                        st.success(f"✅ User '{new_name.strip()}' created successfully!")
                        log("info", f"Created user: {new_name} (ID: {user_id}, Role: {new_role})")
                        st.rerun()
                    except ValueError as e:
                        st.error(f"❌ Validation error: {str(e)}")
                    except Exception as e:
                        st.error(f"❌ Error creating user: {str(e)}")
                        log("error", f"Failed to create user: {e}")

    st.divider()

    # Section 2: Manage Existing Users
    st.subheader("📋 User List")

    try:
        if not manageable_users:
            st.info("No users found that you can manage.")
            return

        # Display users in a table with actions
        for user in manageable_users:
            # Skip current user in the list for masters (they see themselves separately)
            if user_role == UserRole.MASTER.value and user["id"] == user_id:
                continue

            with st.container():
                cols = st.columns([3, 2, 1, 1, 1])

                with cols[0]:
                    st.write(f"**{user['name']}**")
                    if user.get('email'):
                        st.caption(f"📧 {user['email']}")
                    st.caption(f"🆔 {user['id']}")

                    # Show parent info
                    if user.get('parent_name'):
                        st.caption(f"👨‍👦 Parent: {user['parent_name']}")

                with cols[1]:
                    # Status and role
                    status = "🟢 Active" if user.get('is_active', True) else "🔴 Inactive"
                    st.write(status)

                    role = user.get('role', 'normal')
                    role_emoji = "👑" if role == UserRole.ADMIN.value else "⭐" if role == UserRole.MASTER.value else "👤"
                    st.caption(f"{role_emoji} {role}")

                    # Language
                    if user.get('profile', {}).get('language'):
                        st.caption(f"🌐 {user['profile']['language']}")

                with cols[2]:
                    # View details button
                    if st.button("👁️ View",
                               key=f"view_{user['id']}",
                               help=f"View details for {user['name']}",
                               width='stretch'):
                        st.session_state.viewing_user_id = user['id']
                        st.rerun()

                with cols[3]:
                    # Edit button
                    if st.button("✏️ Edit",
                               key=f"edit_{user['id']}",
                               help=f"Edit user {user['name']}",
                               width='stretch'):
                        st.session_state.editing_user_id = user['id']
                        st.rerun()

                with cols[4]:
                    # Delete button
                    # Can't delete yourself or admin if not admin
                    can_delete = True
                    if user['id'] == current_user['id']:
                        can_delete = False
                        tooltip = "Cannot delete yourself"
                    elif user['role'] == UserRole.ADMIN.value and current_user['role'] != UserRole.ADMIN.value:
                        can_delete = False
                        tooltip = "Only admin can delete other admins"
                    else:
                        tooltip = f"Delete user {user['name']}"

                    if st.button("❌ Delete",
                               key=f"delete_{user['id']}",
                               help=tooltip,
                               disabled=not can_delete,
                               width='stretch',
                               type="secondary"):
                        st.session_state.user_to_delete = user
                        st.session_state.show_delete_confirm = True
                        st.rerun()

                st.divider()

        # Show current user info for masters
        if user_role == UserRole.MASTER.value:
            with st.expander("👑 Your Master Account", expanded=False):
                cols = st.columns([4, 1])
                with cols[0]:
                    st.write(f"**{current_user['name']}**")
                    st.caption(f"🆔 {current_user['id']}")
                    if current_user.get('email'):
                        st.caption(f"📧 {current_user['email']}")

                    # Children count
                    children = get_user_manager().get_children(user_id)
                    if children:
                        child_names = ", ".join([c['name'] for c in children])
                        st.caption(f"👨‍👦 Children: {len(children)} ({child_names})")

                with cols[1]:
                    if st.button("✏️ Edit Profile",
                               key="edit_master_profile",
                               width='stretch'):
                        st.session_state.editing_user_id = user_id
                        st.rerun()

        # Delete confirmation dialog
        if st.session_state.get('show_delete_confirm') and st.session_state.get('user_to_delete'):
            user_to_delete = st.session_state.user_to_delete

            st.warning(f"⚠️ **Confirm Deletion**")
            st.error(f"Are you sure you want to delete user **{user_to_delete['name']}**?")

            if user_to_delete.get('role') == UserRole.MASTER.value:
                children = get_user_manager().get_children(user_to_delete['id'])
                if children:
                    st.warning(f"This will also delete {len(children)} child users!")

            col_confirm1, col_confirm2 = st.columns(2)
            with col_confirm1:
                if st.button("✅ Yes, Delete", type="primary", width='stretch'):
                    try:
                        success = get_user_manager().delete_user(user_to_delete['id'], current_user['id'])
                        if success:
                            st.success(f"✅ User '{user_to_delete['name']}' deleted successfully!")
                            log("info", f"Deleted user: {user_to_delete['name']}")
                        else:
                            st.error(f"❌ Failed to delete user '{user_to_delete['name']}'")
                    except Exception as e:
                        st.error(f"❌ Error deleting user: {str(e)}")
                        log("error", f"Error deleting user: {e}")

                    st.session_state.show_delete_confirm = False
                    st.session_state.user_to_delete = None
                    st.rerun()

            with col_confirm2:
                if st.button("❌ Cancel", width='stretch'):
                    st.session_state.show_delete_confirm = False
                    st.session_state.user_to_delete = None
                    st.rerun()

        # View user details
        if st.session_state.get('viewing_user_id'):
            user_id_to_view = st.session_state.viewing_user_id
            user_to_view = get_user_manager().get_user(user_id_to_view, include_children=True)

            if user_to_view:
                st.divider()
                st.subheader(f"👤 User Details: {user_to_view['name']}")

                col1, col2 = st.columns(2)
                with col1:
                    st.write("**Basic Information**")
                    st.write(f"**ID:** {user_to_view['id']}")
                    st.write(f"**Name:** {user_to_view['name']}")
                    st.write(f"**Email:** {user_to_view['email'] or 'Not set'}")
                    st.write(f"**Role:** {user_to_view['role']}")
                    st.write(f"**Status:** {'🟢 Active' if user_to_view['is_active'] else '🔴 Inactive'}")

                    if user_to_view.get('parent_name'):
                        st.write(f"**Parent:** {user_to_view['parent_name']}")

                    if user_to_view.get('created_at'):
                        try:
                            created = datetime.fromisoformat(user_to_view['created_at'].replace('Z', '+00:00'))
                            st.write(f"**Created:** {created.strftime('%Y-%m-%d %H:%M:%S')}")
                        except:
                            pass

                with col2:
                    st.write("**Profile Preferences**")
                    profile = user_to_view.get('profile', {})
                    for key, value in profile.items():
                        st.write(f"**{key.replace('_', ' ').title()}:** {value}")

                # Show children if any
                if user_to_view.get('role') in [UserRole.MASTER.value, UserRole.ADMIN.value]:
                    children = get_user_manager().get_children(user_id_to_view)
                    if children:
                        st.write("**Child Users:**")
                        for child in children:
                            st.write(f"- {child['name']} ({child['role']})")

                if st.button("Close Details", key="close_details"):
                    st.session_state.viewing_user_id = None
                    st.rerun()

        # Edit user form
        if st.session_state.get('editing_user_id'):
            user_id_to_edit = st.session_state.editing_user_id
            user_to_edit = get_user_manager().get_user(user_id_to_edit)

            if user_to_edit:
                st.divider()
                is_editing_self = user_id_to_edit == current_user['id']
                title = "✏️ Edit Your Profile" if is_editing_self else f"✏️ Edit User: {user_to_edit['name']}"
                st.subheader(title)

                with st.form("edit_user_form"):
                    col_e1, col_e2 = st.columns(2)
                    with col_e1:
                        edit_name = st.text_input("Username *",
                                                value=user_to_edit['name'])
                    with col_e2:
                        edit_email = st.text_input("Email",
                                                 value=user_to_edit.get('email', ''))

                    # Role editing (only for admin editing other users)
                    if current_user['role'] == UserRole.ADMIN.value and not is_editing_self:
                        col_role, col_parent = st.columns(2)
                        with col_role:
                            available_roles = [UserRole.ADMIN.value, UserRole.MASTER.value, UserRole.NORMAL.value]
                            edit_role = st.selectbox(
                                "Role",
                                available_roles,
                                index=available_roles.index(user_to_edit.get('role', UserRole.NORMAL.value))
                            )

                        with col_parent:
                            if edit_role == UserRole.NORMAL.value:
                                masters = get_user_manager().get_users_by_role(UserRole.MASTER.value)
                                # Filter out the user being edited if they're a master
                                masters = [m for m in masters if m['id'] != user_id_to_edit]
                                parent_options = [("", "Select a master...")] + [(m["id"], m["name"]) for m in masters]
                                parent_options_dict = dict(parent_options)

                                current_parent = user_to_edit.get('parent_id', '')
                                selected_parent = st.selectbox(
                                    "Parent (Master) *",
                                    options=list(parent_options_dict.keys()),
                                    index=list(parent_options_dict.keys()).index(current_parent) if current_parent in parent_options_dict else 0,
                                    format_func=lambda x: parent_options_dict[x]
                                )
                            else:
                                selected_parent = None
                    else:
                        edit_role = user_to_edit.get('role')
                        selected_parent = user_to_edit.get('parent_id')
                        st.caption(f"**Role:** {edit_role}")
                        if selected_parent:
                            parent_user = get_user_manager().get_user(selected_parent)
                            if parent_user:
                                st.caption(f"**Parent:** {parent_user['name']}")

                    # Profile preferences
                    st.subheader("Profile Preferences")
                    preference_schema = get_user_manager().get_profile_preferences_schema()
                    current_profile = user_to_edit.get('profile', {})

                    # Language
                    current_lang = current_profile.get('language', 'en')
                    language = st.selectbox(
                        "Preferred Language",
                        preference_schema["language"]["options"],
                        index=preference_schema["language"]["options"].index(current_lang)
                        if current_lang in preference_schema["language"]["options"] else 0
                    )

                    # Custom preferences
                    custom_updates = {}
                    for field_name, field_config in preference_schema.items():
                        if field_name != "language":
                            label = field_config.get("label", field_name.replace("_", " ").title())
                            current_value = current_profile.get(field_name, field_config.get("default"))

                            if field_config.get("type") == "select":
                                value = st.selectbox(
                                    label,
                                    field_config["options"],
                                    index=field_config["options"].index(current_value)
                                    if current_value in field_config["options"] else 0,
                                    key=f"pref_{field_name}_edit_{user_id_to_edit}"
                                )
                                custom_updates[field_name] = value
                            elif field_config.get("type") == "checkbox":
                                value = st.checkbox(
                                    label,
                                    value=bool(current_value),
                                    key=f"pref_{field_name}_edit_{user_id_to_edit}"
                                )
                                custom_updates[field_name] = value
                            else:
                                value = st.text_input(
                                    label,
                                    value=str(current_value) if current_value is not None else "",
                                    key=f"pref_{field_name}_edit_{user_id_to_edit}"
                                )
                                custom_updates[field_name] = value

                    # Status toggle (admin/master only, can't deactivate self)
                    if (current_user['role'] in [UserRole.ADMIN.value, UserRole.MASTER.value] and
                        not is_editing_self):
                        edit_active = st.toggle("Active",
                                              value=user_to_edit.get('is_active', True),
                                              help="Deactivate to prevent user from logging in")
                    else:
                        edit_active = user_to_edit.get('is_active', True)

                    # Build profile
                    profile_updates = {"language": language}
                    profile_updates.update(custom_updates)

                    col_ebtn1, col_ebtn2, col_ebtn3 = st.columns([1, 1, 2])
                    with col_ebtn1:
                        submit_edit = st.form_submit_button("💾 Save Changes", type="primary")
                    with col_ebtn2:
                        cancel_edit = st.form_submit_button("❌ Cancel")

                    if submit_edit:
                        if not edit_name or not edit_name.strip():
                            st.error("Username is required!")
                        elif edit_role == UserRole.NORMAL.value and not selected_parent:
                            st.error("Normal users must have a parent!")
                        else:
                            try:
                                updates = {
                                    "name": edit_name.strip(),
                                    "email": edit_email.strip() if edit_email else None,
                                    "is_active": edit_active,
                                    "profile": profile_updates
                                }

                                # Add role and parent if admin editing
                                if current_user['role'] == UserRole.ADMIN.value and not is_editing_self:
                                    updates["role"] = edit_role
                                    if edit_role == UserRole.NORMAL.value:
                                        updates["parent_id"] = selected_parent
                                    else:
                                        updates["parent_id"] = None

                                success = get_user_manager().update_user(
                                    user_id_to_edit,
                                    current_user['id'],
                                    **updates
                                )

                                if success:
                                    st.success("✅ User updated successfully!")

                                    # Update session state if editing current user
                                    if is_editing_self:
                                        updated_user = get_user_manager().get_user(user_id_to_edit)
                                        if updated_user:
                                            st.session_state.current_user = updated_user

                                    log("info", f"Updated user: {edit_name.strip()} (ID: {user_id_to_edit})")
                                    st.session_state.editing_user_id = None
                                    st.rerun()
                                else:
                                    st.error("❌ Failed to update user (permission denied)")
                            except ValueError as e:
                                st.error(f"❌ Validation error: {str(e)}")
                            except Exception as e:
                                st.error(f"❌ Error updating user: {str(e)}")
                                log("error", f"Error updating user: {e}")

                    if cancel_edit:
                        st.session_state.editing_user_id = None
                        st.rerun()

    except Exception as e:
        st.error(f"❌ Error loading users: {str(e)}")
        log("error", f"Error in users admin UI: {e}")


def inject_ui_admin_tab():
    """Register the Users admin tab."""
    return ("Users", show_users_admin_content)


def inject_ui_initialize():
    """Initialize the users admin UI module."""
    if "editing_user_id" not in st.session_state:
        st.session_state.editing_user_id = None
    if "viewing_user_id" not in st.session_state:
        st.session_state.viewing_user_id = None
    if "user_to_delete" not in st.session_state:
        st.session_state.user_to_delete = None
    if "show_delete_confirm" not in st.session_state:
        st.session_state.show_delete_confirm = False
