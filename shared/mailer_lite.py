"""MailerLite integration for registration notifications."""

from __future__ import annotations

import os
from typing import Optional

import requests

from core.logging import log


def notify_account_approved(email: Optional[str], user_name: Optional[str]) -> bool:
    """Push approved user into MailerLite subscribers.

    A MailerLite automation can then send the actual email message.
    """
    if not email:
        return False

    token = os.getenv("MAILER_LITE_API")
    if not token:
        log("warning", "MAILER_LITE_API is not configured, skipping approval email")
        return False

    payload = {
        "email": email,
        "fields": {"name": user_name or ""},
        "status": "active",
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        response = requests.post(
            "https://connect.mailerlite.com/api/subscribers",
            headers=headers,
            json=payload,
            timeout=8,
        )
    except Exception as error:
        log("error", f"MailerLite request failed: {error}")
        return False

    if response.status_code >= 400:
        log(
            "error",
            f"MailerLite returned status {response.status_code}: {response.text[:300]}",
        )
        return False
    return True
