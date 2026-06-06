"""Orchestrate: parse → score → persist → notify. Called once per valid Tally event."""

import json
import logging
import os
from datetime import datetime

from form_parser import parse_tally_payload
from scorer import score_response
from token_utils import encode_result_token
from database import DiagResponse, save_response
from email_service import send_email

logger = logging.getLogger(__name__)


def handle_tally_webhook(payload: dict) -> dict:
    response_id = payload["data"]["responseId"]
    created_at_raw = payload["data"].get("createdAt", "")
    try:
        created_at = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        created_at = datetime.utcnow()

    parsed = parse_tally_payload(payload)

    if parsed.is_disqualified:
        logger.info("Disqualified response %s — no score, no email", response_id)
        return {"status": "disqualified"}

    result = score_response(parsed.raw_scores)

    token = encode_result_token(
        scores=result.scores,
        profile_key=result.profile_key,
        felt_constraint=parsed.felt_constraint,
        situation=parsed.situation,
        response_id=response_id,
    )

    record = DiagResponse(
        response_id=response_id,
        created_at=created_at,
        email=parsed.email,
        situation=parsed.situation,
        felt_constraint=parsed.felt_constraint,
        score_energie=result.scores["energie"],
        score_attention=result.scores["attention"],
        score_liens=result.scores["liens"],
        score_moyens=result.scores["moyens"],
        score_total=result.score_total,
        profile_key=result.profile_key,
        is_rationalisateur=result.is_rationalisateur,
        raw_payload=json.dumps(payload),
    )

    saved = save_response(record)
    if not saved:
        logger.warning("Duplicate response_id %s — emails suppressed", response_id)
        return {"status": "duplicate"}

    base_url = os.environ.get("DIAG_BASE_URL", "https://diag.yoga-pro.xyz")
    share_url = os.environ.get("DIAG_SHARE_URL", base_url)

    user_ctx = {
        "profile": result.profile,
        "result_url": f"{base_url}/r?t={token}",
        "share_url": share_url,
    }
    try:
        send_email(parsed.email, "user", user_ctx)
    except Exception:
        logger.exception("User email failed for response %s", response_id)

    owner_email = os.environ.get("OWNER_EMAIL", "")
    if owner_email:
        owner_ctx = {
            "email": parsed.email,
            "situation": parsed.situation,
            "felt_constraint": parsed.felt_constraint,
            "scores": result.scores,
            "score_total": result.score_total,
            "profile": result.profile,
            "profile_key": result.profile_key,
            "is_rationalisateur": result.is_rationalisateur,
            "submitted_at": created_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
        }
        try:
            send_email(owner_email, "owner", owner_ctx)
        except Exception:
            logger.exception("Owner email failed for response %s", response_id)
    else:
        logger.warning("OWNER_EMAIL not set — owner notification skipped")

    logger.info("Processed response %s → profile=%s", response_id, result.profile_key)
    return {"status": "ok", "profile": result.profile_key}
