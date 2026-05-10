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


def notify_account_approved(email: Optional[str], user_name: Optional[str]) -> bool:
    """Push approved user into MailerLite subscribers and optionally assign to a group.

    Set MAILER_LITE_GROUP_ID to the group ID shown in the Debug → MailerLite tab.
    A MailerLite automation triggered on "subscriber joins group" will then send the email.
    """
    if not email:
        return False

    token = os.getenv("MAILER_LITE_API")
    if not token:
        log("warning", "MAILER_LITE_API is not configured, skipping approval email")
        return False

    group_id = os.getenv("MAILER_LITE_GROUP_ID")

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
            f"[notify_account_approved] Subscriber {email} added to MailerLite but "
            "MAILER_LITE_GROUP_ID is not set — no automation will be triggered. "
            "Set this env var to the group ID shown in Debug → MailerLite tab.",
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
