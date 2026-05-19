"""Transactional email via Brevo (free tier, verified domain required).

Configure:
  BREVO_API_KEY   — API key from app.brevo.com
  BREVO_FROM      — verified sender address, e.g. noreply@yourdomain.com
  BREVO_FROM_NAME — optional sender display name
  APP_URL         — public URL of your app, e.g. https://app.yourdomain.com
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

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


# ---------------------------------------------------------------------------
# Editable email template support
# ---------------------------------------------------------------------------


def _ensure_email_templates_table() -> None:
    """Create email_templates table if it does not exist."""
    from core.database import get_db_manager
    from sqlalchemy import Column, DateTime, MetaData, String, Table, Text, inspect, text

    db = get_db_manager()
    metadata = MetaData()
    email_templates = Table(
        "email_templates",
        metadata,
        Column("id", String(36), primary_key=True),
        Column("scope", String(32), nullable=False),
        Column("scope_id", String(255)),
        Column("template_key", String(64), nullable=False),
        Column("lang", String(8), default="en"),
        Column("subject", Text),
        Column("body_text", Text),
        Column("body_html", Text),
        Column("updated_at", DateTime),
    )
    email_templates.create(bind=db._engine, checkfirst=True)

    inspector = inspect(db._engine)
    cols = {c["name"] for c in inspector.get_columns("email_templates")}
    if "updated_at" not in cols:
        with db._engine.begin() as conn:
            conn.execute(text("ALTER TABLE email_templates ADD COLUMN updated_at TIMESTAMP"))


def _get_template_from_db(
    scope: str, scope_id: Optional[str], template_key: str, lang: str
) -> Optional[Dict[str, Any]]:
    """Return stored template or None."""
    from core.database import get_db_manager
    from sqlalchemy import text

    db = get_db_manager()
    _ensure_email_templates_table()

    query = """
        SELECT subject, body_text, body_html
        FROM email_templates
        WHERE scope = :scope
          AND (scope_id = :scope_id OR (scope_id IS NULL AND :scope_id IS NULL))
          AND template_key = :template_key
          AND lang = :lang
        LIMIT 1
    """
    with db.get_session() as session:
        row = session.execute(
            text(query),
            {"scope": scope, "scope_id": scope_id, "template_key": template_key, "lang": lang},
        ).fetchone()
        if row:
            return {"subject": row[0], "body_text": row[1], "body_html": row[2]}
    return None


def _render_template(template: str, **kwargs: Any) -> str:
    """Safely render a template string with provided kwargs."""
    try:
        return template.format(**kwargs)
    except KeyError:
        return template  # fall back to raw template if placeholder missing


def get_email_template(
    scope: str, scope_id: Optional[str], template_key: str, lang: str = "en"
) -> Dict[str, str]:
    """
    Return the best matching template for the given scope/scope_id/key/lang.

    Falls back in this order:
      1. exact (scope, scope_id, key, lang)
      2. (scope, NULL, key, lang)                — global default for that scope
      3. translation key (welcome_email.* etc.)
    """
    # 1. exact match
    tpl = _get_template_from_db(scope, scope_id, template_key, lang)
    if tpl:
        return tpl

    # 2. scope-level default (scope_id = None)
    tpl = _get_template_from_db(scope, None, template_key, lang)
    if tpl:
        return tpl

    # 3. fallback to translation system (current behaviour)
    def t(key: str, **kw: Any) -> str:
        return _t(f"{template_key}.{key}", lang, **kw)

    subject = t("subject")
    body_intro = t("account_created") if template_key == "welcome_email" else ""
    # For simplicity we keep the existing translation fallback for now
    return {
        "subject": subject,
        "body_text": "",
        "body_html": "",
    }


def get_default_email_template(template_key: str, lang: str = "en") -> Dict[str, str]:
    """
    Return the original default template content (as it was before editable templates).
    Used by "Reset to default".
    """
    app_url = os.getenv("APP_URL", "").rstrip("/")
    login_url = f"{app_url}/login" if app_url else "the login page"

    if template_key in ("welcome", "welcome_email"):
        def t(key: str, **kwargs: Any) -> str:
            return _t(f"welcome_email.{key}", lang, **kwargs)

        subject = t("subject")
        greeting = t("greeting")
        body_intro = t("account_created")
        lbl_code = t("reset_code_label")
        instruction = t("instruction", login_url=login_url)
        validity = t("validity")
        cta = t("cta_button")
        sign_off = t("sign_off")

        text_body = (
            f"{greeting}\n\n{body_intro}\n\n{lbl_code}: {{reset_code}}\n\n"
            f"{instruction}\n\n{validity}\n\n{sign_off}"
        )

        html_body = f"""\
<p>{greeting}</p>
<p>{body_intro}</p>
<table style="border-collapse:collapse;margin:16px 0">
  <tr>
    <td style="padding:4px 12px 4px 0;color:#666">{lbl_code}</td>
    <td><code style="background:#f4f4f4;padding:2px 6px;border-radius:4px;font-size:1.1em">{{reset_code}}</code></td>
  </tr>
</table>
<p>
  <a href="{login_url}"
     style="background:#4f46e5;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;display:inline-block">
    {cta}
  </a>
</p>
<p style="color:#666;font-size:0.9em">
  {instruction}<br>
  <strong>{validity}</strong>
</p>
"""
        return {
            "subject": subject,
            "body_text": text_body,
            "body_html": html_body,
        }

    if template_key == "approved":
        # Waitlist approval default
        subject = "Your account has been approved"
        text_body = (
            "Hello {name},\n\n"
            "Your registration has been approved.\n"
            "Reset code: {reset_code}\n\n"
            f"Please go to {login_url} to set your password."
        )
        html_body = f"""\
<p>Hello {{name}},</p>
<p>Your registration has been approved.</p>
<p>Reset code: <code>{{reset_code}}</code></p>
<p><a href="{login_url}">Set your password</a></p>
"""
        return {
            "subject": subject,
            "body_text": text_body,
            "body_html": html_body,
        }

    # Fallback empty
    return {"subject": "", "body_text": "", "body_html": ""}


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
    scope: str = "global",
    scope_id: Optional[str] = None,
) -> tuple[bool, str]:
    """
    Send welcome/activation email with reset code.

    If a custom template exists for the given scope/scope_id it is used;
    otherwise falls back to the default translation-based template.
    """
    app_url = os.getenv("APP_URL", "").rstrip("/")
    login_url = f"{app_url}/login" if app_url else "the login page"

    tpl = get_email_template(scope, scope_id, "welcome", lang)

    if tpl.get("body_text") or tpl.get("body_html"):
        # Custom template found
        subject = _render_template(tpl.get("subject", ""), reset_code=reset_code, app_url=app_url, name=to_name)
        text_body = _render_template(
            tpl.get("body_text", ""),
            reset_code=reset_code,
            app_url=app_url,
            login_url=login_url,
            name=to_name,
        )
        html_body = _render_template(
            tpl.get("body_html", ""),
            reset_code=reset_code,
            app_url=app_url,
            login_url=login_url,
            name=to_name,
        ) or None
    else:
        # Fallback to translation keys (original behaviour)
        def t(key: str, **kwargs: Any) -> str:
            return _t(f"welcome_email.{key}", lang, **kwargs)

        subject = t("subject")
        greeting = t("greeting")
        body_intro = t("account_created")
        lbl_code = t("reset_code_label")
        instruction = t("instruction", login_url=login_url)
        validity = t("validity")
        cta = t("cta_button")
        sign_off = t("sign_off")

        text_body = (
            f"{greeting}\n\n{body_intro}\n\n{lbl_code}: {reset_code}\n\n"
            f"{instruction}\n\n{validity}\n\n{sign_off}"
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
     style="background:#4f46e5;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;display:inline-block">
    {cta}
  </a>
</p>
<p style="color:#666;font-size:0.9em">{instruction}<br><strong>{validity}</strong></p>
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


# ---------------------------------------------------------------------------
# Waitlist approval email (new requirement)
# ---------------------------------------------------------------------------


def send_waitlist_approved_email(
    to_email: str,
    to_name: str,
    reset_code: str,
    lang: str = "en",
    waitlist_email: Optional[str] = None,
) -> tuple[bool, str]:
    """
    Send the approval email when a waiting-list user is approved.

    Uses per-waitlist template if one exists (scope='waitlist', scope_id=waitlist_email).
    """
    app_url = os.getenv("APP_URL", "").rstrip("/")
    login_url = f"{app_url}/login" if app_url else "the login page"

    tpl = get_email_template("waitlist", waitlist_email, "approved", lang)

    if tpl.get("body_text") or tpl.get("body_html"):
        subject = _render_template(tpl.get("subject", ""), reset_code=reset_code, app_url=app_url, name=to_name)
        text_body = _render_template(
            tpl.get("body_text", ""),
            reset_code=reset_code,
            app_url=app_url,
            login_url=login_url,
            name=to_name,
        )
        html_body = _render_template(
            tpl.get("body_html", ""),
            reset_code=reset_code,
            app_url=app_url,
            login_url=login_url,
            name=to_name,
        ) or None
    else:
        # Minimal default if no custom template
        subject = "Your account has been approved"
        text_body = (
            f"Hello {to_name},\n\n"
            f"Your registration has been approved.\n"
            f"Reset code: {reset_code}\n\n"
            f"Please go to {login_url} to set your password."
        )
        html_body = f"""\
<p>Hello {to_name},</p>
<p>Your registration has been approved.</p>
<p>Reset code: <code>{reset_code}</code></p>
<p><a href="{login_url}">Set your password</a></p>
"""

    return send_email(
        to_email=to_email,
        to_name=to_name,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )
