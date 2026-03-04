"""
Hierarchical FAISS RAG Engine v2 — 3-level hierarchy + BM25 hybrid + RRF fusion

Architecture
------------
Indexing — three granularity levels per document:
  - PARAGRAPH : fine-grained chunks (~300 chars, overlap 50), for precise factual queries
  - SECTION   : one chunk per ## markdown section, for thematic queries
  - SUMMARY   : one standalone chunk per chapter summary (>[!Résumé] block), for broad queries

Search — hybrid pipeline:
  1. Dense search (FAISS cosinus) across all three levels
  2. BM25 sparse search across all chunks (exact token matching)
  3. Reciprocal Rank Fusion (RRF) to merge both ranked lists
  4. Double-threshold: high_threshold for confident results,
     low_threshold fallback if nothing passes the high bar

All code and comments in English.
No Streamlit dependency. Config is injected at construction time.
"""

import os
import re
import math
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

# Chunk type constants
LEVEL_PARAGRAPH = "paragraph"
LEVEL_SECTION = "section"
LEVEL_SUMMARY = "summary"

# RRF constant (standard value, controls rank smoothing)
RRF_K = 60


class FaissHierarchicalV2RAGEngine(RAGEngine):
    """
    3-level hierarchical RAG engine with BM25 + dense hybrid search and RRF fusion.

    Replaces the previous faiss_hierarchical_v2 attempt (retired).

    Config keys (all optional):
        index_path          str     Storage path.            Default: ./data/hier_v2_indexes
        paragraph_size      int     Paragraph chunk size.    Default: 300
        paragraph_overlap   int     Paragraph overlap.       Default: 50
        high_threshold      float   Primary dense threshold. Default: 0.40
        low_threshold       float   Fallback dense threshold. Default: 0.18
        bm25_weight         float   Weight of BM25 in RRF.  Default: 0.5
        dense_weight        float   Weight of dense in RRF. Default: 0.5
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__("faiss_hierarchical_v2")
        self.description = (
            "3-level hierarchical RAG (paragraph / section / summary) "
            "with BM25 sparse + FAISS dense hybrid search and RRF fusion"
        )

        config = config or {}

        self.index_path = Path(config.get("index_path", "./data/hier_v2_indexes"))
        self.index_path.mkdir(parents=True, exist_ok=True)

        self.paragraph_size = config.get("paragraph_size", 300)
        self.paragraph_overlap = config.get("paragraph_overlap", 50)
        self.high_threshold = config.get("high_threshold", 0.40)
        self.low_threshold = config.get("low_threshold", 0.18)
        self.bm25_weight = config.get("bm25_weight", 0.5)
        self.dense_weight = config.get("dense_weight", 0.5)

        # RRF level boosts — summary and section chunks are boosted relative to paragraphs
        # to prevent the higher volume of paragraph chunks from drowning them out.
        self.level_boost: Dict[str, float] = config.get("level_boost", {
            LEVEL_SUMMARY:   1.6,
            LEVEL_SECTION:   1.2,
            LEVEL_PARAGRAPH: 1.0,
        })

        # How many result slots to reserve for summary chunks in pass 1.
        # e.g. with limit=5 and summary_slots=1: up to 4 content/paragraph + 1 summary.
        # Set to 0 to disable reserved slots.
        self.summary_slots = config.get("summary_slots", 1)

        # Alias for compatibility with benchmark tooling
        self.similarity_threshold = self.high_threshold

        log("debug", f"HierV2 config: paragraph_size={self.paragraph_size}, "
                     f"high={self.high_threshold}, low={self.low_threshold}")

        try:
            self.dimension = len(get_embedding(""))
            log("info", f"HierV2 embeddings initialized (dim: {self.dimension})")
        except Exception as e:
            log("error", f"HierV2 failed to initialize embeddings: {str(e)}")
            self.dimension = None

        # Per-user FAISS index and metadata list
        self.indices: Dict[str, faiss.IndexFlatIP] = {}
        self.metadata: Dict[str, List[Dict[str, Any]]] = {}

        # Per-user BM25 index
        self.bm25_indices: Dict[str, "_BM25Index"] = {}

        self._load_indices()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_indices(self):
        for index_file in self.index_path.glob("*_hv2.index"):
            user_id = index_file.stem.replace("_hv2", "")
            try:
                index = faiss.read_index(str(index_file))
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
        index_file = self.index_path / f"{user_id}_hv2.index"
        meta_file = self.index_path / f"{user_id}_hv2_meta.pkl"
        bm25_file = self.index_path / f"{user_id}_hv2_bm25.pkl"

        if user_id in self.indices and self.indices[user_id].ntotal > 0:
            try:
                faiss.write_index(self.indices[user_id], str(index_file))
                with open(meta_file, "wb") as f:
                    pickle.dump(self.metadata[user_id], f)
                if user_id in self.bm25_indices:
                    with open(bm25_file, "wb") as f:
                        pickle.dump(self.bm25_indices[user_id], f)
            except Exception as e:
                log("error", f"HierV2: failed to save index for {user_id}: {str(e)}")
        else:
            for fp in [index_file, meta_file, bm25_file]:
                if fp.exists():
                    fp.unlink()
            self.indices.pop(user_id, None)
            self.metadata.pop(user_id, None)
            self.bm25_indices.pop(user_id, None)

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    def _encode_texts(self, texts: List[str]) -> np.ndarray:
        embeddings = np.array(get_embeddings(texts), dtype=np.float32)
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return embeddings / norms

    # ------------------------------------------------------------------
    # Markdown parsing — 3 levels
    # ------------------------------------------------------------------

    def _extract_all_chunks(self, content: str) -> List[Dict[str, str]]:
        """
        Parse a structured markdown document and produce chunks at three levels:
          - LEVEL_SUMMARY   : one per chapter (the >[!Résumé] block + concepts)
          - LEVEL_SECTION   : one per ## section, embed enriched with chapter summary
          - LEVEL_PARAGRAPH : fine splits (~paragraph_size chars) of each section body
        """
        lines = content.splitlines()
        chunks: List[Dict[str, str]] = []

        current_chapter = ""
        current_summary = ""
        current_concepts: List[str] = []
        current_section = "Introduction"
        current_lines: List[str] = []
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
            line = lines[i]
            stripped = line.strip()

            if stripped.startswith("# "):
                flush()
                flush_summary()
                current_chapter = stripped[2:].strip()
                current_summary = ""
                current_concepts = []
                current_section = "Introduction"
                current_lines = []
                in_block = None

            elif stripped.startswith(">[!Résumé]") or stripped.startswith(">[!Resume]"):
                in_block = "summary"
                current_summary = ""

            elif stripped.startswith(">[!concepts]") or stripped.startswith(">[!Concepts]"):
                in_block = "concepts"
                current_concepts = []

            elif stripped.startswith("## "):
                flush()
                current_section = stripped[3:].strip()
                in_block = None

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
                "level": LEVEL_SECTION,
                "embed_text": content,
                "display_text": content,
                "chapter": "Full document",
                "section": "Main content",
                "raw_text": content,
            })

        return chunks

    def _make_summary_chunk(self, chapter: str, summary: str, concepts: List[str]) -> Dict:
        text = summary.strip()
        concept_str = ", ".join(concepts)
        embed_text = f"{text}\n\n{concept_str}".strip() if concept_str else text
        display_text = f"**{chapter} — Chapter summary**\n\n{text}"
        if concept_str:
            display_text += f"\n\nKey concepts: {concept_str}"
        return {
            "level": LEVEL_SUMMARY,
            "embed_text": embed_text,
            "display_text": display_text,
            "chapter": chapter,
            "section": "",
            "raw_text": text,
        }

    def _make_section_chunk(
        self, chapter: str, summary: str, concepts: List[str],
        section: str, body: str
    ) -> Dict:
        """
        Section embed_text: summary + concepts + body.
        Including the summary anchors the section in its chapter context
        while keeping the full body for thematic matching.
        """
        parts = []
        if summary.strip():
            parts.append(summary.strip())
        if concepts:
            parts.append(", ".join(concepts))
        parts.append(body)
        embed_text = "\n\n".join(parts)
        display_text = f"**{chapter}**\n**{section}**\n\n{body}"
        return {
            "level": LEVEL_SECTION,
            "embed_text": embed_text,
            "display_text": display_text,
            "chapter": chapter,
            "section": section,
            "raw_text": body,
        }

    def _split_paragraphs(
        self, chapter: str, summary: str, concepts: List[str],
        section: str, body: str
    ) -> List[Dict]:
        """
        Split section body into fine-grained paragraph chunks with overlap.
        Each paragraph embed_text is anchored by the chapter summary.
        """
        if not body.strip():
            return []

        para_chunks = []
        start = 0
        while start < len(body):
            end = start + self.paragraph_size
            text = body[start:end].strip()
            if len(text) > 30:
                parts = []
                if summary.strip():
                    parts.append(summary.strip())
                parts.append(text)
                embed_text = "\n\n".join(parts)
                display_text = f"**{chapter}**\n**{section}**\n\n{text}"
                para_chunks.append({
                    "level": LEVEL_PARAGRAPH,
                    "embed_text": embed_text,
                    "display_text": display_text,
                    "chapter": chapter,
                    "section": section,
                    "raw_text": text,
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
        user_id: str,
        filename: str,
        file_path: str,
        content: Optional[str] = None,
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
            file_size = os.path.getsize(file_path)

            if user_id not in self.indices:
                self.indices[user_id] = faiss.IndexFlatIP(self.dimension)
                self.metadata[user_id] = []

            self.indices[user_id].add(embeddings)
            for chunk in chunks_data:
                self.metadata[user_id].append({
                    "level": chunk["level"],
                    "embed_text": chunk["embed_text"],
                    "raw_text": chunk["raw_text"],
                    "content": chunk["display_text"],
                    "filename": filename,
                    "file_size": file_size,
                    "file_path": file_path,
                    "indexed_at": datetime.now().isoformat(),
                    "chapter": chunk["chapter"],
                    "section": chunk["section"],
                })

            # Rebuild BM25 over all chunks for this user
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
                new_index = faiss.IndexFlatIP(self.dimension)
                new_index.add(embeddings)
                self.indices[user_id] = new_index
                self.metadata[user_id] = kept_meta
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
    # Search — dense + BM25 hybrid with RRF fusion
    # ------------------------------------------------------------------

    def search(self, user_id: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Hybrid search pipeline:

        1. Dense FAISS search  → ranked list (score, meta_idx)
        2. BM25 search         → ranked list (score, meta_idx)
        3. Boosted RRF fusion  → summary/section chunks are weighted higher than
                                 paragraphs to prevent volume dilution
        4. Double-threshold with reserved summary slot:
             Pass 1 — split limit into (limit - summary_slots) non-summary slots
                      + summary_slots slots reserved for the best summary chunk.
                      All candidates must pass dense_score >= high_threshold.
             Pass 2 — fallback: best RRF candidate if dense_score >= low_threshold

        Each result exposes score (dense), rrf_score, bm25_score, level, retrieval_pass.
        """
        if (
            self.dimension is None
            or user_id not in self.indices
            or self.indices[user_id].ntotal == 0
        ):
            return []

        try:
            all_meta = self.metadata[user_id]
            n_candidates = min(len(all_meta), limit * 8)

            # --- Dense FAISS search ---
            query_emb = self._encode_texts([query])
            D, I = self.indices[user_id].search(query_emb, n_candidates)

            dense_ranked: List[Tuple[int, float]] = []
            dense_scores: Dict[int, float] = {}
            max_dense_score = 0.0

            for dist, idx in zip(D[0], I[0]):
                if idx == -1:
                    continue
                score = float(dist)
                dense_ranked.append((int(idx), score))
                dense_scores[int(idx)] = score
                if score > max_dense_score:
                    max_dense_score = score

            # --- BM25 search ---
            bm25_ranked: List[Tuple[int, float]] = []
            bm25_scores: Dict[int, float] = {}

            if user_id in self.bm25_indices:
                for idx, score in self.bm25_indices[user_id].search(query, n_candidates):
                    bm25_ranked.append((idx, score))
                    bm25_scores[idx] = score

            # --- Boosted RRF fusion ---
            # Summary and section chunks receive a multiplier on their RRF contribution
            # so they can compete against the larger volume of paragraph chunks.
            rrf_scores: Dict[int, float] = defaultdict(float)
            for rank, (idx, _) in enumerate(dense_ranked):
                boost = self.level_boost.get(all_meta[idx]["level"], 1.0)
                rrf_scores[idx] += self.dense_weight * boost / (RRF_K + rank + 1)
            for rank, (idx, _) in enumerate(bm25_ranked):
                boost = self.level_boost.get(all_meta[idx]["level"], 1.0)
                rrf_scores[idx] += self.bm25_weight * boost / (RRF_K + rank + 1)

            fused = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)

            def build_result(meta_idx: int, rrf_score: float, pass_num: int) -> Dict:
                meta = all_meta[meta_idx]
                return {
                    "filename": meta["filename"],
                    "score": dense_scores.get(meta_idx, 0.0),
                    "rrf_score": rrf_score,
                    "bm25_score": bm25_scores.get(meta_idx, 0.0),
                    "content": meta["content"],
                    "threshold_used": self.high_threshold,
                    "low_threshold_used": self.low_threshold,
                    "max_score_reached": max_dense_score,
                    "level": meta["level"],
                    "chapter": meta["chapter"],
                    "section": meta["section"],
                    "retrieval_pass": pass_num,
                }

            # --- Pass 1: high threshold, with reserved summary slot ---
            #
            # Strategy: fill (limit - summary_slots) slots with the best non-summary
            # chunks, then fill summary_slots with the best summary chunk(s).
            # This guarantees that a relevant chapter summary is never crowded out
            # by the sheer volume of paragraph chunks.
            #
            # If summary_slots == 0, this degenerates to the plain top-limit behavior.

            above = [
                (idx, rrf) for idx, rrf in fused
                if dense_scores.get(idx, 0.0) >= self.high_threshold
            ]

            if above:
                non_summary_limit = max(limit - self.summary_slots, 1)

                non_summary = [
                    (idx, rrf) for idx, rrf in above
                    if all_meta[idx]["level"] != LEVEL_SUMMARY
                ][:non_summary_limit]

                summary_candidates = [
                    (idx, rrf) for idx, rrf in above
                    if all_meta[idx]["level"] == LEVEL_SUMMARY
                ][:self.summary_slots]

                # Merge: summary first so it's visible to the LLM, then content
                merged = summary_candidates + non_summary

                if merged:
                    results = [build_result(idx, rrf, 1) for idx, rrf in merged]
                    log("debug",
                        f"HierV2 pass 1: {len(results)} results "
                        f"({len(summary_candidates)} summary + {len(non_summary)} content)")
                    return results

            # --- Pass 2: fallback — best RRF candidate above low threshold ---
            for idx, rrf in fused:
                if dense_scores.get(idx, 0.0) >= self.low_threshold:
                    log("debug", f"HierV2 pass 2 fallback: dense={dense_scores.get(idx, 0.0):.4f}")
                    return [build_result(idx, rrf, 2)]

            log("debug", f"HierV2: no results above low_threshold (max dense={max_dense_score:.4f})")
            return [{
                "filename": None,
                "score": 0.0,
                "rrf_score": 0.0,
                "bm25_score": 0.0,
                "content": "",
                "threshold_used": self.high_threshold,
                "low_threshold_used": self.low_threshold,
                "max_score_reached": max_dense_score,
                "level": None,
                "chapter": None,
                "section": None,
                "retrieval_pass": 0,
                "no_results": True,
            }]

        except Exception as e:
            log("error", f"HierV2 search failed: {str(e)}", stacktrace=True)
            return []

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
                            "user_id": uid,
                            "filename": fn,
                            "indexed_at": meta["indexed_at"],
                            "size": meta.get("file_size", 0),
                        })
        return documents

    def is_available(self) -> bool:
        return self.dimension is not None

    def get_stats(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        if user_id:
            user_meta = self.metadata.get(user_id, [])
            return {
                "documents_indexed": len({m["filename"] for m in user_meta}),
                "total_chunks": len(user_meta),
                "paragraph_chunks": sum(1 for m in user_meta if m["level"] == LEVEL_PARAGRAPH),
                "section_chunks": sum(1 for m in user_meta if m["level"] == LEVEL_SECTION),
                "summary_chunks": sum(1 for m in user_meta if m["level"] == LEVEL_SUMMARY),
                "bm25_ready": user_id in self.bm25_indices,
                "engine_type": self.engine_type,
            }
        total_docs = sum(len({m["filename"] for m in v}) for v in self.metadata.values())
        total_chunks = sum(len(v) for v in self.metadata.values())
        return {
            "total_documents_indexed": total_docs,
            "total_chunks": total_chunks,
            "users_with_index": len(self.metadata),
            "engine_type": self.engine_type,
        }


# ---------------------------------------------------------------------------
# Lightweight pure-Python BM25 — zero external dependencies
# ---------------------------------------------------------------------------

class _BM25Index:
    """
    Okapi BM25 sparse retrieval.

    k1 : term frequency saturation  (typical: 1.2 – 2.0)
    b  : length normalization        (typical: 0.0 – 1.0)
    """

    def __init__(self, texts: List[str], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus_size = len(texts)
        self.tokenized: List[List[str]] = [self._tokenize(t) for t in texts]
        self.doc_lengths = [len(d) for d in self.tokenized]
        self.avgdl = sum(self.doc_lengths) / max(self.corpus_size, 1)
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
        dl = self.doc_lengths[doc_idx]
        tf_map: Dict[str, int] = defaultdict(int)
        for term in doc:
            tf_map[term] += 1
        score = 0.0
        for term in query_terms:
            if term not in tf_map:
                continue
            tf = tf_map[term]
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
