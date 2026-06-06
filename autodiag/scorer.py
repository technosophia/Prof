"""Compute front scores and determine profile using config/scoring.json — no profile names in code."""

import json
from dataclasses import dataclass
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent / "config" / "scoring.json"


def _load_config() -> dict:
    with open(_CONFIG_PATH) as f:
        return json.load(f)


@dataclass
class ScoringResult:
    scores: dict          # front -> normalized int score (/12 each)
    score_total: int
    profile_key: str
    is_rationalisateur: bool
    profile: dict         # full profile object from scoring.json


def _normalize(raw_scores: dict, config: dict) -> tuple[dict, int]:
    """Apply per-front normalization factors and return (normalized_scores, total)."""
    normalization = config.get("normalization", {})
    normalized = {}
    for front in config["fronts"]:
        raw = raw_scores.get(front, 0)
        factor = normalization.get(front, 1.0)
        normalized[front] = round(raw * factor)
    total = sum(normalized.values())
    return normalized, total


def _check_rationalisateur(scores: dict, config: dict) -> bool:
    rf = config["internal_flags"]["rationalisateur"]["conditions"]
    for front, cond in rf["require"].items():
        if scores.get(front, 0) < cond.get("min", 0):
            return False
    return any(scores.get(c["front"], 0) <= c["max"] for c in rf["any_of"])


def _apply_rules(scores: dict, total: int, config: dict) -> str:
    rules = sorted(config["profile_rules"], key=lambda r: r["priority"])
    for rule in rules:
        cond = rule["condition"]

        if cond["type"] == "min_low_fronts":
            low_count = sum(1 for s in scores.values() if s < cond["low_threshold"])
            if low_count >= cond["min_count"]:
                return rule["profile"]

        elif cond["type"] == "advanced":
            if total >= cond["min_total"] and all(s >= cond["min_per_front"] for s in scores.values()):
                return rule["profile"]

        elif cond["type"] == "weakest_front":
            min_score = min(scores.values())
            weakest = [f for f, s in scores.items() if s == min_score]
            chosen = next(f for f in cond["tiebreak_priority"] if f in weakest)
            return rule["front_to_profile"][chosen]

    # Unreachable if config contains a weakest_front rule, but safe fallback
    return list(config["profiles"].keys())[0]


def score_response(raw_scores: dict) -> ScoringResult:
    config = _load_config()
    scores, total = _normalize(raw_scores, config)
    is_rationalisateur = _check_rationalisateur(scores, config)
    profile_key = _apply_rules(scores, total, config)
    return ScoringResult(
        scores=scores,
        score_total=total,
        profile_key=profile_key,
        is_rationalisateur=is_rationalisateur,
        profile=config["profiles"][profile_key],
    )
