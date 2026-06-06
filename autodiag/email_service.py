"""Generic email renderer and sender. No business logic — template name + context dict only."""

import logging
import os
import urllib.parse
from pathlib import Path

import frontmatter
import jinja2
import markdown
import requests

logger = logging.getLogger(__name__)

_BREVO_ENDPOINT = "https://api.brevo.com/v3/smtp/email"
_EMAILS_DIR = Path(__file__).parent / "config" / "emails"

_CSS_WRAPPERS = {
    "user": (
        '<div style="font-family:Georgia,serif;max-width:600px;margin:auto;'
        'color:#1a1a1a;line-height:1.75;padding:16px 8px;">'
    ),
    "owner": '<div style="font-family:monospace;max-width:640px;color:#1a1a1a;">',
    "default": '<div style="font-family:sans-serif;max-width:600px;margin:auto;color:#1a1a1a;">',
}

_jinja_env = jinja2.Environment(trim_blocks=True, lstrip_blocks=True)
_jinja_env.filters["urlencode"] = urllib.parse.quote


def render_email(template_name: str, context: dict) -> tuple[str, str]:
    """Return (subject, html) by rendering config/emails/<template_name>.md with the given context."""
    path = _EMAILS_DIR / f"{template_name}.md"
    post = frontmatter.load(str(path))

    subject = _jinja_env.from_string(post.metadata.get("subject", "")).render(**context)
    body_md = _jinja_env.from_string(post.content).render(**context)
    body_html = markdown.markdown(body_md, extensions=["tables"])

    style = post.metadata.get("style", "default")
    wrapper = _CSS_WRAPPERS.get(style, _CSS_WRAPPERS["default"])
    html = f"{wrapper}{body_html}</div>"

    return subject, html


def send_email(to_email: str, template_name: str, context: dict) -> None:
    """Render template and send via Brevo."""
    subject, html = render_email(template_name, context)
    resp = requests.post(
        _BREVO_ENDPOINT,
        json={
            "sender": {
                "name": os.environ.get("BREVO_FROM_NAME", "Diagnostic Souveraineté"),
                "email": os.environ["BREVO_FROM"],
            },
            "to": [{"email": to_email}],
            "subject": subject,
            "htmlContent": html,
        },
        headers={"api-key": os.environ["BREVO_API_KEY"], "Content-Type": "application/json"},
        timeout=10,
    )
    resp.raise_for_status()
    logger.info("Email sent — template=%s to=%s", template_name, to_email)
