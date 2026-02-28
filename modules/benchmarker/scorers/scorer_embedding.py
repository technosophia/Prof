"""Embedding similarity scorer plugin."""

from typing import Dict

from core.logging import log
from modules.benchmarker.scorers.base import ScorerPlugin as BaseScorerPlugin, ScoringResult


class ScorerPlugin(BaseScorerPlugin):
    """Automatic cosine similarity scorer."""

    id = "embedding_similarity"
    name = "Embedding Similarity"

    def is_available(self) -> bool:
        try:
            import sentence_transformers  # noqa

            return True
        except ImportError:
            log("warning", "embedding_similarity scorer: sentence-transformers not installed")
            return False

    def compute_score(self, session: Dict, config: Dict, container) -> None:
        from st_shared.cached import get_section

        model_name = get_section("benchmarker").get("embedding_model", "all-MiniLM-L6-v2")
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

        container.info(f"Computing embeddings with model: {model_name}")

        from sentence_transformers import SentenceTransformer, util

        model = SentenceTransformer(model_name)

        scores = {}
        rows = []
        for step in qualifying:
            step_id = step["id"]
            answer = step["result"]["llm_response"]
            expected = step["expected_response"]
            emb_answer = model.encode(answer, convert_to_tensor=True)
            emb_expected = model.encode(expected, convert_to_tensor=True)
            similarity = float(util.cos_sim(emb_answer, emb_expected)[0][0])
            scores[step_id] = round(similarity, 4)
            rows.append({"step": step_id, "similarity": similarity})

        result = ScoringResult(
            scorer_id=self.id,
            session_path=session_path,
            scores=scores,
            scorer_config={"model": model_name, "steps_scored": len(scores)},
            source="embedding",
            notes=None,
            scored_at=self._now(),
            parse_errors=[],
            complete=True,
        )
        self._write_score(result)

        container.success(f"Similarity computed for {len(scores)} step(s). Overall: {result.overall:.4f}")
        container.dataframe(rows)
