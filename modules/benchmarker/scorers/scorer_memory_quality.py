"""Memory quality scorer — uses SemanticEvaluator service."""

from typing import Dict

from modules.benchmarker.scorers.base import ScorerPlugin as BaseScorerPlugin, ScoringResult


def _get_evaluator():
    try:
        from shared.common import get_module_handler
        services = get_module_handler().get_services()
        if services:
            return services.get("semantic_eval")
    except Exception:
        pass
    return None


class ScorerPlugin(BaseScorerPlugin):
    """Automatic scorer for trigger_memory_analysis steps (full-document similarity)."""

    id = "memory_quality"
    name = "Memory Quality (Embedding)"

    def is_available(self) -> bool:
        return _get_evaluator() is not None

    def compute_score(self, session: Dict, config: Dict, container) -> None:
        session_path = config["session_path"]

        qualifying = [
            step for step in session.get("steps", [])
            if step.get("action") == "trigger_memory_analysis"
            and step.get("result", {}).get("memory_content", "").strip()
            and step.get("expected_memory", "").strip()
        ]

        if not qualifying:
            container.warning(
                "No trigger_memory_analysis steps with both memory_content and expected_memory found. "
                "Add 'expected_memory:' to trigger_memory_analysis steps in the scenario YAML."
            )
            return

        evaluator = _get_evaluator()
        if evaluator is None:
            container.error("'semantic_eval' service not found in ServiceLocator.")
            return

        batch_mode = bool(config.get("batch_mode"))
        container.info(
            f"Found {len(qualifying)} qualifying memory step(s). "
            f"Similarity threshold: {evaluator.default_similarity_threshold}"
        )
        submit_key = f"mem_quality_submit_{session_path}"
        if not batch_mode and not container.button("Score memory quality", key=submit_key):
            return

        aggregated_scores = {}
        parse_errors = []

        for step in qualifying:
            step_id = step["id"]
            memory_content = step["result"]["memory_content"]
            expected_memory = step["expected_memory"]

            step_parse_errors = []
            sim_result = None
            try:
                sim_result = evaluator.similarity(memory_content, expected_memory)
            except Exception as exc:
                message = f"Similarity failed for step {step_id}: {exc}"
                parse_errors.append(message)
                step_parse_errors.append(message)

            step_result = ScoringResult(
                scorer_id=self.id,
                session_path=session_path,
                scores={"similarity": sim_result.score} if sim_result else {},
                scorer_config={
                    "level": "step",
                    "step_id": step_id,
                    "threshold": evaluator.default_similarity_threshold,
                },
                source="embedding",
                notes=None,
                scored_at=self._now(),
                parse_errors=step_parse_errors,
                complete=sim_result is not None,
            )
            self._write_score(step_result)

            if sim_result is not None:
                aggregated_scores[step_id] = sim_result.score

        if not aggregated_scores:
            container.warning("All memory quality scoring attempts failed.")
            return

        session_result = ScoringResult(
            scorer_id=self.id,
            session_path=session_path,
            scores=aggregated_scores,
            scorer_config={
                "level": "session",
                "steps_scored": len(aggregated_scores),
                "threshold": evaluator.default_similarity_threshold,
            },
            source="embedding",
            notes=None,
            scored_at=self._now(),
            parse_errors=parse_errors,
            complete=not parse_errors,
        )
        self._write_score(session_result)

        overall = sum(aggregated_scores.values()) / len(aggregated_scores)
        container.success(
            f"Memory quality scored for {len(aggregated_scores)} step(s). "
            f"Overall: {overall:.4f}"
        )
        container.dataframe(
            [{"step_id": sid, "similarity": score} for sid, score in aggregated_scores.items()],
            width="stretch",
        )
