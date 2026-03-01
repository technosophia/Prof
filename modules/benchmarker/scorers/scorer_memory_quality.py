"""Memory quality scorer — evaluates trigger_memory_analysis steps against expected_memory."""

from typing import Dict

from modules.benchmarker.scorers.base import ScorerPlugin as BaseScorerPlugin, ScoringResult


class ScorerPlugin(BaseScorerPlugin):
    """Automatic scorer for trigger_memory_analysis steps."""

    id = "memory_quality"
    name = "Memory Quality (Embedding)"

    def is_available(self) -> bool:
        try:
            from shared.common import get_embedding  # noqa: F401
            import numpy  # noqa: F401
            return True
        except ImportError:
            return False

    def compute_score(self, session: Dict, config: Dict, container) -> None:
        import numpy as np
        from shared.common import get_embedding

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

        batch_mode = bool(config.get("batch_mode"))
        container.info(f"Found {len(qualifying)} qualifying memory step(s) to score.")
        submit_key = f"mem_quality_submit_{session_path}"
        if not batch_mode and not container.button("Score memory quality", key=submit_key):
            return

        def _cosine(a, b):
            norm_a = float(np.linalg.norm(a))
            norm_b = float(np.linalg.norm(b))
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return float(np.dot(a, b) / (norm_a * norm_b))

        aggregated_scores = {}
        parse_errors = []

        for step in qualifying:
            step_id = step["id"]
            memory_content = step["result"]["memory_content"]
            expected_memory = step["expected_memory"]

            similarity = None
            step_parse_errors = []
            try:
                vec_memory = np.asarray(get_embedding(memory_content), dtype=np.float32)
                vec_expected = np.asarray(get_embedding(expected_memory), dtype=np.float32)
                similarity = round(_cosine(vec_memory, vec_expected), 4)
            except Exception as exc:
                message = f"Embedding failed for step {step_id}: {exc}"
                parse_errors.append(message)
                step_parse_errors.append(message)

            step_result = ScoringResult(
                scorer_id=self.id,
                session_path=session_path,
                scores={"similarity": similarity} if similarity is not None else {},
                scorer_config={
                    "model": "global_llm_embedding",
                    "level": "step",
                    "step_id": step_id,
                },
                source="embedding",
                notes=None,
                scored_at=self._now(),
                parse_errors=step_parse_errors,
                complete=similarity is not None,
            )
            self._write_score(step_result)

            if similarity is not None:
                aggregated_scores[step_id] = similarity

        if not aggregated_scores:
            container.warning("All memory quality scoring attempts failed.")
            return

        session_result = ScoringResult(
            scorer_id=self.id,
            session_path=session_path,
            scores=aggregated_scores,
            scorer_config={
                "model": "global_llm_embedding",
                "level": "session",
                "steps_scored": len(aggregated_scores),
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
            f"Overall similarity: {overall:.4f}"
        )
        container.dataframe(
            [{"step_id": sid, "similarity": score} for sid, score in aggregated_scores.items()],
            width="stretch",
        )
