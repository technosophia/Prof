"""Payhip Webhook Admin UI."""

import streamlit as st

from modules.payhip_webhook.payhip_webhook import get_payhip_webhook_manager
from shared.users import UserManager


def _fetch_user_reset_info(email: str) -> dict:
    """Return reset_code info for a user by email (admin diagnostic use only)."""
    from core.database import get_db_manager
    from sqlalchemy import text
    db = get_db_manager()
    with db.get_session() as session:
        row = session.execute(
            text("SELECT id, name, reset_code, reset_code_expires FROM users WHERE LOWER(email) = LOWER(:email)"),
            {"email": email},
        ).fetchone()
    if not row:
        return {}
    code = row[2]
    expires = row[3]
    return {
        "user_id": row[0],
        "username": row[1],
        "reset_code": code,
        "reset_code_expires": str(expires) if expires else None,
        "has_valid_code": bool(code),
    }


def render_admin_tab():
    """Render the Payhip Webhook admin tab."""
    st.header("Payhip Webhook")

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Associations", "Logs", "Simulator", "Resend Email", "Settings"])

    with tab1:
        _render_associations_tab()

    with tab2:
        _render_logs_tab()

    with tab3:
        _render_simulator_tab()

    with tab4:
        _render_resend_tab()

    with tab5:
        _render_settings_tab()


def _render_associations_tab():
    """Manage master-product key associations."""
    st.subheader("Master-Product Associations")

    manager = get_payhip_webhook_manager()
    user_manager = UserManager()

    with st.expander("Add New Association", expanded=False):
        with st.form("add_association"):
            masters = [u for u in user_manager.get_all_users() if u.get("role") == "master"]

            if not masters:
                st.warning("No masters found. Create a master user first.")
                return

            master_options = {m["id"]: f"{m['name']} ({m['email']})" for m in masters}
            selected_master = st.selectbox("Master User", options=list(master_options.keys()), format_func=lambda x: master_options[x])

            product_key = st.text_input("Product Key (Payhip permalink)", placeholder="e.g., nb7fD")
            product_name = st.text_input("Product Name (optional)", placeholder="e.g., My Course")

            submitted = st.form_submit_button("Add Association")

            if submitted and product_key:
                success, msg = manager.add_product_association(
                    master_id=selected_master,
                    product_key=product_key.strip(),
                    product_name=product_name.strip() or None,
                )
                if success:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

    st.divider()

    associations = manager.get_all_associations()

    if not associations:
        st.info("No associations configured yet.")
        return

    for assoc in associations:
        col1, col2, col3, col4 = st.columns([2, 2, 2, 1])

        with col1:
            st.text(f"Product: {assoc['product_key']}")
        with col2:
            st.text(f"Master: {assoc['master_name'] or assoc['master_id']}")
        with col3:
            status = "Active" if assoc["is_active"] else "Inactive"
            st.text(status)
        with col4:
            if st.button("Delete", key=f"del_{assoc['id']}"):
                if manager.remove_product_association(assoc["id"]):
                    st.success("Deleted")
                    st.rerun()
                else:
                    st.error("Failed")


def _render_logs_tab():
    """View webhook operation logs."""
    st.subheader("Webhook Logs")

    manager = get_payhip_webhook_manager()

    col1, col2, col3 = st.columns([1, 1, 2])

    with col1:
        status_filter = st.selectbox("Status", options=["all", "success", "error", "duplicate"], index=0)

    with col2:
        event_filter = st.selectbox("Event Type", options=["all", "paid", "subscription.created"], index=0)

    with col3:
        limit = st.slider("Limit", 10, 500, 100)

    status = None if status_filter == "all" else status_filter
    event_type = None if event_filter == "all" else event_filter

    logs = manager.get_logs(status=status, event_type=event_type, limit=limit)

    if not logs:
        st.info("No logs found.")
        return

    for log_entry in logs:
        with st.expander(f"{log_entry['event_type']} - {log_entry['status']} - {log_entry['created_at']}", expanded=False):
            col1, col2 = st.columns(2)

            with col1:
                st.text(f"Email: {log_entry['customer_email']}")
                st.text(f"Product: {log_entry['product_key']}")
                st.text(f"Master ID: {log_entry['master_id'] or 'N/A'}")

            with col2:
                st.text(f"User ID: {log_entry['user_id'] or 'N/A'}")
                st.text(f"Status: {log_entry['status']}")
                st.text(f"Transaction: {log_entry['transaction_id'] or 'N/A'}")

            if log_entry.get("error_message"):
                st.error(f"Error: {log_entry['error_message']}")

            if log_entry.get("raw_payload"):
                with st.expander("Raw JSON payload", expanded=False):
                    import json
                    try:
                        parsed = json.loads(log_entry["raw_payload"])
                        st.json(parsed)
                    except (json.JSONDecodeError, TypeError):
                        st.code(log_entry["raw_payload"], language="json")


def _render_simulator_tab():
    """Send a simulated webhook payload to test the processing pipeline."""
    st.subheader("Webhook Simulator")
    st.info("Simulate a Payhip purchase event without real payment. Signature verification is skipped.")

    manager = get_payhip_webhook_manager()

    current_user = st.session_state.get("current_user", {})
    current_role = current_user.get("role", "")
    current_id = current_user.get("id", "")

    all_associations = manager.get_all_associations()
    # Masters only see their own products; admins see all
    if current_role == "master":
        associations = [a for a in all_associations if a["master_id"] == current_id]
    else:
        associations = all_associations

    if not associations:
        if current_role == "master" and all_associations:
            st.warning(
                f"No associations found for your master account (id: `{current_id}`). "
                f"There are {len(all_associations)} association(s) in total but they belong to other masters. "
                "Add one for your account in the Associations tab."
            )
        else:
            st.warning("No product associations configured. Add one in the Associations tab first.")
        with st.expander("Debug — current session info", expanded=True):
            st.json({
                "current_role": current_role,
                "current_id": current_id,
                "total_associations_in_db": len(all_associations),
                "associations_for_this_account": len(associations),
                "all_master_ids_in_db": list({a["master_id"] for a in all_associations}),
            })
        return

    product_options = {a["product_key"]: f"{a['product_name'] or a['product_key']} → {a['master_name']}" for a in associations}

    with st.form("simulate_webhook"):
        email = st.text_input("Customer Email", placeholder="student@example.com")
        product_key = st.selectbox("Product Key", options=list(product_options.keys()), format_func=lambda k: product_options[k])
        event_type = st.selectbox("Event Type", ["paid", "subscription.created"])
        force = st.checkbox("Force (bypass duplicate check)", value=True,
                            help="Re-process even if the same email+product was already handled")

        submitted = st.form_submit_button("Send Simulated Webhook")

        if submitted:
            if not email or "@" not in email:
                st.error("Please enter a valid email address.")
            else:
                import json
                payload = {
                    "type": event_type,
                    "email": email.strip(),
                    "product_link": product_key,
                    "id": f"sim_{email.strip().split('@')[0]}",
                }
                raw = json.dumps(payload)
                status_code, message = manager.process_webhook(payload, raw, force=force)

                if status_code < 400:
                    st.success(f"Result ({status_code}): {message.split(' | email_diag=')[0]}")
                else:
                    st.error(f"Error ({status_code}): {message}")

                # ── Reset code + email diagnostic ──────────────────────────
                target_email = email.strip()
                reset_info = _fetch_user_reset_info(target_email)

                if reset_info:
                    with st.expander("Reset code & email delivery", expanded=True):
                        col_a, col_b = st.columns(2)
                        with col_a:
                            st.markdown("**DB reset code**")
                            if reset_info.get("has_valid_code"):
                                st.success(f"`{reset_info['reset_code']}`")
                                st.caption(f"Expires: {reset_info['reset_code_expires']}")
                            else:
                                st.error("No reset code in DB")

                        with col_b:
                            st.markdown("**MailerLite subscriber fields**")
                            from shared.mailer_lite import get_configured_group_id
                            group_id = get_configured_group_id()
                            if group_id:
                                st.success(f"Group: `{group_id}`")
                            else:
                                st.warning("No group configured — automation won't fire")

                            # Parse email_diag out of the message if present
                            if " | email_diag=" in message:
                                import ast
                                try:
                                    diag_str = message.split(" | email_diag=", 1)[1]
                                    diag = ast.literal_eval(diag_str)
                                    ml = diag.get("mailerlite", {})
                                    ms = diag.get("mailersend", {})

                                    if ml.get("ok"):
                                        rc_sent = ml.get("reset_code_included", False)
                                        st.success("MailerLite upsert OK")
                                        if rc_sent:
                                            st.success("reset_code field sent")
                                        else:
                                            st.error("reset_code field NOT sent")
                                    else:
                                        st.error(f"MailerLite failed: {ml.get('error', '?')}")

                                    st.markdown("**MailerSend (transactional)**")
                                    if ms.get("ok"):
                                        st.success("Email queued via MailerSend")
                                    else:
                                        st.warning(f"MailerSend: {ms.get('msg', 'not configured')}")
                                except Exception:
                                    pass

                # ── Last log entry ─────────────────────────────────────────
                recent = manager.get_logs(limit=5)
                match = next((l for l in recent if l["customer_email"] == target_email), None)
                if match:
                    with st.expander("Last webhook log entry"):
                        st.json({k: v for k, v in match.items() if k != "raw_payload"})

    st.divider()
    st.markdown("**Replay a previous webhook** — paste raw payload from a log entry above.")

    raw_payload = st.text_area("Raw JSON payload", height=150)
    if st.button("Replay Payload"):
        import json
        try:
            p = json.loads(raw_payload)
            sc, msg = manager.process_webhook(p, raw_payload)
            if sc < 400:
                st.success(f"Result ({sc}): {msg}")
            else:
                st.error(f"Error ({sc}): {msg}")
        except json.JSONDecodeError as e:
            st.error(f"Invalid JSON: {e}")


def _render_resend_tab():
    """Resend the welcome email (with a fresh reset code) to any registered user."""
    st.subheader("Resend Welcome Email")
    st.info("Generates a new reset code and resends the activation email. Use this when a user lost their email or for testing.")

    manager = get_payhip_webhook_manager()

    with st.form("resend_welcome"):
        email = st.text_input("Customer email", placeholder="user@example.com")
        submitted = st.form_submit_button("Resend")

        if submitted:
            if not email or "@" not in email:
                st.error("Please enter a valid email address.")
            else:
                ok, msg = manager.resend_welcome_email(email.strip())
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)


def _render_settings_tab():
    """Webhook settings and info."""
    st.subheader("Webhook Settings")

    import os

    api_key_set = bool(os.getenv("PAYHIP_API_KEY"))

    col1, col2 = st.columns(2)

    with col1:
        st.text("PAYHIP_API_KEY")
        if api_key_set:
            st.success("Configured")
        else:
            st.error("Not set")

    st.divider()

    st.info("""
    **Webhook Endpoint:**
    ```
    POST /api/webhooks/payhip
    ```

    Configure this URL in your Payhip dashboard under Settings > Developer > Webhooks.
    """)

    st.markdown("""
    **Supported Events:**
    - `paid` - One-time purchase
    - `subscription.created` - New subscription

    The webhook will automatically create a new user associated with the master
    linked to the product key in the purchase.
    """)
