"""
Hybrid RAG Engine — Experimental / Configurable

Combines multiple retrieval strategies, all togglable via config:

  hyde            : HyDE — embed a hypothetical answer instead of the raw query
  contextual      : prepend a per-chunk LLM-generated context summary at index time
  sentence_window : index at sentence level, return ±window_size sentences as context
  bm25_hybrid     : combine BM25 keyword score with cosine score (alpha blend)
  dynamic_chunks  : try multiple chunk sizes at query time, keep best-scoring hit per size
  use_summaries   : if the doc has >[!Résumé] blocks, inject them as extra high-weight chunks
  structured_sheet: parse H2 sections as atomic units; embed signal fields (Question +
                    Concept clé + Mots-clés), return the full sheet as display context.
                    Designed for documents following the Question/Concept clé/Pertinence/
                    Développement/Mots-clés schema. Disabling HyDE is recommended with
                    this strategy since the Question field already acts as a query expander.

No Streamlit dependency. Config is injected at construction time.

QUICK CONFIG REFERENCE (engines.hybrid section in config.json):
------------------------------------------------------------
{
  "hybrid": {
    "enabled": true,
    "index_path": "data/hybrid_indexes",
    "similarity_threshold": 0.25,

    "chunk_strategy": "sentence_window",   # or "structured_sheet"
    "chunk_size": 400,
    "chunk_overlap": 60,
    "sentence_window_size": 3,
    "dynamic_chunk_sizes": [150, 300, 500],

    "hyde": true,
    "hyde_prompt_key": "rag_manager.hyde_prompt",
    "bm25_hybrid": true,
    "bm25_alpha": 0.5,
    "use_summaries": true,

    "contextual_chunking": false,
    "contextual_model": null
  }
}

STRUCTURED SHEET STRATEGY NOTES:
---------------------------------
Each H2 section is parsed into one chunk where:
  - embed_text  = Question + Concept clé + Mots-clés + H1 group title
    (lightweight signal optimised for cosine similarity against student queries)
  - display_text = full H2 section content
    (returned verbatim to the LLM as context)

The >[!Résumé] and >[!concepts] blocks at H1 level are handled by _extract_summaries
as before and injected as high-weight summary chunks when use_summaries=True.

PROMPT KEYS (prompts.en.yaml / prompts.fr.yaml):
------------------------------------------------
Add under rag_manager:
  hyde_prompt: |
    You are an expert tutor. Write a short factual paragraph (3-5 sentences)
    that directly answers the following question as if found in a training document.
    Question: {query}
    Answer:
"""

from __future__ import annotations

import os
import re
import json
import pickle
import numpy as np
import faiss
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from modules.rag_manager.rag_engine import RAGEngine
from shared.common import get_embedding, get_embeddings
from core.logging import log


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cosine_norm(vecs: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vecs / norms


class _BM25:
    def __init__(self, tokenised_corpus: List[List[str]]):
        try:
            from rank_bm25 import BM25Okapi
            self._bm25 = BM25Okapi(tokenised_corpus)
            self._ok = True
        except ImportError:
            log("warning", "rank_bm25 not installed — BM25 hybrid disabled. pip install rank-bm25")
            self._ok = False

    def scores(self, query_tokens: List[str], n: int) -> np.ndarray:
        if not self._ok:
            return np.zeros(n)
        raw = np.array(self._bm25.get_scores(query_tokens), dtype=np.float32)
        mx = raw.max()
        return raw / mx if mx > 0 else raw

    @property
    def available(self) -> bool:
        return self._ok


def _tokenise(text: str) -> List[str]:
    return re.findall(r"[a-zA-ZÀ-ÿ0-9]+", text.lower())


_SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-Ý\"])")


def _split_sentences(text: str) -> List[str]:
    parts = _SENT_RE.split(text.strip())
    return [s.strip() for s in parts if s.strip()]


# ---------------------------------------------------------------------------
# Structured sheet parser helpers
# ---------------------------------------------------------------------------

# Field labels as they appear in the markdown (bold prefix pattern).
# Supports both French field names used in the training corpus and
# potential English variants so the engine stays forward-compatible.
_SHEET_FIELD_RE = re.compile(
    r"^\*\*(Question|Concept clé|Concept clé|Pertinence|Développement|Mots-clés|Source)\s*:\*\*\s*(.*)$",
    re.IGNORECASE,
)

# Canonical field keys (normalised from the regex match group)
_FIELD_ALIASES: Dict[str, str] = {
    "question":      "question",
    "concept clé":   "concept",
    "concept clé":   "concept",
    "pertinence":    "relevance",
    "développement": "development",
    "mots-clés":     "keywords",
    "source":        "source",
}


def _parse_sheet_fields(block: str) -> Dict[str, str]:
    """
    Extract named fields from a single H2 block.
    Multi-line field values are captured until the next bold field marker.
    Returns a dict with keys: question, concept, relevance, development, keywords, source.
    """
    fields: Dict[str, str] = {}
    current_key: Optional[str] = None
    buffer: List[str] = []

    def _flush():
        if current_key:
            fields[current_key] = " ".join(buffer).strip()

    for line in block.splitlines():
        m = _SHEET_FIELD_RE.match(line.strip())
        if m:
            _flush()
            raw_key = m.group(1).strip().lower()
            current_key = _FIELD_ALIASES.get(raw_key)
            first_value = m.group(2).strip().strip('"')
            buffer = [first_value] if first_value else []
        elif current_key:
            stripped = line.strip()
            if stripped:
                buffer.append(stripped)

    _flush()
    return fields


def _build_embed_text(fields: Dict[str, str], h1_title: str, h2_title: str) -> str:
    """
    Compose the signal text used for embedding.

    Included fields and rationale:
      - H1 group title   : thematic anchor, helps cross-sheet disambiguation
      - H2 sheet title   : specific topic label
      - Question         : direct query-intent match
      - Key concept      : TL;DR semantic core
      - Relevance        : pedagogical context — explains WHY this sheet matters,
                           bridges the gap between abstract concepts and student
                           queries about practical application
      - Keywords         : explicit vocabulary for BM25 and cosine coverage

    Développement is intentionally excluded: its verbosity dilutes the
    embedding signal without adding retrieval precision.
    """
    parts = []
    if h1_title:
        parts.append(f"Group: {h1_title}")
    if h2_title:
        parts.append(f"Sheet: {h2_title}")
    if fields.get("question"):
        parts.append(f"Question: {fields['question']}")
    if fields.get("concept"):
        parts.append(f"Key concept: {fields['concept']}")
    if fields.get("relevance"):
        parts.append(f"Relevance: {fields['relevance']}")
    if fields.get("keywords"):
        parts.append(f"Keywords: {fields['keywords']}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

class HybridRAGEngine(RAGEngine):
    """
    Configurable hybrid RAG engine.
    All features are independently togglable via config or update_config().
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None, engine_id: Optional[str] = None):
        super().__init__("hybrid", engine_id)
        self.description = config.get("description", "Hybrid RAG: HyDE + sentence-window + BM25 + contextual chunks") if config else "Hybrid RAG: HyDE + sentence-window + BM25 + contextual chunks"
        self._apply_config(config or {})

        self.indices:  Dict[str, faiss.IndexFlatIP] = {}
        self.metadata: Dict[str, List[Dict[str, Any]]] = {}
        self.bm25s:    Dict[str, Optional[_BM25]] = {}

        try:
            self.dimension = len(get_embedding("test"))
            log("info", f"HybridRAGEngine: embedding dim={self.dimension}")
        except Exception as e:
            log("error", f"HybridRAGEngine: failed to get embedding dim: {e}")
            self.dimension = None

        self._load_indices()
        self._log_active_config()

    # ---------------------------------------------------------------- config

    def _apply_config(self, cfg: Dict[str, Any]) -> None:
        """Write all config values onto self. Called at init and by update_config."""
        default_path = f"data/hybrid_indexes/{self.engine_id}" if hasattr(self, "engine_id") else "data/hybrid_indexes"
        self.index_path           = Path(cfg.get("index_path", default_path))
        self.index_path.mkdir(parents=True, exist_ok=True)
        self.similarity_threshold = cfg.get("similarity_threshold", 0.25)

        self.chunk_strategy       = cfg.get("chunk_strategy", "sentence_window")
        self.chunk_size           = int(cfg.get("chunk_size", 400))
        self.chunk_overlap        = int(cfg.get("chunk_overlap", 60))
        self.sentence_window_size = int(cfg.get("sentence_window_size", 3))
        self.dynamic_chunk_sizes  = cfg.get("dynamic_chunk_sizes", [150, 300, 500])

        self.use_hyde             = bool(cfg.get("hyde", True))
        self.hyde_prompt_key      = cfg.get("hyde_prompt_key", "rag_manager.hyde_prompt")
        self.hyde_use_summaries   = bool(cfg.get("hyde_use_summaries", False))
        self.use_bm25_hybrid      = bool(cfg.get("bm25_hybrid", True))
        self.bm25_alpha           = float(cfg.get("bm25_alpha", 0.5))
        self.bm25_rerank_only     = bool(cfg.get("bm25_rerank_only", True))
        self.use_summaries        = bool(cfg.get("use_summaries", True))

        self.use_contextual       = bool(cfg.get("contextual_chunking", False))
        self.contextual_model     = cfg.get("contextual_model", None)

    def _log_active_config(self) -> None:
        log("debug", (
            f"HybridRAGEngine [{self.engine_id}] ready — strategy={self.chunk_strategy} "
            f"hyde={self.use_hyde}"
            + (f"(+summaries)" if self.use_hyde and self.hyde_use_summaries else "")
            + f" bm25={self.use_bm25_hybrid} "
            f"contextual={self.use_contextual} summaries={self.use_summaries} "
            f"threshold={self.similarity_threshold} path={self.index_path}"
        ))

    def get_config(self) -> Dict[str, Any]:
        """Return all tunable parameters as a plain dict (used by admin UI)."""
        return {
            "similarity_threshold": self.similarity_threshold,
            "chunk_strategy":       self.chunk_strategy,
            "chunk_size":           self.chunk_size,
            "chunk_overlap":        self.chunk_overlap,
            "sentence_window_size": self.sentence_window_size,
            "dynamic_chunk_sizes":  self.dynamic_chunk_sizes,
            "hyde":                 self.use_hyde,
            "hyde_prompt_key":      self.hyde_prompt_key,
            "hyde_use_summaries":   self.hyde_use_summaries,
            "bm25_hybrid":          self.use_bm25_hybrid,
            "bm25_alpha":           self.bm25_alpha,
            "bm25_rerank_only":     self.bm25_rerank_only,
            "use_summaries":        self.use_summaries,
            "contextual_chunking":  self.use_contextual,
            "contextual_model":     self.contextual_model,
        }

    def update_config(self, overrides: Dict[str, Any]) -> None:
        """
        Apply runtime overrides without reconstructing the engine.
        - Retrieval params (threshold, hyde, bm25_alpha…) take effect immediately.
        - Chunking params take effect on the next index_document call.
        """
        current = self.get_config()
        current.update(overrides)
        current["index_path"] = str(self.index_path)
        self._apply_config(current)
        self._log_active_config()

    # ---------------------------------------------------------------- prompt

    def _get_hyde_prompt(self) -> Optional[str]:
        """
        Resolve HyDE prompt text.
        1. Try get_prompt(hyde_prompt_key) from shared.common.
        2. Return None → caller uses built-in fallback.
        """
        if self.hyde_prompt_key:
            try:
                from shared.common import get_prompt
                text = get_prompt(self.hyde_prompt_key)
                if text:
                    return text
            except Exception as e:
                log("debug", f"HybridRAG: could not load hyde prompt '{self.hyde_prompt_key}': {e}")
        return None

    # ---------------------------------------------------------------- persistence

    def _index_file(self, uid: str) -> Path: return self.index_path / f"{uid}_hybrid.index"
    def _meta_file(self, uid: str)  -> Path: return self.index_path / f"{uid}_hybrid_meta.pkl"
    def _model_file(self, uid: str) -> Path: return self.index_path / f"{uid}_hybrid_model.json"

    def _load_indices(self):
        for f in self.index_path.glob("*_hybrid.index"):
            uid = f.stem.replace("_hybrid", "")
            model_f = self._model_file(uid)
            if model_f.exists():
                try:
                    with open(model_f) as fh:
                        meta = json.load(fh)
                    if meta.get("dimension") != self.dimension:
                        log("warning", f"HybridRAG: stale index for {uid} (dim mismatch) — skipping")
                        continue
                except Exception as e:
                    log("error", f"HybridRAG: cannot read model meta for {uid}: {e}")
                    continue
            try:
                idx = faiss.read_index(str(f))
                self.indices[uid] = idx
                meta_f = self._meta_file(uid)
                if meta_f.exists():
                    with open(meta_f, "rb") as fh:
                        self.metadata[uid] = pickle.load(fh)
                self._rebuild_bm25(uid)
                log("debug", f"HybridRAG: loaded index for {uid} ({idx.ntotal} vectors)")
            except Exception as e:
                log("error", f"HybridRAG: failed to load index for {uid}: {e}")

    def _save_index(self, user_id: str):
        if user_id in self.indices and self.indices[user_id].ntotal > 0:
            try:
                faiss.write_index(self.indices[user_id], str(self._index_file(user_id)))
                with open(self._meta_file(user_id), "wb") as fh:
                    pickle.dump(self.metadata[user_id], fh)
                with open(self._model_file(user_id), "w") as fh:
                    json.dump({"dimension": self.dimension,
                               "saved_at": datetime.now().isoformat()}, fh)
            except Exception as e:
                log("error", f"HybridRAG: failed to save index for {user_id}: {e}")
        else:
            for p in [self._index_file(user_id), self._meta_file(user_id),
                      self._model_file(user_id)]:
                if p.exists():
                    p.unlink()
            self.indices.pop(user_id, None)
            self.metadata.pop(user_id, None)
            self.bm25s.pop(user_id, None)

    def _rebuild_bm25(self, user_id: str):
        if not self.use_bm25_hybrid:
            self.bm25s[user_id] = None
            return
        meta = self.metadata.get(user_id, [])
        if not meta:
            self.bm25s[user_id] = None
            return
        corpus = [_tokenise(m["embed_text"]) for m in meta]
        self.bm25s[user_id] = _BM25(corpus)

    # ---------------------------------------------------------------- chunking

    def _extract_summaries(self, content: str) -> List[Dict]:
        chunks, current_chapter, in_block, block_lines = [], "", None, []
        for line in content.splitlines():
            s = line.strip()
            if s.startswith("# "):
                current_chapter = s[2:].strip(); in_block = None; block_lines = []
            elif s.startswith(">[!Résumé]") or s.startswith(">[!concepts]"):
                if block_lines and in_block:
                    chunks.append({"embed_text": f"[{in_block.upper()}] {current_chapter}\n" + "\n".join(block_lines),
                                   "display_text": "\n".join(block_lines), "chunk_type": in_block,
                                   "chapter": current_chapter, "is_summary": True})
                in_block = "résumé" if "Résumé" in s else "concepts"; block_lines = []
            elif in_block and line.startswith(">"):
                block_lines.append(line.lstrip(">").strip())
            else:
                if block_lines and in_block:
                    chunks.append({"embed_text": f"[{in_block.upper()}] {current_chapter}\n" + "\n".join(block_lines),
                                   "display_text": "\n".join(block_lines), "chunk_type": in_block,
                                   "chapter": current_chapter, "is_summary": True})
                in_block = None; block_lines = []
        return chunks

    def _fixed_chunks(self, content: str, filename: str) -> List[Dict]:
        chunks, start = [], 0
        while start < len(content):
            text = content[start:start + self.chunk_size].strip()
            if len(text) > 30:
                chunks.append({"embed_text": text, "display_text": text, "chunk_type": "fixed",
                                "filename": filename, "is_summary": False})
            if start + self.chunk_size >= len(content): break
            start += self.chunk_size - self.chunk_overlap
        return chunks

    def _sentence_window_chunks(self, content: str, filename: str) -> List[Dict]:
        sentences = _split_sentences(content)
        w = self.sentence_window_size
        chunks = []
        for i, sent in enumerate(sentences):
            if len(sent) < 20: continue
            window = " ".join(sentences[max(0, i - w):min(len(sentences), i + w + 1)])
            chunks.append({"embed_text": sent, "display_text": window,
                           "chunk_type": "sentence_window", "filename": filename,
                           "sentence_index": i, "is_summary": False})
        return chunks

    def _sentence_chunks(self, content: str, filename: str) -> List[Dict]:
        return [{"embed_text": s, "display_text": s, "chunk_type": "sentence",
                 "filename": filename, "sentence_index": i, "is_summary": False}
                for i, s in enumerate(_split_sentences(content)) if len(s) > 20]

    def _dynamic_chunks(self, content: str, filename: str) -> List[Dict]:
        chunks = []
        for size in self.dynamic_chunk_sizes:
            step, start = max(size // 2, 1), 0
            while start < len(content):
                text = content[start:start + size].strip()
                if len(text) > 30:
                    chunks.append({"embed_text": text, "display_text": text,
                                   "chunk_type": f"dynamic_{size}", "filename": filename,
                                   "is_summary": False})
                if start + size >= len(content): break
                start += step
        return chunks

    def _structured_sheet_chunks(self, content: str, filename: str) -> List[Dict]:
        """
        Parse H1/H2 structure into atomic sheet chunks.

        Each H2 section becomes one chunk:
          - embed_text  : signal fields only (Question + Concept clé + Mots-clés + titles)
                          optimised for cosine similarity against student queries
          - display_text: full H2 section text returned verbatim as LLM context

        H1 titles are tracked as group context but do not produce chunks themselves
        (>[!Résumé] and >[!concepts] blocks are handled by _extract_summaries).

        Sheets with no parseable signal fields fall back to embedding the full block
        so no content is silently dropped.
        """
        chunks: List[Dict] = []
        current_h1: str = ""
        current_h2: str = ""
        block_lines: List[str] = []

        def _flush_block() -> None:
            if not current_h2 or not block_lines:
                return
            block_text = "\n".join(block_lines).strip()
            if not block_text:
                return
            fields = _parse_sheet_fields(block_text)
            embed_text = _build_embed_text(fields, current_h1, current_h2)
            # Fallback: if no signal fields were found, embed the full block
            if not embed_text.strip():
                embed_text = f"Sheet: {current_h2}\n{block_text}"
            chunks.append({
                "embed_text":   embed_text,
                "display_text": f"## {current_h2}\n\n{block_text}",
                "chunk_type":   "structured_sheet",
                "filename":     filename,
                "chapter":      current_h1,
                "sheet_title":  current_h2,
                "fields":       fields,
                "is_summary":   False,
            })

        for line in content.splitlines():
            stripped = line.strip()

            if stripped.startswith("# ") and not stripped.startswith("## "):
                # H1: flush current sheet, update group title, reset block
                _flush_block()
                current_h1 = stripped[2:].strip()
                current_h2 = ""
                block_lines = []

            elif stripped.startswith("## "):
                # H2: flush previous sheet, start a new one
                _flush_block()
                current_h2 = stripped[3:].strip()
                block_lines = []

            else:
                # Accumulate body lines (includes >[!...] blocks — _extract_summaries
                # handles those separately when use_summaries=True)
                block_lines.append(line)

        # Flush the final block
        _flush_block()

        return chunks

    def _build_chunks(self, content: str, filename: str) -> List[Dict]:
        dispatch = {
            "fixed":            self._fixed_chunks,
            "sentence":         self._sentence_chunks,
            "sentence_window":  self._sentence_window_chunks,
            "dynamic":          self._dynamic_chunks,
            "structured_sheet": self._structured_sheet_chunks,
        }
        fn = dispatch.get(self.chunk_strategy)
        if fn is None:
            log("warning", f"HybridRAG: unknown strategy '{self.chunk_strategy}', using sentence_window")
            fn = self._sentence_window_chunks
        chunks = fn(content, filename)

        if self.use_summaries:
            summary_chunks = self._extract_summaries(content)
            for sc in summary_chunks:
                sc["filename"] = filename
            chunks = summary_chunks + chunks
        return chunks

    def _get_llm_manager(self):
        """
        Resolve the LLM manager via the service locator.
        Tries two paths in order:
          1. shared.common.get_llm_manager()  — normal app runtime
          2. modules.rag_manager.get_rag_manager().manager — bench / early-init contexts
             where the service locator may not be set yet but the rag_manager
             already holds a direct reference to the LLM manager.
        Raises RuntimeError if neither path works.
        """
        import traceback

        # Path 1: Through shared.common (with @require_services decorator)
        try:
            from shared.common import get_llm_manager
            llm_manager = get_llm_manager()
            if llm_manager is not None:
                return llm_manager
            else:
                log("debug", "HybridRAG: get_llm_manager() returned None")
        except Exception as e:
            # Log the full stack trace of the exception
            stack = traceback.format_exc()
            log("error", f"HybridRAG: get_llm_manager() failed with exception:\n{stack}")
            # Don't return here, try the next path

        # Path 2: Through rag_manager.llm_manager reference
        try:
            from modules.rag_manager import get_rag_manager
            rag_mgr = get_rag_manager()
            if rag_mgr is not None and hasattr(rag_mgr, "llm_manager") and rag_mgr.llm_manager is not None:
                return rag_mgr.llm_manager
            else:
                log("debug", f"HybridRAG: rag_manager path failed - rag_mgr={rag_mgr}, has llm_manager={hasattr(rag_mgr, 'llm_manager') if rag_mgr else False}")
        except Exception as e:
            stack = traceback.format_exc()
            log("error", f"HybridRAG: rag_manager path failed with exception:\n{stack}")

        # If we get here, both paths failed
        error_msg = (
            "HybridRAG: cannot resolve LLM manager — "
            "service locator not initialized and rag_manager.llm_manager not set. "
            "HyDE/contextual features require the app to be fully started."
        )
        log("error", error_msg)

        # Raise with full context
        raise RuntimeError(error_msg)

    def _llm_one_shot(self, prompt: str, max_tokens: int = 200) -> str:
        """
        Synchronous wrapper around manager.internal_response() for internal use
        (HyDE, contextual prefix). Bypasses conversation history and context callbacks.

        Always runs in a dedicated thread with its own fresh event loop.
        This is the only pattern that works reliably in both contexts:
          - Streamlit (has a running loop): asyncio.run() inside a new thread
            is safe because the thread has no loop of its own.
          - Bench / subprocess (no running loop): same — works fine too.
        """
        import asyncio
        import concurrent.futures
        manager = self._get_llm_manager()
        messages = [{"role": "user", "content": prompt}]

        def _run_in_thread():
            return asyncio.run(
                manager.internal_response(manager.current_llm, messages)
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_run_in_thread).result(timeout=30)

    def _add_contextual_prefix(self, chunks: List[Dict], full_content: str) -> List[Dict]:
        for chunk in chunks:
            if chunk.get("is_summary"): continue
            try:
                prompt = (f"Document extract:\n{chunk['embed_text'][:600]}\n\n"
                          "Write ONE sentence summarising this extract, starting with 'This passage covers'.")
                ctx = self._llm_one_shot(prompt, max_tokens=80)
                chunk["embed_text"] = f"{ctx.strip()}\n\n{chunk['embed_text']}"
            except Exception as e:
                log("warning", f"HybridRAG: contextual prefix failed: {e}")
        return chunks

    # ---------------------------------------------------------------- indexing

    def index_document(self, user_id: str, filename: str,
                       file_path: str, content: Optional[str] = None) -> bool:
        if self.dimension is None: return False
        try:
            if content is None:
                with open(file_path, "r", encoding="utf-8") as fh:
                    content = fh.read()
            chunks = self._build_chunks(content, filename)
            if not chunks:
                log("warning", f"HybridRAG: no chunks produced for {filename}")
                return False
            if self.use_contextual:
                chunks = self._add_contextual_prefix(chunks, content)

            vecs = _cosine_norm(np.array(
                get_embeddings([c["embed_text"] for c in chunks]), dtype=np.float32))
            file_size = os.path.getsize(file_path)

            if user_id not in self.indices:
                self.indices[user_id]  = faiss.IndexFlatIP(self.dimension)
                self.metadata[user_id] = []

            self.indices[user_id].add(vecs)
            for chunk in chunks:
                self.metadata[user_id].append({
                    "embed_text":   chunk["embed_text"],
                    "content":      chunk["display_text"],
                    "filename":     chunk["filename"],
                    "chunk_type":   chunk.get("chunk_type", "unknown"),
                    "is_summary":   chunk.get("is_summary", False),
                    "chapter":      chunk.get("chapter", ""),
                    "sheet_title":  chunk.get("sheet_title", ""),
                    "fields":       chunk.get("fields", {}),
                    "file_size":    file_size,
                    "indexed_at":   datetime.now().isoformat(),
                })
            self._save_index(user_id)
            self._rebuild_bm25(user_id)
            log("info", f"HybridRAG: indexed {filename} for {user_id} ({len(chunks)} chunks)")
            return True
        except Exception as e:
            log("error", f"HybridRAG: index_document failed: {e}", stacktrace=True)
            return False

    # ---------------------------------------------------------------- search

    def _get_hyde_summary_context(self) -> str:
        """
        Collect all indexed >[!Résumé] chunks across all users and return them
        as a compact context string to ground HyDE generation.
        Only used when hyde_use_summaries=True.
        Caps at 5 summaries / 1500 chars to stay within prompt budget.
        """
        seen, parts = set(), []
        for meta_list in self.metadata.values():
            for m in meta_list:
                if not m.get("is_summary"):
                    continue
                text = m.get("content", "").strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                parts.append(text[:300])
                if len(parts) >= 5:
                    break
            if len(parts) >= 5:
                break
        return "\n\n".join(parts)

    def _build_query_embedding(self, query: str) -> np.ndarray:
        if not self.use_hyde:
            return _cosine_norm(np.array([get_embedding(query)], dtype=np.float32))
        try:
            prompt_text = self._get_hyde_prompt()
            if prompt_text:
                prompt = prompt_text.format(query=query) if "{query}" in prompt_text \
                         else f"{prompt_text}\n\nQuestion: {query}\n\nAnswer:"
            else:
                prompt = (
                    "You are an expert tutor. Write a short, factual paragraph (3-5 sentences) "
                    "that directly answers the following question as if it were found in a "
                    "training document.\n\nQuestion: {query}\n\nAnswer:".format(query=query)
                )
            if self.hyde_use_summaries:
                ctx = self._get_hyde_summary_context()
                if ctx:
                    prompt = (
                        f"The following are summaries from the training document:\n\n{ctx}"
                        f"\n\nUsing only concepts from this document, {prompt}"
                    )
                    log("debug", f"HybridRAG HyDE: injected {len(ctx)} chars of summary context")
            hypothetical = self._llm_one_shot(prompt, max_tokens=200)
            log("debug", f"HybridRAG HyDE: generated {len(hypothetical)} char answer")
            return _cosine_norm(np.array([get_embedding(hypothetical)], dtype=np.float32))
        except Exception as e:
            log("warning", f"HybridRAG: HyDE failed ({e}), falling back to raw query")
            return _cosine_norm(np.array([get_embedding(query)], dtype=np.float32))

    def _hybrid_scores(self, user_id: str, query: str,
                       cosine_scores: np.ndarray) -> np.ndarray:
        """
        Two modes:

        BLEND mode (bm25_rerank_only=False):
            score = alpha * cosine + (1-alpha) * bm25
            Good when the corpus has diverse vocabulary and BM25 discriminates well.

        RERANK mode (bm25_rerank_only=True, default):
            BM25 is used only as a fractional tiebreaker added on top of cosine.
            score = cosine + epsilon * bm25   (epsilon = 0.01)
            This preserves cosine ranking for cases where the dominant topic word
            (e.g. "attention" in every chunk) would otherwise let BM25 swamp the
            signal from rare but critical phrases.
        """
        bm25 = self.bm25s.get(user_id)
        if not self.use_bm25_hybrid or bm25 is None or not bm25.available:
            return cosine_scores

        n = len(self.metadata.get(user_id, []))
        bm25_raw = bm25.scores(_tokenise(query), n)

        if self.bm25_rerank_only:
            epsilon = 0.01
            cos_norm = (cosine_scores + 1.0) / 2.0
            return cos_norm + epsilon * bm25_raw
        else:
            cos_norm = (cosine_scores + 1.0) / 2.0
            return self.bm25_alpha * cos_norm + (1.0 - self.bm25_alpha) * bm25_raw

    def search(self, user_id: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        if self.dimension is None: return []
        if user_id not in self.indices or self.indices[user_id].ntotal == 0:
            log("warning",
                f"HybridRAGEngine [{self.engine_id}]: no index found for user '{user_id}' "
                f"at path '{self.index_path}'. "
                f"This engine needs to be re-indexed (Documents tab → re-index) "
                f"because its index_path differs from the default engine.")
            return []
        try:
            query_vec = self._build_query_embedding(query)
            n_chunks  = self.indices[user_id].ntotal
            k         = min(n_chunks, limit * 6)
            D, I      = self.indices[user_id].search(query_vec, k)

            all_cosine = np.full(n_chunks, -1.0, dtype=np.float32)
            for rank, idx in enumerate(I[0]):
                if idx != -1: all_cosine[idx] = D[0][rank]
            blended = self._hybrid_scores(user_id, query, all_cosine)

            candidates = sorted([i for i in I[0] if i != -1],
                                 key=lambda i: blended[i], reverse=True)
            results, max_score = [], 0.0
            for idx in candidates:
                score = float(blended[idx])
                max_score = max(max_score, score)
                if score < self.similarity_threshold: continue
                meta = self.metadata[user_id][idx]
                results.append({
                    "filename":         meta["filename"],
                    "score":            score,
                    "cosine_score":     float(all_cosine[idx]),
                    "content":          meta["content"],
                    "chunk_type":       meta.get("chunk_type", ""),
                    "is_summary":       meta.get("is_summary", False),
                    "chapter":          meta.get("chapter", ""),
                    "sheet_title":      meta.get("sheet_title", ""),
                    "threshold_used":   self.similarity_threshold,
                    "max_score_reached": None,
                })
                if len(results) >= limit: break
            for r in results:
                r["max_score_reached"] = max_score
            if not results:
                return [{"filename": None, "score": 0, "content": "",
                         "threshold_used": self.similarity_threshold,
                         "max_score_reached": max_score, "no_results": True}]
            return results
        except Exception as e:
            log("error", f"HybridRAG: search failed: {e}", stacktrace=True)
            return []

    # ---------------------------------------------------------------- CRUD

    def delete_document(self, user_id: str, filename: str) -> bool:
        if user_id not in self.metadata: return False
        try:
            kept = [m for m in self.metadata[user_id] if m["filename"] != filename]
            if len(kept) == len(self.metadata[user_id]): return False
            if kept:
                vecs = _cosine_norm(np.array(
                    get_embeddings([m["embed_text"] for m in kept]), dtype=np.float32))
                new_idx = faiss.IndexFlatIP(self.dimension)
                new_idx.add(vecs)
                self.indices[user_id]  = new_idx
                self.metadata[user_id] = kept
            else:
                self.indices.pop(user_id, None)
                self.metadata.pop(user_id, None)
            self._save_index(user_id)
            self._rebuild_bm25(user_id)
            return True
        except Exception as e:
            log("error", f"HybridRAG: delete_document failed: {e}")
            return False

    def get_indexed_documents(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        docs = []
        for uid in ([user_id] if user_id else self.metadata.keys()):
            if uid not in self.metadata: continue
            seen: set = set()
            for m in self.metadata[uid]:
                fn = m["filename"]
                if fn not in seen:
                    seen.add(fn)
                    docs.append({"user_id": uid, "filename": fn,
                                 "indexed_at": m["indexed_at"], "size": m.get("file_size", 0)})
        return docs

    def clear_user_index(self, user_id: str) -> bool:
        try:
            self.indices.pop(user_id, None)
            self.metadata.pop(user_id, None)
            self.bm25s.pop(user_id, None)
            self._save_index(user_id)
            return True
        except Exception as e:
            log("error", f"HybridRAG: clear_user_index failed: {e}")
            return False

    def is_available(self) -> bool:
        return self.dimension is not None

    def get_stats(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        base = {"engine_type": self.engine_type, "active_config": self.get_config()}
        if user_id:
            meta = self.metadata.get(user_id, [])
            return {**base, "documents_indexed": len({m["filename"] for m in meta}),
                    "total_chunks": len(meta)}
        return {**base,
                "total_documents_indexed": sum(len({m["filename"] for m in c})
                                               for c in self.metadata.values()),
                "total_chunks": sum(len(c) for c in self.metadata.values()),
                "users_with_index": len(self.metadata)}
