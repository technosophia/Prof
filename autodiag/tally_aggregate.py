"""Aggregate Tally API submissions into autodiag radar data."""

import json
import logging
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
    profile_counts: dict[str, int] = field(default_factory=dict)
    felt_constraint_counts: dict[str, int] = field(default_factory=dict)
    situation_counts: dict[str, int] = field(default_factory=dict)


def load_form_config() -> dict[str, Any]:
    with open(_FORM_CONFIG_PATH) as f:
        return json.load(f)


def load_scoring_config() -> dict[str, Any]:
    with open(_SCORING_CONFIG_PATH) as f:
        return json.load(f)


def _extract_answer(value: Any) -> str:
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value) if value is not None else ""


def _normalize_question_id(question_id: Any) -> str:
    question_id = str(question_id or "")
    return question_id.removeprefix("question_")


def _build_answer_map(submission: dict[str, Any], questions: list[dict[str, Any]] | None = None) -> dict[str, str]:
    """Return answers keyed by config question key suffix.

    Tally webhooks use ``fields[].key = question_<key>``. The submissions API returns
    ``responses[]``; depending on the field type, ``questionId`` may already be the
    same key or may reference a question/field UUID. This mapper accepts both shapes.
    """
    answers: dict[str, str] = {}

    for field_data in submission.get("fields", []):
        if isinstance(field_data, dict):
            key = _normalize_question_id(field_data.get("key"))
            if key:
                answers[key] = _extract_answer(field_data.get("value"))

    aliases: dict[str, str] = {}
    for question in questions or []:
        if not isinstance(question, dict):
            continue
        question_key = _normalize_question_id(question.get("id"))
        if question_key:
            aliases[str(question.get("id"))] = question_key
            aliases[question_key] = question_key
        for field_data in question.get("fields", []) or []:
            if not isinstance(field_data, dict):
                continue
            for alias_name in ("uuid", "blockGroupUuid", "id"):
                alias_value = field_data.get(alias_name)
                if alias_value and question_key:
                    aliases[str(alias_value)] = question_key

    for response in submission.get("responses", []):
        if not isinstance(response, dict):
            continue
        question_id = response.get("questionId") or response.get("questionKey") or response.get("id")
        key = aliases.get(str(question_id), _normalize_question_id(question_id))
        if not key:
            continue
        answers[key] = _extract_answer(response.get("answer"))

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
    felt_counts: dict[str, int] = {}
    situation_counts: dict[str, int] = {}
    submission_count = 0
    skipped_count = 0
    disqualification_options = set(form_config.get("disqualification_options", []))

    for submission in submissions:
        answers = _build_answer_map(submission, questions)
        if disqualification_options & set(answers.values()):
            skipped_count += 1
            continue

        raw_scores = _raw_scores_from_answers(answers, form_config)
        result = score_response(raw_scores, scoring_config)
        submission_count += 1
        for front in fronts:
            totals[front] += result.scores.get(front, 0)
        profile_counts[result.profile_key] = profile_counts.get(result.profile_key, 0) + 1

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
    return RadarAggregate(
        form_id=form_config["form_id"],
        submission_count=submission_count,
        skipped_count=skipped_count,
        fronts=fronts,
        front_labels=_front_labels(scoring_config),
        average_scores=average_scores,
        max_scores=max_scores,
        profile_counts=profile_counts,
        felt_constraint_counts=felt_counts,
        situation_counts=situation_counts,
    )
