"""
Simple RAG Engine Plugin

No Streamlit dependency. Config is injected at construction time.

Changes vs previous version
----------------------------
- Added ``ENGINE_TYPE = "simple"`` class constant for reliable engine discovery
  (avoids regex-based sniffing in RAGManager.discover_engines).
- ``__init__`` now accepts ``engine_id`` kwarg so ``instantiate_engines()`` can
  create named instances (e.g. "simple_large_ctx") without extra glue code.
- ``similarity_threshold``, ``context_size``, ``max_results`` are now first-class
  config keys stored on the instance and honoured by ``search`` / ``_extract_context``.
- Implemented ``get_config()`` and ``update_config()`` so the admin UI and live
  config-override tests can read / mutate engine settings at runtime.
"""

import os
import re
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path
import pickle

from modules.rag_manager.rag_engine import RAGEngine
from core.logging import log


class SimpleRAGEngine(RAGEngine):
    """Simple RAG engine using basic text matching."""

    # Explicit slug — used by RAGManager.discover_engines() (path 1, cheapest).
    ENGINE_TYPE = "simple"

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        engine_id: Optional[str] = None,
    ):
        """
        Args:
            config:    The engine-specific config dict (the block under
                       ``rag_manager.engines.<engine_id>`` in config.json).
                       If *None*, sensible defaults are used.
            engine_id: Optional instance name (config key).  When *None* the
                       engine_type slug ``"simple"`` is used as the id — this
                       preserves backward-compatibility with existing callers
                       that don't pass the argument.
        """
        super().__init__(engine_type=self.ENGINE_TYPE, engine_id=engine_id)

        self.description = "Simple text-based RAG engine using keyword matching"

        cfg = config or {}

        # --- Tunable parameters (all overridable via config or update_config) ---
        self.index_path = Path(cfg.get("index_path", "data/simple_indexes"))

        # Maximum characters of surrounding text returned per result.
        self.context_size: int = int(cfg.get("context_size", 200))

        # Score threshold: results with score <= threshold are discarded.
        # A value of 0 (default) keeps every document that contains at least
        # one query token — identical to the original behaviour.
        self.similarity_threshold: float = float(cfg.get("similarity_threshold", 0.0))

        # Hard cap on the number of results returned by search().
        self.max_results: int = int(cfg.get("max_results", 5))

        # --- Internal state ---
        self.indices: Dict[str, Dict] = {}
        self.index_path.mkdir(parents=True, exist_ok=True)
        self._load_indices()

    # ------------------------------------------------------------------
    # RAGEngine — config introspection API
    # ------------------------------------------------------------------

    def get_config(self) -> Dict[str, Any]:
        """Return the current runtime configuration as a plain dict."""
        return {
            "index_path": str(self.index_path),
            "context_size": self.context_size,
            "similarity_threshold": self.similarity_threshold,
            "max_results": self.max_results,
        }

    def update_config(self, overrides: Dict[str, Any]) -> None:
        """
        Apply runtime config overrides without reconstructing the engine.

        Supported keys: ``context_size``, ``similarity_threshold``,
        ``max_results``.  ``index_path`` is intentionally excluded because
        changing it at runtime would silently orphan the loaded indices.
        """
        if "context_size" in overrides:
            self.context_size = int(overrides["context_size"])
            log("debug", f"SimpleRAGEngine [{self.engine_id}]: context_size → {self.context_size}")

        if "similarity_threshold" in overrides:
            self.similarity_threshold = float(overrides["similarity_threshold"])
            log("debug",
                f"SimpleRAGEngine [{self.engine_id}]: "
                f"similarity_threshold → {self.similarity_threshold}")

        if "max_results" in overrides:
            self.max_results = int(overrides["max_results"])
            log("debug", f"SimpleRAGEngine [{self.engine_id}]: max_results → {self.max_results}")

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _load_indices(self):
        for pkl_file in self.index_path.glob("*_simple.pkl"):
            user_id = pkl_file.stem.replace("_simple", "")
            try:
                with open(pkl_file, "rb") as f:
                    self.indices[user_id] = pickle.load(f)
                log(
                    "info",
                    f"Loaded simple index for user {user_id} "
                    f"with {len(self.indices[user_id])} documents",
                )
            except Exception as e:
                log("error", f"Failed to load simple index for user {user_id}: {e}")

    def _save_user_index(self, user_id: str):
        user_data = self.indices.get(user_id)
        file_path = self.index_path / f"{user_id}_simple.pkl"
        if user_data:
            try:
                with open(file_path, "wb") as f:
                    pickle.dump(user_data, f)
            except Exception as e:
                log("error", f"Failed to save simple index for user {user_id}: {e}")
        else:
            if file_path.exists():
                try:
                    file_path.unlink()
                except Exception as e:
                    log("error", f"Failed to delete empty simple index file for {user_id}: {e}")

    # ------------------------------------------------------------------
    # RAGEngine — core operations
    # ------------------------------------------------------------------

    def index_document(
        self,
        user_id: str,
        filename: str,
        file_path: str,
        content: Optional[str] = None,
    ) -> bool:
        try:
            if content is None:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()

            if user_id not in self.indices:
                self.indices[user_id] = {}

            self.indices[user_id][filename] = {
                "content": content,
                "metadata": {
                    "indexed_at": datetime.now().isoformat(),
                    "file_path": file_path,
                    "size": os.path.getsize(file_path),
                },
            }
            self._save_user_index(user_id)
            return True
        except Exception as e:
            log("error", f"Failed to index document {filename}: {e}")
            return False

    def delete_document(self, user_id: str, filename: str) -> bool:
        try:
            if user_id in self.indices and filename in self.indices[user_id]:
                del self.indices[user_id][filename]
                if not self.indices[user_id]:
                    del self.indices[user_id]
                self._save_user_index(user_id)
                return True
            return False
        except Exception as e:
            log("error", f"Failed to delete document {filename}: {e}")
            return False

    def search(
        self,
        user_id: str,
        query: str,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Keyword-frequency search.

        The effective result cap is ``min(limit, self.max_results)``.
        Results whose raw keyword score is <= ``self.similarity_threshold``
        are discarded before the limit is applied.
        """
        results = []
        if user_id not in self.indices:
            # Return the standard no-results sentinel so callers always get a
            # consistent structure regardless of whether the user has any index.
            return [
                {
                    "filename": None,
                    "score": 0,
                    "content": "",
                    "threshold_used": self.similarity_threshold,
                    "max_score_reached": 0.0,
                    "no_results": True,
                }
            ]

        query_lower = query.lower()
        max_score_reached = 0.0
        effective_limit = min(limit, self.max_results)

        for filename, data in self.indices[user_id].items():
            content = data["content"].lower()
            score = sum(content.count(word) for word in query_lower.split())

            if score > max_score_reached:
                max_score_reached = score

            # Apply similarity threshold — discard low-signal results.
            if score <= self.similarity_threshold:
                continue

            context = self._extract_context(
                data["content"], query_lower, context_size=self.context_size
            )
            results.append(
                {
                    "filename": filename,
                    "score": score,
                    "content": context,
                    "metadata": data["metadata"],
                    "threshold_used": self.similarity_threshold,
                    "max_score_reached": None,  # back-filled below
                }
            )

        results.sort(key=lambda x: x["score"], reverse=True)
        final = results[:effective_limit]

        for r in final:
            r["max_score_reached"] = max_score_reached

        if not final:
            return [
                {
                    "filename": None,
                    "score": 0,
                    "content": "",
                    "threshold_used": self.similarity_threshold,
                    "max_score_reached": max_score_reached,
                    "no_results": True,
                }
            ]

        return final

    def _extract_context(
        self,
        content: str,
        query: str,
        context_size: Optional[int] = None,
    ) -> str:
        """
        Return a ``context_size``-character window around the best query match.

        ``context_size`` defaults to ``self.context_size`` when not provided,
        allowing callers to override it without mutating instance state.
        """
        if context_size is None:
            context_size = self.context_size

        content_lower = content.lower()
        pos = content_lower.find(query)

        if pos == -1:
            stop_words = {
                "the", "and", "for", "with", "that", "this", "from", "have",
                "what", "when", "where", "who", "also", "just", "about",
                "into", "your", "you", "are", "how", "is", "it", "to", "of",
                "in", "on", "a", "an", "i", "im", "i'm",
            }
            candidates = [
                token
                for token in re.findall(r"[a-zA-Z0-9_]+", query.lower())
                if len(token) >= 3 and token not in stop_words
            ]
            candidates.sort(key=len, reverse=True)

            best_pos = -1
            for token in candidates:
                token_pos = content_lower.find(token)
                if token_pos != -1:
                    best_pos = token_pos
                    break
            pos = best_pos

        if pos == -1:
            return (
                (content[:context_size] + "...")
                if len(content) > context_size
                else content
            )

        start = max(0, pos - context_size // 2)
        end = min(len(content), pos + context_size // 2)
        context = content[start:end]
        if start > 0:
            context = "..." + context
        if end < len(content):
            context = context + "..."
        return context

    def get_indexed_documents(
        self, user_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        documents = []
        for uid in ([user_id] if user_id else self.indices.keys()):
            if uid in self.indices:
                for filename, data in self.indices[uid].items():
                    documents.append(
                        {
                            "user_id": uid,
                            "filename": filename,
                            "indexed_at": data["metadata"]["indexed_at"],
                            "size": data["metadata"]["size"],
                        }
                    )
        return documents

    def clear_user_index(self, user_id: str) -> bool:
        try:
            if user_id in self.indices:
                del self.indices[user_id]
            self._save_user_index(user_id)
            return True
        except Exception as e:
            log("error", f"Failed to clear index for user {user_id}: {e}")
            return False

    def is_available(self) -> bool:
        return True

    def get_stats(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        if user_id:
            return {
                "documents_indexed": len(self.indices.get(user_id, {})),
                "engine_type": self.engine_type,
                "engine_id": self.engine_id,
                "context_size": self.context_size,
                "similarity_threshold": self.similarity_threshold,
                "max_results": self.max_results,
            }
        return {
            "total_documents_indexed": sum(
                len(docs) for docs in self.indices.values()
            ),
            "users_with_index": len(self.indices),
            "engine_type": self.engine_type,
            "engine_id": self.engine_id,
            "context_size": self.context_size,
            "similarity_threshold": self.similarity_threshold,
            "max_results": self.max_results,
        }
