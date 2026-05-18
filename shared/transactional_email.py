"""Transactional email via Brevo (free tier, verified domain required).

Configure:
  BREVO_API_KEY   — API key from app.brevo.com
  BREVO_FROM      — verified sender address, e.g. noreply@yourdomain.com
  BREVO_FROM_NAME — optional sender display name
  APP_URL         — public URL of your app, e.g. https://app.yourdomain.com
"""

from __future__ import annotations

import os
from typing import Optional

import requests

from core.logging import log

_BASE = "https://api.brevo.com/v3"

_translations_cache: Optional[dict] = None


def _get_translations() -> dict:
    global _translations_cache
    if _translations_cache is None:
        from core.translate import load_all_translations
        _translations_cache = load_all_translations()
    return _translations_cache


def _t(key: str, lang: str, **kwargs) -> str:
    """Translate key in the given language, substituting any {placeholders}."""
    from core.translate import get_translation
    text = get_translation(key, lang, _get_translations())
    if kwargs:
        try:
            text = text.format(**kwargs)
        except KeyError:
            pass
    return text


def _is_configured() -> bool:
    return bool(os.getenv("BREVO_API_KEY")) and bool(os.getenv("BREVO_FROM"))


def _headers() -> dict:
    return {
        "api-key": os.getenv("BREVO_API_KEY", ""),
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
    """Send a transactional email via Brevo.

    Returns (success, message).
    """
    if not _is_configured():
        return False, "BREVO_API_KEY or BREVO_FROM not configured"

    from_addr = os.getenv("BREVO_FROM", "")
    from_name = os.getenv("BREVO_FROM_NAME", from_addr)

    payload: dict = {
        "sender": {"email": from_addr, "name": from_name},
        "to": [{"email": to_email, "name": to_name}],
        "subject": subject,
        "textContent": text_body,
    }
    if html_body:
        payload["htmlContent"] = html_body

    try:
        resp = requests.post(
            f"{_BASE}/smtp/email",
            headers=_headers(),
            json=payload,
            timeout=10,
        )
    except Exception as e:
        log("error", f"[transactional_email] Request failed: {e}")
        return False, f"Request failed: {e}"

    if resp.status_code == 201:
        return True, "Email queued successfully"
    else:
        msg = f"Brevo returned {resp.status_code}: {resp.text[:300]}"
        log("error", f"[transactional_email] {msg}")
        return False, msg


def send_welcome_reset_code(
    to_email: str,
    to_name: str,
    reset_code: str,
    lang: str = "en",
) -> tuple[bool, str]:
    """Send welcome email with reset code so the user can set their first password.

    The email body is built from translation keys under welcome_email.* so the
    message is delivered in the master's (and thus the student's) language.
    """
    app_url = os.getenv("APP_URL", "").rstrip("/")
    login_url = f"{app_url}/login" if app_url else "the login page"

    def t(key: str, **kwargs) -> str:
        return _t(f"welcome_email.{key}", lang, **kwargs)

    subject    = t("subject")
    greeting   = t("greeting")
    body_intro = t("account_created")
    lbl_code   = t("reset_code_label")
    instruction = t("instruction", login_url=login_url)
    validity   = t("validity")
    cta        = t("cta_button")
    sign_off   = t("sign_off")

    text_body = (
        f"{greeting}\n\n"
        f"{body_intro}\n\n"
        f"{lbl_code}: {reset_code}\n\n"
        f"{instruction}\n\n"
        f"{validity}\n\n"
        f"{sign_off}"
    )

    html_body = f"""\
<p>{greeting}</p>
<p>{body_intro}</p>
<table style="border-collapse:collapse;margin:16px 0">
  <tr>
    <td style="padding:4px 12px 4px 0;color:#666">{lbl_code}</td>
    <td><code style="background:#f4f4f4;padding:2px 6px;border-radius:4px;font-size:1.1em">{reset_code}</code></td>
  </tr>
</table>
<p>
  <a href="{login_url}"
     style="background:#4f46e5;color:#fff;padding:10px 20px;
            border-radius:6px;text-decoration:none;display:inline-block">
    {cta}
  </a>
</p>
<p style="color:#666;font-size:0.9em">
  {instruction}<br>
  <strong>{validity}</strong>
</p>
"""

    return send_email(
        to_email=to_email,
        to_name=to_name,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )


def send_enrollment_expired_alert(
    master_email: str,
    master_name: str,
    student_email: str,
) -> tuple[bool, str]:
    """Notify the master that one of their students' enrollment has expired."""
    subject = f"[Prof] Enrollment expired — {student_email}"
    text_body = (
        f"Hello {master_name},\n\n"
        f"Your student {student_email} just tried to log in but their enrollment "
        f"has expired. You may want to contact them or renew their access.\n\n"
        f"This is an automated notification."
    )
    html_body = f"""\
<p>Hello {master_name},</p>
<p>Your student <strong>{student_email}</strong> just tried to log in but their
enrollment has expired.</p>
<p>You may want to contact them or renew their access.</p>
<p style="color:#888;font-size:0.9em">This is an automated notification.</p>
"""
    return send_email(
        to_email=master_email,
        to_name=master_name,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )
