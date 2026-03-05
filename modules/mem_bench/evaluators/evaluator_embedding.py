"""Embedding-based semantic evaluator for mem_bench."""

from __future__ import annotations

from statistics import mean
from typing import List

import numpy as np

from shared.common import get_embeddings

from .base import EvalCheck, EvalResult, MemEvaluator


class EmbeddingEvaluator(MemEvaluator):
    id = "embedding"
    label = "Embedding semantic checks"

    def evaluate(self, memory_content: str, scenario: dict, context: dict) -> EvalResult:
        del context
        threshold = float(scenario.get("semantic_threshold") or 0.55)
        contains = [str(x) for x in (scenario.get("expected_memory_contains") or [])]
        excludes = [str(x) for x in (scenario.get("expected_memory_excludes") or [])]
        chunks = self._chunk_text(memory_content)

        checks: List[EvalCheck] = []
        if not chunks:
            for term in contains:
                checks.append(EvalCheck(term=term, passed=False, score=0.0, method="embedding", note="Memory content is empty"))
            for term in excludes:
                checks.append(EvalCheck(term=term, passed=True, score=1.0, method="embedding", note="Memory content is empty"))
            return EvalResult(evaluator_id=self.id, passed=all(c.passed for c in checks), score=mean([c.score for c in checks] or [0.0]), checks=checks)

        for term in contains:
            max_sim = self._max_similarity(term, chunks)
            term_passed = max_sim >= threshold
            checks.append(
                EvalCheck(
                    term=term,
                    passed=term_passed,
                    score=max(0.0, min(1.0, max_sim)),
                    method="embedding",
                    note=f"max_similarity={max_sim:.3f} threshold>={threshold:.2f}",
                )
            )

        for term in excludes:
            max_sim = self._max_similarity(term, chunks)
            term_passed = max_sim < threshold
            checks.append(
                EvalCheck(
                    term=term,
                    passed=term_passed,
                    score=max(0.0, min(1.0, 1.0 - max_sim)),
                    method="embedding",
                    note=f"max_similarity={max_sim:.3f} threshold<{threshold:.2f}",
                )
            )

        return EvalResult(
            evaluator_id=self.id,
            passed=all(item.passed for item in checks),
            score=mean([item.score for item in checks] or [0.0]),
            checks=checks,
            details={"threshold": threshold, "chunks": len(chunks)},
        )

    @staticmethod
    def _chunk_text(text: str, chunk_size: int = 350) -> List[str]:
        cleaned = (text or "").strip()
        if not cleaned:
            return []
        return [cleaned[i : i + chunk_size] for i in range(0, len(cleaned), chunk_size)]

    @staticmethod
    def _cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
        denom = (np.linalg.norm(vec_a) * np.linalg.norm(vec_b))
        if denom == 0:
            return 0.0
        return float(np.dot(vec_a, vec_b) / denom)

    def _max_similarity(self, term: str, chunks: List[str]) -> float:
        texts = [term] + chunks
        vectors = get_embeddings(texts)
        if not vectors or len(vectors) < 2:
            return 0.0
        term_vec = np.array(vectors[0], dtype=float)
        max_score = 0.0
        for chunk_vec in vectors[1:]:
            score = self._cosine_similarity(term_vec, np.array(chunk_vec, dtype=float))
            if score > max_score:
                max_score = score
        return max_score
