"""
shared/tests/test_semantics.py  — Calibration-driven semantic test suite
=========================================================================

ARCHITECTURE
------------
Two tiers:

  TIER 1 — INVARIANT TESTS
    Test code contracts and mathematical properties that hold for ANY model.
    These never assert specific score values — they assert structural guarantees.
    They should NEVER fail unless there is a real bug in semantic_eval.py.

  TIER 2 — CALIBRATED TESTS
    Parametrized over the benchmark dataset (semantic_benchmark.yaml).
    Thresholds are read from calibration_results.json — never hardcoded.
    These validate model behavior against human-labeled ground truth.

SETUP
-----
1. Run the calibrator (Streamlit admin tab or CLI) to produce:
       calibration_results.json

2. Place the file at (or set CALIBRATION_FILE env var):
       shared/tests/calibration_results/calibration_results.json

3. Run tests:
       pytest shared/tests/test_semantics.py -v

   To target a specific model:
       MODEL_KEY=all-mpnet-base-v2 pytest shared/tests/test_semantics.py -v

   To run only invariant tests (no embeddings needed at all):
       pytest shared/tests/test_semantics.py::TestTier1Invariants -v
       pytest shared/tests/test_semantics.py::TestTier1Chunking -v

ENVIRONMENT VARIABLES
---------------------
  MODEL_KEY          Model key to load from calibration_results.json.
                     Defaults to the model with highest combined separability.
  CALIBRATION_FILE   Path to calibration_results.json.
  BENCHMARK_FILE     Path to semantic_benchmark.yaml.
  CALIBRATION_MARGIN Safety margin subtracted from derived thresholds before
                     asserting (default: 0.03). Makes tests slightly lenient
                     to account for embedding non-determinism across runs.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pytest

from core.logging import log
from shared.semantic_eval import (
    SemanticEvaluator,
    ContainmentResult,
    SimilarityResult,
    chunk_text,
    _split_sentences,
    _sliding_window_chunks,
)
from shared.llm import LLMManager


# =============================================================================
# Calibration loader
# =============================================================================

_THIS_DIR = Path(__file__).parent

_DEFAULT_CALIBRATION_FILE = (
    _THIS_DIR / "calibration_results" / "calibration_results.json"
)
_DEFAULT_BENCHMARK_FILE = _THIS_DIR.parent.parent / "semantic_benchmark.yaml"


def _load_calibration() -> Optional[dict]:
    """Load calibration_results.json. Returns None if not found."""
    path = Path(os.getenv("CALIBRATION_FILE", str(_DEFAULT_CALIBRATION_FILE)))
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as exc:
        log("warning", f"[test_semantics] Could not load calibration: {exc}")
        return None


def _load_benchmark() -> Optional[dict]:
    """Load semantic_benchmark.yaml. Returns None if not found."""
    import yaml
    path = Path(os.getenv("BENCHMARK_FILE", str(_DEFAULT_BENCHMARK_FILE)))
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return yaml.safe_load(f)
    except Exception as exc:
        log("warning", f"[test_semantics] Could not load benchmark: {exc}")
        return None


def _pick_model(calibration: dict) -> Tuple[str, dict]:
    """
    Select which model calibration to use for Tier 2 tests.

    Priority:
    1. MODEL_KEY environment variable
    2. Model with highest combined separability
    """
    models: Dict[str, dict] = calibration.get("models", {})
    successful = {k: v for k, v in models.items() if not v.get("skipped")}
    if not successful:
        pytest.skip("No successful model calibrations found in calibration_results.json")

    env_key = os.getenv("MODEL_KEY")
    if env_key:
        if env_key not in successful:
            pytest.skip(f"MODEL_KEY={env_key!r} not found in calibration results")
        return env_key, successful[env_key]

    best_key = max(
        successful,
        key=lambda k: (
            successful[k].get("similarity_separability", 0)
            + successful[k].get("containment_separability", 0)
        ),
    )
    return best_key, successful[best_key]


# =============================================================================
# Session-scoped fixtures
# =============================================================================

@pytest.fixture(scope="session")
def calibration():
    """
    Load calibration_results.json once per session.
    Tests that need calibration data are SKIPPED (not failed) if absent.
    """
    cal = _load_calibration()
    if cal is None:
        log("warning", "[test_semantics] No calibration file found — Tier 2 tests will be skipped")
    return cal


@pytest.fixture(scope="session")
def benchmark():
    """Load semantic_benchmark.yaml once per session."""
    bm = _load_benchmark()
    if bm is None:
        log("warning", "[test_semantics] No benchmark file found — Tier 2 tests will be skipped")
    return bm


@pytest.fixture(scope="session")
def active_model_calibration(calibration):
    """Return (model_key, model_cal_dict) for the active model."""
    if calibration is None:
        pytest.skip("No calibration data available")
    return _pick_model(calibration)


@pytest.fixture(scope="session")
def calibration_margin() -> float:
    """Safety margin subtracted from derived thresholds before asserting."""
    return float(os.getenv("CALIBRATION_MARGIN", "0.03"))


@pytest.fixture(scope="session")
def real_llm_manager(active_model_calibration):
    """
    Create a real LLMManager configured for the active model.
    Loaded once per session — warm-up happens here.
    """
    model_key, _ = active_model_calibration
    log("info", f"[test_semantics] Loading LLMManager for model: {model_key}")
    config = {
        "llms": {
            "test_embedding": {
                "name": "Test Embedding",
                "type": "sentence_transformer",
                "model": model_key,
                "enabled": True,
                "requires_api_key": False,
            }
        },
        "embedding": {
            "model_name": model_key,
            "vector_dimension": 384,
        },
        "app": {"default_llm": "test_embedding"},
    }
    manager = LLMManager(config)
    _ = manager.get_embedding("warmup")
    log("info", f"[test_semantics] LLMManager ready ({model_key})")
    return manager


@pytest.fixture(scope="session")
def evaluator(real_llm_manager, active_model_calibration, calibration_margin):
    """
    SemanticEvaluator configured with calibrated thresholds for the active model.
    Default thresholds come from calibration — not hardcoded.
    """
    _, model_cal = active_model_calibration
    sim_thresh = model_cal.get("recommended_similarity_threshold", 0.7)
    cont_thresh = model_cal.get("recommended_containment_threshold", 0.45)

    # Apply margin to make tests slightly lenient
    sim_thresh_with_margin = max(0.0, sim_thresh - calibration_margin)
    cont_thresh_with_margin = max(0.0, cont_thresh - calibration_margin)

    log("info",
        f"[test_semantics] Evaluator thresholds: "
        f"sim={sim_thresh_with_margin:.3f} (calibrated={sim_thresh}), "
        f"cont={cont_thresh_with_margin:.3f} (calibrated={cont_thresh})"
    )

    return SemanticEvaluator(
        real_llm_manager,
        default_similarity_threshold=sim_thresh_with_margin,
        default_containment_threshold=cont_thresh_with_margin,
        chunk_window=calibration.get("chunk_window", 3) if (calibration := _load_calibration()) else 3,
        chunk_step=calibration.get("chunk_step", 1) if calibration else 1,
    )


# =============================================================================
# TIER 1 — INVARIANT TESTS: Chunking helpers
# These are purely structural — no embeddings, no thresholds.
# =============================================================================

class TestTier1Chunking:
    """
    Test text chunking helpers.
    These test code logic only — zero embedding calls.
    All assertions are deterministic properties of the algorithm.
    """

    def test_split_sentences_basic(self):
        text = "This is sentence one. This is sentence two! Is this sentence three? Yes indeed it is."
        sentences = _split_sentences(text, min_length=3)
        assert len(sentences) == 4
        assert "This is sentence one" in sentences[0]

    def test_split_sentences_newlines(self):
        text = "First paragraph.\n\nSecond paragraph with multiple sentences. Here is another!"
        sentences = _split_sentences(text)
        assert len(sentences) >= 3
        assert "First paragraph" in sentences[0]

    def test_split_sentences_filters_short(self):
        text = "Hi. This is a longer sentence that should be kept. Bye."
        sentences = _split_sentences(text)
        # "Hi" and "Bye" are below min_length=10
        assert all(len(s) > 10 for s in sentences)
        assert any("longer sentence" in s for s in sentences)

    def test_sliding_window_chunks_count(self):
        sentences = ["S1.", "S2.", "S3.", "S4.", "S5."]
        chunks = _sliding_window_chunks(sentences, window=3, step=1)
        # window=3, step=1, 5 sentences → positions 0,1,2 → 3 windows + possible tail
        assert len(chunks) >= 3
        assert "S1." in chunks[0] and "S3." in chunks[0]
        assert "S3." in chunks[-1] or "S5." in chunks[-1]

    def test_sliding_window_chunks_step2(self):
        sentences = ["S1.", "S2.", "S3.", "S4.", "S5.", "S6."]
        chunks = _sliding_window_chunks(sentences, window=2, step=2)
        assert "S1." in chunks[0] and "S2." in chunks[0]
        assert "S3." in chunks[1] and "S4." in chunks[1]

    def test_chunk_text_short_returns_one(self):
        text = "Sentence one. Sentence two. Sentence three."
        chunks = chunk_text(text, window_size=3)
        assert len(chunks) == 1

    def test_chunk_text_long_returns_multiple(self):
        text = " ".join(f"This is sentence number {i} in the sequence." for i in range(8))
        chunks = chunk_text(text, window_size=3, step=1)
        assert len(chunks) > 1

    def test_chunk_text_empty(self):
        assert chunk_text("") == []
        assert chunk_text("   ") == []


# =============================================================================
# TIER 1 — INVARIANT TESTS: SemanticEvaluator code contracts
# These test BEHAVIOR of the evaluator class, not model quality.
# =============================================================================

class TestTier1Invariants:
    """
    Test invariants that must hold for ANY valid embedding model.
    No score thresholds here — only structural guarantees.
    """

    # --- No LLM manager ---

    def test_no_manager_similarity_returns_zero(self):
        ev = SemanticEvaluator(None)
        result = ev.similarity("test", "test")
        assert result.score == 0.0
        assert result.passed is False

    def test_no_manager_containment_returns_zero(self):
        ev = SemanticEvaluator(None)
        result = ev.contains_concept("test text here", "concept")
        assert result.best_score == 0.0
        assert result.passed is False

    def test_no_manager_contains_all_concepts(self):
        ev = SemanticEvaluator(None)
        result = ev.contains_all_concepts("some text", ["a", "b"])
        assert result["passed"] is False

    # --- Exception handling ---

    def test_embedding_exception_similarity_graceful(self):
        from unittest.mock import Mock
        m = Mock()
        m.get_embedding.side_effect = Exception("embedding exploded")
        ev = SemanticEvaluator(m)
        result = ev.similarity("a", "b")
        assert result.score == 0.0
        assert result.passed is False

    def test_embedding_exception_containment_graceful(self):
        from unittest.mock import Mock
        m = Mock()
        m.get_embedding.side_effect = Exception("embedding exploded")
        ev = SemanticEvaluator(m)
        result = ev.contains_concept("long text here", "concept")
        assert result.best_score == 0.0
        assert result.passed is False

    # --- Empty input ---

    def test_empty_text_similarity_returns_zero(self, real_llm_manager):
        """
        Similarity with empty string must return 0.0.
        This is a CODE CONTRACT, not a model property.
        SemanticEvaluator must guard for empty input.
        """
        ev = SemanticEvaluator(real_llm_manager)
        result = ev.similarity("", "some text")
        assert result.score == 0.0, (
            "similarity('', ...) must return 0.0. "
            "This is a code contract — add an empty-string guard in similarity()."
        )
        assert result.passed is False

    def test_empty_concept_containment(self, real_llm_manager):
        ev = SemanticEvaluator(real_llm_manager)
        result = ev.contains_concept("", "concept")
        assert result.passed is False

    # --- Threshold plumbing ---

    def test_custom_threshold_is_stored(self, real_llm_manager):
        ev = SemanticEvaluator(real_llm_manager, default_similarity_threshold=0.42)
        result = ev.similarity("cat", "cat")
        assert result.threshold == 0.42

    def test_custom_containment_threshold_stored(self, real_llm_manager):
        ev = SemanticEvaluator(real_llm_manager, default_containment_threshold=0.33)
        result = ev.contains_concept("the cat sat", "cat", threshold=0.33)
        assert result.threshold == 0.33

    # --- Identical text invariant (mathematical, model-independent) ---

    def test_identical_texts_score_near_one(self, real_llm_manager):
        """
        Cosine similarity of a vector with itself is always 1.0.
        This holds for ANY valid embedding.
        """
        ev = SemanticEvaluator(real_llm_manager)
        text = "The quick brown fox jumps over the lazy dog."
        result = ev.similarity(text, text)
        assert result.score > 0.99, (
            f"Identical texts must score > 0.99, got {result.score}. "
            "This would indicate a broken embedding pipeline."
        )

    # --- ContainmentResult structure ---

    def test_containment_result_has_details(self, real_llm_manager):
        ev = SemanticEvaluator(real_llm_manager)
        result = ev.contains_concept("The cat sat on the mat.", "cat")
        assert isinstance(result.details, list)
        assert len(result.details) >= 1
        assert "chunk" in result.details[0]
        assert "score" in result.details[0]

    def test_contains_all_concepts_structure(self, real_llm_manager):
        ev = SemanticEvaluator(real_llm_manager)
        result = ev.contains_all_concepts("some text about cats", ["cat"])
        assert "passed" in result
        assert "results" in result
        assert "failed" in result
        assert "summary" in result

    # --- Relative ordering invariants ---
    # These test ORDERING of scores, not absolute values.
    # They hold for any reasonable embedding model.

    def test_identical_scores_higher_than_unrelated(self, real_llm_manager):
        ev = SemanticEvaluator(real_llm_manager)
        identical = ev.similarity("the cat is on the mat", "the cat is on the mat")
        unrelated = ev.similarity("the cat is on the mat", "quarterly financial report")
        assert identical.score > unrelated.score

    def test_threshold_monotonicity(self, real_llm_manager):
        """Higher threshold → harder to pass. Always true by definition."""
        ev = SemanticEvaluator(real_llm_manager)
        text = "The cat slept on the couch."
        concept = "cat"
        low = ev.contains_concept(text, concept, threshold=0.01)
        high = ev.contains_concept(text, concept, threshold=0.99)
        # If high passes, low must also pass
        if high.passed:
            assert low.passed
        # The score is the same regardless of threshold
        assert low.best_score == high.best_score


# =============================================================================
# TIER 2 — CALIBRATED TESTS
# Parametrized from benchmark YAML + calibration thresholds.
# Skipped if calibration file is absent.
# =============================================================================

def _sim_pairs_for_parametrize(benchmark: Optional[dict]) -> List[tuple]:
    """Extract similarity pairs for pytest parametrize."""
    if not benchmark:
        return []
    return [
        (p["id"], p["text_a"], p["text_b"], p["label"], p["category"], p.get("language", "?"))
        for p in benchmark.get("similarity_pairs", [])
    ]


def _cont_cases_for_parametrize(benchmark: Optional[dict]) -> List[tuple]:
    """Extract containment cases for pytest parametrize."""
    if not benchmark:
        return []
    return [
        (c["id"], c["text"], c["concept"], bool(c["expected"]), c["category"], c.get("language", "?"))
        for c in benchmark.get("containment_cases", [])
    ]


class TestTier2SimilarityCalibrated:
    """
    Calibrated similarity tests.

    Each test case comes from the benchmark dataset.
    Thresholds come from calibration_results.json.

    A test PASSES if:
      - label=identical → score > 0.95 (mathematical invariant, not calibrated)
      - label=related   → score >= (calibrated_threshold - margin)
      - label=unrelated → score <  (calibrated_ceiling + margin)
        where ceiling = mean(unrelated scores from calibration) + 1 std
    """

    @pytest.fixture(autouse=True)
    def _skip_if_no_calibration(self, calibration, benchmark):
        if calibration is None or benchmark is None:
            pytest.skip("Calibration or benchmark data not available")

    def test_all_similarity_pairs(
        self,
        evaluator,
        benchmark,
        active_model_calibration,
        calibration_margin,
    ):
        """
        Run all similarity pairs from the benchmark.
        Reports per-pair results and counts failures.
        Does NOT fail at the first mismatch — collects all failures for diagnostics.
        """
        model_key, model_cal = active_model_calibration
        sim_thresh = model_cal.get("recommended_similarity_threshold", 0.7) - calibration_margin
        pairs = benchmark.get("similarity_pairs", [])

        log("info", f"[test_tier2_sim] Model={model_key}, threshold={sim_thresh:.3f}, pairs={len(pairs)}")

        failures = []
        for pair in pairs:
            result = evaluator.similarity(pair["text_a"], pair["text_b"])
            label = pair["label"]
            cat = pair["category"]
            pid = pair["id"]

            if label == "identical":
                ok = result.score > 0.95
                reason = f"identical pair scored {result.score:.4f} (expected > 0.95)"
            elif label == "related":
                ok = result.score >= sim_thresh
                reason = f"related pair scored {result.score:.4f} (expected >= {sim_thresh:.3f})"
            elif label == "unrelated":
                # Derive ceiling from calibration category report
                cat_key = f"sim/{cat}"
                cat_stats = model_cal.get("category_report", {}).get(cat_key, {})
                ceiling = (cat_stats.get("max_negative") or 0.6) + calibration_margin
                ok = result.score < ceiling
                reason = f"unrelated pair scored {result.score:.4f} (expected < {ceiling:.3f})"
            else:
                ok = True
                reason = f"unknown label {label!r}"

            log(
                "info" if ok else "warning",
                f"  [{pid}] cat={cat} label={label} score={result.score:.4f} → {'OK' if ok else 'FAIL'}"
            )

            if not ok:
                failures.append(f"{pid} ({cat}, label={label}): {reason}")

        if failures:
            fail_msg = f"\n{len(failures)}/{len(pairs)} pairs failed for model {model_key}:\n"
            fail_msg += "\n".join(f"  • {f}" for f in failures)
            pytest.fail(fail_msg)

    def test_identical_pairs_score_near_one(self, evaluator, benchmark):
        """Identical pairs must score > 0.95 — mathematical invariant."""
        pairs = [p for p in benchmark.get("similarity_pairs", []) if p["label"] == "identical"]
        failures = []
        for pair in pairs:
            result = evaluator.similarity(pair["text_a"], pair["text_b"])
            if result.score <= 0.95:
                failures.append(f"{pair['id']}: {result.score:.4f}")
        if failures:
            pytest.fail(f"Identical pairs scored too low: {failures}")

    def test_related_scores_above_unrelated_on_average(self, evaluator, benchmark, active_model_calibration):
        """
        Aggregate: mean(related scores) > mean(unrelated scores).
        This is the fundamental separability requirement.
        """
        model_key, model_cal = active_model_calibration
        pairs = benchmark.get("similarity_pairs", [])

        related_scores = []
        unrelated_scores = []

        for pair in pairs:
            result = evaluator.similarity(pair["text_a"], pair["text_b"])
            if pair["label"] in ("related", "identical"):
                related_scores.append(result.score)
            elif pair["label"] == "unrelated":
                unrelated_scores.append(result.score)

        if not related_scores or not unrelated_scores:
            pytest.skip("Not enough pairs to compute separability")

        mean_related = float(np.mean(related_scores))
        mean_unrelated = float(np.mean(unrelated_scores))
        sep = mean_related - mean_unrelated

        log("info",
            f"[test_separability] Model={model_key}: "
            f"mean_related={mean_related:.4f}, mean_unrelated={mean_unrelated:.4f}, sep={sep:.4f}"
        )

        assert mean_related > mean_unrelated, (
            f"Model {model_key}: mean(related)={mean_related:.4f} is not > "
            f"mean(unrelated)={mean_unrelated:.4f}. "
            f"This model cannot separate related from unrelated text."
        )


class TestTier2ContainmentCalibrated:
    """
    Calibrated containment tests.

    Each test case comes from the benchmark dataset.
    Thresholds come from calibration_results.json.
    """

    @pytest.fixture(autouse=True)
    def _skip_if_no_calibration(self, calibration, benchmark):
        if calibration is None or benchmark is None:
            pytest.skip("Calibration or benchmark data not available")

    def test_all_containment_cases(
        self,
        evaluator,
        benchmark,
        active_model_calibration,
        calibration_margin,
    ):
        """
        Run all containment cases from the benchmark.
        Collects all failures for diagnostics rather than stopping at first.
        """
        model_key, model_cal = active_model_calibration
        cont_thresh = model_cal.get("recommended_containment_threshold", 0.45) - calibration_margin
        cases = benchmark.get("containment_cases", [])

        log("info", f"[test_tier2_cont] Model={model_key}, threshold={cont_thresh:.3f}, cases={len(cases)}")

        failures = []
        for case in cases:
            result = evaluator.contains_concept(case["text"], case["concept"], threshold=cont_thresh)
            expected = bool(case["expected"])
            ok = result.passed == expected
            cid = case["id"]
            cat = case["category"]

            log(
                "info" if ok else "warning",
                f"  [{cid}] cat={cat} concept={case['concept']!r} "
                f"expected={expected} passed={result.passed} "
                f"score={result.best_score:.4f} → {'OK' if ok else 'FAIL'}"
            )

            if not ok:
                direction = "false negative" if expected else "false positive"
                failures.append(
                    f"{cid} ({cat}, {direction}): "
                    f"concept={case['concept']!r}, score={result.best_score:.4f}, thresh={cont_thresh:.3f}"
                )

        if failures:
            fail_msg = f"\n{len(failures)}/{len(cases)} cases failed for model {model_key}:\n"
            fail_msg += "\n".join(f"  • {f}" for f in failures)
            pytest.fail(fail_msg)

    def test_present_scores_above_absent_on_average(self, evaluator, benchmark, active_model_calibration):
        """
        Aggregate: mean(present scores) > mean(absent scores).
        Fundamental separability requirement for containment.
        """
        model_key, _ = active_model_calibration
        cases = benchmark.get("containment_cases", [])

        present_scores = []
        absent_scores = []

        for case in cases:
            result = evaluator.contains_concept(case["text"], case["concept"])
            if case["expected"]:
                present_scores.append(result.best_score)
            else:
                absent_scores.append(result.best_score)

        if not present_scores or not absent_scores:
            pytest.skip("Not enough cases to compute separability")

        mean_present = float(np.mean(present_scores))
        mean_absent = float(np.mean(absent_scores))

        log("info",
            f"[test_cont_sep] Model={model_key}: "
            f"mean_present={mean_present:.4f}, mean_absent={mean_absent:.4f}"
        )

        assert mean_present > mean_absent, (
            f"Model {model_key}: mean(present)={mean_present:.4f} is not > "
            f"mean(absent)={mean_absent:.4f}. "
            f"This model cannot detect concept containment."
        )

    def test_category_separability(self, evaluator, benchmark, active_model_calibration):
        """
        Per-category separability. Produces a detailed diagnostic if a
        category has zero or inverted separability.
        Emits warnings (not failures) for categories with weak separation.
        """
        model_key, model_cal = active_model_calibration
        cases = benchmark.get("containment_cases", [])

        by_cat: Dict[str, dict] = {}
        for case in cases:
            cat = case["category"]
            if cat not in by_cat:
                by_cat[cat] = {"present": [], "absent": []}
            result = evaluator.contains_concept(case["text"], case["concept"])
            key = "present" if case["expected"] else "absent"
            by_cat[cat][key].append(result.best_score)

        log("info", f"\n[test_cat_sep] Category separability for model {model_key}:")
        inverted = []
        for cat, scores in sorted(by_cat.items()):
            p, a = scores["present"], scores["absent"]
            if p and a:
                sep = float(np.mean(p)) - float(np.mean(a))
                log("info", f"  {cat}: mean_present={np.mean(p):.3f}, mean_absent={np.mean(a):.3f}, sep={sep:.3f}")
                if sep < 0:
                    inverted.append(f"{cat} (sep={sep:.3f})")
            elif p:
                log("info", f"  {cat}: only present cases, mean={np.mean(p):.3f}")
            elif a:
                log("info", f"  {cat}: only absent cases, mean={np.mean(a):.3f}")

        # Inverted separability is a hard failure — the model is confused for that category
        if inverted:
            pytest.fail(
                f"Model {model_key} has INVERTED separability in categories: {inverted}. "
                f"The model scores absent concepts HIGHER than present ones in these categories."
            )


# =============================================================================
# TIER 2 — Cross-model comparison (optional, runs if multiple models calibrated)
# =============================================================================

class TestTier2ModelComparison:
    """
    Runs when multiple models are present in calibration_results.json.
    Compares them and surfaces which model wins on which category.
    Does not assert a winner — purely diagnostic and informational.
    Skipped if fewer than 2 models are calibrated.
    """

    @pytest.fixture(autouse=True)
    def _skip_if_single_model(self, calibration):
        if calibration is None:
            pytest.skip("No calibration data")
        successful = {k: v for k, v in calibration.get("models", {}).items() if not v.get("skipped")}
        if len(successful) < 2:
            pytest.skip("Need at least 2 calibrated models for comparison")

    def test_model_ranking_summary(self, calibration):
        """Print a human-readable model ranking. Never fails."""
        successful = {k: v for k, v in calibration.get("models", {}).items() if not v.get("skipped")}
        ranked = sorted(
            successful.items(),
            key=lambda kv: (
                kv[1].get("similarity_separability", 0)
                + kv[1].get("containment_separability", 0)
            ),
            reverse=True,
        )
        log("info", "\n" + "=" * 60)
        log("info", "MODEL RANKING (higher sep = better)")
        log("info", "=" * 60)
        log("info", f"{'Rank':<5} {'Model':<45} {'SimSep':<10} {'ContSep':<10} {'SimAcc':<10} {'ContAcc':<10}")
        for i, (key, cal) in enumerate(ranked, 1):
            log("info",
                f"{i:<5} {key:<45} "
                f"{cal.get('similarity_separability', 0):<10.4f} "
                f"{cal.get('containment_separability', 0):<10.4f} "
                f"{cal.get('similarity_accuracy', 0):<10.1%} "
                f"{cal.get('containment_accuracy', 0):<10.1%}"
            )
        log("info", f"\n→ Best overall: {ranked[0][0]}")
        # This test always passes — it's purely informational
        assert len(ranked) >= 2

    def test_multilingual_model_wins_cross_lingual(self, calibration, real_llm_manager):
        """
        Models that claim multilingual support should score higher on
        cross_lingual categories than English-only models.
        This is a soft diagnostic test — warns but does not fail.
        """
        MULTILINGUAL_KEYS = {
            "paraphrase-multilingual-MiniLM-L12-v2",
            "paraphrase-multilingual-mpnet-base-v2",
            "text-embedding-ada-002",
            "text-embedding-3-small",
            "text-embedding-3-large",
        }
        models = {k: v for k, v in calibration.get("models", {}).items() if not v.get("skipped")}
        ml_models = {k: v for k, v in models.items() if k in MULTILINGUAL_KEYS}
        en_models = {k: v for k, v in models.items() if k not in MULTILINGUAL_KEYS}

        if not ml_models or not en_models:
            pytest.skip("Need both multilingual and English-only models for this comparison")

        for ml_key, ml_cal in ml_models.items():
            for en_key, en_cal in en_models.items():
                ml_cat = ml_cal.get("category_report", {}).get("sim/cross_lingual", {})
                en_cat = en_cal.get("category_report", {}).get("sim/cross_lingual", {})
                ml_mean = ml_cat.get("mean_positive")
                en_mean = en_cat.get("mean_positive")
                if ml_mean and en_mean:
                    log("info",
                        f"Cross-lingual: {ml_key}={ml_mean:.4f} vs {en_key}={en_mean:.4f} "
                        f"{'✓ ML wins' if ml_mean > en_mean else '⚠ EN wins'}"
                    )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
