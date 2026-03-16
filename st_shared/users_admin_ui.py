"""
Users Admin UI Module
====================

Provides admin interface for user management with hierarchical roles:
- Admin: Can view and manage all users
- Master: Can view and manage only themselves and their children
- Normal: No access to admin tab

"""

import streamlit as st
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import json
from shared.common import UserRole
from st_shared.cached import get_config, get_user_manager


from core.logging import log, set_log_module_level
from st_shared.cached import _
def is_production_mode() -> bool:
    """Check if we're in production mode (not local and not test)."""
    config = get_config()
    prod_mode = config.get("app.prod_mode", False)
    test_mode = config.get("app.test_mode", False) or "pytest" in str(st.__file__)

    # Production mode = not local and not test
    return prod_mode and not test_mode


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
    production_mode = is_production_mode()

    st.header("👥 User Administration")
    st.caption(f"Role: {user_role.capitalize()} | Viewing users you can manage")

    # Get manageable users based on role
    manageable_users = get_user_manager().get_manageable_users(user_id)

    # Create main tabs
    if user_role in [UserRole.ADMIN.value, UserRole.MASTER.value]:
        tab_names = ["📋 Manage Users", "➕ Create User", "📧 Pre-registered Emails"]

        # Add Activity Logs tab for production mode
        if production_mode:
            tab_names.append("📊 Activity Logs")

        if user_role == UserRole.ADMIN.value:
            tab_names.append("📦 Import/Export")

        tabs = st.tabs(tab_names)

        with tabs[0]:
            _render_user_management_tab(current_user, user_role, user_id, manageable_users, production_mode)

        with tabs[1]:
            _render_create_user_tab(current_user, user_role, production_mode)

        with tabs[2]:
            _render_preregistered_emails_tab(current_user)

        activity_logs_idx = 3
        if production_mode and len(tabs) > activity_logs_idx:
            with tabs[activity_logs_idx]:
                _render_activity_logs_tab(current_user, user_role, user_id)

        if user_role == UserRole.ADMIN.value:
            import_export_idx = activity_logs_idx + 1 if production_mode else 3
            if len(tabs) > import_export_idx:
                with tabs[import_export_idx]:
                    _render_import_export_tab(current_user)

    else:  # Should not happen due to can_access_admin_tab check
        st.info("No users found that you can manage.")


def _render_preregistered_emails_tab(current_user: Dict[str, Any]):
    """Render pre-registered email import/management."""
    st.subheader("📧 Pre-registered Emails")

    user_manager = get_user_manager()
    import_tab, manage_tab = st.tabs(["📥 Import CSV", "📋 Manage List"])

    with import_tab:
        uploaded_file = st.file_uploader(
            "Upload a CSV file with pre-registered emails",
            type=["csv"],
            key="preregistered_emails_csv_uploader",
        )

        if uploaded_file is not None:
            try:
                csv_content = uploaded_file.getvalue().decode("utf-8")
            except UnicodeDecodeError:
                st.error("❌ Could not decode CSV file as UTF-8")
            else:
                result = user_manager.import_preregistered_emails(
                    csv_content,
                    requesting_user_id=current_user.get("id"),
                )

                st.success(
                    f"Imported: {result['imported']} | Skipped duplicates: {result['skipped']}"
                )

                if result["invalid"]:
                    st.warning("Invalid emails skipped:")
                    for invalid_email in result["invalid"]:
                        st.caption(f"- {invalid_email}")

                if result["errors"]:
                    for error in result["errors"]:
                        st.error(error)

        with st.expander("Expected CSV format"):
            st.code(
                "email\n"
                "alice@example.com\n"
                "bob@company.org\n\n"
                "Accepted headers: email, e-mail, mail, email address, e-mail address, courriel",
                language="text",
            )

    with manage_tab:
        preregistered = user_manager.get_preregistered_emails()
        st.caption(f"Total pre-registered emails: {len(preregistered)}")

        if not preregistered:
            st.info("No pre-registered emails yet. Use the Import CSV tab to add some.")
            return

        for row in preregistered:
            cols = st.columns([4, 2, 2, 1])
            cols[0].write(row["email"])
            cols[1].caption(row.get("added_at") or "-")
            cols[2].caption(row.get("added_by") or "-")
            if cols[3].button("🗑️ Remove", key=f"remove_preregistered_{row['email']}", width='stretch'):
                if user_manager.delete_preregistered_email(row["email"]):
                    st.rerun()
                st.error("❌ Failed to remove email")



def _render_activity_logs_tab(current_user: Dict[str, Any], user_role: str, user_id: str):
    """Render the activity logs tab for production mode."""
    st.subheader("📊 User Activity Logs")

    # Filters
    col_filter1, col_filter2, col_filter3 = st.columns(3)

    with col_filter1:
        # Filter by action type
        action_options = ["All Actions", "login", "logout", "create_user", "update_user",
                         "delete_user", "generate_reset_code", "reset_password", "switch_user"]
        selected_action = st.selectbox("Action Type", action_options)

    with col_filter2:
        # Filter by user
        if user_role == UserRole.ADMIN.value:
            user_options = ["All Users"] + [u["name"] for u in get_user_manager().get_all_users()]
            selected_user_filter = st.selectbox("User", user_options)
        else:
            selected_user_filter = None

    with col_filter3:
        # Date range
        date_range = st.selectbox("Time Period", ["Last 24 hours", "Last 7 days", "Last 30 days", "All time"])

    # Determine date filter
    days_map = {
        "Last 24 hours": 1,
        "Last 7 days": 7,
        "Last 30 days": 30,
        "All time": None
    }
    days = days_map.get(date_range)

    # Get logs
    user_manager = get_user_manager()

    # Build filter parameters
    filter_params = {
        "current_user_id": user_id,
        "limit": 200
    }

    if selected_action and selected_action != "All Actions":
        filter_params["action"] = selected_action

    if selected_user_filter and selected_user_filter != "All Users":
        # Find user ID for the selected name
        all_users = user_manager.get_all_users_dict()
        target_user_id = None
        for uid, u in all_users.items():
            if u["name"] == selected_user_filter:
                target_user_id = uid
                break
        if target_user_id:
            filter_params["user_id"] = target_user_id

    logs = user_manager.get_user_action_logs(**filter_params)

    # Filter by date if needed
    if days:
        cutoff = datetime.utcnow() - timedelta(days=days)
        logs = [log for log in logs if datetime.fromisoformat(log["timestamp"]) >= cutoff]

    # Display logs
    if not logs:
        st.info("No activity logs found.")
        return

    st.write(f"Showing {len(logs)} log entries")

    # Display logs in a table
    for log_entry in logs:
        with st.container():
            cols = st.columns([2, 1.5, 2, 3])

            with cols[0]:
                timestamp = datetime.fromisoformat(log_entry["timestamp"])
                st.write(f"**{timestamp.strftime('%Y-%m-%d %H:%M:%S')}**")

            with cols[1]:
                status = "✅" if log_entry["success"] else "❌"
                st.write(f"{status} {log_entry['action'].replace('_', ' ').title()}")

            with cols[2]:
                user_display = log_entry.get("username") or log_entry.get("user_id", "System")
                if log_entry.get("target_username"):
                    user_display += f" → {log_entry['target_username']}"
                st.write(user_display)

            with cols[3]:
                if log_entry.get("details"):
                    details = log_entry["details"]
                    if isinstance(details, dict):
                        # Show a preview of important details
                        if "reason" in details:
                            st.caption(f"Reason: {details['reason']}")
                        elif "changes" in details:
                            changed_fields = list(details.get("changes", {}).keys())
                            st.caption(f"Changed: {', '.join(changed_fields)}")
                if log_entry.get("error_message"):
                    st.error(log_entry["error_message"])

            st.divider()

    # Export logs button
    if st.button("📥 Export Logs", width='stretch'):
        export_data = {
            "exported_at": datetime.utcnow().isoformat(),
            "logs": logs
        }
        json_str = json.dumps(export_data, indent=2, default=str)
        st.download_button(
            label="⬇️ Download JSON",
            data=json_str,
            file_name=f"activity_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json"
        )


def _render_user_management_tab(current_user: Dict[str, Any], user_role: str,
                               user_id: str, manageable_users: List[Dict[str, Any]],
                               production_mode: bool):
    """Render the user management tab with user list and operations."""
    st.subheader("📋 User List")

    try:
        if not manageable_users:
            st.info("No users found that you can manage.")
            return

        pending_users = [user for user in manageable_users if user.get("registration_status") == "pending"]
        if pending_users:
            col_banner, col_action = st.columns([4, 1])
            with col_banner:
                st.warning(f"⏳ {len(pending_users)} registration(s) pending approval")
            with col_action:
                if st.button("Review", key="review_pending_registrations", width='stretch'):
                    st.session_state.pending_registration_review = True

        if st.session_state.get("pending_registration_review") and pending_users:
            st.markdown("<a id='pending-registrations'></a>", unsafe_allow_html=True)
            st.info("Review pending registrations below.")

        # Display users in a table with actions
        for user in manageable_users:
            if user.get("registration_status") == "rejected":
                continue
            # Skip current user in the list for masters (they see themselves separately)
            if user_role == UserRole.MASTER.value and user["id"] == user_id:
                continue

            _render_user_row(current_user, user_role, user, production_mode)

        # Show current user info for masters
        if user_role == UserRole.MASTER.value:
            _render_master_account_section(current_user, user_id, production_mode)

        # Delete confirmation dialog
        _render_delete_confirmation(current_user, production_mode)

        # View user details
        _render_user_details(production_mode)

        # Edit user form
        _render_edit_user_form(current_user, production_mode)

    except Exception as e:
        st.error(f"❌ Error loading users: {str(e)}")
        log("error", f"Error in users admin UI: {e}")


def _generate_reset_code(target_user_id: str, requesting_user_id: str):
    """Generate a password reset code for a user."""
    user_manager = get_user_manager()
    reset_code = user_manager.generate_reset_code(target_user_id, requesting_user_id)

    if reset_code:
        target_user = user_manager.get_user(target_user_id)

        # Special handling for admin user to save code to file
        if target_user and target_user.get('name', '').lower() == 'admin':
            try:
                import os
                from datetime import datetime
                from st_shared.cached import get_config

                # Get database path from config
                config = get_config()
                db_path = config.get("database.path", "data")

                # Ensure directory exists
                os.makedirs(db_path, exist_ok=True)

                # Write reset code to file in database path
                reset_code_file = os.path.join(db_path, "reset_code.txt")
                with open(reset_code_file, 'w') as f:
                    f.write(f"Reset Code for admin generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"Reset Code: {reset_code}\n")
                    f.write(f"Expires: {(datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')}\n")

                st.success(f"✅ Reset code generated for {target_user['name']}")
                st.info(f"🔑 **Reset Code:** `{reset_code}`")
                st.info(f"📁 Reset code has been saved to `{reset_code_file}`")
                st.warning("⚠️ This code will expire in 24 hours. Share it securely with the user.")
            except Exception as e:
                st.success(f"✅ Reset code generated for {target_user['name']}")
                st.info(f"🔑 **Reset Code:** `{reset_code}`")
                st.warning(f"⚠️ Could not save to file: {str(e)}")
                st.warning("⚠️ This code will expire in 24 hours. Share it securely with the user.")
        else:
            st.success(f"✅ Reset code generated for {target_user['name']}")
            st.info(f"🔑 **Reset Code:** `{reset_code}`")
            st.warning("⚠️ This code will expire in 24 hours. Share it securely with the user.")

        st.rerun()
    else:
        st.error("❌ Failed to generate reset code")


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


def _render_master_account_section(current_user: Dict[str, Any], user_id: str, production_mode: bool):
    """Render the master account section with children information."""
    with st.expander("👑 Your Master Account", expanded=False):
        cols = st.columns([4, 1])
        with cols[0]:
            st.write(f"**{current_user['name']}**")
            st.caption(f"🆔 {current_user['id']}")
            if current_user.get('email'):
                st.caption(f"📧 {current_user['email']}")

            if production_mode:
                st.caption("🔒 " + ("Password set" if current_user.get('has_password') else "No password set"))

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


def _render_delete_confirmation(current_user: Dict[str, Any], production_mode: bool):
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
                _execute_user_deletion(user_to_delete, current_user, production_mode)

        with col_confirm2:
            if st.button("❌ Cancel", width='stretch'):
                _clear_delete_confirmation()


def _execute_user_deletion(user_to_delete: Dict[str, Any], current_user: Dict[str, Any], production_mode: bool):
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


def _render_user_details(production_mode: bool):
    """Render user details view."""
    if st.session_state.get('viewing_user_id'):
        user_id_to_view = st.session_state.viewing_user_id
        user_to_view = get_user_manager().get_user(user_id_to_view, include_children=True)

        if user_to_view:
            st.divider()
            st.subheader(f"👤 User Details: {user_to_view['name']}")

            col1, col2 = st.columns(2)
            with col1:
                _render_user_basic_info(user_to_view, production_mode)

            with col2:
                _render_user_profile_preferences(user_to_view)

            # Show children if any
            if user_to_view.get('role') in [UserRole.MASTER.value, UserRole.ADMIN.value]:
                _render_user_children(user_id_to_view)

            if st.button("Close Details", key="close_details"):
                st.session_state.viewing_user_id = None
                st.rerun()


def _render_user_basic_info(user: Dict[str, Any], production_mode: bool):
    """Render basic user information."""
    st.write("**Basic Information**")
    st.write(f"**ID:** {user['id']}")
    st.write(f"**Name:** {user['name']}")
    st.write(f"**Email:** {user.get('email') or 'Not set'}")
    st.write(f"**Role:** {user['role']}")
    st.write(f"**Status:** {'🟢 Active' if user['is_active'] else '🔴 Inactive'}")

    if production_mode:
        st.write(f"**Password:** {'✅ Set' if user.get('has_password') else '❌ Not set'}")

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


def _render_edit_user_form(current_user: Dict[str, Any], production_mode: bool):
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
        edit_data = _render_edit_form_fields(current_user, user_to_edit, is_editing_self, production_mode)

        col_ebtn1, col_ebtn2, col_ebtn3 = st.columns([1, 1, 2])
        with col_ebtn1:
            submit_edit = st.form_submit_button("💾 Save Changes", type="primary")
        with col_ebtn2:
            cancel_edit = st.form_submit_button("❌ Cancel")

        if submit_edit:
            _process_edit_submission(current_user, user_id_to_edit, is_editing_self, edit_data, production_mode)

        if cancel_edit:
            st.session_state.editing_user_id = None
            st.rerun()


def _render_edit_form_fields(current_user: Dict[str, Any], user_to_edit: Dict[str, Any],
                            is_editing_self: bool, production_mode: bool) -> Dict[str, Any]:
    """Render edit form fields and return the collected data."""
    col_e1, col_e2 = st.columns(2)
    with col_e1:
        edit_name = st.text_input("Username *", value=user_to_edit['name'])
    with col_e2:
        edit_email = st.text_input("Email", value=user_to_edit.get('email', ''))

    # User ID editing - only for admin users and not editing self
    new_id = None
    if current_user['role'] == UserRole.ADMIN.value and not is_editing_self:
        st.subheader("User ID")
        st.caption("⚠️ Changing user ID is a sensitive operation that may affect relationships")
        col_id1, col_id2 = st.columns([3, 1])
        with col_id1:
            new_id = st.text_input(
                "User ID",
                value=user_to_edit['id'],
                help="Change the user's unique identifier. Use with caution!"
            )
        with col_id2:
            st.write("")
            st.write("")
            if new_id != user_to_edit['id']:
                st.warning("⚠️ ID will be changed")
    else:
        st.caption(f"**User ID:** {user_to_edit['id']}")

    edit_role = user_to_edit.get('role')
    selected_parent = user_to_edit.get('parent_id')

    # Password reset section (production mode only)
    if production_mode and not is_editing_self:
        st.subheader("Password Management")
        if st.checkbox("Reset user's password", key="reset_pw_check"):
            col_reset1, col_reset2 = st.columns(2)
            with col_reset1:
                new_pw = st.text_input("New Password", type="password", key="admin_new_pw")
            with col_reset2:
                confirm_new_pw = st.text_input("Confirm New Password", type="password", key="admin_confirm_pw")

            if new_pw and new_pw == confirm_new_pw:
                st.session_state.admin_new_password = new_pw
                st.success("✅ Password will be updated")
            else:
                st.warning("Passwords do not match")

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
        "new_id": new_id if new_id and new_id != user_to_edit['id'] else None,
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


def _render_create_user_tab(current_user: Dict[str, Any], user_role: str, production_mode: bool):
    """Render the create user tab."""
    st.subheader("➕ Create New User")

    with st.form("create_user_form", clear_on_submit=True):
        user_data = _render_create_user_form_fields(current_user, user_role, production_mode)

        col_btn1, col_btn2 = st.columns([1, 3])
        with col_btn1:
            submit_create = st.form_submit_button("Create User", type="primary")

        if submit_create:
            _process_create_user_submission(user_data, current_user, production_mode)


def _render_create_user_form_fields(current_user: Dict[str, Any], user_role: str,
                                   production_mode: bool) -> Dict[str, Any]:
    """Render create user form fields and return the collected data."""
    col1, col2 = st.columns(2)
    with col1:
        new_name = st.text_input("Username *",
                               help="Required. This will be the display name.")
    with col2:
        new_email = st.text_input("Email",
                                help="Optional email address")

    # Password setup for production mode
    set_password = None
    if production_mode:
        st.write("**Password Setup**")
        col_pw1, col_pw2 = st.columns(2)
        with col_pw1:
            set_password = st.text_input("Set Password (optional)", type="password",
                                       help="Leave empty to generate a reset code")
        with col_pw2:
            confirm_password = st.text_input("Confirm Password", type="password")

        if set_password and set_password != confirm_password:
            st.warning("Passwords do not match")

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
        "profile": profile,
        "password": set_password if production_mode and set_password else None
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


def _process_create_user_submission(user_data: Dict[str, Any],
                                   current_user: Dict[str, Any],
                                   production_mode: bool):
    """Process the create user form submission."""
    if not user_data["name"] or not user_data["name"].strip():
        st.error("Username is required!")
    elif user_data["role"] == UserRole.NORMAL.value and not user_data["parent_id"]:
        st.error("Normal users must have a parent!")
    else:
        try:
            user_manager = get_user_manager()
            user_id, reset_code = user_manager.create_user(
                name=user_data["name"].strip(),
                role=user_data["role"],
                email=user_data["email"].strip() if user_data["email"] else None,
                parent_id=user_data["parent_id"] if user_data["parent_id"] else None,
                profile=user_data["profile"],
                password=user_data.get("password"),
                requesting_user_id=current_user['id']
            )

            if production_mode and not user_data.get("password") and reset_code:
                st.success(f"✅ User '{user_data['name'].strip()}' created successfully!")
                st.info(f"🔑 **Reset Code:** `{reset_code}`")
                st.warning("⚠️ This code will expire in 24 hours. Share it securely with the user.")
            else:
                st.success(f"✅ User '{user_data['name'].strip()}' created successfully!")

            log("info", f"Created user: {user_data['name']} (ID: {user_id}, Role: {user_data['role']})")
            st.rerun()
        except ValueError as e:
            st.error(f"❌ Validation error: {str(e)}")
        except Exception as e:
            st.error(f"❌ Error creating user: {str(e)}")
            log("error", f"Failed to create user: {e}")


def _process_edit_submission(current_user: Dict[str, Any], user_id_to_edit: str,
                            is_editing_self: bool, edit_data: Dict[str, Any],
                            production_mode: bool):
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

            # Add new_id if provided (only for admin)
            if edit_data.get("new_id") and current_user['role'] == UserRole.ADMIN.value and not is_editing_self:
                updates["new_id"] = edit_data["new_id"].strip()

            # Add role and parent if admin editing
            if current_user['role'] == UserRole.ADMIN.value and not is_editing_self:
                updates["role"] = edit_data["role"]
                if edit_data["role"] == UserRole.NORMAL.value:
                    updates["parent_id"] = edit_data["parent_id"]
                else:
                    updates["parent_id"] = None

            # Handle password reset in production mode
            if production_mode and not is_editing_self:
                if st.session_state.get('reset_pw_check', False):
                    if st.session_state.get('admin_new_password'):
                        user_manager = get_user_manager()
                        user_manager.set_password(
                            user_id_to_edit,
                            st.session_state.admin_new_password,
                            current_user['id']
                        )
                        st.success("✅ Password updated successfully!")

            success = get_user_manager().update_user(
                user_id_to_edit,
                current_user['id'],
                **updates
            )

            if success:
                # If ID was changed, show a message about the new ID
                if updates.get("new_id") and updates["new_id"] != user_id_to_edit:
                    st.success(f"✅ User updated successfully! New ID: {updates['new_id']}")
                else:
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


def _render_import_export_tab(current_user: Dict[str, Any]):
    """Render the import/export tab for admin users."""
    st.subheader("📦 Import/Export Users")

    # Create tabs for import and export
    import_export_tab1, import_export_tab2 = st.tabs(["📤 Export Users", "📥 Import Users"])

    with import_export_tab1:
        _render_export_section(current_user)

    with import_export_tab2:
        _render_import_section(current_user)


def _render_export_section(current_user: Dict[str, Any]):
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
            all_users_list = get_user_manager().get_all_users(current_user['id'])
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
            _execute_export(current_user, include_children, selected_user_ids)

    # Display download button if export data is available
    if st.session_state.get('export_json_data'):
        st.download_button(
            label="⬇️ Download JSON File",
            data=st.session_state.export_json_data,
            file_name=st.session_state.export_filename,
            mime="application/json",
            width='stretch'
        )


def _execute_export(current_user: Dict[str, Any], include_children: bool, selected_user_ids: List[str]):
    """Execute the export operation."""
    try:
        export_data = get_user_manager().export_users(
            include_children=include_children,
            user_ids=selected_user_ids if selected_user_ids else None,
            requesting_user_id=current_user['id']
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


def _render_import_section(current_user: Dict[str, Any]):
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
        _process_import_file(uploaded_file, current_user)


def _process_import_file(uploaded_file, current_user: Dict[str, Any]):
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
            _execute_import(import_data, overwrite, validate_only, current_user)

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


def _execute_import(import_data: Dict[str, Any], overwrite: bool, validate_only: bool,
                   current_user: Dict[str, Any]):
    """Execute the import operation."""
    try:
        with st.spinner("Importing users..."):
            result = get_user_manager().import_users(
                import_data,
                overwrite_existing=overwrite,
                validate_only=validate_only,
                requesting_user_id=current_user['id']
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

def _render_user_row(current_user: Dict[str, Any], user_role: str,
                    user: Dict[str, Any], production_mode: bool):
    """Render a single user row in the user list."""
    with st.container():
        cols = st.columns([3, 2, 1, 1, 2])

        with cols[0]:
            pending_badge = " ⏳ Pending" if user.get('registration_status') == 'pending' else ""
            st.write(f"**{user['name']}**{pending_badge}")
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

            # Password status (production mode only)
            if production_mode:
                if user.get('has_password'):
                    st.caption("🔒 Password set")
                else:
                    st.caption("⚠️ No password")

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

        is_pending = user.get('registration_status') == 'pending'

        with cols[3]:
            if is_pending:
                if st.button("✅ Approve",
                           key=f"approve_{user['id']}",
                           help=f"Approve registration for {user['name']}",
                           width='stretch'):
                    if get_user_manager().set_registration_status(user['id'], 'approved'):
                        st.rerun()
                    st.error("❌ Failed to approve user")
            else:
                # Edit button
                if st.button("✏️ Edit",
                           key=f"edit_{user['id']}",
                           help=f"Edit user {user['name']}",
                           width='stretch'):
                    st.session_state.editing_user_id = user['id']
                    st.rerun()

        with cols[4]:
            if is_pending:
                if st.button("❌ Reject",
                           key=f"reject_{user['id']}",
                           help=f"Reject registration for {user['name']}",
                           width='stretch'):
                    if get_user_manager().set_registration_status(user['id'], 'rejected'):
                        st.rerun()
                    st.error("❌ Failed to reject user")
            else:
                # Check if current user can generate reset code for this user
                can_generate_reset = False

                # Admin can generate for anyone
                if user_role == UserRole.ADMIN.value:
                    can_generate_reset = True
                # Master can generate for their children (normal users)
                elif user_role == UserRole.MASTER.value:
                    # Master can generate for normal users that are their children
                    if user.get('role') == UserRole.NORMAL.value:
                        # Check if this user is a child of the current master
                        if user.get('parent_id') == current_user['id']:
                            can_generate_reset = True

                if can_generate_reset:
                    # Check for existing reset code in database
                    user_manager = get_user_manager()
                    from core.database import get_db_manager

                    # Direct database query to check for reset code
                    db_manager = get_db_manager()
                    if db_manager.is_initialized():
                        with db_manager.get_session() as session:
                            from shared.users import UserTable
                            db_user = session.query(UserTable).filter_by(id=user['id']).first()

                            if db_user and db_user.reset_code and db_user.reset_code_expires:
                                # Check if code is still valid (not expired)
                                if db_user.reset_code_expires > datetime.utcnow():
                                    # Display the existing reset code
                                    st.info("🔑 Reset Code Available")
                                    with st.expander("Show Reset Code", expanded=False):
                                        st.code(db_user.reset_code, language="text")
                                        expiry = db_user.reset_code_expires.strftime('%Y-%m-%d %H:%M:%S')
                                        st.caption(f"Expires: {expiry}")
                                else:
                                    # Code expired, show button to generate new one
                                    if st.button("🔑 New Reset Code",
                                                key=f"reset_{user['id']}",
                                                help=f"Generate new password reset code for {user['name']}",
                                                width='stretch'):
                                        _generate_reset_code(user['id'], current_user['id'])
                            else:
                                # No reset code, show button to generate one
                                if st.button("🔑 Generate Code",
                                            key=f"reset_{user['id']}",
                                            help=f"Generate password reset code for {user['name']}",
                                            width='stretch'):
                                    _generate_reset_code(user['id'], current_user['id'])
                else:
                    # If user can't generate reset code, show placeholder or nothing
                    st.write("")  # Empty placeholder to maintain layout
                _render_delete_button(current_user, user)

        st.divider()


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
    if "pending_registration_review" not in st.session_state:
        st.session_state.pending_registration_review = False
