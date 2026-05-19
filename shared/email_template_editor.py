"""Reusable email template editor for transactional emails.

Supports placeholders and per-scope editing (global, payhip, waitlist).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import streamlit as st

from shared.transactional_email import (
    _ensure_email_templates_table,
    get_email_template,
    get_default_email_template,
)


def _reset_template_to_default(scope: str, scope_id: Optional[str], template_key: str) -> None:
    """Restore usable default templates for both 'en' and 'fr'."""
    from core.database import get_db_manager
    from sqlalchemy import text
    import uuid
    from datetime import datetime

    db = get_db_manager()
    _ensure_email_templates_table()

    with db.get_session() as session:
        # Remove existing custom templates for this scope/template
        session.execute(
            text(
                "DELETE FROM email_templates "
                "WHERE scope = :scope "
                "AND (scope_id = :scope_id OR (scope_id IS NULL AND :scope_id IS NULL)) "
                "AND template_key = :template_key"
            ),
            {"scope": scope, "scope_id": scope_id, "template_key": template_key},
        )

        # Insert fresh defaults for en and fr
        for lang in ("en", "fr"):
            default = get_default_email_template(template_key, lang)
            session.execute(
                text(
                    "INSERT INTO email_templates "
                    "(id, scope, scope_id, template_key, lang, subject, body_text, body_html, updated_at) "
                    "VALUES (:id, :scope, :scope_id, :template_key, :lang, :subject, :body_text, :body_html, :now)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "scope": scope,
                    "scope_id": scope_id,
                    "template_key": template_key,
                    "lang": lang,
                    "subject": default.get("subject", ""),
                    "body_text": default.get("body_text", ""),
                    "body_html": default.get("body_html", ""),
                    "now": datetime.utcnow(),
                },
            )

        session.commit()


def render_email_template_editor(
    scope: str,
    scope_id: Optional[str] = None,
    template_key: str = "welcome",
    langs: list[str] = ("en", "fr"),
) -> None:
    """
    Render a Streamlit editor for an email template.

    The caller is responsible for handling save / preview actions.
    """
    _ensure_email_templates_table()

    st.subheader(f"Email Template — {template_key} ({scope})")

    col1, col2 = st.columns([1, 3])
    with col1:
        if st.button("🔄 Reset to default (EN + FR)", key=f"reset_{scope}_{scope_id}_{template_key}"):
            _reset_template_to_default(scope, scope_id, template_key)
            st.success("Template reset to default. Reloading...")
            st.rerun()

    for lang in langs:
        with st.expander(f"🌐 {lang.upper()}", expanded=(lang == "en")):
            tpl = get_email_template(scope, scope_id, template_key, lang)

            subject = st.text_input(
                "Subject",
                value=tpl.get("subject", ""),
                key=f"subj_{scope}_{scope_id}_{template_key}_{lang}",
            )
            body_text = st.text_area(
                "Plain text body",
                value=tpl.get("body_text", ""),
                height=120,
                key=f"txt_{scope}_{scope_id}_{template_key}_{lang}",
            )
            body_html = st.text_area(
                "HTML body",
                value=tpl.get("body_html", ""),
                height=200,
                key=f"html_{scope}_{scope_id}_{template_key}_{lang}",
            )

            st.caption("Available placeholders: {reset_code}, {app_url}, {login_url}, {name}, {email}")

            if st.button("💾 Save", key=f"save_{scope}_{scope_id}_{template_key}_{lang}"):
                _save_template(scope, scope_id, template_key, lang, subject, body_text, body_html)
                st.success("Template saved")


def _save_template(
    scope: str,
    scope_id: Optional[str],
    template_key: str,
    lang: str,
    subject: str,
    body_text: str,
    body_html: str,
) -> None:
    """Persist a template to the database."""
    from core.database import get_db_manager
    from sqlalchemy import text
    import uuid
    from datetime import datetime

    db = get_db_manager()
    _ensure_email_templates_table()

    tpl_id = str(uuid.uuid4())
    now = datetime.utcnow()

    with db.get_session() as session:
        # delete existing
        session.execute(
            text(
                "DELETE FROM email_templates WHERE scope=:s AND (scope_id=:sid OR (scope_id IS NULL AND :sid IS NULL)) "
                "AND template_key=:k AND lang=:l"
            ),
            {"s": scope, "sid": scope_id, "k": template_key, "l": lang},
        )
        session.execute(
            text(
                "INSERT INTO email_templates (id, scope, scope_id, template_key, lang, subject, body_text, body_html, updated_at) "
                "VALUES (:id, :s, :sid, :k, :l, :subj, :txt, :html, :now)"
            ),
            {
                "id": tpl_id,
                "s": scope,
                "sid": scope_id,
                "k": template_key,
                "l": lang,
                "subj": subject,
                "txt": body_text,
                "html": body_html,
                "now": now,
            },
        )
        session.commit()