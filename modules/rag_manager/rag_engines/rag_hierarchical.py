"""
Hierarchical FAISS RAG Engine — unified, fully configurable.

Replaces both the original ``rag_hierarchical.py`` (flat search) and
``rag_hierarchical_v2.py`` (inverted sieve cascade) in a single file.
The behaviour is entirely driven by two orthogonal axes:

Axis 1 — chunk_strategy  (controls what is indexed)
  ``hierarchical``   Original v1 style: one chunk per ## section, embed-text
                     enriched with the chapter résumé and key concepts.
  ``multi_level``    v2 style: every document produces three granularity
                     levels — PARAGRAPH (fine slices), SECTION (one per ##),
                     and SUMMARY (one per >[!Résumé] block) — giving the
                     search stage a choice of granularity.

Axis 2 — search_mode  (controls how results are retrieved)
  ``flat``           Dense cosine search across all indexed chunks with a
                     hard similarity_threshold cutoff.  Optional per-level
                     score boosts and a summary_slots force-include.
                     Reproduces the original v1 retrieval exactly when
                     chunk_strategy=hierarchical.
  ``cascade``        Inverted sieve — BM25 → paragraph dense → section
                     dense → summary dense.  Each stage has its own
                     confidence gate; the first confident stage wins.
                     Requires chunk_strategy=multi_level.
  ``bm25_only``      Pure BM25 keyword retrieval.  Useful as a baseline or
                     for exact-wording factual queries.
  ``dense_only``     Dense cosine search on all chunks, no BM25, no cascade.
                     Confidence gate (dense_margin_ratio) applied; falls
                     back to flat threshold if no stage is confident.
  ``paragraph``      Dense search restricted to PARAGRAPH chunks only.
  ``section``        Dense search restricted to SECTION chunks only.
  ``summary``        Dense search restricted to SUMMARY chunks only.

ENGINE_TYPE = "faiss_hierarchical"   ← single type slug; instances are
                                        differentiated by engine_id in
                                        config.json.

All code in English.  No Streamlit dependency.  Config injected at
construction time.
"""

from __future__ import annotations

import math
import os
import re
import json
import pickle
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import faiss
import numpy as np

from ..rag_engine import RAGEngine
from shared.common import get_embedding, get_embeddings
from core.logging import log

# ---------------------------------------------------------------------------
# Chunk level constants  (also stored in each metadata entry)
# ---------------------------------------------------------------------------

LEVEL_PARAGRAPH = "paragraph"
LEVEL_SECTION   = "section"
LEVEL_SUMMARY   = "summary"

# ---------------------------------------------------------------------------
# Chunk strategy and search mode slugs
# ---------------------------------------------------------------------------

STRATEGY_HIERARCHICAL = "hierarchical"  # v1-style: one chunk per section
STRATEGY_MULTI_LEVEL  = "multi_level"   # v2-style: paragraph + section + summary

MODE_FLAT        = "flat"         # dense, hard threshold, optional boosts
MODE_CASCADE     = "cascade"      # BM25 → paragraph → section → summary
MODE_BM25_ONLY   = "bm25_only"    # pure BM25
MODE_DENSE_ONLY  = "dense_only"   # dense, confidence-gated, no cascade
MODE_PARAGRAPH   = "paragraph"    # dense, PARAGRAPH level only
MODE_SECTION     = "section"      # dense, SECTION level only
MODE_SUMMARY     = "summary"      # dense, SUMMARY level only

_LEVEL_MODES = {MODE_PARAGRAPH, MODE_SECTION, MODE_SUMMARY}


class FaissHierarchicalRAGEngine(RAGEngine):
    """
    Unified hierarchical FAISS RAG engine.

    Backward compatible with the original ``faiss_hierarchical`` engine
    (ENGINE_TYPE and default parameters are unchanged).  New features are
    opt-in via config keys.
    """

    ENGINE_TYPE = "faiss_hierarchical"

    def __init__(
        self,
        config:    Optional[Dict[str, Any]] = None,
        engine_id: Optional[str] = None,
    ):
        """
        Args:
            config:    Engine-specific config dict
                       (``rag_manager.engines.<engine_id>`` block).
            engine_id: Instance name (config key).  Falls back to ENGINE_TYPE
                       when absent — preserves backward compatibility.
        """
        super().__init__(engine_type=self.ENGINE_TYPE, engine_id=engine_id)
        self.description = "FAISS hierarchical RAG engine"

        cfg = config or {}

        # ----------------------------------------------------------------
        # Storage
        # ----------------------------------------------------------------
        self.index_path = Path(cfg.get("index_path", "./data/hierarchical_indexes"))
        self.index_path.mkdir(parents=True, exist_ok=True)

        # ----------------------------------------------------------------
        # Chunking
        # ----------------------------------------------------------------
        self.chunk_strategy: str = cfg.get("chunk_strategy", STRATEGY_HIERARCHICAL)
        self.paragraph_size:    int = int(cfg.get("paragraph_size",    300))
        self.paragraph_overlap: int = int(cfg.get("paragraph_overlap",  50))

        # ----------------------------------------------------------------
        # Search
        # ----------------------------------------------------------------
        self.search_mode: str = cfg.get("search_mode", MODE_FLAT)

        # flat / dense_only / per-level modes: hard threshold
        self.similarity_threshold: float = float(cfg.get("similarity_threshold", 0.5))

        # flat mode extras
        raw_boost = cfg.get("level_boost", {})
        self.level_boost: Dict[str, float] = {
            LEVEL_SUMMARY:   float(raw_boost.get("summary",   1.0)),
            LEVEL_SECTION:   float(raw_boost.get("section",   1.0)),
            LEVEL_PARAGRAPH: float(raw_boost.get("paragraph", 1.0)),
        }
        self.summary_slots: int = int(cfg.get("summary_slots", 0))

        # cascade / dense_only confidence parameters
        self.bm25_dominance_ratio: float = float(cfg.get("bm25_dominance_ratio", 2.0))
        self.bm25_min_score:       float = float(cfg.get("bm25_min_score",       1.0))
        self.dense_margin_ratio:   float = float(cfg.get("dense_margin_ratio",   1.3))
        self.dense_min_score:      float = float(cfg.get("dense_min_score",      0.30))
        self.floor_threshold:      float = float(cfg.get("floor_threshold",      0.15))
        self.top_k_for_margin:     int   = int(cfg.get("top_k_for_margin",       5))

        # ----------------------------------------------------------------
        # Embedding
        # ----------------------------------------------------------------
        self.model_name: str = cfg.get("model_name", "all-MiniLM-L6-v2")

        log(
            "debug",
            f"FaissHierarchical [{self.engine_id}] "
            f"strategy={self.chunk_strategy} mode={self.search_mode} "
            f"threshold={self.similarity_threshold} model={self.model_name}",
        )

        try:
            self.dimension: Optional[int] = len(get_embedding(""))
            log("info",
                f"FaissHierarchical [{self.engine_id}]: "
                f"embeddings ready (dim={self.dimension}, model={self.model_name})")
        except Exception as e:
            log("error", f"FaissHierarchical [{self.engine_id}]: embedding init failed — {e}")
            self.dimension = None

        self.indices:      Dict[str, faiss.IndexFlatIP]    = {}
        self.metadata:     Dict[str, List[Dict[str, Any]]] = {}
        self.bm25_indices: Dict[str, _BM25Index]           = {}

        self._load_indices()

    # ====================================================================
    # RAGEngine — config introspection API
    # ====================================================================

    def get_config(self) -> Dict[str, Any]:
        return {
            "index_path":           str(self.index_path),
            "chunk_strategy":       self.chunk_strategy,
            "paragraph_size":       self.paragraph_size,
            "paragraph_overlap":    self.paragraph_overlap,
            "search_mode":          self.search_mode,
            "similarity_threshold": self.similarity_threshold,
            "level_boost":          dict(self.level_boost),
            "summary_slots":        self.summary_slots,
            "bm25_dominance_ratio": self.bm25_dominance_ratio,
            "bm25_min_score":       self.bm25_min_score,
            "dense_margin_ratio":   self.dense_margin_ratio,
            "dense_min_score":      self.dense_min_score,
            "floor_threshold":      self.floor_threshold,
            "top_k_for_margin":     self.top_k_for_margin,
            "model_name":           self.model_name,
        }

    def update_config(self, overrides: Dict[str, Any]) -> None:
        """
        Apply runtime config overrides.
        ``index_path``, ``chunk_strategy``, and ``model_name`` are excluded —
        changing them at runtime would silently invalidate loaded indices.
        """
        _float_keys = {
            "similarity_threshold", "bm25_dominance_ratio", "bm25_min_score",
            "dense_margin_ratio", "dense_min_score", "floor_threshold",
        }
        _int_keys = {"paragraph_size", "paragraph_overlap", "summary_slots", "top_k_for_margin"}
        _str_keys = {"search_mode"}

        for key, val in overrides.items():
            if key in _float_keys:
                setattr(self, key, float(val))
            elif key in _int_keys:
                setattr(self, key, int(val))
            elif key in _str_keys:
                setattr(self, key, str(val))
            elif key == "level_boost" and isinstance(val, dict):
                for lv in (LEVEL_SUMMARY, LEVEL_SECTION, LEVEL_PARAGRAPH):
                    if lv in val:
                        self.level_boost[lv] = float(val[lv])
            # index_path / chunk_strategy / model_name intentionally excluded

        log("debug", f"FaissHierarchical [{self.engine_id}]: config updated — {list(overrides)}")

    # ====================================================================
    # Persistence
    # ====================================================================

    def _index_prefix(self, user_id: str) -> str:
        return f"{user_id}_faiss_hier"

    def _load_indices(self) -> None:
        for index_file in self.index_path.glob("*_faiss_hier.index"):
            user_id = index_file.stem.replace("_faiss_hier", "")
            model_meta_file = self.index_path / f"{self._index_prefix(user_id)}_model_meta.json"

            if model_meta_file.exists():
                try:
                    with open(model_meta_file) as f:
                        model_meta = json.load(f)
                    if model_meta.get("dimension") != self.dimension:
                        log(
                            "warning",
                            f"FaissHierarchical [{self.engine_id}]: skipping index for "
                            f"{user_id} — dimension mismatch "
                            f"(stored={model_meta.get('dimension')}, "
                            f"current={self.dimension})",
                        )
                        continue
                except Exception as e:
                    log("error", f"FaissHierarchical [{self.engine_id}]: "
                                 f"failed to read model meta for {user_id}: {e}")
                    continue

            try:
                index = faiss.read_index(str(index_file))
                if index.d != self.dimension:
                    log("warning",
                        f"FaissHierarchical [{self.engine_id}]: "
                        f"skipping {user_id} — index dim {index.d} != {self.dimension}")
                    continue

                self.indices[user_id] = index

                meta_file = self.index_path / f"{self._index_prefix(user_id)}_meta.pkl"
                if meta_file.exists():
                    with open(meta_file, "rb") as f:
                        self.metadata[user_id] = pickle.load(f)

                bm25_file = self.index_path / f"{self._index_prefix(user_id)}_bm25.pkl"
                if bm25_file.exists():
                    with open(bm25_file, "rb") as f:
                        self.bm25_indices[user_id] = pickle.load(f)

                log("info",
                    f"FaissHierarchical [{self.engine_id}]: "
                    f"loaded index for {user_id} ({index.ntotal} vectors)")
            except Exception as e:
                log("error",
                    f"FaissHierarchical [{self.engine_id}]: "
                    f"failed to load index for {user_id}: {e}")

    def _save_user_index(self, user_id: str) -> None:
        pfx        = self._index_prefix(user_id)
        index_file = self.index_path / f"{pfx}.index"
        meta_file  = self.index_path / f"{pfx}_meta.pkl"
        bm25_file  = self.index_path / f"{pfx}_bm25.pkl"
        model_file = self.index_path / f"{pfx}_model_meta.json"

        if user_id in self.indices and self.indices[user_id].ntotal > 0:
            try:
                faiss.write_index(self.indices[user_id], str(index_file))
                with open(meta_file, "wb") as f:
                    pickle.dump(self.metadata[user_id], f)
                if user_id in self.bm25_indices:
                    with open(bm25_file, "wb") as f:
                        pickle.dump(self.bm25_indices[user_id], f)
                with open(model_file, "w") as f:
                    json.dump({
                        "model_name": self.model_name,
                        "dimension":  self.dimension,
                        "created_at": datetime.now().isoformat(),
                    }, f)
            except Exception as e:
                log("error",
                    f"FaissHierarchical [{self.engine_id}]: "
                    f"failed to save index for {user_id}: {e}")
        else:
            for fp in (index_file, meta_file, bm25_file, model_file):
                if fp.exists():
                    fp.unlink()
            self.indices.pop(user_id, None)
            self.metadata.pop(user_id, None)
            self.bm25_indices.pop(user_id, None)

    # ====================================================================
    # Index management
    # ====================================================================

    def index_document(
        self,
        user_id:   str,
        filename:  str,
        file_path: str,
        content:   Optional[str] = None,
    ) -> bool:
        if self.dimension is None:
            return False
        try:
            if content is None:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()

            chunks = (
                self._extract_hierarchical_chunks(content)
                if self.chunk_strategy == STRATEGY_HIERARCHICAL
                else self._extract_multi_level_chunks(content)
            )
            if not chunks:
                return False

            embeddings = self._encode_texts([c["embed_text"] for c in chunks])
            file_size  = os.path.getsize(file_path)

            if user_id not in self.indices:
                self.indices[user_id]  = faiss.IndexFlatIP(self.dimension)
                self.metadata[user_id] = []
            else:
                if self.indices[user_id].d != self.dimension:
                    log("warning",
                        f"FaissHierarchical [{self.engine_id}]: "
                        f"dimension mismatch for {user_id} — rebuilding index")
                    self.indices[user_id]  = faiss.IndexFlatIP(self.dimension)
                    self.metadata[user_id] = []
                    self.bm25_indices.pop(user_id, None)

            self.indices[user_id].add(embeddings)
            for chunk in chunks:
                self.metadata[user_id].append({
                    "level":      chunk.get("level", LEVEL_SECTION),
                    "embed_text": chunk["embed_text"],
                    "raw_text":   chunk.get("raw_text", chunk.get("display_text", "")),
                    "content":    chunk["display_text"],
                    "filename":   filename,
                    "file_size":  file_size,
                    "file_path":  file_path,
                    "indexed_at": datetime.now().isoformat(),
                    "chapter":    chunk.get("chapter", ""),
                    "section":    chunk.get("section", ""),
                })

            # Always build BM25 index — needed for cascade and bm25_only modes
            all_raw = [m["raw_text"] for m in self.metadata[user_id]]
            self.bm25_indices[user_id] = _BM25Index(all_raw)

            self._save_user_index(user_id)

            counts = {lv: sum(1 for c in chunks if c.get("level") == lv)
                      for lv in [LEVEL_PARAGRAPH, LEVEL_SECTION, LEVEL_SUMMARY]}
            log(
                "info",
                f"FaissHierarchical [{self.engine_id}]: indexed {filename} for {user_id} — "
                f"{counts[LEVEL_PARAGRAPH]}p / {counts[LEVEL_SECTION]}s / "
                f"{counts[LEVEL_SUMMARY]}sum  (strategy={self.chunk_strategy})",
            )
            return True
        except Exception as e:
            log("error",
                f"FaissHierarchical [{self.engine_id}]: "
                f"failed to index {filename}: {e}")
            return False

    def delete_document(self, user_id: str, filename: str) -> bool:
        if user_id not in self.metadata:
            return False
        try:
            kept = [m for m in self.metadata[user_id] if m["filename"] != filename]
            if len(kept) == len(self.metadata[user_id]):
                return False
            if kept:
                embs = self._encode_texts([m["embed_text"] for m in kept])
                new_idx = faiss.IndexFlatIP(self.dimension)
                new_idx.add(embs)
                self.indices[user_id]      = new_idx
                self.metadata[user_id]     = kept
                self.bm25_indices[user_id] = _BM25Index([m["raw_text"] for m in kept])
            else:
                self.indices.pop(user_id, None)
                self.metadata.pop(user_id, None)
                self.bm25_indices.pop(user_id, None)
            self._save_user_index(user_id)
            return True
        except Exception as e:
            log("error",
                f"FaissHierarchical [{self.engine_id}]: "
                f"failed to delete {filename}: {e}")
            return False

    def clear_user_index(self, user_id: str) -> bool:
        try:
            self.indices.pop(user_id, None)
            self.metadata.pop(user_id, None)
            self.bm25_indices.pop(user_id, None)
            self._save_user_index(user_id)
            return True
        except Exception as e:
            log("error",
                f"FaissHierarchical [{self.engine_id}]: "
                f"failed to clear index for {user_id}: {e}")
            return False

    def force_rebuild_index(self, user_id: str) -> bool:
        """
        Force a full rebuild by clearing both memory and on-disk files.
        Use when changing the embedding model or chunk_strategy.
        """
        try:
            self.indices.pop(user_id, None)
            self.metadata.pop(user_id, None)
            self.bm25_indices.pop(user_id, None)
            pfx = self._index_prefix(user_id)
            for suffix in (".index", "_meta.pkl", "_bm25.pkl", "_model_meta.json"):
                fp = self.index_path / f"{pfx}{suffix}"
                if fp.exists():
                    fp.unlink()
            log("info",
                f"FaissHierarchical [{self.engine_id}]: rebuilt index for {user_id}")
            return True
        except Exception as e:
            log("error",
                f"FaissHierarchical [{self.engine_id}]: "
                f"force_rebuild_index failed for {user_id}: {e}")
            return False

    # ====================================================================
    # Search — dispatcher
    # ====================================================================

    def search(self, user_id: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Route to the correct retrieval implementation based on ``search_mode``.
        """
        if (
            self.dimension is None
            or user_id not in self.indices
            or self.indices[user_id].ntotal == 0
        ):
            return [self._empty_result()]

        if self.indices[user_id].d != self.dimension:
            log("error",
                f"FaissHierarchical [{self.engine_id}]: dimension mismatch for "
                f"{user_id} — please rebuild index")
            return [self._empty_result(
                error=f"Dimension mismatch: index={self.indices[user_id].d}, "
                      f"model={self.dimension}"
            )]

        mode = self.search_mode

        if mode == MODE_CASCADE:
            return self._search_cascade(user_id, query, limit)
        if mode == MODE_BM25_ONLY:
            return self._search_bm25_only(user_id, query, limit)
        if mode == MODE_DENSE_ONLY:
            return self._search_dense_only(user_id, query, limit)
        if mode in _LEVEL_MODES:
            level = {
                MODE_PARAGRAPH: LEVEL_PARAGRAPH,
                MODE_SECTION:   LEVEL_SECTION,
                MODE_SUMMARY:   LEVEL_SUMMARY,
            }[mode]
            return self._search_level_only(user_id, query, limit, level)
        # default: MODE_FLAT
        return self._search_flat(user_id, query, limit)

    # ====================================================================
    # Search implementations
    # ====================================================================

    # ------------------------------------------------------------------
    # Mode: flat
    # ------------------------------------------------------------------

    def _search_flat(
        self, user_id: str, query: str, limit: int
    ) -> List[Dict[str, Any]]:
        """
        Dense cosine search across all chunks.
        Optional per-level score multipliers (level_boost) and forced
        summary slot injection (summary_slots).
        """
        all_meta = self.metadata[user_id]
        query_emb = self._encode_texts([query])
        n = min(len(all_meta), max(limit * 6, limit + self.summary_slots * 2))
        D, I = self.indices[user_id].search(query_emb, n)

        threshold    = self.similarity_threshold
        max_reached  = 0.0
        candidates: List[Tuple[float, int]] = []

        for dist, idx in zip(D[0], I[0]):
            if idx == -1:
                continue
            if float(dist) > max_reached:
                max_reached = float(dist)
            level  = all_meta[idx].get("level", LEVEL_SECTION)
            boosted = float(dist) * self.level_boost.get(level, 1.0)
            if boosted >= threshold:
                candidates.append((boosted, int(idx)))

        candidates.sort(key=lambda x: x[0], reverse=True)

        # Force-include top summary chunks (summary_slots)
        results: List[Dict[str, Any]] = []
        included: set = set()

        if self.summary_slots > 0:
            summary_cands = [
                (score, idx) for score, idx in candidates
                if all_meta[idx].get("level") == LEVEL_SUMMARY
            ]
            for score, idx in summary_cands[: self.summary_slots]:
                results.append(self._build_result(
                    all_meta, idx, dense_score=score,
                    bm25_score=0.0, stage=0,
                    max_score_reached=max_reached,
                ))
                included.add(idx)

        for score, idx in candidates:
            if len(results) >= limit:
                break
            if idx not in included:
                results.append(self._build_result(
                    all_meta, idx, dense_score=score,
                    bm25_score=0.0, stage=0,
                    max_score_reached=max_reached,
                ))

        if not results:
            return [self._empty_result(max_score_reached=max_reached)]
        return results

    # ------------------------------------------------------------------
    # Mode: cascade
    # ------------------------------------------------------------------

    def _search_cascade(
        self, user_id: str, query: str, limit: int
    ) -> List[Dict[str, Any]]:
        """
        Inverted sieve: BM25 → paragraph dense → section dense → summary dense.
        """
        all_meta = self.metadata[user_id]

        # Build per-level position maps
        positions_by_level: Dict[str, List[int]] = defaultdict(list)
        for pos, meta in enumerate(all_meta):
            positions_by_level[meta.get("level", LEVEL_SECTION)].append(pos)

        # Stage 1 — BM25
        if user_id in self.bm25_indices:
            bm25_res = self.bm25_indices[user_id].search(query, top_k=limit * 3)
            if self._bm25_confident(bm25_res):
                log("debug",
                    f"FaissHierarchical [{self.engine_id}] cascade stage=1 (BM25) "
                    f"top={bm25_res[0][1]:.3f}")
                return [
                    self._build_result(
                        all_meta, idx, dense_score=0.0,
                        bm25_score=score, stage=1,
                    )
                    for idx, score in bm25_res[:limit]
                ]

        # Dense pre-computation (shared across stages 2–4)
        query_emb    = self._encode_texts([query])
        n_candidates = min(len(all_meta), limit * 6)
        D, I = self.indices[user_id].search(query_emb, n_candidates)

        dense_scores: Dict[int, float] = {}
        max_dense = 0.0
        for dist, idx in zip(D[0], I[0]):
            if idx == -1:
                continue
            dense_scores[int(idx)] = float(dist)
            if float(dist) > max_dense:
                max_dense = float(dist)

        def scored_for_level(level: str) -> List[Tuple[int, float]]:
            return sorted(
                [(pos, dense_scores[pos])
                 for pos in positions_by_level[level]
                 if pos in dense_scores],
                key=lambda x: x[1], reverse=True,
            )

        # Stage 2 — paragraph dense
        para = scored_for_level(LEVEL_PARAGRAPH)
        if para and self._dense_confident([s for _, s in para]):
            log("debug",
                f"FaissHierarchical [{self.engine_id}] cascade stage=2 (paragraph) "
                f"top={para[0][1]:.3f}")
            return [
                self._build_result(
                    all_meta, idx, dense_score=score,
                    bm25_score=0.0, stage=2, max_score_reached=max_dense,
                )
                for idx, score in para[:limit]
            ]

        # Stage 3 — section dense
        sec = scored_for_level(LEVEL_SECTION)
        if sec and self._dense_confident([s for _, s in sec]):
            log("debug",
                f"FaissHierarchical [{self.engine_id}] cascade stage=3 (section) "
                f"top={sec[0][1]:.3f}")
            return [
                self._build_result(
                    all_meta, idx, dense_score=score,
                    bm25_score=0.0, stage=3, max_score_reached=max_dense,
                )
                for idx, score in sec[:limit]
            ]

        # Stage 4 — summary dense (no confidence gate)
        summ = scored_for_level(LEVEL_SUMMARY)
        above_floor = [(idx, s) for idx, s in summ if s >= self.floor_threshold]
        if above_floor:
            log("debug",
                f"FaissHierarchical [{self.engine_id}] cascade stage=4 (summary) "
                f"top={above_floor[0][1]:.3f}")
            return [
                self._build_result(
                    all_meta, idx, dense_score=score,
                    bm25_score=0.0, stage=4, max_score_reached=max_dense,
                )
                for idx, score in above_floor[:limit]
            ]

        log("debug",
            f"FaissHierarchical [{self.engine_id}] cascade: all stages exhausted "
            f"(max_dense={max_dense:.4f})")
        return [self._empty_result(max_score_reached=max_dense)]

    # ------------------------------------------------------------------
    # Mode: bm25_only
    # ------------------------------------------------------------------

    def _search_bm25_only(
        self, user_id: str, query: str, limit: int
    ) -> List[Dict[str, Any]]:
        if user_id not in self.bm25_indices:
            return [self._empty_result()]
        all_meta = self.metadata[user_id]
        bm25_res = self.bm25_indices[user_id].search(query, top_k=limit)
        if not bm25_res:
            return [self._empty_result()]
        return [
            self._build_result(
                all_meta, idx, dense_score=0.0,
                bm25_score=score, stage=1,
            )
            for idx, score in bm25_res
        ]

    # ------------------------------------------------------------------
    # Mode: dense_only
    # ------------------------------------------------------------------

    def _search_dense_only(
        self, user_id: str, query: str, limit: int
    ) -> List[Dict[str, Any]]:
        """
        Dense search over all chunks.  Applies the confidence gate
        (dense_margin_ratio); if no stage is confident, falls back to
        flat threshold behaviour.
        """
        all_meta  = self.metadata[user_id]
        query_emb = self._encode_texts([query])
        n = min(len(all_meta), limit * 6)
        D, I = self.indices[user_id].search(query_emb, n)

        scored: List[Tuple[int, float]] = []
        max_dense = 0.0
        for dist, idx in zip(D[0], I[0]):
            if idx == -1:
                continue
            scored.append((int(idx), float(dist)))
            if float(dist) > max_dense:
                max_dense = float(dist)
        scored.sort(key=lambda x: x[1], reverse=True)

        scores_only = [s for _, s in scored]
        if self._dense_confident(scores_only):
            results = [
                self._build_result(
                    all_meta, idx, dense_score=score,
                    bm25_score=0.0, stage=2, max_score_reached=max_dense,
                )
                for idx, score in scored[:limit]
            ]
        else:
            # Fallback: flat threshold
            results = [
                self._build_result(
                    all_meta, idx, dense_score=score,
                    bm25_score=0.0, stage=0, max_score_reached=max_dense,
                )
                for idx, score in scored
                if score >= self.similarity_threshold
            ][:limit]

        return results or [self._empty_result(max_score_reached=max_dense)]

    # ------------------------------------------------------------------
    # Mode: paragraph / section / summary  (level-restricted dense)
    # ------------------------------------------------------------------

    def _search_level_only(
        self, user_id: str, query: str, limit: int, level: str
    ) -> List[Dict[str, Any]]:
        all_meta  = self.metadata[user_id]
        positions = [i for i, m in enumerate(all_meta) if m.get("level") == level]

        if not positions:
            return [self._empty_result()]

        query_emb = self._encode_texts([query])
        n = min(len(all_meta), limit * 6)
        D, I = self.indices[user_id].search(query_emb, n)

        scored: List[Tuple[int, float]] = []
        max_dense = 0.0
        pos_set   = set(positions)
        for dist, idx in zip(D[0], I[0]):
            if idx == -1:
                continue
            if int(idx) in pos_set:
                scored.append((int(idx), float(dist)))
                if float(dist) > max_dense:
                    max_dense = float(dist)
        scored.sort(key=lambda x: x[1], reverse=True)

        results = [
            self._build_result(
                all_meta, idx, dense_score=score,
                bm25_score=0.0, stage=0, max_score_reached=max_dense,
            )
            for idx, score in scored
            if score >= self.similarity_threshold
        ][:limit]

        return results or [self._empty_result(max_score_reached=max_dense)]

    # ====================================================================
    # Confidence helpers
    # ====================================================================

    def _bm25_confident(self, scored: List[Tuple[int, float]]) -> bool:
        if not scored:
            return False
        top = scored[0][1]
        if top < self.bm25_min_score:
            return False
        if len(scored) < 2:
            return True
        second = scored[1][1]
        return top >= self.bm25_dominance_ratio * max(second, 1e-9)

    def _dense_confident(self, scores: List[float]) -> bool:
        if not scores:
            return False
        top = scores[0]
        if top < self.dense_min_score:
            return False
        k = min(self.top_k_for_margin, len(scores))
        mean_k = sum(scores[:k]) / k
        return top >= self.dense_margin_ratio * max(mean_k, 1e-9)

    # ====================================================================
    # Result builders
    # ====================================================================

    def _build_result(
        self,
        all_meta:        List[Dict],
        meta_idx:        int,
        dense_score:     float,
        bm25_score:      float,
        stage:           int,
        max_score_reached: float = 0.0,
    ) -> Dict[str, Any]:
        meta = all_meta[meta_idx]
        return {
            "filename":           meta["filename"],
            "score":              dense_score or bm25_score,
            "dense_score":        dense_score,
            "bm25_score":         bm25_score,
            "content":            meta["content"],
            "level":              meta.get("level", LEVEL_SECTION),
            "chapter":            meta.get("chapter", ""),
            "section":            meta.get("section", ""),
            "retrieval_pass":     stage,
            "threshold_used":     self.similarity_threshold,
            "max_score_reached":  max_score_reached,
        }

    def _empty_result(
        self,
        max_score_reached: float = 0.0,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "filename":          None,
            "score":             0.0,
            "dense_score":       0.0,
            "bm25_score":        0.0,
            "content":           "",
            "level":             None,
            "chapter":           None,
            "section":           None,
            "retrieval_pass":    0,
            "threshold_used":    self.similarity_threshold,
            "max_score_reached": max_score_reached,
            "no_results":        True,
        }
        if error:
            result["error"] = error
        return result

    # ====================================================================
    # Chunking — strategy 1: hierarchical  (v1 style)
    # ====================================================================

    def _extract_hierarchical_chunks(self, content: str) -> List[Dict[str, Any]]:
        """
        One chunk per ## section.  embed_text is enriched with the chapter
        résumé and key concepts.  All chunks are tagged LEVEL_SECTION so
        per-level search modes and cascade work correctly.
        """
        lines = content.splitlines()
        chunks: List[Dict[str, Any]] = []
        i = 0
        current_chapter  = ""
        current_summary  = ""
        current_concepts: List[str] = []
        current_section  = "Introduction"
        current_lines:   List[str] = []
        in_block: Optional[str]    = None

        while i < len(lines):
            line     = lines[i]
            stripped = line.strip()

            if stripped.startswith("# "):
                if current_lines and current_summary:
                    chunks.append(self._make_hierarchical_chunk(
                        current_chapter, current_summary, current_concepts,
                        current_section, current_lines,
                    ))
                    current_lines = []
                current_chapter  = stripped[2:].strip()
                current_summary  = ""
                current_concepts = []
                current_section  = "Introduction"
                in_block         = None

            elif stripped.startswith(">[!Résumé]") or stripped.startswith(">[!Resume]"):
                in_block        = "summary"
                current_summary = ""

            elif stripped.startswith(">[!concepts]") or stripped.startswith(">[!Concepts]"):
                in_block         = "concepts"
                current_concepts = []

            elif stripped.startswith("## "):
                if current_lines and current_summary:
                    chunks.append(self._make_hierarchical_chunk(
                        current_chapter, current_summary, current_concepts,
                        current_section, current_lines,
                    ))
                current_section = stripped[3:].strip()
                current_lines   = []
                in_block        = None

            else:
                if in_block == "summary":
                    if line.startswith(">"):
                        current_summary += line.lstrip(">").lstrip(" ").rstrip() + "\n"
                    else:
                        in_block = None
                elif in_block == "concepts":
                    if line.startswith(">"):
                        concept_line = line.lstrip(">").lstrip(" ").rstrip()
                        current_concepts.extend(
                            [c.strip() for c in concept_line.split(",") if c.strip()]
                        )
                    else:
                        in_block = None
                else:
                    if current_chapter:
                        current_lines.append(line)
            i += 1

        if current_lines and current_summary:
            chunks.append(self._make_hierarchical_chunk(
                current_chapter, current_summary, current_concepts,
                current_section, current_lines,
            ))

        if not chunks and content.strip():
            chunks.append({
                "level":        LEVEL_SECTION,
                "embed_text":   content,
                "display_text": content,
                "raw_text":     content,
                "chapter":      "Document",
                "section":      "Main content",
            })

        return chunks

    def _make_hierarchical_chunk(
        self,
        chapter:  str,
        summary:  str,
        concepts: List[str],
        section:  str,
        lines:    List[str],
    ) -> Dict[str, Any]:
        display_text = "\n".join(lines).strip()
        embed_text   = (
            f"Chapitre : {chapter}\n"
            f"Résumé : {summary.strip()}\n"
            f"Concepts clés : {', '.join(concepts)}\n\n"
            f"Section : {section}\n\n"
            f"{display_text}"
        )
        return {
            "level":        LEVEL_SECTION,
            "embed_text":   embed_text,
            "display_text": f"{section}\n\n{display_text}",
            "raw_text":     display_text,
            "chapter":      chapter,
            "section":      section,
        }

    # ====================================================================
    # Chunking — strategy 2: multi_level  (v2 style)
    # ====================================================================

    def _extract_multi_level_chunks(self, content: str) -> List[Dict[str, Any]]:
        """
        Three granularity levels per document:
          SUMMARY   — one per chapter (>[!Résumé] block + concepts)
          SECTION   — one per ## section, embed-text enriched with résumé
          PARAGRAPH — fixed-size slices of each section body
        """
        lines = content.splitlines()
        chunks: List[Dict[str, Any]] = []

        current_chapter  = ""
        current_summary  = ""
        current_concepts: List[str] = []
        current_section  = "Introduction"
        current_lines:   List[str] = []
        in_block: Optional[str]    = None

        def flush() -> None:
            nonlocal current_lines
            if not current_chapter:
                return
            body = "\n".join(current_lines).strip()
            if not body:
                current_lines = []
                return
            chunks.append(self._make_section_chunk(
                current_chapter, current_summary, current_concepts,
                current_section, body,
            ))
            for para in self._split_paragraph_chunks(
                current_chapter, current_summary, current_concepts,
                current_section, body,
            ):
                chunks.append(para)
            current_lines = []

        def flush_summary() -> None:
            if current_summary.strip() and current_chapter:
                chunks.append(self._make_summary_chunk(
                    current_chapter, current_summary, current_concepts,
                ))

        i = 0
        while i < len(lines):
            line     = lines[i]
            stripped = line.strip()

            if stripped.startswith("# "):
                flush()
                flush_summary()
                current_chapter  = stripped[2:].strip()
                current_summary  = ""
                current_concepts = []
                current_section  = "Introduction"
                current_lines    = []
                in_block         = None

            elif stripped.startswith(">[!Résumé]") or stripped.startswith(">[!Resume]"):
                in_block        = "summary"
                current_summary = ""

            elif stripped.startswith(">[!concepts]") or stripped.startswith(">[!Concepts]"):
                in_block         = "concepts"
                current_concepts = []

            elif stripped.startswith("## "):
                flush()
                current_section = stripped[3:].strip()
                in_block        = None

            else:
                if in_block == "summary":
                    if line.startswith(">"):
                        current_summary += line.lstrip(">").lstrip(" ").rstrip() + "\n"
                    else:
                        in_block = None
                elif in_block == "concepts":
                    if line.startswith(">"):
                        concept_line = line.lstrip(">").lstrip(" ").rstrip()
                        current_concepts.extend(
                            [c.strip() for c in concept_line.split(",") if c.strip()]
                        )
                    else:
                        in_block = None
                else:
                    if current_chapter:
                        current_lines.append(line)
            i += 1

        flush()
        flush_summary()

        if not chunks and content.strip():
            chunks.append({
                "level":        LEVEL_SECTION,
                "embed_text":   content,
                "display_text": content,
                "raw_text":     content,
                "chapter":      "Document",
                "section":      "Main content",
            })

        return chunks

    def _make_summary_chunk(
        self, chapter: str, summary: str, concepts: List[str]
    ) -> Dict[str, Any]:
        text        = summary.strip()
        concept_str = ", ".join(concepts)
        embed_text  = f"{text}\n\n{concept_str}".strip() if concept_str else text
        display_text = f"**{chapter} — Chapter summary**\n\n{text}"
        if concept_str:
            display_text += f"\n\nKey concepts: {concept_str}"
        return {
            "level":        LEVEL_SUMMARY,
            "embed_text":   embed_text,
            "display_text": display_text,
            "raw_text":     text,
            "chapter":      chapter,
            "section":      "",
        }

    def _make_section_chunk(
        self,
        chapter:  str,
        summary:  str,
        concepts: List[str],
        section:  str,
        body:     str,
    ) -> Dict[str, Any]:
        parts: List[str] = []
        if summary.strip():
            parts.append(summary.strip())
        if concepts:
            parts.append(", ".join(concepts))
        parts.append(body)
        embed_text   = "\n\n".join(parts)
        display_text = f"**{chapter}**\n**{section}**\n\n{body}"
        return {
            "level":        LEVEL_SECTION,
            "embed_text":   embed_text,
            "display_text": display_text,
            "raw_text":     body,
            "chapter":      chapter,
            "section":      section,
        }

    def _split_paragraph_chunks(
        self,
        chapter:  str,
        summary:  str,
        concepts: List[str],
        section:  str,
        body:     str,
    ) -> List[Dict[str, Any]]:
        if not body.strip():
            return []
        para_chunks: List[Dict[str, Any]] = []
        start = 0
        while start < len(body):
            end  = start + self.paragraph_size
            text = body[start:end].strip()
            if len(text) > 30:
                parts: List[str] = []
                if summary.strip():
                    parts.append(summary.strip())
                parts.append(text)
                embed_text   = "\n\n".join(parts)
                display_text = f"**{chapter}**\n**{section}**\n\n{text}"
                para_chunks.append({
                    "level":        LEVEL_PARAGRAPH,
                    "embed_text":   embed_text,
                    "display_text": display_text,
                    "raw_text":     text,
                    "chapter":      chapter,
                    "section":      section,
                })
            if end >= len(body):
                break
            start = end - self.paragraph_overlap
        return para_chunks

    # ====================================================================
    # Embedding
    # ====================================================================

    def _encode_texts(self, texts: List[str]) -> np.ndarray:
        embeddings = np.array(get_embeddings(texts), dtype=np.float32)
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return embeddings / norms

    # ====================================================================
    # Stats / availability
    # ====================================================================

    def is_available(self) -> bool:
        return self.dimension is not None

    def get_indexed_documents(
        self, user_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        docs: List[Dict[str, Any]] = []
        for uid in ([user_id] if user_id else self.metadata.keys()):
            if uid in self.metadata:
                seen: set = set()
                for meta in self.metadata[uid]:
                    fn = meta["filename"]
                    if fn not in seen:
                        seen.add(fn)
                        docs.append({
                            "user_id":    uid,
                            "filename":   fn,
                            "indexed_at": meta["indexed_at"],
                            "size":       meta.get("file_size", 0),
                        })
        return docs

    def get_stats(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        if user_id:
            user_meta = self.metadata.get(user_id, [])
            return {
                "documents_indexed": len({m["filename"] for m in user_meta}),
                "total_chunks":      len(user_meta),
                "paragraph_chunks":  sum(1 for m in user_meta if m.get("level") == LEVEL_PARAGRAPH),
                "section_chunks":    sum(1 for m in user_meta if m.get("level") == LEVEL_SECTION),
                "summary_chunks":    sum(1 for m in user_meta if m.get("level") == LEVEL_SUMMARY),
                "bm25_ready":        user_id in self.bm25_indices,
                "engine_type":       self.engine_type,
                "engine_id":         self.engine_id,
                "chunk_strategy":    self.chunk_strategy,
                "search_mode":       self.search_mode,
                "model_name":        self.model_name,
                "dimension":         self.dimension,
            }
        total_docs   = sum(len({m["filename"] for m in v}) for v in self.metadata.values())
        total_chunks = sum(len(v) for v in self.metadata.values())
        return {
            "total_documents_indexed": total_docs,
            "total_chunks":            total_chunks,
            "users_with_index":        len(self.metadata),
            "engine_type":             self.engine_type,
            "engine_id":               self.engine_id,
            "chunk_strategy":          self.chunk_strategy,
            "search_mode":             self.search_mode,
            "model_name":              self.model_name,
            "dimension":               self.dimension,
        }


# =============================================================================
# Lightweight pure-Python BM25 — zero external dependencies
# =============================================================================

class _BM25Index:
    """
    Okapi BM25 sparse retrieval.
    k1 — term frequency saturation  (typical 1.2–2.0)
    b  — length normalisation        (typical 0.0–1.0)
    """

    def __init__(self, texts: List[str], k1: float = 1.5, b: float = 0.75):
        self.k1          = k1
        self.b           = b
        self.corpus_size = len(texts)
        self.tokenized   = [self._tokenize(t) for t in texts]
        self.doc_lengths = [len(d) for d in self.tokenized]
        self.avgdl       = sum(self.doc_lengths) / max(self.corpus_size, 1)
        self.df: Dict[str, int] = defaultdict(int)
        for doc in self.tokenized:
            for term in set(doc):
                self.df[term] += 1

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        return re.findall(r"\w+", text.lower())

    def _idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log((self.corpus_size - df + 0.5) / (df + 0.5) + 1)

    def _score(self, query_terms: List[str], doc_idx: int) -> float:
        doc    = self.tokenized[doc_idx]
        dl     = self.doc_lengths[doc_idx]
        tf_map: Dict[str, int] = defaultdict(int)
        for term in doc:
            tf_map[term] += 1
        score = 0.0
        for term in query_terms:
            if term not in tf_map:
                continue
            tf  = tf_map[term]
            idf = self._idf(term)
            num = tf * (self.k1 + 1)
            den = tf + self.k1 * (1 - self.b + self.b * dl / max(self.avgdl, 1))
            score += idf * num / den
        return score

    def search(self, query: str, top_k: int = 20) -> List[Tuple[int, float]]:
        """Return [(doc_idx, bm25_score)] sorted descending, zero-scores excluded."""
        terms = self._tokenize(query)
        if not terms:
            return []
        scored = [(i, self._score(terms, i)) for i in range(self.corpus_size)]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [(i, s) for i, s in scored[:top_k] if s > 0]
