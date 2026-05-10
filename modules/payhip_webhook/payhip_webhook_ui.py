"""Payhip Webhook Admin UI."""

import streamlit as st

from modules.payhip_webhook.payhip_webhook import get_payhip_webhook_manager
from shared.users import UserManager


def render_admin_tab():
    """Render the Payhip Webhook admin tab."""
    st.header("Payhip Webhook")

    tab1, tab2, tab3 = st.tabs(["Associations", "Logs", "Settings"])

    with tab1:
        _render_associations_tab()

    with tab2:
        _render_logs_tab()

    with tab3:
        _render_settings_tab()


def _render_associations_tab():
    """Manage master-product key associations."""
    st.subheader("Master-Product Associations")

    manager = get_payhip_webhook_manager()
    user_manager = UserManager()

    with st.expander("Add New Association", expanded=False):
        with st.form("add_association"):
            masters = user_manager.get_all_users(role_filter="master")

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
