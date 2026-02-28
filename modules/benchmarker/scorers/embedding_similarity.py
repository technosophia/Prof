"""Embedding similarity scorer plugin."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from core.logging import log
from st_shared.cached import get_section

from modules.benchmarker.scorers.base import ScorerPlugin, ScoringResult


class EmbeddingSimilarityScorer(ScorerPlugin):
    """Score responses by cosine similarity against expected responses."""

    id = "embedding_similarity"
    name = "Embedding Similarity"

    def __init__(self):
        self._cached_model_name: Optional[str] = None
        self._cached_model = None

    def is_available(self) -> bool:
        try:
            import sentence_transformers  # noqa: F401

            return True
        except ImportError:
            log("warning", "embedding_similarity scorer: sentence-transformers not installed")
            return False

    def score(self, session: Dict, config: Dict) -> ScoringResult:
        """Compute per-step cosine similarity for steps with expected responses."""
        session_path = str(config.get("session_path", ""))
        parse_errors: List[str] = []

        configured_default_model = get_section("benchmarker").get("embedding_similarity_default_model")
        model_name = str(config.get("model") or configured_default_model or "").strip()
        if not model_name:
            parse_errors.append("Missing embedding model configuration: benchmarker.embedding_similarity_default_model")
            return self._failed_result(session_path, model_name, 0, parse_errors)

        step_pairs = self._collect_text_pairs(session)
        if not step_pairs:
            parse_errors.append("No steps with both llm_response and expected_response found")
            return self._failed_result(session_path, model_name, 0, parse_errors)

        try:
            model = self._get_model(model_name)
        except Exception as exc:
            parse_errors.append(f"Failed to load embedding model '{model_name}': {exc}")
            return self._failed_result(session_path, model_name, 0, parse_errors)

        scores: Dict[str, Optional[float]] = {}
        for step_id, response, expected in step_pairs:
            try:
                emb_response = model.encode(response, convert_to_tensor=True)
                emb_expected = model.encode(expected, convert_to_tensor=True)
                scores[step_id] = self._similarity(emb_response, emb_expected)
            except Exception as exc:
                parse_errors.append(f"Failed to score step {step_id}: {exc}")
                scores[step_id] = None

        complete = bool(scores) and not parse_errors and all(v is not None for v in scores.values())
        return ScoringResult(
            scorer_id=self.id,
            session_path=session_path,
            scores=scores,
            overall=self._compute_overall(scores),
            scorer_config={"model": model_name, "steps_scored": len(scores)},
            source="embedding",
            notes=None,
            scored_at=self._now(),
            parse_errors=parse_errors,
            complete=complete,
        )

    def _collect_text_pairs(self, session: Dict) -> List[Tuple[str, str, str]]:
        pairs: List[Tuple[str, str, str]] = []
        for step in session.get("steps", []):
            if step.get("action") != "user_send_message":
                continue
            response = step.get("result", {}).get("llm_response")
            expected = step.get("expected_response")
            step_id = str(step.get("id", "")).strip()
            if not step_id:
                continue
            if isinstance(response, str) and response.strip() and isinstance(expected, str) and expected.strip():
                pairs.append((step_id, response.strip(), expected.strip()))
        return pairs

    def _get_model(self, model_name: str):
        if self._cached_model_name == model_name and self._cached_model is not None:
            return self._cached_model
        from sentence_transformers import SentenceTransformer

        self._cached_model = SentenceTransformer(model_name)
        self._cached_model_name = model_name
        return self._cached_model

    @staticmethod
    def _similarity(embedding_a, embedding_b) -> float:
        from sentence_transformers import util

        return float(util.cos_sim(embedding_a, embedding_b)[0][0])

    def _failed_result(self, session_path: str, model_name: str, steps_scored: int, parse_errors: List[str]) -> ScoringResult:
        return ScoringResult(
            scorer_id=self.id,
            session_path=session_path,
            scores={},
            overall=None,
            scorer_config={"model": model_name, "steps_scored": steps_scored},
            source="embedding",
            notes=None,
            scored_at=self._now(),
            parse_errors=parse_errors,
            complete=False,
        )
