"""
modules/semantic_calibrator/calibrator_engine.py
=================================================
Pure-Python calibration engine. No Streamlit. No shared/llm.py dependency.

Supports three embedder backends:
  - sentence_transformer  local, no API key
  - together              Together AI API (TOGETHER_API_KEY), OpenAI-compatible
  - openrouter            OpenRouter API (OPENROUTER_API_KEY), OpenAI-compatible

Five-level similarity labels
-----------------------------
  identical        Strictly the same text                  → score ~1.0
  strongly_related Direct paraphrase, same meaning         → score ~0.80–0.95
  related          Same topic, different angle             → score ~0.55–0.75
  weakly_related   Same broad domain, distinct content     → score ~0.30–0.50
  unrelated        Genuinely different subjects            → score ~0.05–0.25

The calibrator derives TWO similarity thresholds per model:
  recommended_similarity_threshold  separates (identical+strongly_related) from rest
                                    → use for response validation, strict assertions
  weak_similarity_threshold         separates (identical+strongly_related+related) from rest
                                    → use for RAG retrieval candidates

Public API
----------
  run_calibration(benchmark, model_configs, chunk_window, chunk_step, progress_cb)
      → dict  (calibration_results structure, JSON-serializable)

  load_benchmark(source)
      → dict

  list_available_models(config)
      → list[dict]

  check_api_key_available(model_cfg)
      → (bool, str)
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
from huggingface_hub import snapshot_download, model_info

# ---------------------------------------------------------------------------
# Label taxonomy
# ---------------------------------------------------------------------------

VALID_LABELS = ["identical", "strongly_related", "related", "weakly_related", "unrelated"]
STRONG_POSITIVE_LABELS = {"identical", "strongly_related"}
WEAK_POSITIVE_LABELS = {"identical", "strongly_related", "related"}
NEGATIVE_LABELS = {"unrelated"}
AMBIGUOUS_LABELS = {"weakly_related"}


# ---------------------------------------------------------------------------
# Default model registry
# ---------------------------------------------------------------------------

DEFAULT_MODELS: List[Dict] = [
    {
        "key": "all-MiniLM-L6-v2",
        "type": "sentence_transformer",
        "description": "Rapide, léger. Anglais. 384 dims.",
        "language_strength": "en",
    },
    {
        "key": "paraphrase-multilingual-mpnet-base-v2",
        "type": "sentence_transformer",
        "description": "Multilingue haute qualité. 768 dims.",
        "language_strength": "multilingual",
    },
    {
        "key": "BAAI/bge-m3",
        "type": "sentence_transformer",
        "description": "Multilingue 100+ langues. 1024 dims.",
        "language_strength": "multilingual",
    },
    {
        "key": "qwen/qwen3-embedding-8b",
        "type": "openrouter",
        "api_model_id": "qwen/qwen3-embedding-8b",
        "description": "Qwen3 8B via OpenRouter. Multilingue. ~$0.01/M tokens.",
        "language_strength": "multilingual",
        "requires_api_key": "OPENROUTER_API_KEY",
    },
    {
        "key": "mistralai/mistral-embed-2312",
        "type": "openrouter",
        "api_model_id": "mistralai/mistral-embed-2312",
        "description": "Mistral Embed via OpenRouter. Bon pour le français.",
        "language_strength": "multilingual",
        "requires_api_key": "OPENROUTER_API_KEY",
    },
    {
        "key": "BAAI/bge-large-en-v1.5",
        "type": "together",
        "api_model_id": "BAAI/bge-large-en-v1.5",
        "description": "BGE Large via Together AI. Anglais. 1024 dims.",
        "language_strength": "en",
        "requires_api_key": "TOGETHER_API_KEY",
    },
]

def get_model_info(model_key: str) -> dict:
    """
    Get information about a Sentence-Transformers model including:
    - Download status (if already cached locally)
    - Model size (if available)
    - Total parameters
    """
    info = {
        "downloaded": False,
        "size_mb": None,
        "size_readable": None,
        "parameters": None,
        "error": None
    }

    try:
        # Check if model is in HuggingFace cache
        cache_dir = os.path.expanduser("~/.cache/huggingface/hub")
        if os.path.exists(cache_dir):
            # Look for model in cache
            model_name_safe = model_key.replace("/", "--")
            for item in os.listdir(cache_dir):
                if model_name_safe in item and "models--" in item:
                    model_path = os.path.join(cache_dir, item, "snapshots")
                    if os.path.exists(model_path):
                        # Model is downloaded, calculate size
                        total_size = 0
                        for root, dirs, files in os.walk(model_path):
                            total_size += sum(os.path.getsize(os.path.join(root, f)) for f in files)

                        info["downloaded"] = True
                        info["size_mb"] = round(total_size / (1024 * 1024), 2)

                        # Format size
                        if info["size_mb"] > 1024:
                            info["size_readable"] = f"{info['size_mb'] / 1024:.2f} GB"
                        else:
                            info["size_readable"] = f"{info['size_mb']:.1f} MB"
                        break

        # Get model info from HuggingFace Hub (for size/parameters)
        try:
            hf_info = model_info(model_key)

            # Try to get model size from various sources
            if hasattr(hf_info, 'siblings'):
                # Calculate total size from all files
                total_size = sum(s.size for s in hf_info.siblings if s.size)
                if total_size:
                    info["hf_size_mb"] = round(total_size / (1024 * 1024), 2)
                    if info["hf_size_mb"] > 1024:
                        info["hf_size_readable"] = f"{info['hf_size_mb'] / 1024:.2f} GB"
                    else:
                        info["hf_size_readable"] = f"{info['hf_size_mb']:.1f} MB"

            # Try to get parameter count
            if hasattr(hf_info, 'cardData'):
                if 'parameters' in hf_info.cardData:
                    params = hf_info.cardData['parameters']
                    if isinstance(params, (int, float)):
                        info["parameters"] = params
                    elif isinstance(params, str):
                        # Parse string like "109M", "1.2B"
                        if params.endswith('B'):
                            info["parameters"] = float(params[:-1]) * 1e9
                        elif params.endswith('M'):
                            info["parameters"] = float(params[:-1]) * 1e6
                        else:
                            try:
                                info["parameters"] = float(params)
                            except ValueError:
                                pass
        except Exception as e:
            info["error"] = f"Could not fetch model info from Hub: {e}"

    except Exception as e:
        info["error"] = str(e)

    return info

# ---------------------------------------------------------------------------
# Embedders
# ---------------------------------------------------------------------------

class _SentenceTransformerEmbedder:
    def __init__(self, model_name: str, progress_cb: Optional[Callable] = None):
        if progress_cb:
            progress_cb(f"Chargement de {model_name}…")
        log("info", f"[calibrator] Chargement SentenceTransformer: {model_name}")
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
        log("info", f"[calibrator] {model_name} chargé en {elapsed:.1f}s sur {device}")
        if progress_cb:
            progress_cb(f"✓ {model_name} prêt ({elapsed:.1f}s, device={device})")

    def embed_batch(self, texts: List[str]) -> np.ndarray:
        return self._model.encode(texts, convert_to_numpy=True, show_progress_bar=False)


class _OpenAICompatibleEmbedder:
    """
    Generic embedder for any OpenAI-compatible embeddings API.
    Handles both Together AI and OpenRouter — same protocol, different base_url.
    """

    def __init__(
        self,
        model_name: str,
        api_key: str,
        base_url: str,
        provider_label: str,
        progress_cb: Optional[Callable] = None,
    ):
        if progress_cb:
            progress_cb(f"Connexion à {provider_label}: {model_name}…")
        log("info", f"[calibrator] Connexion {provider_label}: {model_name}")
        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError(
                "Le package 'openai' est requis pour les APIs distantes. "
                "Installe-le avec: pip install openai"
            ) from e
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self.model_name = model_name
        self.provider_label = provider_label
        if progress_cb:
            progress_cb(f"✓ {provider_label} prêt: {model_name}")

    def embed_batch(self, texts: List[str]) -> np.ndarray:
        # Chunk into batches of 50 to stay within provider limits
        CHUNK_SIZE = 50
        all_vectors = []
        for i in range(0, len(texts), CHUNK_SIZE):
            batch = texts[i: i + CHUNK_SIZE]
            response = self._client.embeddings.create(
                model=self.model_name,
                input=batch,
            )
            for item in response.data:
                all_vectors.append(item.embedding)
        return np.array(all_vectors, dtype=np.float32)


def _load_embedder(model_cfg: dict, progress_cb: Optional[Callable] = None):
    """Instantiate the correct embedder for a given model config dict."""
    model_type = model_cfg.get("type", "sentence_transformer")
    model_key = model_cfg["key"]
    api_model_id = model_cfg.get("api_model_id", model_key)

    if model_type == "sentence_transformer":
        return _SentenceTransformerEmbedder(model_key, progress_cb)

    elif model_type == "together":
        env_var = model_cfg.get("requires_api_key", "TOGETHER_API_KEY")
        api_key = os.getenv(env_var)
        if not api_key:
            raise RuntimeError(f"Variable {env_var} non définie.")
        return _OpenAICompatibleEmbedder(
            model_name=api_model_id,
            api_key=api_key,
            base_url="https://api.together.xyz/v1",
            provider_label="Together AI",
            progress_cb=progress_cb,
        )

    elif model_type == "openrouter":
        env_var = model_cfg.get("requires_api_key", "OPENROUTER_API_KEY")
        api_key = os.getenv(env_var)
        if not api_key:
            raise RuntimeError(f"Variable {env_var} non définie.")
        return _OpenAICompatibleEmbedder(
            model_name=api_model_id,
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            provider_label="OpenRouter",
            progress_cb=progress_cb,
        )

    else:
        raise ValueError(f"Type de modèle inconnu: {model_type!r}")


# ---------------------------------------------------------------------------
# Cosine similarity
# ---------------------------------------------------------------------------

def _cosine(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    na, nb = float(np.linalg.norm(vec_a)), float(np.linalg.norm(vec_b))
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / (na * nb))


# ---------------------------------------------------------------------------
# Text chunker
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
# Score dataclasses
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


# ---------------------------------------------------------------------------
# Score computation
# ---------------------------------------------------------------------------

def _run_similarity_pairs(
    embedder,
    pairs: List[dict],
    progress_cb: Optional[Callable] = None,
) -> List[SimilarityScore]:
    texts = list({p["text_a"] for p in pairs} | {p["text_b"] for p in pairs})
    if progress_cb:
        progress_cb(f"Embedding {len(texts)} textes (similarité)…")

    vecs = embedder.embed_batch(texts)
    vec_map: Dict[str, np.ndarray] = {t: v for t, v in zip(texts, vecs)}

    results = []
    for pair in pairs:
        label = pair.get("label", "related")
        if label not in VALID_LABELS:
            log("warning", f"[calibrator] Label inconnu '{label}' → traité comme 'related'")
            label = "related"
        score = _cosine(
            np.asarray(vec_map[pair["text_a"]], dtype=np.float32),
            np.asarray(vec_map[pair["text_b"]], dtype=np.float32),
        )
        results.append(SimilarityScore(
            pair_id=pair["id"],
            label=label,
            category=pair.get("category", "unknown"),
            language=pair.get("language", "?"),
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
        progress_cb(f"Embedding {len(text_list)} textes (containment)…")

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
            category=case.get("category", "unknown"),
            language=case.get("language", "?"),
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
    """Maximise F1. Returns (threshold, f1, accuracy)."""
    if not positive_scores or not negative_scores:
        return 0.5, 0.0, 0.0

    all_scores = sorted(set(positive_scores + negative_scores))
    candidates = [0.0]
    for i in range(len(all_scores) - 1):
        candidates.append((all_scores[i] + all_scores[i + 1]) / 2)
    candidates.append(1.0)
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
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
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
    """Compute all derived metrics. Returns a JSON-serializable dict."""

    # Strong threshold: (identical + strongly_related) vs unrelated
    strong_pos = [s.score for s in sim_scores if s.label in STRONG_POSITIVE_LABELS]
    strong_neg = [s.score for s in sim_scores if s.label in NEGATIVE_LABELS]
    strong_thresh, strong_f1, strong_acc = _find_optimal_threshold(strong_pos, strong_neg)

    # Weak threshold: (identical + strongly_related + related) vs unrelated
    weak_pos = [s.score for s in sim_scores if s.label in WEAK_POSITIVE_LABELS]
    weak_neg = [s.score for s in sim_scores if s.label in NEGATIVE_LABELS]
    weak_thresh, weak_f1, weak_acc = _find_optimal_threshold(weak_pos, weak_neg)

    # Separability using all positives vs negatives
    all_pos = [s.score for s in sim_scores if s.label in WEAK_POSITIVE_LABELS]
    all_neg = [s.score for s in sim_scores if s.label in NEGATIVE_LABELS]
    sim_sep = round(
        float(np.mean(all_pos) - np.mean(all_neg)) if all_pos and all_neg else 0.0, 4
    )

    # Per-label score distributions
    label_distributions: Dict[str, dict] = {}
    for label in VALID_LABELS:
        scores = [s.score for s in sim_scores if s.label == label]
        if scores:
            label_distributions[label] = {
                "count": len(scores),
                "mean": round(float(np.mean(scores)), 4),
                "min": round(float(min(scores)), 4),
                "max": round(float(max(scores)), 4),
                "std": round(float(np.std(scores)), 4),
            }

    # Containment threshold
    present = [s.best_score for s in cont_scores if s.expected]
    absent = [s.best_score for s in cont_scores if not s.expected]
    cont_thresh, cont_f1, cont_acc = _find_optimal_threshold(present, absent)
    cont_sep = round(
        float(np.mean(present) - np.mean(absent)) if present and absent else 0.0, 4
    )

    # Per-category breakdown
    category_report: Dict[str, dict] = {}

    for cat, items in _group_by(sim_scores, "category").items():
        strong_p = [s.score for s in items if s.label in STRONG_POSITIVE_LABELS]
        weak_p = [s.score for s in items if s.label in WEAK_POSITIVE_LABELS]
        neg = [s.score for s in items if s.label in NEGATIVE_LABELS]
        ambig = [s.score for s in items if s.label in AMBIGUOUS_LABELS]
        category_report[f"sim/{cat}"] = {
            "n_strong_positive": len(strong_p),
            "n_weak_positive": len(weak_p),
            "n_negative": len(neg),
            "n_ambiguous": len(ambig),
            "mean_strong_positive": round(float(np.mean(strong_p)), 4) if strong_p else None,
            "mean_weak_positive": round(float(np.mean(weak_p)), 4) if weak_p else None,
            "mean_negative": round(float(np.mean(neg)), 4) if neg else None,
            "mean_ambiguous": round(float(np.mean(ambig)), 4) if ambig else None,
            "min_strong_positive": round(float(min(strong_p)), 4) if strong_p else None,
            "max_negative": round(float(max(neg)), 4) if neg else None,
        }

    for cat, items in _group_by(cont_scores, "category").items():
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
        # Primary thresholds for strict validation (response checking)
        "recommended_similarity_threshold": strong_thresh,
        # Threshold for loose matching (RAG retrieval)
        "weak_similarity_threshold": weak_thresh,
        # Containment threshold
        "recommended_containment_threshold": cont_thresh,
        # Quality metrics
        "strong_similarity_f1": strong_f1,
        "strong_similarity_accuracy": strong_acc,
        "weak_similarity_f1": weak_f1,
        "weak_similarity_accuracy": weak_acc,
        "containment_f1": cont_f1,
        "containment_accuracy": cont_acc,
        # Separability (diagnostic — higher = better)
        "similarity_separability": sim_sep,
        "containment_separability": cont_sep,
        # Score distributions per label (for visual inspection in UI)
        "label_distributions": label_distributions,
        # Per-category detail
        "category_report": category_report,
    }


def _group_by(items, attr: str) -> Dict[str, list]:
    """Group a list of dataclass instances by a field value."""
    result: Dict[str, list] = {}
    for item in items:
        key = getattr(item, attr, "unknown")
        result.setdefault(key, []).append(item)
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_benchmark(source) -> dict:
    """Parse benchmark YAML from a file path or raw YAML string/bytes."""
    import yaml
    if isinstance(source, bytes):
        source = source.decode("utf-8")
    if isinstance(source, str) and '\n' not in source.strip() and len(source.strip()) < 512:
        try:
            with open(source) as f:
                return yaml.safe_load(f)
        except (OSError, TypeError):
            pass
    return yaml.safe_load(source)


def list_available_models(config: Optional[dict] = None) -> List[dict]:
    """Return model descriptors from config or defaults."""
    if config:
        configured = config.get("semantic_calibrator", {}).get("available_models")
        if configured:
            return configured
    return None


def check_api_key_available(model_cfg: dict) -> Tuple[bool, str]:
    """Returns (key_present: bool, env_var_name: str)."""
    env_var = model_cfg.get("requires_api_key")
    if not env_var:
        return True, ""
    return bool(os.getenv(env_var)), env_var


def run_calibration(
    benchmark: dict,
    model_configs: List[dict],
    chunk_window: int = 3,
    chunk_step: int = 1,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> dict:
    """
    Run calibration for all requested models.
    Returns a JSON-serializable dict consumed by the test suite and Streamlit UI.
    """
    def _cb(msg: str):
        log("info", f"[calibrator] {msg}")
        if progress_cb:
            progress_cb(msg)

    sim_pairs = benchmark.get("similarity_pairs", [])
    cont_cases = benchmark.get("containment_cases", [])

    # Validate and report labels
    unknown_labels = {p.get("label") for p in sim_pairs if p.get("label") not in VALID_LABELS}
    if unknown_labels:
        _cb(f"⚠ Labels inconnus : {unknown_labels}. Valides : {VALID_LABELS}")
    label_counts: Dict[str, int] = {}
    for p in sim_pairs:
        lbl = p.get("label", "?")
        label_counts[lbl] = label_counts.get(lbl, 0) + 1
    _cb(f"Benchmark : {len(sim_pairs)} paires {label_counts}, {len(cont_cases)} cas de containment")

    model_results: Dict[str, dict] = {}

    for model_cfg in model_configs:
        model_key = model_cfg["key"]
        model_type = model_cfg.get("type", "sentence_transformer")
        _cb(f"═══ {model_key} ({model_type}) ═══")

        key_ok, env_var = check_api_key_available(model_cfg)
        if not key_ok:
            _cb(f"⏭ Ignoré : {env_var} non défini")
            model_results[model_key] = {
                "model_key": model_key, "model_type": model_type,
                "timestamp": datetime.now().isoformat(),
                "error": f"API key manquante : {env_var}", "skipped": True,
            }
            continue

        try:
            embedder = _load_embedder(model_cfg, progress_cb=_cb)
        except Exception as exc:
            _cb(f"✗ Chargement échoué : {exc}")
            model_results[model_key] = {
                "model_key": model_key, "model_type": model_type,
                "timestamp": datetime.now().isoformat(),
                "error": str(exc), "skipped": True,
            }
            continue

        try:
            sim_scores = _run_similarity_pairs(embedder, sim_pairs, _cb)
            cont_scores = _run_containment_cases(embedder, cont_cases, chunk_window, chunk_step, _cb)
            derived = _derive_thresholds(sim_scores, cont_scores)

            model_results[model_key] = {
                "model_key": model_key, "model_type": model_type,
                "timestamp": datetime.now().isoformat(),
                "skipped": False, "error": None,
                **derived,
                "similarity_scores": [asdict(s) for s in sim_scores],
                "containment_scores": [asdict(s) for s in cont_scores],
            }
            _cb(
                f"✓ strong_thresh={derived['recommended_similarity_threshold']:.3f} "
                f"(F1={derived['strong_similarity_f1']:.2f}) | "
                f"weak_thresh={derived['weak_similarity_threshold']:.3f} "
                f"(F1={derived['weak_similarity_f1']:.2f}) | "
                f"cont_thresh={derived['recommended_containment_threshold']:.3f} "
                f"(acc={derived['containment_accuracy']:.0%})"
            )

        except Exception as exc:
            log("error", f"[calibrator] Erreur : {exc}", stacktrace=True)
            _cb(f"✗ Erreur calibration : {exc}")
            model_results[model_key] = {
                "model_key": model_key, "model_type": model_type,
                "timestamp": datetime.now().isoformat(),
                "error": str(exc), "skipped": True,
            }

    return {
        "generated_at": datetime.now().isoformat(),
        "chunk_window": chunk_window,
        "chunk_step": chunk_step,
        "valid_labels": VALID_LABELS,
        "models": model_results,
    }
