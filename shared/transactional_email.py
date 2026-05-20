"""Transactional email via Brevo (free tier, verified domain required).

Configure:
  BREVO_API_KEY   — API key from app.brevo.com
  BREVO_FROM      — verified sender address, e.g. noreply@yourdomain.com
  BREVO_FROM_NAME — optional sender display name
  APP_URL         — public URL of your app, e.g. https://app.yourdomain.com

Default templates are defined in translations/{en,fr}.json under the
``email_tpl`` key (one entry per template with subject / body_text / body_html).
Admins may override any template per scope via the email_templates DB table.
"""

from __future__ import annotations

import os
from collections import defaultdict
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


def _t(key: str, lang: str) -> str:
    from core.translate import get_translation
    return get_translation(key, lang, _get_translations())


def _is_configured() -> bool:
    return bool(os.getenv("BREVO_API_KEY")) and bool(os.getenv("BREVO_FROM"))


def _headers() -> dict:
    return {
        "api-key": os.getenv("BREVO_API_KEY", ""),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _render(template: str, **ctx: Any) -> str:
    """Render a template string, silently replacing unknown placeholders with ''."""
    try:
        return template.format_map(defaultdict(str, ctx))
    except Exception:
        return template


# ---------------------------------------------------------------------------
# DB template store
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_default_email_template(template_key: str, lang: str = "en") -> Dict[str, str]:
    """Return the built-in default for a template key, read from translations.

    Keys live at ``email_tpl.<template_key>.{subject,body_text,body_html}``.
    """
    prefix = f"email_tpl.{template_key}"
    return {
        "subject": _t(f"{prefix}.subject", lang),
        "body_text": _t(f"{prefix}.body_text", lang),
        "body_html": _t(f"{prefix}.body_html", lang),
    }


def get_email_template(
    scope: str, scope_id: Optional[str], template_key: str, lang: str = "en"
) -> Dict[str, str]:
    """Return the best matching template for the given scope / key / lang.

    Lookup order:
      1. DB exact  (scope, scope_id, key, lang)
      2. DB scope-level default  (scope, NULL, key, lang)
      3. Translation default  (email_tpl.<key>.*)
    """
    tpl = _get_template_from_db(scope, scope_id, template_key, lang)
    if tpl and (tpl.get("body_text") or tpl.get("body_html")):
        return tpl

    if scope_id is not None:
        tpl = _get_template_from_db(scope, None, template_key, lang)
        if tpl and (tpl.get("body_text") or tpl.get("body_html")):
            return tpl

    return get_default_email_template(template_key, lang)


def send_email(
    to_email: str,
    to_name: str,
    subject: str,
    text_body: str,
    html_body: Optional[str] = None,
) -> tuple[bool, str]:
    """Send a transactional email via Brevo. Returns (success, message)."""
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
    msg = f"Brevo returned {resp.status_code}: {resp.text[:300]}"
    log("error", f"[transactional_email] {msg}")
    return False, msg


def send_transactional_email(
    template_key: str,
    to_email: str,
    to_name: str,
    scope: str = "global",
    scope_id: Optional[str] = None,
    lang: str = "en",
    **ctx: Any,
) -> tuple[bool, str]:
    """Resolve a template, render placeholders, and send via Brevo.

    Always-available context variables: {name}, {app_url}, {login_url}.
    Pass additional variables (reset_code, expiry_date, master_name, …) as
    keyword arguments; unknown placeholders in the template render as ''.
    """
    app_url = os.getenv("APP_URL", "").rstrip("/")
    login_url = f"{app_url}/login" if app_url else ""
    full_ctx = {"name": to_name, "app_url": app_url, "login_url": login_url, **ctx}

    tpl = get_email_template(scope, scope_id, template_key, lang)
    subject = _render(tpl.get("subject", ""), **full_ctx)
    text_body = _render(tpl.get("body_text", ""), **full_ctx)
    html_body = _render(tpl.get("body_html", ""), **full_ctx) or None

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
