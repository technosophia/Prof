"""Parse raw Tally webhook payloads using config/form.json — no question keys in code."""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / "config" / "form.json"


def _load_config() -> dict:
    with open(_CONFIG_PATH) as f:
        return json.load(f)


@dataclass
class ParsedResponse:
    email: str
    situation: str
    felt_constraint: str
    raw_scores: dict = field(default_factory=dict)  # front -> raw int score
    is_disqualified: bool = False


def _extract_value(field_data: dict) -> str:
    """Return string value from a Tally field, handling both string and list formats."""
    value = field_data.get("value", "")
    if isinstance(value, list):
        return value[0] if value else ""
    return str(value) if value is not None else ""


def parse_tally_payload(payload: dict) -> ParsedResponse:
    config = _load_config()
    fields_by_key = {f["key"]: f for f in payload["data"]["fields"]}

    logger.debug("Payload keys: %s", list(fields_by_key.keys()))

    email_key = f"question_{config['email_question_key']}"
    email = _extract_value(fields_by_key.get(email_key, {}))
    if not email:
        logger.warning("Email field not found (looked up key=%s)", email_key)
    else:
        logger.info("Email: %s", email)

    ctx = config["context_questions"]

    situation_key = f"question_{ctx['situation']['key']}"
    situation_uuid = _extract_value(fields_by_key.get(situation_key, {}))
    situation = ctx["situation"]["options"].get(situation_uuid, "")
    if not situation:
        logger.warning("Situation not resolved (key=%s, answer_uuid=%s)", situation_key, situation_uuid)
    else:
        logger.info("Situation: %s", situation)

    felt_key = f"question_{ctx['felt_constraint']['key']}"
    felt_uuid = _extract_value(fields_by_key.get(felt_key, {}))
    felt_constraint = ctx["felt_constraint"]["options"].get(felt_uuid, "")
    if not felt_constraint:
        logger.warning("Felt constraint not resolved (key=%s, answer_uuid=%s)", felt_key, felt_uuid)
    else:
        logger.info("Felt constraint: %s", felt_constraint)

    disq_options = set(config.get("disqualification_options", []))
    answered_uuids = {_extract_value(f) for f in fields_by_key.values()}
    if disq_options & answered_uuids:
        logger.info("Response disqualified — matched option(s): %s", disq_options & answered_uuids)
        return ParsedResponse(
            email=email,
            situation=situation,
            felt_constraint=felt_constraint,
            is_disqualified=True,
        )

    raw_scores: dict[str, int] = {}
    for q in config["scored_questions"]:
        question_key = f"question_{q['key']}"
        answer_uuid = _extract_value(fields_by_key.get(question_key, {}))
        score = q["scores"].get(answer_uuid, 0)
        front = q["front"]
        raw_scores[front] = raw_scores.get(front, 0) + score
        logger.debug("  %s → answer=%s score=%d (front=%s)", question_key, answer_uuid[:8] if answer_uuid else "MISSING", score, front)

    logger.info("Raw scores: %s", raw_scores)

    return ParsedResponse(
        email=email,
        situation=situation,
        felt_constraint=felt_constraint,
        raw_scores=raw_scores,
    )
