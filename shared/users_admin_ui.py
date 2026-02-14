"""
Users Admin UI Module
====================

Provides admin interface for user management with hierarchical roles:
- Admin: Can view and manage all users
- Master: Can view and manage only themselves and their children
- Normal: No access to admin tab

[agent]

How to get the current user : user = st.session_state.current_user
How to check if a user can access admin tab : can_access_admin_tab(user)
How to check user role : user.get("role") in [UserRole.ADMIN.value, UserRole.MASTER.value]

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

    # Create main tabs
    if user_role in [UserRole.ADMIN.value, UserRole.MASTER.value]:
        tab_names = ["📋 Manage Users", "➕ Create User"]
        if user_role == UserRole.ADMIN.value:
            tab_names.append("📦 Import/Export")

        tabs = st.tabs(tab_names)

        # Tab 1: Manage Users
        with tabs[0]:
            _render_user_management_tab(current_user, user_role, user_id, manageable_users)

        # Tab 2: Create User
        with tabs[1]:
            _render_create_user_tab(current_user, user_role)

        # Tab 3: Import/Export (Admin only)
        if user_role == UserRole.ADMIN.value and len(tabs) > 2:
            with tabs[2]:
                _render_import_export_tab()

    else:  # Should not happen due to can_access_admin_tab check
        st.info("No users found that you can manage.")


def _render_user_management_tab(current_user: Dict[str, Any], user_role: str,
                               user_id: str, manageable_users: List[Dict[str, Any]]):
    """Render the user management tab with user list and operations."""
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

            _render_user_row(current_user, user_role, user)

        # Show current user info for masters
        if user_role == UserRole.MASTER.value:
            _render_master_account_section(current_user, user_id)

        # Delete confirmation dialog
        _render_delete_confirmation(current_user)

        # View user details
        _render_user_details()

        # Edit user form
        _render_edit_user_form(current_user)

    except Exception as e:
        st.error(f"❌ Error loading users: {str(e)}")
        log("error", f"Error in users admin UI: {e}")


def _render_user_row(current_user: Dict[str, Any], user_role: str, user: Dict[str, Any]):
    """Render a single user row in the user list."""
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
            # Delete button with permissions check
            _render_delete_button(current_user, user)

        st.divider()


def _render_delete_button(current_user: Dict[str, Any], user: Dict[str, Any]):
    """Render delete button with appropriate permissions and tooltip."""
    can_delete = True
    tooltip = f"Delete user {user['name']}"

    if user['id'] == current_user['id']:
        can_delete = False
        tooltip = "Cannot delete yourself"
    elif user['role'] == UserRole.ADMIN.value and current_user['role'] != UserRole.ADMIN.value:
        can_delete = False
        tooltip = "Only admin can delete other admins"

    st.button("❌ Delete",
             key=f"delete_{user['id']}",
             help=tooltip,
             disabled=not can_delete,
             width='stretch',
             type="secondary",
             on_click=_set_user_to_delete,
             args=(user,))


def _set_user_to_delete(user: Dict[str, Any]):
    """Set the user to delete in session state."""
    st.session_state.user_to_delete = user
    st.session_state.show_delete_confirm = True


def _render_master_account_section(current_user: Dict[str, Any], user_id: str):
    """Render the master account section with children information."""
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


def _render_delete_confirmation(current_user: Dict[str, Any]):
    """Render delete confirmation dialog."""
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
                _execute_user_deletion(user_to_delete, current_user)

        with col_confirm2:
            if st.button("❌ Cancel", width='stretch'):
                _clear_delete_confirmation()


def _execute_user_deletion(user_to_delete: Dict[str, Any], current_user: Dict[str, Any]):
    """Execute the user deletion operation."""
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

    _clear_delete_confirmation()
    st.rerun()


def _clear_delete_confirmation():
    """Clear delete confirmation from session state."""
    st.session_state.show_delete_confirm = False
    st.session_state.user_to_delete = None


def _render_user_details():
    """Render user details view."""
    if st.session_state.get('viewing_user_id'):
        user_id_to_view = st.session_state.viewing_user_id
        user_to_view = get_user_manager().get_user(user_id_to_view, include_children=True)

        if user_to_view:
            st.divider()
            st.subheader(f"👤 User Details: {user_to_view['name']}")

            col1, col2 = st.columns(2)
            with col1:
                _render_user_basic_info(user_to_view)

            with col2:
                _render_user_profile_preferences(user_to_view)

            # Show children if any
            if user_to_view.get('role') in [UserRole.MASTER.value, UserRole.ADMIN.value]:
                _render_user_children(user_id_to_view)

            if st.button("Close Details", key="close_details"):
                st.session_state.viewing_user_id = None
                st.rerun()


def _render_user_basic_info(user: Dict[str, Any]):
    """Render basic user information."""
    st.write("**Basic Information**")
    st.write(f"**ID:** {user['id']}")
    st.write(f"**Name:** {user['name']}")
    st.write(f"**Email:** {user.get('email') or 'Not set'}")
    st.write(f"**Role:** {user['role']}")
    st.write(f"**Status:** {'🟢 Active' if user['is_active'] else '🔴 Inactive'}")

    if user.get('parent_name'):
        st.write(f"**Parent:** {user['parent_name']}")

    if user.get('created_at'):
        try:
            created = datetime.fromisoformat(user['created_at'].replace('Z', '+00:00'))
            st.write(f"**Created:** {created.strftime('%Y-%m-%d %H:%M:%S')}")
        except:
            pass


def _render_user_profile_preferences(user: Dict[str, Any]):
    """Render user profile preferences."""
    st.write("**Profile Preferences**")
    profile = user.get('profile', {})
    for key, value in profile.items():
        st.write(f"**{key.replace('_', ' ').title()}:** {value}")


def _render_user_children(user_id: str):
    """Render children users for a master or admin."""
    children = get_user_manager().get_children(user_id)
    if children:
        st.write("**Child Users:**")
        for child in children:
            st.write(f"- {child['name']} ({child['role']})")


def _render_edit_user_form(current_user: Dict[str, Any]):
    """Render the edit user form."""
    if not st.session_state.get('editing_user_id'):
        return

    user_id_to_edit = st.session_state.editing_user_id
    user_to_edit = get_user_manager().get_user(user_id_to_edit)

    if not user_to_edit:
        return

    st.divider()
    is_editing_self = user_id_to_edit == current_user['id']
    title = "✏️ Edit Your Profile" if is_editing_self else f"✏️ Edit User: {user_to_edit['name']}"
    st.subheader(title)

    with st.form("edit_user_form"):
        edit_data = _render_edit_form_fields(current_user, user_to_edit, is_editing_self)

        col_ebtn1, col_ebtn2, col_ebtn3 = st.columns([1, 1, 2])
        with col_ebtn1:
            submit_edit = st.form_submit_button("💾 Save Changes", type="primary")
        with col_ebtn2:
            cancel_edit = st.form_submit_button("❌ Cancel")

        if submit_edit:
            _process_edit_submission(current_user, user_id_to_edit, is_editing_self, edit_data)

        if cancel_edit:
            st.session_state.editing_user_id = None
            st.rerun()


def _render_edit_form_fields(current_user: Dict[str, Any], user_to_edit: Dict[str, Any],
                            is_editing_self: bool) -> Dict[str, Any]:
    """Render edit form fields and return the collected data."""
    col_e1, col_e2 = st.columns(2)
    with col_e1:
        edit_name = st.text_input("Username *", value=user_to_edit['name'])
    with col_e2:
        edit_email = st.text_input("Email", value=user_to_edit.get('email', ''))

    edit_role = user_to_edit.get('role')
    selected_parent = user_to_edit.get('parent_id')

    # Role editing (only for admin editing other users)
    if current_user['role'] == UserRole.ADMIN.value and not is_editing_self:
        edit_role, selected_parent = _render_role_parent_edit_fields(user_to_edit, edit_role)
    else:
        st.caption(f"**Role:** {edit_role}")
        if selected_parent:
            parent_user = get_user_manager().get_user(selected_parent)
            if parent_user:
                st.caption(f"**Parent:** {parent_user['name']}")

    # Profile preferences
    st.subheader("Profile Preferences")
    preference_schema = get_user_manager().get_profile_preferences_schema()
    current_profile = user_to_edit.get('profile', {})

    profile_updates = _render_profile_preferences_edit(preference_schema, current_profile, user_to_edit['id'])

    # Status toggle (admin/master only, can't deactivate self)
    if (current_user['role'] in [UserRole.ADMIN.value, UserRole.MASTER.value] and
        not is_editing_self):
        edit_active = st.toggle("Active",
                              value=user_to_edit.get('is_active', True),
                              help="Deactivate to prevent user from logging in")
    else:
        edit_active = user_to_edit.get('is_active', True)

    return {
        "name": edit_name,
        "email": edit_email,
        "role": edit_role,
        "parent_id": selected_parent,
        "profile": profile_updates,
        "is_active": edit_active
    }


def _render_role_parent_edit_fields(user_to_edit: Dict[str, Any], current_role: str) -> tuple:
    """Render role and parent selection fields for admin editing."""
    col_role, col_parent = st.columns(2)
    with col_role:
        available_roles = [UserRole.ADMIN.value, UserRole.MASTER.value, UserRole.NORMAL.value]
        edit_role = st.selectbox(
            "Role",
            available_roles,
            index=available_roles.index(user_to_edit.get('role', UserRole.NORMAL.value))
        )

    with col_parent:
        selected_parent = None
        if edit_role == UserRole.NORMAL.value:
            masters = get_user_manager().get_users_by_role(UserRole.MASTER.value)
            # Filter out the user being edited if they're a master
            masters = [m for m in masters if m['id'] != user_to_edit['id']]
            parent_options = [("", "Select a master...")] + [(m["id"], m["name"]) for m in masters]
            parent_options_dict = dict(parent_options)

            current_parent = user_to_edit.get('parent_id', '')
            selected_parent = st.selectbox(
                "Parent (Master) *",
                options=list(parent_options_dict.keys()),
                index=list(parent_options_dict.keys()).index(current_parent) if current_parent in parent_options_dict else 0,
                format_func=lambda x: parent_options_dict[x]
            )

    return edit_role, selected_parent


def _render_create_user_tab(current_user: Dict[str, Any], user_role: str):
    """Render the create user tab."""
    st.subheader("➕ Create New User")

    with st.form("create_user_form", clear_on_submit=True):
        user_data = _render_create_user_form_fields(current_user, user_role)

        col_btn1, col_btn2 = st.columns([1, 3])
        with col_btn1:
            submit_create = st.form_submit_button("Create User", type="primary")

        if submit_create:
            _process_create_user_submission(user_data)


def _render_create_user_form_fields(current_user: Dict[str, Any], user_role: str) -> Dict[str, Any]:
    """Render create user form fields and return the collected data."""
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
        selected_parent = _render_parent_selection(current_user, user_role, new_role)

    # Profile configuration
    st.subheader("Profile Configuration", help="User profile settings")
    profile = _render_profile_preferences_create()

    return {
        "name": new_name,
        "email": new_email,
        "role": new_role,
        "parent_id": selected_parent,
        "profile": profile
    }


def _render_parent_selection(current_user: Dict[str, Any], user_role: str, new_role: str) -> str:
    """Render parent selection dropdown for normal users."""
    if new_role == UserRole.NORMAL.value:
        # For admin: all masters, for master: only themselves
        if user_role == UserRole.ADMIN.value:
            masters = get_user_manager().get_users_by_role(UserRole.MASTER.value)
            parent_options = [("", "Select a master...")] + [(m["id"], m["name"]) for m in masters]
        else:  # Master
            parent_options = [(current_user["id"], current_user["name"])]

        parent_options_dict = dict(parent_options)
        return st.selectbox(
            "Parent (Master) *",
            options=list(parent_options_dict.keys()),
            format_func=lambda x: parent_options_dict[x],
            help="Normal users must have a master as parent"
        )
    else:
        st.selectbox("Parent", [""], disabled=True, help="Only normal users have parents")
        return None


def _render_profile_preferences_create() -> Dict[str, Any]:
    """Render profile preferences for user creation."""
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
            custom_preferences[field_name] = _render_preference_field(
                field_name, field_config, "create"
            )

    profile = {"language": language}
    profile.update(custom_preferences)
    return profile


def _render_profile_preferences_edit(preference_schema: Dict[str, Any],
                                    current_profile: Dict[str, Any],
                                    user_id: str) -> Dict[str, Any]:
    """Render profile preferences for user editing."""
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
            current_value = current_profile.get(field_name, field_config.get("default"))
            custom_updates[field_name] = _render_preference_field(
                field_name, field_config, f"edit_{user_id}", current_value
            )

    profile_updates = {"language": language}
    profile_updates.update(custom_updates)
    return profile_updates


def _render_preference_field(field_name: str, field_config: Dict[str, Any],
                            key_suffix: str, current_value: Any = None) -> Any:
    """Render a single preference field based on its configuration."""
    label = field_config.get("label", field_name.replace("_", " ").title())

    if current_value is None:
        current_value = field_config.get("default")

    if field_config.get("type") == "select":
        if current_value not in field_config["options"]:
            current_value = field_config["options"][0]

        return st.selectbox(
            label,
            field_config["options"],
            index=field_config["options"].index(current_value),
            key=f"pref_{field_name}_{key_suffix}"
        )
    elif field_config.get("type") == "checkbox":
        return st.checkbox(
            label,
            value=bool(current_value),
            key=f"pref_{field_name}_{key_suffix}"
        )
    else:  # text input
        return st.text_input(
            label,
            value=str(current_value) if current_value is not None else "",
            key=f"pref_{field_name}_{key_suffix}"
        )


def _process_create_user_submission(user_data: Dict[str, Any]):
    """Process the create user form submission."""
    if not user_data["name"] or not user_data["name"].strip():
        st.error("Username is required!")
    elif user_data["role"] == UserRole.NORMAL.value and not user_data["parent_id"]:
        st.error("Normal users must have a parent!")
    else:
        try:
            user_id = get_user_manager().create_user(
                name=user_data["name"].strip(),
                role=user_data["role"],
                email=user_data["email"].strip() if user_data["email"] else None,
                parent_id=user_data["parent_id"] if user_data["parent_id"] else None,
                profile=user_data["profile"]
            )

            st.success(f"✅ User '{user_data['name'].strip()}' created successfully!")
            log("info", f"Created user: {user_data['name']} (ID: {user_id}, Role: {user_data['role']})")
            st.rerun()
        except ValueError as e:
            st.error(f"❌ Validation error: {str(e)}")
        except Exception as e:
            st.error(f"❌ Error creating user: {str(e)}")
            log("error", f"Failed to create user: {e}")


def _process_edit_submission(current_user: Dict[str, Any], user_id_to_edit: str,
                            is_editing_self: bool, edit_data: Dict[str, Any]):
    """Process the edit user form submission."""
    if not edit_data["name"] or not edit_data["name"].strip():
        st.error("Username is required!")
    elif edit_data["role"] == UserRole.NORMAL.value and not edit_data.get("parent_id"):
        st.error("Normal users must have a parent!")
    else:
        try:
            updates = {
                "name": edit_data["name"].strip(),
                "email": edit_data["email"].strip() if edit_data["email"] else None,
                "is_active": edit_data["is_active"],
                "profile": edit_data["profile"]
            }

            # Add role and parent if admin editing
            if current_user['role'] == UserRole.ADMIN.value and not is_editing_self:
                updates["role"] = edit_data["role"]
                if edit_data["role"] == UserRole.NORMAL.value:
                    updates["parent_id"] = edit_data["parent_id"]
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

                log("info", f"Updated user: {edit_data['name'].strip()} (ID: {user_id_to_edit})")
                st.session_state.editing_user_id = None
                st.rerun()
            else:
                st.error("❌ Failed to update user (permission denied)")
        except ValueError as e:
            st.error(f"❌ Validation error: {str(e)}")
        except Exception as e:
            st.error(f"❌ Error updating user: {str(e)}")
            log("error", f"Error updating user: {e}")


def _render_import_export_tab():
    """Render the import/export tab for admin users."""
    st.subheader("📦 Import/Export Users")

    # Create tabs for import and export
    import_export_tab1, import_export_tab2 = st.tabs(["📤 Export Users", "📥 Import Users"])

    with import_export_tab1:
        _render_export_section()

    with import_export_tab2:
        _render_import_section()


def _render_export_section():
    """Render the export section."""
    col_export1, col_export2 = st.columns([2, 1])

    with col_export1:
        # Export options
        st.caption("Export all users or select specific users to export")
        export_scope = st.radio(
            "Export scope",
            options=["All users", "Selected users"],
            horizontal=True,
            key="export_scope_radio"
        )

        selected_user_ids = []
        if export_scope == "Selected users":
            all_users_list = get_user_manager().get_all_users()
            user_options = {u["id"]: f"{u['name']} ({u['role']})" for u in all_users_list}
            selected_user_ids = st.multiselect(
                "Select users to export",
                options=list(user_options.keys()),
                format_func=lambda x: user_options[x],
                key="export_user_multiselect"
            )

        include_children = st.checkbox(
            "Include child users in export",
            value=True,
            help="When checked, includes all descendants of selected users"
        )

    with col_export2:
        st.caption(" ")
        st.caption(" ")
        if st.button("📥 Generate Export", type="primary", width='stretch'):
            _execute_export(include_children, selected_user_ids)

    # Display download button if export data is available
    if st.session_state.get('export_json_data'):
        st.download_button(
            label="⬇️ Download JSON File",
            data=st.session_state.export_json_data,
            file_name=st.session_state.export_filename,
            mime="application/json",
            width='stretch'
        )


def _execute_export(include_children: bool, selected_user_ids: List[str]):
    """Execute the export operation."""
    try:
        export_data = get_user_manager().export_users(
            include_children=include_children,
            user_ids=selected_user_ids if selected_user_ids else None
        )

        # Convert to JSON string
        json_str = json.dumps(export_data, indent=2, ensure_ascii=False)

        # Store in session state
        st.session_state.export_json_data = json_str
        st.session_state.export_filename = f"users_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        st.success(f"✅ Exported {export_data['user_count']} users successfully!")

    except Exception as e:
        st.error(f"❌ Export failed: {str(e)}")
        log("error", f"Export failed: {e}")


def _render_import_section():
    """Render the import section."""
    st.caption("Import users from a JSON export file")

    # File uploader
    uploaded_file = st.file_uploader(
        "Choose a JSON file",
        type=['json'],
        help="Upload a JSON file exported from the system or in compatible format",
        key="import_file_uploader"
    )

    if uploaded_file is not None:
        _process_import_file(uploaded_file)


def _process_import_file(uploaded_file):
    """Process the uploaded import file."""
    try:
        import_data = json.load(uploaded_file)

        # Preview import data
        st.info(f"📊 File contains {len(import_data.get('users', []))} users")

        # Import options
        col_import1, col_import2 = st.columns(2)
        with col_import1:
            overwrite = st.checkbox(
                "Overwrite existing users",
                help="If checked, will replace existing users with same ID",
                key="import_overwrite"
            )

        with col_import2:
            validate_only = st.checkbox(
                "Validate only (no import)",
                help="Check if the import would succeed without making changes",
                key="import_validate_only"
            )

        # Preview table
        if import_data.get("users"):
            _render_import_preview(import_data["users"])

        # Import button
        if st.button("🚀 Import Users", type="primary", width='stretch'):
            _execute_import(import_data, overwrite, validate_only)

    except json.JSONDecodeError:
        st.error("❌ Invalid JSON file")
    except Exception as e:
        st.error(f"❌ Error reading file: {str(e)}")


def _render_import_preview(users: List[Dict[str, Any]]):
    """Render a preview of users to import."""
    with st.expander("👁️ Preview users to import", expanded=False):
        preview_data = []
        for user in users[:10]:  # Show first 10
            preview_data.append({
                "ID": user.get("id", "N/A"),
                "Name": user.get("name", "N/A"),
                "Role": user.get("role", "N/A"),
                "Email": user.get("email", "N/A"),
                "Parent": user.get("parent_id", "None")
            })
        st.table(preview_data)
        if len(users) > 10:
            st.caption(f"... and {len(users) - 10} more users")


def _execute_import(import_data: Dict[str, Any], overwrite: bool, validate_only: bool):
    """Execute the import operation."""
    try:
        with st.spinner("Importing users..."):
            result = get_user_manager().import_users(
                import_data,
                overwrite_existing=overwrite,
                validate_only=validate_only
            )

        # Display results
        _render_import_results(result, validate_only)

        if not validate_only and result["success_count"] > 0:
            st.success(f"✅ Successfully imported {result['success_count']} users!")
            st.rerun()

    except Exception as e:
        st.error(f"❌ Import failed: {str(e)}")
        log("error", f"Import failed: {e}")


def _render_import_results(result: Dict[str, Any], validate_only: bool):
    """Render import results."""
    if validate_only:
        st.subheader("✅ Validation Results")
    else:
        st.subheader("📋 Import Results")

    col_res1, col_res2, col_res3 = st.columns(3)
    with col_res1:
        st.metric("Successful", result["success_count"])
    with col_res2:
        st.metric("Failed", result["failure_count"])
    with col_res3:
        st.metric("Total", result["success_count"] + result["failure_count"])

    if result["errors"]:
        with st.expander("⚠️ Errors", expanded=True):
            for error in result["errors"][:20]:
                st.error(error)
            if len(result["errors"]) > 20:
                st.warning(f"... and {len(result['errors']) - 20} more errors")


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
