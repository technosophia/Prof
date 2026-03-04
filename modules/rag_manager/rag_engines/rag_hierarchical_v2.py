"""
Hierarchical FAISS RAG Engine v2 — Inverted Sieve Cascade

Architecture
------------
Indexing — three granularity levels per document:
  - PARAGRAPH : fine-grained chunks (~300 chars, overlap 50), for precise factual queries
  - SECTION   : one chunk per ## markdown section, for thematic queries
  - SUMMARY   : one standalone chunk per chapter summary (>[!Résumé] block), for broad queries

Search — inverted sieve cascade (most precise → most abstract):

  Stage 1 — BM25 exact match
    Best for: precise factual queries ("200 000 ans", "quatre niveaux")
    Confidence: top BM25 score >= bm25_dominance_ratio × second score
    (a dominant gap means BM25 found something unambiguous)

  Stage 2 — Dense search on PARAGRAPH chunks
    Best for: semantically specific queries where exact wording may vary
    Confidence: top dense score >= paragraph_margin × mean of top-k scores
    (a score standing clearly above its peers signals a clear match)

  Stage 3 — Dense search on SECTION chunks
    Best for: thematic queries spanning a whole subsection
    Confidence: same margin logic as Stage 2

  Stage 4 — Dense search on SUMMARY chunks  (always returns if above floor_threshold)
    Best for: broad conceptual queries ("what are the three levers…")
    No confidence gate — last resort, returns best summary above floor

Confidence is measured by score gap / margin rather than absolute thresholds,
making the cascade robust across documents with varying score distributions.

All code and comments in English.
No Streamlit dependency. Config is injected at construction time.
"""

import os
import re
import math
import json
import numpy as np
import faiss
import pickle
from datetime import datetime
from collections import defaultdict
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path

from ..rag_engine import RAGEngine
from shared.common import get_embedding, get_embeddings
from core.logging import log

# Chunk level constants
LEVEL_PARAGRAPH = "paragraph"
LEVEL_SECTION   = "section"
LEVEL_SUMMARY   = "summary"


class FaissHierarchicalV2RAGEngine(RAGEngine):
    """
    Inverted sieve cascade RAG engine.

    Searches from the most precise retrieval method to the most abstract,
    stopping as soon as one stage returns a confident result.

    Config keys (all optional):
        index_path              str    Storage path.
                                       Default: ./data/hier_v2_indexes
        paragraph_size          int    Paragraph chunk char size.
                                       Default: 300
        paragraph_overlap       int    Paragraph overlap chars.
                                       Default: 50
        model_name              str    Embedding model name.
                                       Default: all-MiniLM-L6-v2

        --- Confidence parameters ---
        bm25_dominance_ratio    float  Stage 1 gate: top BM25 score must be >= this
                                       ratio × second score.  Default: 2.0
                                       (top score must be 2× the runner-up)
        bm25_min_score          float  Stage 1 floor: top BM25 score must also exceed
                                       this absolute minimum.  Default: 1.0
        dense_margin_ratio      float  Stage 2/3 gate: top dense score must be >=
                                       this ratio × mean of top-k dense scores.
                                       Default: 1.3
        dense_min_score         float  Stage 2/3 floor: top dense score absolute min.
                                       Default: 0.30
        floor_threshold         float  Stage 4 floor: minimum dense score to return
                                       anything at all.  Default: 0.15
        top_k_for_margin        int    How many top results to use when computing the
                                       mean for margin check.  Default: 5
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__("faiss_hierarchical_v2")
        self.description = (
            "Inverted sieve cascade: BM25 → paragraph dense → section dense → summary dense"
        )

        config = config or {}

        self.index_path = Path(config.get("index_path", "./data/hier_v2_indexes"))
        self.index_path.mkdir(parents=True, exist_ok=True)

        self.paragraph_size    = config.get("paragraph_size", 300)
        self.paragraph_overlap = config.get("paragraph_overlap", 50)

        # Add model name to track which model was used for embeddings
        self.model_name = config.get("model_name", "all-MiniLM-L6-v2")

        # Confidence parameters
        self.bm25_dominance_ratio = config.get("bm25_dominance_ratio", 2.0)
        self.bm25_min_score       = config.get("bm25_min_score", 1.0)
        self.dense_margin_ratio   = config.get("dense_margin_ratio", 1.3)
        self.dense_min_score      = config.get("dense_min_score", 0.30)
        self.floor_threshold      = config.get("floor_threshold", 0.15)
        self.top_k_for_margin     = config.get("top_k_for_margin", 5)

        # Alias for benchmark tooling compatibility
        self.similarity_threshold = self.dense_min_score

        log("debug",
            f"HierV2 (sieve) config: bm25_dom={self.bm25_dominance_ratio}, "
            f"dense_margin={self.dense_margin_ratio}, floor={self.floor_threshold}, "
            f"model={self.model_name}")

        try:
            self.dimension = len(get_embedding(""))
            log("info", f"HierV2 embeddings initialized (dim: {self.dimension}, model: {self.model_name})")
        except Exception as e:
            log("error", f"HierV2 failed to initialize embeddings: {str(e)}")
            self.dimension = None

        self.indices:      Dict[str, faiss.IndexFlatIP]  = {}
        self.metadata:     Dict[str, List[Dict[str, Any]]] = {}
        self.bm25_indices: Dict[str, "_BM25Index"]       = {}

        self._load_indices()

    # ------------------------------------------------------------------
    # Persistence with Model Metadata
    # ------------------------------------------------------------------

    def _load_indices(self):
        """Load indices with dimension validation."""
        for index_file in self.index_path.glob("*_hv2.index"):
            user_id = index_file.stem.replace("_hv2", "")

            # Check model metadata first
            model_meta_file = self.index_path / f"{user_id}_hv2_model_meta.json"

            # Verify model compatibility
            if model_meta_file.exists():
                try:
                    with open(model_meta_file, 'r') as f:
                        model_meta = json.load(f)

                    if model_meta.get('dimension') != self.dimension:
                        log("warning",
                            f"Index for user {user_id} uses different model "
                            f"({model_meta.get('model_name')}, dim={model_meta.get('dimension')}). "
                            f"Current model: {self.model_name}, dim={self.dimension}. Skipping load.")
                        continue
                except Exception as e:
                    log("error", f"Failed to read model metadata for {user_id}: {str(e)}")
                    continue

            try:
                index = faiss.read_index(str(index_file))

                # Verify index dimension matches
                if index.d != self.dimension:
                    log("warning",
                        f"Index for user {user_id} has dimension {index.d}, "
                        f"but hierarchical v2 model expects {self.dimension}. Skipping load.")
                    continue

                self.indices[user_id] = index

                meta_file = self.index_path / f"{user_id}_hv2_meta.pkl"
                if meta_file.exists():
                    with open(meta_file, "rb") as f:
                        self.metadata[user_id] = pickle.load(f)

                bm25_file = self.index_path / f"{user_id}_hv2_bm25.pkl"
                if bm25_file.exists():
                    with open(bm25_file, "rb") as f:
                        self.bm25_indices[user_id] = pickle.load(f)

                log("info", f"HierV2: loaded index for {user_id} ({index.ntotal} vectors)")
            except Exception as e:
                log("error", f"HierV2: failed to load index for {user_id}: {str(e)}")

    def _save_user_index(self, user_id: str):
        """Save index with model metadata."""
        index_file = self.index_path / f"{user_id}_hv2.index"
        meta_file  = self.index_path / f"{user_id}_hv2_meta.pkl"
        bm25_file  = self.index_path / f"{user_id}_hv2_bm25.pkl"
        model_meta_file = self.index_path / f"{user_id}_hv2_model_meta.json"

        if user_id in self.indices and self.indices[user_id].ntotal > 0:
            try:
                faiss.write_index(self.indices[user_id], str(index_file))
                with open(meta_file, "wb") as f:
                    pickle.dump(self.metadata[user_id], f)
                if user_id in self.bm25_indices:
                    with open(bm25_file, "wb") as f:
                        pickle.dump(self.bm25_indices[user_id], f)

                # Save model metadata
                with open(model_meta_file, 'w') as f:
                    json.dump({
                        'model_name': self.model_name,
                        'dimension': self.dimension,
                        'created_at': datetime.now().isoformat()
                    }, f)

            except Exception as e:
                log("error", f"HierV2: failed to save index for {user_id}: {str(e)}")
        else:
            for fp in [index_file, meta_file, bm25_file, model_meta_file]:
                if fp.exists():
                    fp.unlink()
            self.indices.pop(user_id, None)
            self.metadata.pop(user_id, None)
            self.bm25_indices.pop(user_id, None)

    # ------------------------------------------------------------------
    # Force Rebuild Methods
    # ------------------------------------------------------------------

    def force_rebuild_index(self, user_id: str) -> bool:
        """
        Force rebuild of index by clearing memory and deleting files.
        Use this when changing embedding models.
        """
        try:
            # Clear from memory
            self.indices.pop(user_id, None)
            self.metadata.pop(user_id, None)
            self.bm25_indices.pop(user_id, None)

            # Delete physical files
            index_file = self.index_path / f"{user_id}_hv2.index"
            meta_file = self.index_path / f"{user_id}_hv2_meta.pkl"
            bm25_file = self.index_path / f"{user_id}_hv2_bm25.pkl"
            model_meta_file = self.index_path / f"{user_id}_hv2_model_meta.json"

            for file in [index_file, meta_file, bm25_file, model_meta_file]:
                if file.exists():
                    file.unlink()

            log("info", f"HierV2: force rebuilt index for user {user_id}")
            return True
        except Exception as e:
            log("error", f"HierV2: failed to force rebuild index: {str(e)}")
            return False

    def reset_all_indices(self) -> bool:
        """
        Completely reset all indices for all users.
        Use this when changing embedding models globally.
        """
        try:
            # Clear all memory
            self.indices.clear()
            self.metadata.clear()
            self.bm25_indices.clear()

            # Delete all files in index directory
            for file in self.index_path.glob("*"):
                file.unlink()

            log("info", "HierV2: reset all indices successfully")
            return True
        except Exception as e:
            log("error", f"HierV2: failed to reset all indices: {str(e)}")
            return False

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    def _encode_texts(self, texts: List[str]) -> np.ndarray:
        embeddings = np.array(get_embeddings(texts), dtype=np.float32)
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return embeddings / norms

    # ------------------------------------------------------------------
    # Confidence helpers
    # ------------------------------------------------------------------

    def _bm25_confident(self, scored: List[Tuple[int, float]]) -> bool:
        """
        Stage 1 confidence gate.
        Returns True if:
          - top score >= bm25_min_score  (absolute floor)
          - top score >= bm25_dominance_ratio × second score  (relative dominance)
        """
        if not scored:
            return False
        top = scored[0][1]
        if top < self.bm25_min_score:
            return False
        if len(scored) < 2:
            return True  # single result and above floor → confident
        second = scored[1][1]
        return top >= self.bm25_dominance_ratio * max(second, 1e-9)

    def _dense_confident(self, scores: List[float]) -> bool:
        """
        Stage 2/3 confidence gate.
        Returns True if:
          - top score >= dense_min_score  (absolute floor)
          - top score >= dense_margin_ratio × mean of top-k scores  (stands out from crowd)
        """
        if not scores:
            return False
        top = scores[0]
        if top < self.dense_min_score:
            return False
        k = min(self.top_k_for_margin, len(scores))
        mean_topk = sum(scores[:k]) / k
        return top >= self.dense_margin_ratio * max(mean_topk, 1e-9)

    # ------------------------------------------------------------------
    # Markdown parsing — 3 levels
    # ------------------------------------------------------------------

    def _extract_all_chunks(self, content: str) -> List[Dict[str, str]]:
        """
        Parse structured markdown and produce chunks at three levels:
          LEVEL_SUMMARY   — one per chapter (>[!Résumé] block + concepts)
          LEVEL_SECTION   — one per ## section, embed enriched with chapter summary
          LEVEL_PARAGRAPH — fine splits of each section body
        """
        lines = content.splitlines()
        chunks: List[Dict[str, str]] = []

        current_chapter  = ""
        current_summary  = ""
        current_concepts: List[str] = []
        current_section  = "Introduction"
        current_lines:   List[str] = []
        in_block: Optional[str] = None

        def flush():
            nonlocal current_lines
            if not current_chapter:
                return
            body = "\n".join(current_lines).strip()
            if not body:
                current_lines = []
                return
            chunks.append(self._make_section_chunk(
                current_chapter, current_summary, current_concepts,
                current_section, body
            ))
            for para in self._split_paragraphs(
                current_chapter, current_summary, current_concepts,
                current_section, body
            ):
                chunks.append(para)
            current_lines = []

        def flush_summary():
            if current_summary.strip() and current_chapter:
                chunks.append(self._make_summary_chunk(
                    current_chapter, current_summary, current_concepts
                ))

        i = 0
        while i < len(lines):
            line    = lines[i]
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
                "chapter":      "Full document",
                "section":      "Main content",
                "raw_text":     content,
            })

        return chunks

    def _make_summary_chunk(self, chapter: str, summary: str, concepts: List[str]) -> Dict:
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
            "chapter":      chapter,
            "section":      "",
            "raw_text":     text,
        }

    def _make_section_chunk(
        self, chapter: str, summary: str, concepts: List[str],
        section: str, body: str
    ) -> Dict:
        parts = []
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
            "chapter":      chapter,
            "section":      section,
            "raw_text":     body,
        }

    def _split_paragraphs(
        self, chapter: str, summary: str, concepts: List[str],
        section: str, body: str
    ) -> List[Dict]:
        if not body.strip():
            return []
        para_chunks = []
        start = 0
        while start < len(body):
            end  = start + self.paragraph_size
            text = body[start:end].strip()
            if len(text) > 30:
                parts = []
                if summary.strip():
                    parts.append(summary.strip())
                parts.append(text)
                embed_text   = "\n\n".join(parts)
                display_text = f"**{chapter}**\n**{section}**\n\n{text}"
                para_chunks.append({
                    "level":        LEVEL_PARAGRAPH,
                    "embed_text":   embed_text,
                    "display_text": display_text,
                    "chapter":      chapter,
                    "section":      section,
                    "raw_text":     text,
                })
            if end >= len(body):
                break
            start = end - self.paragraph_overlap
        return para_chunks

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

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

            chunks_data = self._extract_all_chunks(content)
            if not chunks_data:
                return False

            embeddings = self._encode_texts([c["embed_text"] for c in chunks_data])
            file_size  = os.path.getsize(file_path)

            # Check if we need to create a new index or use existing
            if user_id not in self.indices:
                self.indices[user_id]  = faiss.IndexFlatIP(self.dimension)
                self.metadata[user_id] = []
            else:
                # Validate existing index dimension
                existing_dim = self.indices[user_id].d
                if existing_dim != self.dimension:
                    log("warning",
                        f"Dimension mismatch for user {user_id}: "
                        f"index has {existing_dim}, model expects {self.dimension}. "
                        f"Rebuilding index automatically.")
                    # Create new index with correct dimension
                    self.indices[user_id] = faiss.IndexFlatIP(self.dimension)
                    self.metadata[user_id] = []
                    # Also clear BM25 index as it needs to be rebuilt
                    self.bm25_indices.pop(user_id, None)

            self.indices[user_id].add(embeddings)
            for chunk in chunks_data:
                self.metadata[user_id].append({
                    "level":      chunk["level"],
                    "embed_text": chunk["embed_text"],
                    "raw_text":   chunk["raw_text"],
                    "content":    chunk["display_text"],
                    "filename":   filename,
                    "file_size":  file_size,
                    "file_path":  file_path,
                    "indexed_at": datetime.now().isoformat(),
                    "chapter":    chunk["chapter"],
                    "section":    chunk["section"],
                })

            all_raw = [m["raw_text"] for m in self.metadata[user_id]]
            self.bm25_indices[user_id] = _BM25Index(all_raw)

            self._save_user_index(user_id)

            counts = {lv: sum(1 for c in chunks_data if c["level"] == lv)
                      for lv in [LEVEL_PARAGRAPH, LEVEL_SECTION, LEVEL_SUMMARY]}
            log("info",
                f"HierV2: indexed {filename} — "
                f"{counts[LEVEL_PARAGRAPH]} paragraphs / "
                f"{counts[LEVEL_SECTION]} sections / "
                f"{counts[LEVEL_SUMMARY]} summaries")
            return True

        except Exception as e:
            log("error", f"HierV2: failed to index {filename}: {str(e)}")
            return False

    def delete_document(self, user_id: str, filename: str) -> bool:
        if user_id not in self.metadata:
            return False
        try:
            kept_meta = [m for m in self.metadata[user_id] if m["filename"] != filename]
            if len(kept_meta) == len(self.metadata[user_id]):
                return False
            if kept_meta:
                embeddings = self._encode_texts([m["embed_text"] for m in kept_meta])
                new_index  = faiss.IndexFlatIP(self.dimension)
                new_index.add(embeddings)
                self.indices[user_id]      = new_index
                self.metadata[user_id]     = kept_meta
                self.bm25_indices[user_id] = _BM25Index([m["raw_text"] for m in kept_meta])
            else:
                self.indices.pop(user_id, None)
                self.metadata.pop(user_id, None)
                self.bm25_indices.pop(user_id, None)
            self._save_user_index(user_id)
            return True
        except Exception as e:
            log("error", f"HierV2: failed to delete {filename}: {str(e)}")
            return False

    def clear_user_index(self, user_id: str) -> bool:
        try:
            self.indices.pop(user_id, None)
            self.metadata.pop(user_id, None)
            self.bm25_indices.pop(user_id, None)
            self._save_user_index(user_id)
            return True
        except Exception as e:
            log("error", f"HierV2: failed to clear index for {user_id}: {str(e)}")
            return False

    # ------------------------------------------------------------------
    # Search — inverted sieve cascade
    # ------------------------------------------------------------------

    def search(self, user_id: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Inverted sieve cascade — from most precise to most abstract:

        Stage 1 — BM25 on all chunks
            Confidence gate: top score dominates second score by bm25_dominance_ratio
            and exceeds bm25_min_score. Catches exact-wording factual queries.

        Stage 2 — Dense search restricted to PARAGRAPH chunks
            Confidence gate: top score exceeds dense_min_score AND stands out from
            the crowd by dense_margin_ratio × mean(top-k scores).

        Stage 3 — Dense search restricted to SECTION chunks
            Same confidence gate as Stage 2.

        Stage 4 — Dense search restricted to SUMMARY chunks
            No confidence gate — returns best result above floor_threshold,
            or an empty result if nothing clears even that bar.

        Each result includes the stage number (retrieval_pass) that fired.
        """
        if (
            self.dimension is None
            or user_id not in self.indices
            or self.indices[user_id].ntotal == 0
        ):
            return []

        # Validate dimension before search
        index_dim = self.indices[user_id].d
        if index_dim != self.dimension:
            log("error",
                f"Dimension mismatch in HierV2 search: index has {index_dim}, "
                f"model expects {self.dimension}. Please rebuild index.")
            return [{
                "filename": None,
                "score": 0.0,
                "bm25_score": 0.0,
                "content": "",
                "threshold_used": self.dense_min_score,
                "low_threshold_used": self.floor_threshold,
                "max_score_reached": 0.0,
                "level": None,
                "chapter": None,
                "section": None,
                "retrieval_pass": 0,
                "no_results": True,
                "error": f'Dimension mismatch: index={index_dim}, model={self.dimension}'
            }]

        try:
            all_meta = self.metadata[user_id]

            # Pre-compute per-level position maps (FAISS index position → level)
            positions_by_level: Dict[str, List[int]] = defaultdict(list)
            for pos, meta in enumerate(all_meta):
                positions_by_level[meta["level"]].append(pos)

            # ----------------------------------------------------------------
            # Stage 1 — BM25
            # ----------------------------------------------------------------
            if user_id in self.bm25_indices:
                bm25_results = self.bm25_indices[user_id].search(query, top_k=limit * 3)
                if self._bm25_confident(bm25_results):
                    log("debug", f"HierV2 Stage 1 (BM25) fired: top={bm25_results[0][1]:.3f}")
                    return [
                        self._build_result(
                            all_meta, idx,
                            dense_score=0.0,
                            bm25_score=score,
                            stage=1,
                        )
                        for idx, score in bm25_results[:limit]
                    ]

            # ----------------------------------------------------------------
            # Dense search — shared setup
            # ----------------------------------------------------------------
            query_emb   = self._encode_texts([query])
            n_candidates = min(len(all_meta), limit * 6)
            D, I = self.indices[user_id].search(query_emb, n_candidates)

            dense_scores_all: Dict[int, float] = {}
            max_dense = 0.0
            for dist, idx in zip(D[0], I[0]):
                if idx == -1:
                    continue
                dense_scores_all[int(idx)] = float(dist)
                if float(dist) > max_dense:
                    max_dense = float(dist)

            def scored_for_level(level: str) -> List[Tuple[int, float]]:
                """Return (pos, dense_score) for a given level, sorted desc."""
                return sorted(
                    [(pos, dense_scores_all[pos])
                     for pos in positions_by_level[level]
                     if pos in dense_scores_all],
                    key=lambda x: x[1], reverse=True
                )

            # ----------------------------------------------------------------
            # Stage 2 — Dense on PARAGRAPH chunks
            # ----------------------------------------------------------------
            para_scored = scored_for_level(LEVEL_PARAGRAPH)
            if para_scored:
                para_top_scores = [s for _, s in para_scored]
                if self._dense_confident(para_top_scores):
                    log("debug",
                        f"HierV2 Stage 2 (paragraph dense) fired: "
                        f"top={para_top_scores[0]:.3f}")
                    return [
                        self._build_result(
                            all_meta, idx,
                            dense_score=score,
                            bm25_score=0.0,
                            stage=2,
                        )
                        for idx, score in para_scored[:limit]
                    ]

            # ----------------------------------------------------------------
            # Stage 3 — Dense on SECTION chunks
            # ----------------------------------------------------------------
            sec_scored = scored_for_level(LEVEL_SECTION)
            if sec_scored:
                sec_top_scores = [s for _, s in sec_scored]
                if self._dense_confident(sec_top_scores):
                    log("debug",
                        f"HierV2 Stage 3 (section dense) fired: "
                        f"top={sec_top_scores[0]:.3f}")
                    return [
                        self._build_result(
                            all_meta, idx,
                            dense_score=score,
                            bm25_score=0.0,
                            stage=3,
                        )
                        for idx, score in sec_scored[:limit]
                    ]

            # ----------------------------------------------------------------
            # Stage 4 — Dense on SUMMARY chunks  (no confidence gate)
            # ----------------------------------------------------------------
            sum_scored = scored_for_level(LEVEL_SUMMARY)
            if sum_scored and sum_scored[0][1] >= self.floor_threshold:
                log("debug",
                    f"HierV2 Stage 4 (summary dense) fired: "
                    f"top={sum_scored[0][1]:.3f}")
                return [
                    self._build_result(
                        all_meta, idx,
                        dense_score=score,
                        bm25_score=0.0,
                        stage=4,
                    )
                    for idx, score in sum_scored[:limit]
                    if score >= self.floor_threshold
                ] or [self._empty_result(max_dense)]

            # Nothing found anywhere
            log("debug", f"HierV2: all stages exhausted (max dense={max_dense:.4f})")
            return [self._empty_result(max_dense)]

        except Exception as e:
            log("error", f"HierV2 search failed: {str(e)}", stacktrace=True)
            return []

    def _build_result(
        self,
        all_meta:    List[Dict],
        meta_idx:    int,
        dense_score: float,
        bm25_score:  float,
        stage:       int,
    ) -> Dict[str, Any]:
        meta = all_meta[meta_idx]
        return {
            "filename":          meta["filename"],
            "score":             dense_score,
            "bm25_score":        bm25_score,
            "content":           meta["content"],
            "threshold_used":    self.dense_min_score,
            "low_threshold_used": self.floor_threshold,
            "max_score_reached": dense_score,
            "level":             meta["level"],
            "chapter":           meta["chapter"],
            "section":           meta["section"],
            "retrieval_pass":    stage,
        }

    def _empty_result(self, max_dense: float = 0.0) -> Dict[str, Any]:
        return {
            "filename":          None,
            "score":             0.0,
            "bm25_score":        0.0,
            "content":           "",
            "threshold_used":    self.dense_min_score,
            "low_threshold_used": self.floor_threshold,
            "max_score_reached": max_dense,
            "level":             None,
            "chapter":           None,
            "section":           None,
            "retrieval_pass":    0,
            "no_results":        True,
        }

    # ------------------------------------------------------------------
    # Stats / metadata
    # ------------------------------------------------------------------

    def get_indexed_documents(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        documents = []
        for uid in ([user_id] if user_id else self.metadata.keys()):
            if uid in self.metadata:
                seen: set = set()
                for meta in self.metadata[uid]:
                    fn = meta["filename"]
                    if fn not in seen:
                        seen.add(fn)
                        documents.append({
                            "user_id":    uid,
                            "filename":   fn,
                            "indexed_at": meta["indexed_at"],
                            "size":       meta.get("file_size", 0),
                        })
        return documents

    def is_available(self) -> bool:
        return self.dimension is not None

    def get_stats(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        if user_id:
            user_meta = self.metadata.get(user_id, [])
            return {
                "documents_indexed": len({m["filename"] for m in user_meta}),
                "total_chunks":      len(user_meta),
                "paragraph_chunks":  sum(1 for m in user_meta if m["level"] == LEVEL_PARAGRAPH),
                "section_chunks":    sum(1 for m in user_meta if m["level"] == LEVEL_SECTION),
                "summary_chunks":    sum(1 for m in user_meta if m["level"] == LEVEL_SUMMARY),
                "bm25_ready":        user_id in self.bm25_indices,
                "engine_type":       self.engine_type,
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
            "model_name":              self.model_name,
            "dimension":               self.dimension,
        }


# ---------------------------------------------------------------------------
# Lightweight pure-Python BM25 — zero external dependencies
# ---------------------------------------------------------------------------

class _BM25Index:
    """
    Okapi BM25 sparse retrieval.
    k1 : term frequency saturation  (typical 1.2–2.0)
    b  : length normalization        (typical 0.0–1.0)
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
        doc = self.tokenized[doc_idx]
        dl  = self.doc_lengths[doc_idx]
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
        """Return [(doc_idx, bm25_score)] sorted descending, zeros excluded."""
        terms = self._tokenize(query)
        if not terms:
            return []
        scored = [(i, self._score(terms, i)) for i in range(self.corpus_size)]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [(i, s) for i, s in scored[:top_k] if s > 0]
