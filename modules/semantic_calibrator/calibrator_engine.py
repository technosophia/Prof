"""
modules/semantic_calibrator/calibrator_engine.py
=================================================
Pure-Python calibration engine. No Streamlit. No shared/llm.py dependency.

This module is intentionally self-contained so it can be:
  - Called from the Streamlit admin UI
  - Called from a CLI script
  - Imported in tests

It loads embedding models directly (sentence-transformers or OpenAI),
runs them against a benchmark dataset, and derives optimal thresholds
via F1-maximizing threshold search.

Public API
----------
  run_calibration(benchmark, model_keys, chunk_window, chunk_step, progress_cb)
      → dict  (the calibration_results structure, JSON-serializable)

  load_benchmark(yaml_path_or_content)
      → dict  (parsed benchmark)

  list_available_models(config)
      → list[dict]
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from core.logging import log


# ---------------------------------------------------------------------------
# Model descriptors (mirrors config.json — merged at runtime)
# ---------------------------------------------------------------------------

DEFAULT_MODELS: List[Dict] = [
    {
        "key": "all-MiniLM-L6-v2",
        "type": "sentence_transformer",
        "description": "Fast, lightweight. English-biased. 384 dims.",
    },
    {
        "key": "all-mpnet-base-v2",
        "type": "sentence_transformer",
        "description": "Higher quality than MiniLM. English. 768 dims.",
    },
    {
        "key": "paraphrase-multilingual-MiniLM-L12-v2",
        "type": "sentence_transformer",
        "description": "Multilingual (50+ languages). 384 dims.",
    },
    {
        "key": "paraphrase-multilingual-mpnet-base-v2",
        "type": "sentence_transformer",
        "description": "Multilingual, higher quality. 768 dims.",
    },
    {
        "key": "text-embedding-ada-002",
        "type": "openai",
        "description": "OpenAI Ada-002. 1536 dims. Requires OPENAI_API_KEY.",
    },
    {
        "key": "text-embedding-3-small",
        "type": "openai",
        "description": "OpenAI v3 small. Requires OPENAI_API_KEY.",
    },
    {
        "key": "text-embedding-3-large",
        "type": "openai",
        "description": "OpenAI v3 large. 3072 dims. Requires OPENAI_API_KEY.",
    },
]


# ---------------------------------------------------------------------------
# Embedders
# ---------------------------------------------------------------------------

class _SentenceTransformerEmbedder:
    """Wraps a sentence-transformers model."""

    def __init__(self, model_name: str, progress_cb: Optional[Callable] = None):
        if progress_cb:
            progress_cb(f"Loading {model_name}…")
        log("info", f"[calibrator] Loading SentenceTransformer: {model_name}")
        t0 = time.time()
        from sentence_transformers import SentenceTransformer
        import torch
        device = (
            "cuda" if torch.cuda.is_available()
            else "mps" if torch.backends.mps.is_available()
            else "cpu"
        )
        self._model = SentenceTransformer(model_name, device=device)
        self.model_name = model_name
        elapsed = time.time() - t0
        log("info", f"[calibrator] Loaded {model_name} in {elapsed:.1f}s on {device}")
        if progress_cb:
            progress_cb(f"Loaded {model_name} ({elapsed:.1f}s, device={device})")

    def embed_batch(self, texts: List[str]) -> np.ndarray:
        return self._model.encode(texts, convert_to_numpy=True, show_progress_bar=False)


class _OpenAIEmbedder:
    """Wraps an OpenAI embeddings model."""

    def __init__(self, model_name: str, progress_cb: Optional[Callable] = None):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY environment variable is not set.")
        if progress_cb:
            progress_cb(f"Connecting to OpenAI: {model_name}…")
        import openai
        self._client = openai.OpenAI(api_key=api_key)
        self.model_name = model_name
        log("info", f"[calibrator] OpenAI embedder ready: {model_name}")

    def embed_batch(self, texts: List[str]) -> np.ndarray:
        response = self._client.embeddings.create(model=self.model_name, input=texts)
        vectors = [item.embedding for item in response.data]
        return np.array(vectors, dtype=np.float32)


def _load_embedder(model_key: str, model_type: str, progress_cb: Optional[Callable] = None):
    """Instantiate the correct embedder for a given model."""
    if model_type == "sentence_transformer":
        return _SentenceTransformerEmbedder(model_key, progress_cb)
    elif model_type == "openai":
        return _OpenAIEmbedder(model_key, progress_cb)
    else:
        raise ValueError(f"Unknown model type: {model_type!r}")


# ---------------------------------------------------------------------------
# Cosine similarity
# ---------------------------------------------------------------------------

def _cosine(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    na, nb = float(np.linalg.norm(vec_a)), float(np.linalg.norm(vec_b))
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / (na * nb))


# ---------------------------------------------------------------------------
# Text chunker (mirrors shared/semantic_eval.py — kept in sync manually)
# ---------------------------------------------------------------------------

def _split_sentences(text: str, min_length: int = 10) -> List[str]:
    raw = re.split(r'(?<=[.!?])\s+', text.strip())
    sentences: List[str] = []
    for part in raw:
        sub = [s.strip() for s in part.split('\n') if s.strip()]
        sentences.extend(sub)
    return [s for s in sentences if len(s) > min_length]


def _sliding_window_chunks(sentences: List[str], window: int, step: int) -> List[str]:
    if not sentences:
        return []
    if len(sentences) <= window:
        return [" ".join(sentences)]
    chunks = []
    for i in range(0, len(sentences) - window + 1, step):
        chunks.append(" ".join(sentences[i: i + window]))
    tail = " ".join(sentences[-window:])
    if tail not in chunks:
        chunks.append(tail)
    return chunks


def _chunk_text(text: str, window_size: int = 3, step: int = 1) -> List[str]:
    sentences = _split_sentences(text)
    if not sentences:
        return [text] if text.strip() else []
    if len(sentences) <= window_size:
        return [" ".join(sentences)]
    return _sliding_window_chunks(sentences, window=window_size, step=step)


# ---------------------------------------------------------------------------
# Score computation
# ---------------------------------------------------------------------------

@dataclass
class SimilarityScore:
    pair_id: str
    label: str
    category: str
    language: str
    score: float


@dataclass
class ContainmentScore:
    case_id: str
    expected: bool
    category: str
    language: str
    best_score: float
    best_chunk: str


def _run_similarity_pairs(
    embedder,
    pairs: List[dict],
    progress_cb: Optional[Callable] = None,
) -> List[SimilarityScore]:
    """Batch-embed all texts and compute cosine scores."""
    # Collect unique texts
    texts = list({p["text_a"] for p in pairs} | {p["text_b"] for p in pairs})
    if progress_cb:
        progress_cb(f"Embedding {len(texts)} unique texts (similarity)…")
    log("info", f"[calibrator] Embedding {len(texts)} texts for similarity")

    vecs = embedder.embed_batch(texts)
    vec_map: Dict[str, np.ndarray] = {t: v for t, v in zip(texts, vecs)}

    results = []
    for pair in pairs:
        score = _cosine(
            np.asarray(vec_map[pair["text_a"]], dtype=np.float32),
            np.asarray(vec_map[pair["text_b"]], dtype=np.float32),
        )
        results.append(SimilarityScore(
            pair_id=pair["id"],
            label=pair["label"],
            category=pair["category"],
            language=pair["language"],
            score=round(score, 4),
        ))
    return results


def _run_containment_cases(
    embedder,
    cases: List[dict],
    window_size: int,
    step: int,
    progress_cb: Optional[Callable] = None,
) -> List[ContainmentScore]:
    """Chunk texts, batch-embed everything, compute max-pool scores."""
    # Pre-chunk and collect unique texts
    case_chunks: List[List[str]] = []
    all_texts: set = set()
    for case in cases:
        chunks = _chunk_text(case["text"], window_size=window_size, step=step)
        if not chunks:
            chunks = [case["text"]]
        case_chunks.append(chunks)
        all_texts.update(chunks)
        all_texts.add(case["concept"])

    text_list = list(all_texts)
    if progress_cb:
        progress_cb(f"Embedding {len(text_list)} unique texts (containment)…")
    log("info", f"[calibrator] Embedding {len(text_list)} texts for containment")

    vecs = embedder.embed_batch(text_list)
    vec_map: Dict[str, np.ndarray] = {t: v for t, v in zip(text_list, vecs)}

    results = []
    for case, chunks in zip(cases, case_chunks):
        vec_concept = np.asarray(vec_map[case["concept"]], dtype=np.float32)
        best_score = -1.0
        best_chunk = ""
        for chunk in chunks:
            score = _cosine(np.asarray(vec_map[chunk], dtype=np.float32), vec_concept)
            if score > best_score:
                best_score = score
                best_chunk = chunk

        results.append(ContainmentScore(
            case_id=case["id"],
            expected=bool(case["expected"]),
            category=case["category"],
            language=case["language"],
            best_score=round(best_score, 4),
            best_chunk=best_chunk[:120],
        ))
    return results


# ---------------------------------------------------------------------------
# Threshold derivation
# ---------------------------------------------------------------------------

def _find_optimal_threshold(
    positive_scores: List[float],
    negative_scores: List[float],
) -> Tuple[float, float, float]:
    """
    Find threshold maximizing F1 on the positive/negative split.
    Returns (threshold, f1, accuracy).
    """
    if not positive_scores or not negative_scores:
        return 0.5, 0.0, 0.0

    # Candidate thresholds: midpoints between every consecutive unique score
    all_scores = sorted(set(positive_scores + negative_scores))
    candidates = [0.0]
    for i in range(len(all_scores) - 1):
        candidates.append((all_scores[i] + all_scores[i + 1]) / 2)
    candidates.append(1.0)
    # Add a coarse grid for edge cases
    candidates += [round(x * 0.05, 2) for x in range(21)]
    candidates = sorted(set(round(c, 4) for c in candidates))

    best_f1 = -1.0
    best_thresh = 0.5
    best_acc = 0.0

    for thresh in candidates:
        tp = sum(1 for s in positive_scores if s >= thresh)
        fp = sum(1 for s in negative_scores if s >= thresh)
        fn = sum(1 for s in positive_scores if s < thresh)
        tn = sum(1 for s in negative_scores if s < thresh)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)
              if (precision + recall) > 0 else 0.0)
        acc = (tp + tn) / (len(positive_scores) + len(negative_scores))

        if f1 > best_f1:
            best_f1 = f1
            best_thresh = thresh
            best_acc = acc

    return best_thresh, round(best_f1, 4), round(best_acc, 4)


def _derive_thresholds(
    sim_scores: List[SimilarityScore],
    cont_scores: List[ContainmentScore],
) -> dict:
    """Compute all derived metrics. Returns a flat dict."""
    # Similarity
    related = [s.score for s in sim_scores if s.label in ("related", "identical")]
    unrelated = [s.score for s in sim_scores if s.label == "unrelated"]
    sim_thresh, sim_f1, sim_acc = _find_optimal_threshold(related, unrelated)
    sim_sep = round(
        float(np.mean(related) - np.mean(unrelated))
        if related and unrelated else 0.0,
        4,
    )

    # Containment
    present = [s.best_score for s in cont_scores if s.expected]
    absent = [s.best_score for s in cont_scores if not s.expected]
    cont_thresh, cont_f1, cont_acc = _find_optimal_threshold(present, absent)
    cont_sep = round(
        float(np.mean(present) - np.mean(absent))
        if present and absent else 0.0,
        4,
    )

    # Per-category breakdown
    category_report: Dict[str, dict] = {}

    sim_by_cat: Dict[str, list] = {}
    for s in sim_scores:
        sim_by_cat.setdefault(s.category, []).append(s)
    for cat, items in sim_by_cat.items():
        pos = [s.score for s in items if s.label in ("related", "identical")]
        neg = [s.score for s in items if s.label == "unrelated"]
        category_report[f"sim/{cat}"] = {
            "n_positive": len(pos),
            "n_negative": len(neg),
            "mean_positive": round(float(np.mean(pos)), 4) if pos else None,
            "mean_negative": round(float(np.mean(neg)), 4) if neg else None,
            "min_positive": round(float(min(pos)), 4) if pos else None,
            "max_negative": round(float(max(neg)), 4) if neg else None,
        }

    cont_by_cat: Dict[str, list] = {}
    for s in cont_scores:
        cont_by_cat.setdefault(s.category, []).append(s)
    for cat, items in cont_by_cat.items():
        pos = [s.best_score for s in items if s.expected]
        neg = [s.best_score for s in items if not s.expected]
        category_report[f"cont/{cat}"] = {
            "n_positive": len(pos),
            "n_negative": len(neg),
            "mean_positive": round(float(np.mean(pos)), 4) if pos else None,
            "mean_negative": round(float(np.mean(neg)), 4) if neg else None,
            "min_positive": round(float(min(pos)), 4) if pos else None,
            "max_negative": round(float(max(neg)), 4) if neg else None,
        }

    return {
        "recommended_similarity_threshold": sim_thresh,
        "recommended_containment_threshold": cont_thresh,
        "similarity_f1": sim_f1,
        "containment_f1": cont_f1,
        "similarity_accuracy": sim_acc,
        "containment_accuracy": cont_acc,
        "similarity_separability": sim_sep,
        "containment_separability": cont_sep,
        "category_report": category_report,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_benchmark(source) -> dict:
    """
    Parse benchmark YAML from a file path (str/Path) or raw bytes/str content.
    Returns the parsed dict.
    """
    import yaml
    if isinstance(source, (str, bytes)) and (
        (isinstance(source, str) and source.strip().startswith("{"))
        or isinstance(source, bytes)
        or (isinstance(source, str) and len(source) < 512 and '\n' not in source)
    ):
        # Treat as a file path
        try:
            with open(source) as f:
                return yaml.safe_load(f)
        except (OSError, TypeError):
            pass
    # Treat as raw YAML content
    if isinstance(source, bytes):
        source = source.decode("utf-8")
    return yaml.safe_load(source)


def list_available_models(config: Optional[dict] = None) -> List[dict]:
    """
    Return the list of available model descriptors.
    If a module config dict is provided (from config.json), merge with defaults.
    """
    if config:
        configured = config.get("semantic_calibrator", {}).get("available_models")
        if configured:
            return configured
    return DEFAULT_MODELS


def run_calibration(
    benchmark: dict,
    model_configs: List[dict],
    chunk_window: int = 3,
    chunk_step: int = 1,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> dict:
    """
    Run calibration for all requested models.

    Parameters
    ----------
    benchmark:
        Parsed benchmark dict (from load_benchmark()).
    model_configs:
        List of model descriptors to run, each with at least "key" and "type".
    chunk_window, chunk_step:
        Chunking parameters for containment cases.
    progress_cb:
        Optional callable(message: str) for progress reporting to UI.

    Returns
    -------
    dict — JSON-serializable calibration_results structure.
    """
    def _cb(msg: str):
        log("info", f"[calibrator] {msg}")
        if progress_cb:
            progress_cb(msg)

    sim_pairs: List[dict] = benchmark.get("similarity_pairs", [])
    cont_cases: List[dict] = benchmark.get("containment_cases", [])
    _cb(f"Benchmark loaded: {len(sim_pairs)} similarity pairs, {len(cont_cases)} containment cases")

    model_results: Dict[str, dict] = {}

    for model_cfg in model_configs:
        model_key: str = model_cfg["key"]
        model_type: str = model_cfg.get("type", "sentence_transformer")
        _cb(f"═══ Starting model: {model_key} ═══")

        try:
            embedder = _load_embedder(model_key, model_type, progress_cb=_cb)
        except Exception as exc:
            _cb(f"SKIPPED {model_key}: {exc}")
            log("warning", f"[calibrator] Skipped {model_key}: {exc}")
            model_results[model_key] = {
                "model_key": model_key,
                "timestamp": datetime.now().isoformat(),
                "error": str(exc),
                "skipped": True,
            }
            continue

        try:
            _cb(f"Running similarity pairs for {model_key}…")
            sim_scores = _run_similarity_pairs(embedder, sim_pairs, _cb)

            _cb(f"Running containment cases for {model_key}…")
            cont_scores = _run_containment_cases(
                embedder, cont_cases, chunk_window, chunk_step, _cb
            )

            _cb(f"Deriving thresholds for {model_key}…")
            derived = _derive_thresholds(sim_scores, cont_scores)

            model_results[model_key] = {
                "model_key": model_key,
                "model_type": model_type,
                "timestamp": datetime.now().isoformat(),
                "skipped": False,
                "error": None,
                **derived,
                "similarity_scores": [asdict(s) for s in sim_scores],
                "containment_scores": [asdict(s) for s in cont_scores],
            }

            _cb(
                f"✓ {model_key} → "
                f"sim_thresh={derived['recommended_similarity_threshold']}, "
                f"cont_thresh={derived['recommended_containment_threshold']}, "
                f"sim_acc={derived['similarity_accuracy']:.1%}, "
                f"cont_acc={derived['containment_accuracy']:.1%}"
            )

        except Exception as exc:
            log("error", f"[calibrator] Error calibrating {model_key}: {exc}", exc_info=True)
            _cb(f"ERROR calibrating {model_key}: {exc}")
            model_results[model_key] = {
                "model_key": model_key,
                "timestamp": datetime.now().isoformat(),
                "error": str(exc),
                "skipped": True,
            }

    return {
        "generated_at": datetime.now().isoformat(),
        "chunk_window": chunk_window,
        "chunk_step": chunk_step,
        "models": model_results,
    }
