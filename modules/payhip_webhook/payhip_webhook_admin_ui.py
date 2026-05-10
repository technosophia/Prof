"""Payhip Webhook admin tab registration."""

from modules.payhip_webhook.payhip_webhook_ui import render_admin_tab


def inject_ui_admin_tab():
    """Register the Payhip Webhook admin tab."""
    return ("Payhip Webhook", render_admin_tab)
