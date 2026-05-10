"""Transactional email via MailerSend (free tier, verified domain required).

Configure:
  MAILERSEND_API_KEY  — API key from app.mailersend.com
  MAILERSEND_FROM     — verified sender address, e.g. noreply@yourdomain.com
  APP_URL             — public URL of your app, e.g. https://app.yourdomain.com
"""

from __future__ import annotations

import os
from typing import Optional

import requests

from core.logging import log

_BASE = "https://api.mailersend.com/v1"


def _is_configured() -> bool:
    return bool(os.getenv("MAILERSEND_API_KEY")) and bool(os.getenv("MAILERSEND_FROM"))


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.getenv('MAILERSEND_API_KEY', '')}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def send_email(
    to_email: str,
    to_name: str,
    subject: str,
    text_body: str,
    html_body: Optional[str] = None,
) -> tuple[bool, str]:
    """Send a transactional email via MailerSend.

    Returns (success, message).
    """
    if not _is_configured():
        return False, "MAILERSEND_API_KEY or MAILERSEND_FROM not configured"

    from_addr = os.getenv("MAILERSEND_FROM", "")
    from_name = os.getenv("MAILERSEND_FROM_NAME", from_addr)

    payload: dict = {
        "from": {"email": from_addr, "name": from_name},
        "to": [{"email": to_email, "name": to_name}],
        "subject": subject,
        "text": text_body,
    }
    if html_body:
        payload["html"] = html_body

    try:
        resp = requests.post(
            f"{_BASE}/email",
            headers=_headers(),
            json=payload,
            timeout=10,
        )
    except Exception as e:
        log("error", f"[transactional_email] Request failed: {e}")
        return False, f"Request failed: {e}"

    if resp.status_code == 202:
        return True, "Email queued successfully"
    else:
        msg = f"MailerSend returned {resp.status_code}: {resp.text[:300]}"
        log("error", f"[transactional_email] {msg}")
        return False, msg


def send_welcome_reset_code(
    to_email: str,
    to_name: str,
    reset_code: str,
) -> tuple[bool, str]:
    """Send welcome email with reset code so the user can set their first password."""
    app_url = os.getenv("APP_URL", "").rstrip("/")
    login_url = f"{app_url}/login" if app_url else "the login page"

    subject = "Welcome — set your password"

    text_body = (
        f"Hello {to_name},\n\n"
        "Your account has been created.\n\n"
        f"Your username is: {to_name}\n"
        f"Your reset code is: {reset_code}\n\n"
        f"Go to {login_url}, click 'Forgot Password', "
        "enter your username and this reset code to set your password.\n\n"
        "This code is valid for 24 hours.\n\n"
        "Welcome aboard!"
    )

    html_body = f"""
<p>Hello <strong>{to_name}</strong>,</p>
<p>Your account has been created.</p>
<table style="border-collapse:collapse;margin:16px 0">
  <tr><td style="padding:4px 12px 4px 0;color:#666">Username</td>
      <td><strong>{to_name}</strong></td></tr>
  <tr><td style="padding:4px 12px 4px 0;color:#666">Reset code</td>
      <td><code style="background:#f4f4f4;padding:2px 6px;border-radius:4px">{reset_code}</code></td></tr>
</table>
<p>
  <a href="{login_url}" style="background:#4f46e5;color:#fff;padding:10px 20px;
     border-radius:6px;text-decoration:none;display:inline-block">
    Set my password
  </a>
</p>
<p style="color:#666;font-size:0.9em">
  Click "Forgot Password" on the login page, enter your username and the reset code above.<br>
  This code is valid for <strong>24 hours</strong>.
</p>
"""

    return send_email(
        to_email=to_email,
        to_name=to_name,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )
