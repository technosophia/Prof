"""
shared/semantic_eval.py
=======================
Semantic evaluation service for comparing and searching text semantically.

Registered in the ServiceLocator as "semantic_eval".

Two distinct problems are solved here:

1. SIMILARITY  — "How close is text A to text B overall?"
   → Full-document cosine similarity.  Good for response-vs-reference,
     memory-vs-expected, etc.

2. CONCEPT CONTAINMENT — "Does this text *contain* concept X somewhere?"
   → Chunked search with max-pooling.  Avoids semantic dilution in long
     responses.  A single high-scoring chunk is enough to pass.

Usage
-----
# At app startup (st_shared/cached.py or wherever services are wired):
    from shared.semantic_eval import SemanticEvaluator
    services.register("semantic_eval", SemanticEvaluator(llm_manager))

# In assertion handlers / scorer plugins:
    evaluator = services.get("semantic_eval")

    # Problem 1 — overall similarity
    score = evaluator.similarity(text_a, text_b)          # float 0-1

    # Problem 2 — concept containment
    result = evaluator.contains_concept(text, "évolutionnaire")
    result.passed          # bool
    result.best_score      # float — score of the best matching chunk
    result.best_chunk      # str  — the chunk that matched
    result.details         # list[dict] — per-chunk scores (for debugging)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from core.logging import log


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ContainmentResult:
    """Result of a concept-containment check."""
    passed: bool
    best_score: float
    best_chunk: str
    concept: str
    threshold: float
    details: List[dict] = field(default_factory=list)

    @property
    def summary(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return (
            f"[{status}] concept='{self.concept}' "
            f"best_score={self.best_score:.3f} threshold={self.threshold} "
            f"chunk='{self.best_chunk[:80]}...'"
        )


@dataclass
class SimilarityResult:
    """Result of a full-document similarity check."""
    score: float
    passed: bool
    threshold: float

    @property
    def summary(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] similarity={self.score:.4f} threshold={self.threshold}"


# ---------------------------------------------------------------------------
# Chunking helpers
# ---------------------------------------------------------------------------

def _split_sentences(text: str) -> List[str]:
    """Split text into sentences using punctuation heuristics."""
    # Split on . ! ? followed by whitespace or end-of-string
    raw = re.split(r'(?<=[.!?])\s+', text.strip())
    # Also split on newlines that look like paragraph breaks
    sentences: List[str] = []
    for part in raw:
        sub = [s.strip() for s in part.split('\n') if s.strip()]
        sentences.extend(sub)
    return [s for s in sentences if len(s) > 10]  # drop trivially short


def _sliding_window_chunks(
    sentences: List[str],
    window: int = 3,
    step: int = 1,
) -> List[str]:
    """Combine sentences into overlapping windows."""
    if not sentences:
        return []
    if len(sentences) <= window:
        return [" ".join(sentences)]
    chunks = []
    for i in range(0, len(sentences) - window + 1, step):
        chunk = " ".join(sentences[i : i + window])
        chunks.append(chunk)
    # Always include a tail chunk so the last sentences aren't orphaned
    tail = " ".join(sentences[-(window):])
    if tail not in chunks:
        chunks.append(tail)
    return chunks


def chunk_text(
    text: str,
    window_size: int = 3,
    step: int = 1,
) -> List[str]:
    """
    Adaptive chunker.

    Short texts (≤ 3 sentences) → return as-is (single chunk).
    Longer texts → sliding window over sentences.

    The window_size controls how many consecutive sentences form one chunk.
    Overlapping windows (step < window_size) ensure no concept falls
    entirely between chunk boundaries.
    """
    sentences = _split_sentences(text)
    if not sentences:
        return [text] if text.strip() else []
    if len(sentences) <= window_size:
        return [" ".join(sentences)]
    return _sliding_window_chunks(sentences, window=window_size, step=step)


# ---------------------------------------------------------------------------
# Core service
# ---------------------------------------------------------------------------

class SemanticEvaluator:
    """
    Semantic evaluation service.

    Parameters
    ----------
    llm_manager:
        The application LLMManager instance (provides get_embedding()).
        Can be None for testing — all methods will raise RuntimeError.
    default_similarity_threshold:
        Default cosine threshold for similarity() pass/fail.
    default_containment_threshold:
        Default cosine threshold for contains_concept() pass/fail.
    chunk_window:
        Number of sentences per chunk for concept-containment search.
    chunk_step:
        Sliding step between chunks (< window → overlap).
    """

    def __init__(
        self,
        llm_manager,
        default_similarity_threshold: float = 0.70,
        default_containment_threshold: float = 0.45,
        chunk_window: int = 3,
        chunk_step: int = 1,
    ):
        self._llm_manager = llm_manager
        self.default_similarity_threshold = default_similarity_threshold
        self.default_containment_threshold = default_containment_threshold
        self.chunk_window = chunk_window
        self.chunk_step = chunk_step

    # ------------------------------------------------------------------
    # Public API — Problem 1: Similarity
    # ------------------------------------------------------------------

    def similarity(
        self,
        text_a: str,
        text_b: str,
        threshold: Optional[float] = None,
    ) -> SimilarityResult:
        """
        Compute cosine similarity between two full texts.

        Good for: response-vs-expected, memory-vs-expected.
        NOT good for: checking if a concept appears somewhere in a long text
                      (use contains_concept() instead).
        """
        if threshold is None:
            threshold = self.default_similarity_threshold

        try:
            import numpy as np
            vec_a = np.asarray(self._embed(text_a), dtype=np.float32)
            vec_b = np.asarray(self._embed(text_b), dtype=np.float32)
            score = float(self._cosine(vec_a, vec_b))
            return SimilarityResult(
                score=round(score, 4),
                passed=score >= threshold,
                threshold=threshold,
            )
        except Exception as exc:
            log("error", f"SemanticEvaluator.similarity failed: {exc}", exc_info=True)
            return SimilarityResult(score=0.0, passed=False, threshold=threshold)

    # ------------------------------------------------------------------
    # Public API — Problem 2: Concept containment
    # ------------------------------------------------------------------

    def contains_concept(
        self,
        text: str,
        concept: str,
        threshold: Optional[float] = None,
        window_size: Optional[int] = None,
        step: Optional[int] = None,
    ) -> ContainmentResult:
        """
        Check whether *any part* of `text` is semantically close to `concept`.

        Strategy
        --------
        1. Chunk the text into overlapping sentence windows.
        2. Embed each chunk and the concept query.
        3. Take the MAX similarity across all chunks (max-pooling).
        4. Pass if max_score >= threshold.

        This avoids semantic dilution: a concept buried in a long response
        will score well on its own chunk even if the overall document
        embedding is diluted by other topics.
        """
        if threshold is None:
            threshold = self.default_containment_threshold
        if window_size is None:
            window_size = self.chunk_window
        if step is None:
            step = self.chunk_step

        try:
            import numpy as np

            chunks = chunk_text(text, window_size=window_size, step=step)
            if not chunks:
                return ContainmentResult(
                    passed=False,
                    best_score=0.0,
                    best_chunk="",
                    concept=concept,
                    threshold=threshold,
                    details=[{"error": "no chunks produced"}],
                )

            vec_concept = np.asarray(self._embed(concept), dtype=np.float32)
            norm_concept = float(np.linalg.norm(vec_concept))
            if norm_concept == 0:
                return ContainmentResult(
                    passed=False,
                    best_score=0.0,
                    best_chunk="",
                    concept=concept,
                    threshold=threshold,
                    details=[{"error": "concept embedding is zero vector"}],
                )

            details = []
            best_score = -1.0
            best_chunk = ""

            for chunk in chunks:
                vec_chunk = np.asarray(self._embed(chunk), dtype=np.float32)
                score = float(self._cosine(vec_chunk, vec_concept))
                details.append({"chunk": chunk[:120], "score": round(score, 4)})
                if score > best_score:
                    best_score = score
                    best_chunk = chunk

            # Sort details descending by score for easier debugging
            details.sort(key=lambda d: d.get("score", 0), reverse=True)

            return ContainmentResult(
                passed=best_score >= threshold,
                best_score=round(best_score, 4),
                best_chunk=best_chunk,
                concept=concept,
                threshold=threshold,
                details=details,
            )

        except Exception as exc:
            log("error", f"SemanticEvaluator.contains_concept failed: {exc}", exc_info=True)
            return ContainmentResult(
                passed=False,
                best_score=0.0,
                best_chunk="",
                concept=concept,
                threshold=threshold,
                details=[{"error": str(exc)}],
            )

    def contains_all_concepts(
        self,
        text: str,
        concepts: Sequence[str],
        threshold: Optional[float] = None,
        window_size: Optional[int] = None,
        step: Optional[int] = None,
    ) -> dict:
        """
        Check that ALL concepts are contained in the text (AND semantics).

        Returns a dict with:
          passed       bool   — True only if every concept passes
          results      dict   — concept → ContainmentResult
          failed       list   — concepts that did not pass
          summary      str    — human-readable summary
        """
        results = {}
        failed = []
        for concept in concepts:
            r = self.contains_concept(text, concept, threshold, window_size, step)
            results[concept] = r
            if not r.passed:
                failed.append(concept)

        passed = len(failed) == 0
        lines = [r.summary for r in results.values()]
        summary = ("ALL concepts found" if passed else f"Missing: {failed}") + "\n" + "\n".join(lines)

        return {
            "passed": passed,
            "results": results,
            "failed": failed,
            "summary": summary,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _embed(self, text: str) -> list:
        """Get embedding via the injected LLM manager."""
        if self._llm_manager is None:
            raise RuntimeError("SemanticEvaluator has no LLM manager — cannot embed")
        return self._llm_manager.get_embedding(text)

    @staticmethod
    def _cosine(vec_a, vec_b) -> float:
        import numpy as np
        norm_a = float(np.linalg.norm(vec_a))
        norm_b = float(np.linalg.norm(vec_b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(vec_a, vec_b) / (norm_a * norm_b))
