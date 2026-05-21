"""Waitlist UI components for the admin panel."""

import streamlit as st
from typing import Any, Dict, List

from shared.common import UserRole
from st_shared.cached import get_user_manager


def _get_masters(user_manager) -> List[Dict[str, Any]]:
    all_users = user_manager.get_all_users() if hasattr(user_manager, "get_all_users") else []
    return [u for u in all_users if u.get("role") == "master"]


def _render_create_waitlist_list_form(current_user: Dict[str, Any], user_manager) -> None:
    masters = _get_masters(user_manager)
    master_options = [""] + [m["id"] for m in masters]
    master_names = {m["id"]: m["name"] for m in masters}

    col_create, col_btn = st.columns([4, 1])
    with col_create:
        new_list_name = st.text_input("Create new waitlist list", placeholder="e.g., Spring 2026 Cohort")
        selected_master = st.selectbox(
            "Default master for this list",
            options=master_options,
            format_func=lambda x: master_names.get(x, "Select master...") if x else "Select master...",
            key="new_waitlist_master",
        )
        default_dur = st.number_input(
            "Default expiration (days, 0 = unlimited)",
            min_value=0, value=365, step=30, key="new_waitlist_duration",
        )
    with col_btn:
        st.write("")
        if st.button("➕ Create", key="create_waitlist_list", type="primary"):
            if not (new_list_name and new_list_name.strip()):
                st.error("Please enter a list name")
                return
            list_id = user_manager.create_waitlist_list(
                new_list_name.strip(),
                current_user["id"],
                default_master_id=selected_master or None,
                default_duration_days=default_dur if default_dur > 0 else None,
            )
            if list_id:
                st.success(f"✅ Created list: {new_list_name}")
                st.rerun()
            else:
                st.error("❌ List already exists or invalid name")


def _render_waitlist_list_row(wl_list: Dict[str, Any], user_manager) -> None:
    cols = st.columns([3, 2, 2, 1])
    with cols[0]:
        st.write(f"**{wl_list['name']}**")
        if wl_list.get("created_at"):
            st.caption(f"Created: {wl_list['created_at'][:10]}")
    with cols[1]:
        if wl_list.get("created_by"):
            creator = user_manager.get_user(wl_list["created_by"])
            if creator:
                st.caption(f"By: {creator['name']}")
    with cols[2]:
        entry_count = len(user_manager.get_waitlist_entries(list_id=wl_list["id"]))
        st.caption(f"{entry_count} entries")
        if wl_list.get("default_duration_days"):
            st.caption(f"⏱️ {wl_list['default_duration_days']} days")
        if wl_list.get("default_master_id"):
            m = user_manager.get_user(wl_list["default_master_id"])
            if m:
                st.caption(f"⭐ {m['name']}")
    with cols[3]:
        if st.button("🗑️ Delete", key=f"delete_waitlist_list_{wl_list['id']}", width="stretch"):
            if user_manager.delete_waitlist_list(wl_list["id"]):
                st.warning(f"⚠️ Deleted list: {wl_list['name']}")
                st.rerun()
            else:
                st.error("❌ Failed to delete list")


def _render_edit_waitlist_list_defaults(lists: List[Dict[str, Any]], user_manager) -> None:
    st.write("**Edit list defaults (master + expiration duration):**")
    edit_ids = [""] + [wl["id"] for wl in lists]
    edit_names = {wl["id"]: wl["name"] for wl in lists}
    selected_edit = st.selectbox(
        "Select list to edit",
        options=edit_ids,
        format_func=lambda x: edit_names.get(x, "Select a list...") if x else "Select a list...",
        key="edit_waitlist_list_select",
    )
    if not selected_edit:
        return

    current_list = next((wl for wl in lists if wl["id"] == selected_edit), None)
    current_master = current_list.get("default_master_id") if current_list else None
    current_duration = (current_list.get("default_duration_days") or 365) if current_list else 365

    masters = _get_masters(user_manager)
    master_options = [""] + [m["id"] for m in masters]
    master_names = {m["id"]: m["name"] for m in masters}

    new_master = st.selectbox(
        "Default master",
        options=master_options,
        index=master_options.index(current_master) if current_master in master_options else 0,
        format_func=lambda x: master_names.get(x, "Select master...") if x else "Select master...",
        key="edit_waitlist_master",
    )
    new_duration = st.number_input(
        "Expiration duration (days, 0 = unlimited)",
        min_value=0, value=current_duration, step=30, key="edit_waitlist_duration",
    )
    if st.button("💾 Save defaults", key="save_waitlist_defaults"):
        if user_manager.update_waitlist_list_defaults(
            selected_edit,
            default_master_id=new_master or None,
            default_duration_days=new_duration if new_duration > 0 else None,
        ):
            st.success("✅ Defaults updated")
            st.rerun()
        else:
            st.error("❌ Failed to update")


def _render_waitlist_lists_tab(
    current_user: Dict[str, Any],
    user_role: str,
) -> None:
    """Render waitlist lists management tab."""
    st.subheader("📝 Waitlist Lists")
    _ = user_role

    user_manager = get_user_manager()
    _render_create_waitlist_list_form(current_user, user_manager)
    st.divider()

    lists = user_manager.get_all_waitlist_lists()
    if not lists:
        st.info("No waitlist lists yet. Create one above.")
        return

    st.write(f"**Existing Lists ({len(lists)}):**")
    for wl_list in lists:
        _render_waitlist_list_row(wl_list, user_manager)
    st.divider()
    _render_edit_waitlist_list_defaults(lists, user_manager)


def _render_waitlist_entry_row(
    entry: Dict[str, Any],
    lists: List[Dict[str, Any]],
    masters: List[Dict[str, Any]],
    user_manager,
    default_days,
) -> None:
    list_name = next((l["name"] for l in lists if l["id"] == entry["list_id"]), entry["list_id"])
    master_name = ""
    if entry.get("master_id"):
        master = user_manager.get_user(entry["master_id"])
        if master:
            master_name = master["name"]

    entry_duration = 0
    cols = st.columns([3, 2, 1, 1, 1, 1])
    with cols[0]:
        st.write(f"**{entry['email']}**")
        st.caption(f"List: {list_name}")
        if entry.get("created_at"):
            st.caption(f"Added: {entry['created_at'][:10]}")
    with cols[1]:
        status_color = "🟡" if entry["status"] == "pending" else "🟢" if entry["status"] == "approved" else "🔴"
        st.caption(f"Status: {status_color} {entry['status']}")
        if master_name:
            st.caption(f"Master: {master_name}")
        if entry.get("user_id"):
            st.caption(f"User: {entry['user_id']}")
    with cols[2]:
        if entry["status"] == "pending":
            entry_duration = st.number_input(
                "Days",
                min_value=0,
                max_value=3650,
                value=default_days or 0,
                step=1,
                key=f"entry_duration_{entry['id']}",
                help="Activation duration in days (0 = no expiration)",
                label_visibility="collapsed",
            )
    with cols[3]:
        if entry["status"] == "pending":
            if st.button("✅ Approve", key=f"approve_entry_{entry['id']}", width="stretch"):
                if masters:
                    days_to_use = int(entry_duration) if entry_duration > 0 else None
                    created_user = user_manager.approve_waitlist_entry(entry["id"], masters[0]["id"], duration_days=days_to_use)
                    if created_user:
                        st.success(f"✅ Approved! User: {created_user}")
                        st.rerun()
                    st.error("❌ Failed to approve")
                else:
                    st.error("No masters available")
    with cols[4]:
        if entry["status"] == "pending":
            if st.button("❌ Reject", key=f"reject_entry_{entry['id']}", width="stretch"):
                if user_manager.reject_waitlist_entry(entry["id"]):
                    st.warning("❌ Rejected")
                    st.rerun()
                st.error("❌ Failed to reject")
    with cols[5]:
        if entry["status"] == "rejected":
            if st.button("🔄 Re-approve", key=f"reetry_entry_{entry['id']}", width="stretch"):
                if user_manager.reapprove_waitlist_entry(entry["id"]):
                    st.success("✅ Re-approved! Set back to pending.")
                    st.rerun()
                st.error("❌ Failed to re-approve")
    st.divider()


def _render_waitlist_bulk_actions(
    entries: List[Dict[str, Any]],
    masters: List[Dict[str, Any]],
    user_manager,
    default_days,
) -> None:
    pending_entries = [e["id"] for e in entries if e["status"] == "pending"]

    col_select_all, col_select_pending = st.columns(2)
    with col_select_all:
        if st.button("Select All", key="select_all_entries", width="stretch"):
            st.session_state.waitlist_entries_bulk_selection = [e["id"] for e in entries]
            st.rerun()
    with col_select_pending:
        if st.button("Select All Pending", key="select_pending_entries", width="stretch", disabled=not pending_entries):
            st.session_state.waitlist_entries_bulk_selection = pending_entries
            st.rerun()

    current_entry_ids = [e["id"] for e in entries]
    valid_default = [eid for eid in st.session_state.get("waitlist_entries_bulk_selection", []) if eid in current_entry_ids]
    selected_entry_ids = st.multiselect(
        "Select multiple entries",
        options=current_entry_ids,
        format_func=lambda eid: next(
            (f"{e['email']} - {e['status']}" for e in entries if e["id"] == eid), eid
        ),
        key="waitlist_entries_bulk_selection",
        default=valid_default,
    )

    master_ids = [m["id"] for m in masters]
    master_names = {m["id"]: m["name"] for m in masters}
    col_bulk_actions = st.columns([2, 1, 2, 2])
    with col_bulk_actions[0]:
        selected_master = st.selectbox(
            "Assign to master",
            options=master_ids,
            format_func=lambda x: master_names.get(x, "Select master...") if x else "Select master...",
            key="bulk_approve_master_select",
        )
    with col_bulk_actions[1]:
        bulk_duration = st.number_input(
            "Days",
            min_value=0,
            max_value=3650,
            value=default_days or 0,
            step=1,
            key="waitlist_bulk_duration",
            help="Activation duration in days (0 = use default / no expiration)",
        )
    with col_bulk_actions[2]:
        if st.button("✅ Approve selected", key="waitlist_bulk_approve_entries", width="stretch", disabled=not selected_master or not selected_entry_ids):
            days_to_use = int(bulk_duration) if bulk_duration > 0 else None
            created = user_manager.bulk_approve_waitlist_entries(selected_entry_ids, selected_master, duration_days=days_to_use)
            if created:
                st.success(f"✅ Approved {len(created)} user(s).")
                st.rerun()
            st.warning("No entries were approved.")
    with col_bulk_actions[3]:
        if st.button("❌ Reject selected", key="waitlist_bulk_reject_entries", width="stretch", disabled=not selected_entry_ids):
            rejected = user_manager.bulk_reject_waitlist_entries(selected_entry_ids)
            if rejected:
                st.warning(f"Rejected {rejected} entry(s).")
                st.rerun()
            st.warning("No entries were rejected.")


def _render_waitlist_entries_tab(
    current_user: Dict[str, Any],
    user_role: str,
    manageable_users: List[Dict[str, Any]],
) -> None:
    """Render waitlist entries with filtering by list and master approval."""
    st.subheader("🕒 Waitlist Entries")
    _ = user_role

    user_manager = get_user_manager()
    lists = user_manager.get_all_waitlist_lists()

    col_filter1, col_filter2 = st.columns(2)
    list_ids = [""] + [l["id"] for l in lists]
    list_names = {l["id"]: l["name"] for l in lists}
    with col_filter1:
        selected_list = st.selectbox(
            "Filter by list",
            options=list_ids,
            format_func=lambda x: list_names.get(x, "All lists") if x else "All lists",
            key="waitlist_entries_filter_list",
        )
    with col_filter2:
        selected_status = st.selectbox(
            "Filter by status",
            options=["", "pending", "approved", "rejected"],
            format_func=lambda x: x.capitalize() if x else "All statuses",
            key="waitlist_entries_filter_status",
        )

    entries = user_manager.get_waitlist_entries(
        list_id=selected_list if selected_list else None,
        status=selected_status if selected_status else None,
    )

    if not entries:
        st.success("No waitlist entries found.")
        return

    st.info(f"{len(entries)} entry(s) found.")

    masters = user_manager.get_users_by_role(UserRole.MASTER.value)
    default_days = user_manager.get_default_activation_duration_days()

    _render_waitlist_bulk_actions(entries, masters, user_manager, default_days)
    st.divider()
    for entry in entries:
        _render_waitlist_entry_row(entry, lists, masters, user_manager, default_days)


def _render_waitlist_tab(
    current_user: Dict[str, Any],
    user_role: str,
    manageable_users: List[Dict[str, Any]],
) -> None:
    """Render waitlist registrations with single and bulk approval actions."""
    st.subheader("🕒 Waitlist")
    _ = user_role

    waitlist_users = [
        user
        for user in manageable_users
        if user.get("registration_status") == "pending"
        and (user.get("metadata") or {}).get("created_via") == "waitlist"
        and user.get("id") != current_user.get("id")
    ]

    if not waitlist_users:
        st.success("No users are currently waiting on the waitlist.")
        return

    st.info(f"{len(waitlist_users)} waitlist registration(s) awaiting approval.")

    selected_ids = st.multiselect(
        "Select multiple waitlist users",
        options=[user["id"] for user in waitlist_users],
        format_func=lambda uid: next(
            (
                f"{user.get('name', user['id'])} ({user.get('email') or 'no-email'})"
                for user in waitlist_users
                if user["id"] == uid
            ),
            uid,
        ),
        key="waitlist_bulk_selection",
    )
    col_bulk_approve, col_bulk_reject = st.columns(2)
    with col_bulk_approve:
        if st.button("✅ Approve selected", key="waitlist_bulk_approve", width="stretch"):
            changed = sum(
                1 for uid in selected_ids
                if get_user_manager().set_registration_status(uid, "approved")
            )
            if changed:
                st.success(f"Approved {changed} waitlist user(s).")
                st.rerun()
            st.warning("No waitlist user was approved.")
    with col_bulk_reject:
        if st.button("❌ Reject selected", key="waitlist_bulk_reject", width="stretch"):
            changed = sum(
                1 for uid in selected_ids
                if get_user_manager().set_registration_status(uid, "rejected")
            )
            if changed:
                st.warning(f"Rejected {changed} waitlist user(s).")
                st.rerun()
            st.warning("No waitlist user was rejected.")

    st.divider()
    for user in waitlist_users:
        cols = st.columns([3, 2, 1, 1])
        with cols[0]:
            st.write(f"**{user.get('name', user['id'])}**")
            st.caption(f"📧 {user.get('email') or '-'}")
            st.caption(f"🆔 {user['id']}")
        with cols[1]:
            if user.get("created_at"):
                st.caption(f"📅 Requested: {user['created_at'][:10]}")
            st.caption("Source: waitlist")
        with cols[2]:
            if st.button("✅ Approve", key=f"waitlist_approve_{user['id']}", width="stretch"):
                if get_user_manager().set_registration_status(user["id"], "approved"):
                    st.success(f"✅ {user.get('name', user['id'])} approved.")
                    st.rerun()
                st.error("❌ Failed to approve user.")
        with cols[3]:
            if st.button("❌ Reject", key=f"waitlist_reject_{user['id']}", width="stretch"):
                if get_user_manager().set_registration_status(user["id"], "rejected"):
                    st.warning(f"❌ {user.get('name', user['id'])} rejected.")
                    st.rerun()
                st.error("❌ Failed to reject user.")
        st.divider()
