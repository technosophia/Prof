"""Manual scorer plugin for human-provided rubric scores."""

from __future__ import annotations

from typing import Dict, List, Optional

import yaml

from core.logging import log
from modules.benchmarker.scoring_pipeline import get_scoring_pipeline
from modules.benchmarker.scorers.base import ScorerPlugin, ScoringResult
from modules.benchmarker.scorers.prompt_renderer import RubricLoader


class ManualScorer(ScorerPlugin):
    """Scorer plugin that validates and stores manually provided rubric scores."""

    id = "manual"
    name = "Manual Scoring"

    def score(self, session: Dict, config: Dict) -> ScoringResult:
        """Validate rubric-based manual scores and return a scoring result."""
        del session

        session_path = str(config.get("session_path", ""))
        rubric_name = str(config.get("rubric", "")).strip()
        input_scores = config.get("scores") or {}
        notes = config.get("notes")
        parse_errors: List[str] = []

        if not rubric_name:
            parse_errors.append("Missing required config key: rubric")
            return self._failed_result(session_path, rubric_name, notes, parse_errors)
        if not isinstance(input_scores, dict):
            parse_errors.append("Missing required config key: scores")
            return self._failed_result(session_path, rubric_name, notes, parse_errors)

        try:
            rubric = RubricLoader().load(rubric_name)
        except Exception as exc:
            parse_errors.append(f"Failed to load rubric '{rubric_name}': {exc}")
            return self._failed_result(session_path, rubric_name, notes, parse_errors)

        scores = self._validate_dimension_scores(rubric, input_scores, parse_errors)
        complete = not parse_errors and all(v is not None for v in scores.values())

        return ScoringResult(
            scorer_id=self.id,
            session_path=session_path,
            scores=scores,
            overall=self._compute_overall(scores),
            scorer_config={"rubric": rubric_name},
            source="manual",
            notes=notes,
            scored_at=self._now(),
            parse_errors=parse_errors,
            complete=complete,
        )

    def import_from_session_yaml(self, session_path: str, rubric_name: Optional[str] = None) -> ScoringResult:
        """Import manual scores from a session YAML `scores` block and persist the result."""
        parse_errors: List[str] = []
        session_data: Dict = {}

        try:
            with open(session_path, "r", encoding="utf-8") as handle:
                session_data = yaml.safe_load(handle) or {}
        except Exception as exc:
            parse_errors.append(f"Failed to read session yaml: {exc}")
            return self._failed_result(session_path, rubric_name or "", None, parse_errors, imported_from_yaml=True)

        scores_block = session_data.get("scores") or {}
        if not isinstance(scores_block, dict) or not scores_block:
            parse_errors.append("Missing scores block in session YAML")
            return self._failed_result(session_path, rubric_name or "", None, parse_errors, imported_from_yaml=True)

        selected_rubric = (rubric_name or scores_block.get("rubric") or "").strip()
        if not selected_rubric:
            parse_errors.append("Missing rubric name: pass rubric_name or set scores.rubric")
            return self._failed_result(session_path, selected_rubric, scores_block.get("notes"), parse_errors, imported_from_yaml=True)

        dimensions = scores_block.get("dimensions") or {}
        if not isinstance(dimensions, dict):
            parse_errors.append("scores.dimensions must be a mapping")
            dimensions = {}

        notes = scores_block.get("notes")
        result = self.score(
            session={},
            config={
                "session_path": session_path,
                "rubric": selected_rubric,
                "scores": dimensions,
                "notes": notes,
            },
        )
        result.scorer_config = {"rubric": selected_rubric, "imported_from_yaml": True}

        get_scoring_pipeline().persist_result(session_path, result)
        return result

    def _validate_dimension_scores(self, rubric: Dict, input_scores: Dict, parse_errors: List[str]) -> Dict[str, Optional[float]]:
        scores: Dict[str, Optional[float]] = {}
        for dimension in rubric.get("dimensions", []):
            dimension_id = str(dimension.get("id", "")).strip()
            if not dimension_id:
                continue
            if dimension_id not in input_scores:
                parse_errors.append(f"Missing dimension score: {dimension_id}")
                scores[dimension_id] = None
                continue
            value = input_scores.get(dimension_id)
            try:
                scores[dimension_id] = float(value)
            except (TypeError, ValueError):
                parse_errors.append(f"Non-numeric dimension score: {dimension_id}")
                scores[dimension_id] = None
        return scores

    def _failed_result(
        self,
        session_path: str,
        rubric_name: str,
        notes: Optional[str],
        parse_errors: List[str],
        imported_from_yaml: bool = False,
    ) -> ScoringResult:
        config = {"rubric": rubric_name}
        if imported_from_yaml:
            config["imported_from_yaml"] = True
        return ScoringResult(
            scorer_id=self.id,
            session_path=session_path,
            scores={},
            overall=None,
            scorer_config=config,
            source="manual",
            notes=notes,
            scored_at=self._now(),
            parse_errors=parse_errors,
            complete=False,
        )
