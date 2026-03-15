"""
RRF Ensemble Engine

Fuses ranked results from two existing engines using Reciprocal Rank Fusion
(Cormack, Clarke & Buettcher, 2009). Purely compositional — holds no FAISS
index and performs no embedding.

DESIGN CONSTRAINTS (read before modifying):
--------------------------------------------
1. No circular import.
   This engine is instantiated BY the RAGManager. It cannot call
   get_rag_manager() at init or search time without triggering a circular
   import / infinite recursion. The manager injects itself via
   set_manager() immediately after construction (see patch below).

2. No-op indexing.
   reindex_all_documents() calls index_document() on every engine in
   self.engines, including this one. The source engines (engine_a/b) are
   ALSO in self.engines and will be indexed directly by the manager.
   Delegating indexing here would double-index them. All write operations
   (index_document, delete_document, clear_user_index) are therefore
   intentional no-ops — the manager handles them on the source engines.

3. Lazy source resolution.
   Source engines may not exist yet when this engine is constructed
   (declaration order in config.json is not guaranteed). They are resolved
   on the first search() call via the injected manager reference.

REQUIRED ONE-LINE PATCH IN rag_manager.py > instantiate_engines():
-------------------------------------------------------------------
Find the line:
    self.engines[engine_id] = instance
Add immediately after:
    if hasattr(instance, 'set_manager'):
        instance.set_manager(self)

CONFIG REFERENCE:
-----------------
{
  "rrf_blend_sheet": {
    "type": "rrf",
    "enabled": true,
    "description": "RRF fusion of hybrid_bm25_blend + structured_sheet",
    "engine_a": "hybrid_bm25_blend",
    "engine_b": "structured_sheet",
    "rrf_k": 60,
    "limit": 5
  }
}

RRF FORMULA:
    score(doc) = 1/(k + rank_a) + 1/(k + rank_b)
    rank is 1-based. k=60 is the validated default (Cormack et al. 2009).
    A document appearing in only one list still scores via that list.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

from modules.rag_manager.rag_engine import RAGEngine
from core.logging import log

if TYPE_CHECKING:
    from modules.rag_manager.rag_manager import RAGManager

ENGINE_TYPE = "rrf"


class RRFEnsembleEngine(RAGEngine):
    """
    Reciprocal Rank Fusion over two configured RAG engines.

    Source engines are resolved lazily on first search() call via the
    manager reference injected by set_manager() post-construction.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None, engine_id: Optional[str] = None):
        super().__init__(ENGINE_TYPE, engine_id)
        cfg = config or {}
        self.description = cfg.get("description", "RRF ensemble (engine_a + engine_b)")
        self.engine_a_id = cfg.get("engine_a", "hybrid_bm25_blend")
        self.engine_b_id = cfg.get("engine_b", "structured_sheet")
        self.rrf_k       = int(cfg.get("rrf_k", 60))
        self._limit      = int(cfg.get("limit", 5))

        # Injected by the manager after construction — see set_manager()
        self._manager: Optional["RAGManager"] = None
        # Resolved on first search() call
        self._engine_a: Optional[RAGEngine] = None
        self._engine_b: Optional[RAGEngine] = None

        log("info", (
            f"RRFEnsembleEngine [{self.engine_id}] created — "
            f"a={self.engine_a_id} b={self.engine_b_id} k={self.rrf_k} "
            f"(waiting for manager injection)"
        ))

    # ---------------------------------------------------------------- manager injection

    def set_manager(self, manager: "RAGManager") -> None:
        """
        Called by RAGManager.instantiate_engines() immediately after:
            self.engines[engine_id] = instance

        Avoids circular imports: the engine never imports the manager module.
        Resets cached engine references so _resolve_engines() re-runs with
        the live manager on next search() call.
        """
        self._manager  = manager
        self._engine_a = None
        self._engine_b = None
        log("debug", f"RRFEnsemble [{self.engine_id}]: manager injected")

    # ---------------------------------------------------------------- config

    def get_config(self) -> Dict[str, Any]:
        return {
            "engine_a": self.engine_a_id,
            "engine_b": self.engine_b_id,
            "rrf_k":    self.rrf_k,
            "limit":    self._limit,
        }

    def update_config(self, overrides: Dict[str, Any]) -> None:
        if "engine_a" in overrides:
            self.engine_a_id = overrides["engine_a"]
            self._engine_a   = None
        if "engine_b" in overrides:
            self.engine_b_id = overrides["engine_b"]
            self._engine_b   = None
        if "rrf_k"  in overrides: self.rrf_k   = int(overrides["rrf_k"])
        if "limit"  in overrides: self._limit  = int(overrides["limit"])

    # ---------------------------------------------------------------- source engine resolution

    def _resolve_engines(self) -> bool:
        """
        Resolve engine_a and engine_b from the injected manager.
        Returns True when both are available.
        """
        if self._engine_a is not None and self._engine_b is not None:
            return True

        if self._manager is None:
            log("error", (
                f"RRFEnsemble [{self.engine_id}]: manager not injected. "
                f"Add `if hasattr(instance, 'set_manager'): instance.set_manager(self)` "
                f"in RAGManager.instantiate_engines() after `self.engines[engine_id] = instance`."
            ))
            return False

        self._engine_a = self._manager.get_engine(self.engine_a_id)
        self._engine_b = self._manager.get_engine(self.engine_b_id)

        if self._engine_a is None:
            log("error", (
                f"RRFEnsemble [{self.engine_id}]: engine_a '{self.engine_a_id}' not found. "
                f"Available: {self._manager.get_engine_ids()}"
            ))
            return False

        if self._engine_b is None:
            log("error", (
                f"RRFEnsemble [{self.engine_id}]: engine_b '{self.engine_b_id}' not found. "
                f"Available: {self._manager.get_engine_ids()}"
            ))
            return False

        log("debug", f"RRFEnsemble [{self.engine_id}]: resolved a={self.engine_a_id} b={self.engine_b_id}")
        return True

    # ---------------------------------------------------------------- RRF core

    @staticmethod
    def _dedup_key(result: Dict[str, Any]) -> str:
        """
        Content-based deduplication key — first 120 chars of display content.
        Robust to minor trailing whitespace differences between engine outputs.
        """
        return (result.get("content") or "")[:120].strip()

    def _rrf_merge(
        self,
        results_a: List[Dict[str, Any]],
        results_b: List[Dict[str, Any]],
        limit: int,
    ) -> List[Dict[str, Any]]:
        """
        Merge two ranked result lists via Reciprocal Rank Fusion.

        score(doc) = Σ  1 / (k + rank_i)
        rank is 1-based. Documents missing from a list contribute 0 for that
        list (they still carry the score from the other list).
        Sentinel no_results entries are stripped before ranking.
        """
        k = self.rrf_k
        rrf_scores: Dict[str, float]          = {}
        result_map: Dict[str, Dict[str, Any]] = {}

        clean_a = [r for r in results_a if not r.get("no_results")]
        clean_b = [r for r in results_b if not r.get("no_results")]

        for rank, r in enumerate(clean_a, start=1):
            key = self._dedup_key(r)
            rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (k + rank)
            result_map[key] = r

        for rank, r in enumerate(clean_b, start=1):
            key = self._dedup_key(r)
            rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (k + rank)
            if key not in result_map:
                result_map[key] = r

        ranked = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)

        merged = []
        for key, rrf_score in ranked[:limit]:
            base = dict(result_map[key])
            base["score"]      = round(rrf_score, 6)
            base["chunk_type"] = base.get("chunk_type", "") + "+rrf"
            merged.append(base)

        return merged

    # ---------------------------------------------------------------- search

    def search(self, user_id: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        if not self._resolve_engines():
            return []

        effective_limit = max(limit, self._limit)
        fetch_k = effective_limit * 4   # wide candidate pool for reranking

        try:
            results_a = self._engine_a.search(user_id, query, limit=fetch_k)
        except Exception as e:
            log("error", f"RRFEnsemble [{self.engine_id}]: engine_a search failed: {e}")
            results_a = []

        try:
            results_b = self._engine_b.search(user_id, query, limit=fetch_k)
        except Exception as e:
            log("error", f"RRFEnsemble [{self.engine_id}]: engine_b search failed: {e}")
            results_b = []

        merged = self._rrf_merge(results_a, results_b, limit=effective_limit)

        if not merged:
            max_a = max((r.get("score", 0) for r in results_a if not r.get("no_results")), default=0)
            max_b = max((r.get("score", 0) for r in results_b if not r.get("no_results")), default=0)
            return [{"filename": None, "score": 0, "content": "",
                     "no_results": True, "max_score_reached": max(max_a, max_b)}]

        n_a = len([r for r in results_a if not r.get("no_results")])
        n_b = len([r for r in results_b if not r.get("no_results")])
        log("debug", (
            f"RRFEnsemble [{self.engine_id}]: {n_a} + {n_b} → {len(merged)} results "
            f"for user={user_id}"
        ))
        return merged

    # ---------------------------------------------------------------- no-op writes
    #
    # The manager calls index_document / delete_document / clear_user_index on
    # every engine in self.engines, including the source engines (engine_a/b).
    # Delegating here would double-index / double-delete them.
    # These are intentional no-ops — the manager handles writes on source engines.

    def index_document(self, user_id: str, filename: str,
                       file_path: str, content: Optional[str] = None) -> bool:
        log("debug", f"RRFEnsemble [{self.engine_id}]: index_document no-op ({filename})")
        return True

    def delete_document(self, user_id: str, filename: str) -> bool:
        log("debug", f"RRFEnsemble [{self.engine_id}]: delete_document no-op ({filename})")
        return True

    def clear_user_index(self, user_id: str) -> bool:
        log("debug", f"RRFEnsemble [{self.engine_id}]: clear_user_index no-op ({user_id})")
        return True

    def get_indexed_documents(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Proxy to engine_a — both source engines hold the same document set."""
        if not self._resolve_engines():
            return []
        return self._engine_a.get_indexed_documents(user_id)

    def is_available(self) -> bool:
        return self._manager is not None and self._resolve_engines()

    def get_stats(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "engine_type":   ENGINE_TYPE,
            "active_config": self.get_config(),
        }
        if not self._resolve_engines():
            return base
        return {
            **base,
            "engine_a_stats": self._engine_a.get_stats(user_id),
            "engine_b_stats": self._engine_b.get_stats(user_id),
        }
