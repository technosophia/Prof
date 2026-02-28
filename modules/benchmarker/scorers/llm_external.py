"""External LLM scorer plugin for pasted judge responses."""

from __future__ import annotations

from typing import Dict, List, Optional

import yaml

from core.logging import log
from modules.benchmarker.scorers.base import ScorerPlugin, ScoringResult
from modules.benchmarker.scorers.prompt_renderer import JudgePromptRenderer, RubricLoader


class LLMExternalScorer(ScorerPlugin):
    """Scorer plugin that parses scores produced by an external LLM."""

    id = "llm_external"
    name = "External LLM Judge"

    def generate_prompt(self, session: Dict, config: Dict) -> str:
        """Generate judge prompt for copy-paste into any external LLM."""
        rubric_name = str(config.get("rubric", "")).strip()
        if not rubric_name:
            raise ValueError("Missing required config key: rubric")
        rubric = RubricLoader().load(rubric_name)
        return JudgePromptRenderer().render(session, rubric)

    def score(self, session: Dict, config: Dict) -> ScoringResult:
        """Parse pasted YAML response from external LLM and produce scores."""
        parse_errors: List[str] = []
        session_path = str(config.get("session_path", ""))
        rubric_name = str(config.get("rubric", "")).strip()
        response_text = str(config.get("response_text", ""))

        if not rubric_name:
            parse_errors.append("Missing required config key: rubric")
            return self._failed_result(session_path, rubric_name, parse_errors)

        try:
            rubric = RubricLoader().load(rubric_name)
        except Exception as exc:
            parse_errors.append(f"Failed to load rubric '{rubric_name}': {exc}")
            return self._failed_result(session_path, rubric_name, parse_errors)

        scores: Dict[str, Optional[float]] = {str(d.get("id")): None for d in rubric.get("dimensions", []) if d.get("id")}

        try:
            normalized = self._strip_fences(response_text)
            parsed = yaml.safe_load(normalized) or {}
            parsed_dimensions = ((parsed.get("scores") or {}).get("dimensions") or {})

            for dimension_id in scores.keys():
                value = parsed_dimensions.get(dimension_id)
                if value is None:
                    parse_errors.append(f"Missing dimension score: {dimension_id}")
                    continue
                try:
                    scores[dimension_id] = float(value)
                except (TypeError, ValueError):
                    parse_errors.append(f"Non-numeric dimension score: {dimension_id}")
                    scores[dimension_id] = None
        except Exception as exc:
            log("warning", f"llm_external scorer parse failure: {exc}")
            parse_errors.append(f"Failed to parse pasted YAML response: {exc}")

        complete = not parse_errors and all(v is not None for v in scores.values())
        return ScoringResult(
            scorer_id=self.id,
            session_path=session_path,
            scores=scores,
            overall=self._compute_overall(scores),
            scorer_config={"rubric": rubric_name},
            source="llm_paste",
            notes=None,
            scored_at=self._now(),
            parse_errors=parse_errors,
            complete=complete,
        )

    @staticmethod
    def _strip_fences(text: str) -> str:
        normalized = (text or "").strip()
        if not normalized.startswith("```"):
            return normalized
        lines = normalized.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines)

    def _failed_result(self, session_path: str, rubric_name: str, parse_errors: List[str]) -> ScoringResult:
        return ScoringResult(
            scorer_id=self.id,
            session_path=session_path,
            scores={},
            overall=None,
            scorer_config={"rubric": rubric_name},
            source="llm_paste",
            notes=None,
            scored_at=self._now(),
            parse_errors=parse_errors,
            complete=False,
        )
