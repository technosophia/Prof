"""Aggregate Tally API submissions into autodiag radar data."""

import json
import logging
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scorer import score_response

logger = logging.getLogger(__name__)

_FORM_CONFIG_PATH = Path(__file__).parent / "config" / "form.json"
_SCORING_CONFIG_PATH = Path(__file__).parent / "config" / "scoring.json"


@dataclass
class RadarAggregate:
    """Summary ready to render as a radar chart."""

    form_id: str
    submission_count: int
    skipped_count: int
    fronts: list[str]
    front_labels: dict[str, str]
    average_scores: dict[str, float]
    max_scores: dict[str, int]
    std_scores: dict[str, float] = field(default_factory=dict)
    actual_min_scores: dict[str, float] = field(default_factory=dict)
    actual_max_scores: dict[str, float] = field(default_factory=dict)
    profile_counts: dict[str, int] = field(default_factory=dict)
    calculated_constraint_counts: dict[str, int] = field(default_factory=dict)
    felt_constraint_counts: dict[str, int] = field(default_factory=dict)
    situation_counts: dict[str, int] = field(default_factory=dict)


def load_form_config() -> dict[str, Any]:
    with open(_FORM_CONFIG_PATH) as f:
        return json.load(f)


def load_scoring_config() -> dict[str, Any]:
    with open(_SCORING_CONFIG_PATH) as f:
        return json.load(f)


def _extract_answer(value: Any) -> str:
    """Return the option ID/value from Tally answers across webhook and API shapes."""
    if value is None:
        return ""
    if isinstance(value, list):
        return _extract_answer(value[0]) if value else ""
    if isinstance(value, dict):
        for key in ("id", "uuid", "value", "answer"):
            if key in value:
                return _extract_answer(value[key])
        return ""
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") or text.startswith("{"):
            try:
                return _extract_answer(json.loads(text))
            except json.JSONDecodeError:
                pass
        return text
    return str(value)


def _normalize_question_id(question_id: Any) -> str:
    question_id = str(question_id or "")
    return question_id.removeprefix("question_")


def _configured_question_keys(form_config: dict[str, Any]) -> set[str]:
    keys = {form_config["email_question_key"]} if form_config.get("email_question_key") else set()
    keys.update(question["key"] for question in form_config["context_questions"].values())
    keys.update(question["key"] for question in form_config["scored_questions"])
    return keys


def _normalize_label(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _question_label_aliases(form_config: dict[str, Any]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for question in form_config["context_questions"].values():
        if question.get("label"):
            aliases[_normalize_label(question["label"])] = question["key"]
    for question in form_config["scored_questions"]:
        if question.get("label"):
            aliases[_normalize_label(question["label"])] = question["key"]
    return aliases


def _answer_aliases_by_question(form_config: dict[str, Any]) -> dict[str, dict[str, str]]:
    aliases: dict[str, dict[str, str]] = {}
    for question in form_config["context_questions"].values():
        aliases[question["key"]] = {
            _normalize_label(alias): option_id
            for alias, option_id in question.get("answer_aliases", {}).items()
        }
    for question in form_config["scored_questions"]:
        aliases[question["key"]] = {
            _normalize_label(alias): option_id
            for alias, option_id in question.get("answer_aliases", {}).items()
        }
    return aliases


def _resolve_answer(
    question_key: str,
    candidates: list[str],
    answer_aliases: dict[str, dict[str, str]],
) -> str:
    aliases = answer_aliases.get(question_key, {})
    for candidate in candidates:
        if _normalize_label(candidate) in aliases:
            return aliases[_normalize_label(candidate)]
    return next((candidate for candidate in candidates if candidate), "")


def _matches_config_key(value: Any, configured_keys: set[str]) -> str:
    normalized = _normalize_question_id(value)
    if normalized in configured_keys:
        return normalized
    return ""


def _question_config_key(
    question: dict[str, Any],
    configured_keys: set[str],
    label_aliases: dict[str, str],
) -> str:
    for value in (question.get("id"), question.get("key"), question.get("questionKey")):
        key = _matches_config_key(value, configured_keys)
        if key:
            return key

    title_key = label_aliases.get(_normalize_label(question.get("title")))
    if title_key:
        return title_key

    for field_data in question.get("fields", []) or []:
        if not isinstance(field_data, dict):
            continue
        for alias_name in ("key", "questionKey", "uuid", "blockGroupUuid", "id"):
            key = _matches_config_key(field_data.get(alias_name), configured_keys)
            if key:
                return key
        title_key = label_aliases.get(_normalize_label(field_data.get("title")))
        if title_key:
            return title_key
    return ""


def _build_answer_map(
    submission: dict[str, Any],
    questions: list[dict[str, Any]] | None = None,
    form_config: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Return answers keyed by config question key suffix.

    Tally webhooks use ``fields[].key = question_<key>``. The submissions API returns
    ``responses[]`` with ``questionId`` values that can be UUIDs, while the
    corresponding ``questions[].fields[]`` metadata can carry the configured Tally
    field key. We first detect the configured key anywhere in a question/field and
    then alias every ID from that question back to the configured key.
    """
    configured_keys = _configured_question_keys(form_config) if form_config else set()
    label_aliases = _question_label_aliases(form_config) if form_config else {}
    answer_aliases = _answer_aliases_by_question(form_config) if form_config else {}
    answers: dict[str, str] = {}

    for field_data in submission.get("fields", []):
        if isinstance(field_data, dict):
            key = _normalize_question_id(field_data.get("key"))
            if key:
                answer = _extract_answer(field_data.get("value"))
                answers[key] = _resolve_answer(key, [answer], answer_aliases)

    aliases: dict[str, str] = {}
    for question in questions or []:
        if not isinstance(question, dict):
            continue
        question_key = (
            _question_config_key(question, configured_keys, label_aliases)
            if configured_keys
            else _normalize_question_id(question.get("id"))
        )
        if not question_key:
            continue
        for alias_value in (
            question.get("id"),
            question.get("key"),
            question.get("questionKey"),
            question_key,
            f"question_{question_key}",
        ):
            if alias_value:
                aliases[str(alias_value)] = question_key
                aliases[_normalize_question_id(alias_value)] = question_key
        for field_data in question.get("fields", []) or []:
            if not isinstance(field_data, dict):
                continue
            for alias_name in ("key", "questionKey", "uuid", "blockGroupUuid", "id"):
                alias_value = field_data.get(alias_name)
                if alias_value:
                    aliases[str(alias_value)] = question_key
                    aliases[_normalize_question_id(alias_value)] = question_key

    for response in submission.get("responses", []):
        if not isinstance(response, dict):
            continue
        question_id = response.get("questionId") or response.get("questionKey") or response.get("id")
        fallback_key = _normalize_question_id(question_id)
        key = aliases.get(str(question_id), aliases.get(fallback_key, fallback_key))
        if configured_keys and key not in configured_keys:
            logger.debug("Skipping Tally response with unmapped questionId=%s", question_id)
            continue
        if not key:
            continue
        answers[key] = _resolve_answer(
            key,
            [
                _extract_answer(response.get("answer")),
                _extract_answer(response.get("formattedAnswer")),
            ],
            answer_aliases,
        )

    return answers


def _raw_scores_from_answers(answers: dict[str, str], form_config: dict[str, Any]) -> dict[str, int]:
    raw_scores: dict[str, int] = {}
    for question in form_config["scored_questions"]:
        answer = answers.get(question["key"], "")
        front = question["front"]
        raw_scores[front] = raw_scores.get(front, 0) + int(question["scores"].get(answer, 0))
    return raw_scores


def _context_value(answers: dict[str, str], form_config: dict[str, Any], name: str) -> str:
    question = form_config["context_questions"][name]
    return question["options"].get(answers.get(question["key"], ""), "")


def _front_labels(scoring_config: dict[str, Any]) -> dict[str, str]:
    labels = {front: front for front in scoring_config["fronts"]}
    for profile in scoring_config["profiles"].values():
        if profile.get("front") and profile.get("front_label"):
            labels[profile["front"]] = profile["front_label"]
    return labels


def aggregate_submissions(
    submissions: list[dict[str, Any]],
    *,
    questions: list[dict[str, Any]] | None = None,
    form_config: dict[str, Any] | None = None,
    scoring_config: dict[str, Any] | None = None,
) -> RadarAggregate:
    """Aggregate submissions into averages and distribution counters."""
    form_config = form_config or load_form_config()
    scoring_config = scoring_config or load_scoring_config()
    fronts = list(scoring_config["fronts"])
    totals = {front: 0.0 for front in fronts}
    all_scores: dict[str, list[float]] = {front: [] for front in fronts}
    max_scores = {
        front: round(
            sum(
                max(question["scores"].values(), default=0)
                for question in form_config["scored_questions"]
                if question["front"] == front
            )
            * scoring_config.get("normalization", {}).get(front, 1.0)
        )
        for front in fronts
    }
    profile_counts: dict[str, int] = {}
    calculated_counts: dict[str, int] = {}
    felt_counts: dict[str, int] = {}
    situation_counts: dict[str, int] = {}
    submission_count = 0
    skipped_count = 0
    disqualification_options = set(form_config.get("disqualification_options", []))
    _tiebreak_priority = next(
        (
            r["condition"]["tiebreak_priority"]
            for r in scoring_config.get("profile_rules", [])
            if r["condition"]["type"] == "weakest_front"
        ),
        fronts,
    )

    for submission in submissions:
        answers = _build_answer_map(submission, questions, form_config)
        if disqualification_options & set(answers.values()):
            skipped_count += 1
            continue

        raw_scores = _raw_scores_from_answers(answers, form_config)
        result = score_response(raw_scores, scoring_config)
        submission_count += 1
        for front in fronts:
            score = result.scores.get(front, 0)
            totals[front] += score
            all_scores[front].append(score)
        profile_counts[result.profile_key] = profile_counts.get(result.profile_key, 0) + 1

        min_score = min(result.scores.get(f, 0) for f in fronts)
        weakest_fronts = [f for f in fronts if result.scores.get(f, 0) == min_score]
        weakest = next((f for f in _tiebreak_priority if f in weakest_fronts), weakest_fronts[0])
        calculated_counts[weakest] = calculated_counts.get(weakest, 0) + 1

        felt = _context_value(answers, form_config, "felt_constraint")
        if felt:
            felt_counts[felt] = felt_counts.get(felt, 0) + 1
        situation = _context_value(answers, form_config, "situation")
        if situation:
            situation_counts[situation] = situation_counts.get(situation, 0) + 1

    average_scores = {
        front: round(totals[front] / submission_count, 2) if submission_count else 0.0
        for front in fronts
    }
    std_scores = {
        front: round(statistics.stdev(all_scores[front]), 2)
        if len(all_scores[front]) >= 2
        else 0.0
        for front in fronts
    }
    actual_min_scores = {
        front: float(min(all_scores[front])) if all_scores[front] else 0.0
        for front in fronts
    }
    actual_max_scores = {
        front: float(max(all_scores[front])) if all_scores[front] else 0.0
        for front in fronts
    }
    return RadarAggregate(
        form_id=form_config["form_id"],
        submission_count=submission_count,
        skipped_count=skipped_count,
        fronts=fronts,
        front_labels=_front_labels(scoring_config),
        average_scores=average_scores,
        std_scores=std_scores,
        actual_min_scores=actual_min_scores,
        actual_max_scores=actual_max_scores,
        max_scores=max_scores,
        profile_counts=profile_counts,
        calculated_constraint_counts=calculated_counts,
        felt_constraint_counts=felt_counts,
        situation_counts=situation_counts,
    )
