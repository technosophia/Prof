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


def notify_account_approved(
    email: Optional[str],
    user_name: Optional[str],
    reset_code: Optional[str] = None,
) -> tuple[bool, dict]:
    """Push approved user into MailerLite subscribers and optionally assign to a group.

    Includes reset_code as a subscriber field if provided, so MailerLite automation
    emails can use {{ subscriber.fields.reset_code }}.

    Returns (success, diagnostic_dict) so callers can log/display what was sent.
    """
    if not email:
        return False, {"error": "no email"}

    token = os.getenv("MAILER_LITE_API")
    if not token:
        log("warning", "MAILER_LITE_API is not configured, skipping MailerLite upsert")
        return False, {"error": "MAILER_LITE_API not set"}

    group_id = get_configured_group_id()

    fields: dict = {"name": user_name or ""}
    if reset_code:
        fields["reset_code"] = reset_code

    payload: dict = {
        "email": email,
        "fields": fields,
        "status": "active",
    }
    if group_id:
        payload["groups"] = [group_id]

    diagnostic = {
        "email": email,
        "fields_sent": {k: (v if k != "reset_code" else f"{v[:6]}…") for k, v in fields.items()},
        "group_id": group_id,
        "reset_code_included": bool(reset_code),
    }

    try:
        response = requests.post(
            f"{_BASE}/subscribers",
            headers=_headers(),
            json=payload,
            timeout=8,
        )
    except Exception as error:
        log("error", f"MailerLite request failed: {error}")
        return False, {**diagnostic, "error": str(error)}

    diagnostic["http_status"] = response.status_code

    if response.status_code >= 400:
        log(
            "error",
            f"[notify_account_approved] MailerLite returned {response.status_code}: {response.text[:300]}",
        )
        return False, {**diagnostic, "error": response.text[:300]}

    if not group_id:
        log(
            "warning",
            "[notify_account_approved] Subscriber added to MailerLite but no group is configured — "
            "no automation will trigger. Set the group in Debug → MailerLite tab.",
        )

    return True, diagnostic


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


def get_subscriber_by_email(email: str) -> Optional[dict]:
    """Return MailerLite subscriber dict for an email address, or None."""
    token = os.getenv("MAILER_LITE_API")
    if not token:
        return None
    try:
        resp = requests.get(
            f"{_BASE}/subscribers",
            headers=_headers(),
            params={"filter[email]": email},
            timeout=8,
        )
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            return data[0] if data else None
    except Exception:
        pass
    return None


def remove_subscriber_from_group(subscriber_id: str, group_id: str) -> tuple[bool, str]:
    """Remove a subscriber from a group so the 'joins group' automation can re-fire."""
    token = os.getenv("MAILER_LITE_API")
    if not token:
        return False, "MAILER_LITE_API not set"
    try:
        resp = requests.delete(
            f"{_BASE}/subscribers/{subscriber_id}/groups/{group_id}",
            headers=_headers(),
            timeout=8,
        )
        if resp.status_code in (200, 204):
            return True, "Removed from group"
        return False, f"Status {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, str(e)
