"""Embedding similarity scorer plugin — uses SemanticEvaluator service."""

from typing import Dict

from modules.benchmarker.scorers.base import ScorerPlugin as BaseScorerPlugin, ScoringResult


def _get_evaluator():
    """Retrieve SemanticEvaluator from the ServiceLocator."""
    try:
        from shared.common import get_module_handler
        services = get_module_handler().get_services()
        if services:
            return services.get("semantic_eval")
    except Exception:
        pass
    return None


class ScorerPlugin(BaseScorerPlugin):
    """Automatic cosine similarity scorer (full-document, response vs expected)."""

    id = "embedding_similarity"
    name = "Embedding Similarity"

    def compute_score(self, session: Dict, config: Dict, container) -> None:
        session_path = config["session_path"]

        qualifying = [
            step for step in session.get("steps", [])
            if step.get("action") == "user_send_message"
            and step.get("result", {}).get("llm_response", "").strip()
            and step.get("expected_response", "").strip()
        ]

        if not qualifying:
            container.warning(
                "No steps with both llm_response and expected_response found. "
                "Add expected_response to scenario steps to use this scorer."
            )
            return

        evaluator = _get_evaluator()
        if evaluator is None:
            container.error(
                "'semantic_eval' service not found in ServiceLocator. "
                "Register SemanticEvaluator at startup."
            )
            return

        batch_mode = bool(config.get("batch_mode"))
        container.info(
            f"Full-document cosine similarity for {len(qualifying)} step(s). "
            f"Threshold: {evaluator.default_similarity_threshold}"
        )
        submit_key = f"embedding_submit_{session_path}"
        if not batch_mode and not container.button("Compute similarity", key=submit_key):
            return

        scores = {}
        rows = []

        for step in qualifying:
            step_id = step["id"]
            answer = step["result"]["llm_response"]
            expected = step["expected_response"]

            result = evaluator.similarity(answer, expected)
            scores[step_id] = result.score
            rows.append({
                "step": step_id,
                "similarity": result.score,
                "passed": result.passed,
                "threshold": result.threshold,
            })

            step_result = ScoringResult(
                scorer_id=self.id,
                session_path=session_path,
                scores={"similarity": result.score},
                scorer_config={
                    "level": "step",
                    "step_id": step_id,
                    "threshold": result.threshold,
                },
                source="embedding",
                notes=None,
                scored_at=self._now(),
                parse_errors=[],
                complete=True,
            )
            self._write_score(step_result)

        session_result = ScoringResult(
            scorer_id=self.id,
            session_path=session_path,
            scores=scores,
            scorer_config={
                "steps_scored": len(scores),
                "level": "session",
                "threshold": evaluator.default_similarity_threshold,
            },
            source="embedding",
            notes=None,
            scored_at=self._now(),
            parse_errors=[],
            complete=True,
        )
        self._write_score(session_result)

        overall = session_result.overall
        container.success(
            f"Similarity computed for {len(scores)} step(s). "
            f"Overall: {overall:.4f}"
        )
        container.dataframe(rows)
