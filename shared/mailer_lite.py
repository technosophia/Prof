"""MailerLite integration for registration notifications."""

from __future__ import annotations

import os
from typing import Optional

import requests

from core.logging import log

_BASE = "https://connect.mailerlite.com/api"


def _headers() -> dict:
    token = os.getenv("MAILER_LITE_API", "")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def get_configured_group_id() -> Optional[str]:
    """Return the MailerLite group ID from config or env var (env takes precedence)."""
    env_val = os.getenv("MAILER_LITE_GROUP_ID")
    if env_val:
        return env_val
    try:
        from st_shared.cached import get_config
        return get_config().get("mailer_lite.group_id") or None
    except Exception:
        return None


def notify_account_approved(email: Optional[str], user_name: Optional[str]) -> bool:
    """Push approved user into MailerLite subscribers and optionally assign to a group.

    The group is read from config (set via Debug → MailerLite tab) or MAILER_LITE_GROUP_ID env var.
    A MailerLite automation triggered on "subscriber joins group" will then send the email.
    """
    if not email:
        return False

    token = os.getenv("MAILER_LITE_API")
    if not token:
        log("warning", "MAILER_LITE_API is not configured, skipping approval email")
        return False

    group_id = get_configured_group_id()

    payload: dict = {
        "email": email,
        "fields": {"name": user_name or ""},
        "status": "active",
    }
    if group_id:
        payload["groups"] = [group_id]

    try:
        response = requests.post(
            f"{_BASE}/subscribers",
            headers=_headers(),
            json=payload,
            timeout=8,
        )
    except Exception as error:
        log("error", f"MailerLite request failed: {error}")
        return False

    if response.status_code >= 400:
        log(
            "error",
            f"[notify_account_approved] MailerLite returned status {response.status_code}: {response.text[:300]}",
        )
        return False

    if not group_id:
        log(
            "warning",
            "[notify_account_approved] Subscriber added to MailerLite but no group is configured — "
            "no automation will trigger. Set the group in Debug → MailerLite tab.",
        )

    return True


def get_groups() -> list[dict]:
    """Return all MailerLite groups. Empty list if not configured or on error."""
    token = os.getenv("MAILER_LITE_API")
    if not token:
        return []
    try:
        resp = requests.get(f"{_BASE}/groups", headers=_headers(), timeout=8)
        if resp.status_code == 200:
            return resp.json().get("data", [])
    except Exception:
        pass
    return []
