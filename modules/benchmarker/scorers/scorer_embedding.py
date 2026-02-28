"""Embedding similarity scorer plugin."""

from typing import Dict

from modules.benchmarker.scorers.base import ScorerPlugin as BaseScorerPlugin, ScoringResult


class ScorerPlugin(BaseScorerPlugin):
    """Automatic cosine similarity scorer."""

    id = "embedding_similarity"
    name = "Embedding Similarity"

    def compute_score(self, session: Dict, config: Dict, container) -> None:
        import numpy as np

        from shared.common import get_embedding

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

        batch_mode = bool(config.get("batch_mode"))
        container.info("Computing embeddings with the global LLM embedding service")
        submit_key = f"embedding_submit_{session_path}"
        if not batch_mode and not container.button("Compute similarity", key=submit_key):
            return

        def _cosine_similarity(vec_a, vec_b) -> float:
            denominator = float(np.linalg.norm(vec_a) * np.linalg.norm(vec_b))
            if denominator == 0:
                return 0.0
            return float(np.dot(vec_a, vec_b) / denominator)

        scores = {}
        rows = []
        for step in qualifying:
            step_id = step["id"]
            answer = step["result"]["llm_response"]
            expected = step["expected_response"]
            emb_answer = get_embedding(answer)
            emb_expected = get_embedding(expected)
            similarity = _cosine_similarity(np.array(emb_answer), np.array(emb_expected))
            scores[step_id] = round(similarity, 4)
            rows.append({"step": step_id, "similarity": similarity})

        result = ScoringResult(
            scorer_id=self.id,
            session_path=session_path,
            scores=scores,
            scorer_config={"model": "global_llm_embedding", "steps_scored": len(scores)},
            source="embedding",
            notes=None,
            scored_at=self._now(),
            parse_errors=[],
            complete=True,
        )
        self._write_score(result)

        container.success(f"Similarity computed for {len(scores)} step(s). Overall: {result.overall:.4f}")
        container.dataframe(rows)
