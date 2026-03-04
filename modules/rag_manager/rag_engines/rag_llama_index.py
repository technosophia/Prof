"""
LlamaIndex RAG Engine Plugin

Wraps LlamaIndex's VectorStoreIndex with SentenceWindowNodeParser for retrieval,
adapted to the existing RAGEngine plugin interface.

Why LlamaIndex?
---------------
- SentenceWindowNodeParser: indexes at sentence granularity but returns a wider
  window of surrounding context, combining precision and context richness.
- MetadataReplacementPostProcessor: at query time, replaces the matched sentence
  with its full surrounding window before passing to the LLM.
- Pluggable embeddings: uses the same get_embedding / get_embeddings abstraction
  as the other engines so it works with any configured embedding backend.

Requirements (pip install):
    llama-index-core
    llama-index-embeddings-openai   (if using OpenAI embeddings)
    llama-index-embeddings-ollama   (if using Ollama)
    -- or any llama-index embedding adapter matching your stack

All code and comments in English.
No Streamlit dependency. Config is injected at construction time.
"""

import os
import json
import pickle
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..rag_engine import RAGEngine
from core.logging import log

# LlamaIndex imports — guarded so the rest of the app doesn't break
# if the package is not installed.
try:
    from llama_index.core import (
        Document,
        Settings,
        StorageContext,
        VectorStoreIndex,
        load_index_from_storage,
    )
    from llama_index.core.node_parser import SentenceWindowNodeParser
    from llama_index.core.postprocessor import MetadataReplacementPostProcessor
    from llama_index.core.embeddings import BaseEmbedding
    from llama_index.core.schema import TextNode
    from llama_index.core.vector_stores.simple import SimpleVectorStore
    import numpy as np
    LLAMAINDEX_AVAILABLE = True
except ImportError:
    LLAMAINDEX_AVAILABLE = False


# ---------------------------------------------------------------------------
# Custom embedding bridge — routes LlamaIndex embedding calls through
# the existing get_embeddings() abstraction so no second API key is needed.
# ---------------------------------------------------------------------------

if LLAMAINDEX_AVAILABLE:
    from shared.common import get_embeddings as _get_embeddings_bridge
    from shared.common import get_embedding as _get_embedding_bridge

    class _BridgeEmbedding(BaseEmbedding):
        """
        Thin adapter that satisfies LlamaIndex's BaseEmbedding interface
        while delegating actual calls to the project's shared embedding function.
        """

        model_name: str = "bridge"

        def __init__(self, dimension: Optional[int] = None):
            super().__init__()
            self._dimension = dimension

        def _get_query_embedding(self, query: str) -> List[float]:
            results = _get_embeddings_bridge([query])
            embedding = list(results[0])
            # Validate dimension if we know what it should be
            if self._dimension and len(embedding) != self._dimension:
                log("warning",
                    f"Query embedding dimension mismatch: got {len(embedding)}, expected {self._dimension}")
            return embedding

        def _get_text_embedding(self, text: str) -> List[float]:
            results = _get_embeddings_bridge([text])
            embedding = list(results[0])
            # Validate dimension if we know what it should be
            if self._dimension and len(embedding) != self._dimension:
                log("warning",
                    f"Text embedding dimension mismatch: got {len(embedding)}, expected {self._dimension}")
            return embedding

        def _get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
            results = _get_embeddings_bridge(texts)
            embeddings = [list(r) for r in results]
            # Validate dimensions if we know what they should be
            if self._dimension:
                for i, emb in enumerate(embeddings):
                    if len(emb) != self._dimension:
                        log("warning",
                            f"Embedding {i} dimension mismatch: got {len(emb)}, expected {self._dimension}")
            return embeddings

        async def _aget_query_embedding(self, query: str) -> List[float]:
            return self._get_query_embedding(query)

        async def _aget_text_embedding(self, text: str) -> List[float]:
            return self._get_text_embedding(text)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class LlamaIndexRAGEngine(RAGEngine):
    """
    RAG engine backed by LlamaIndex with SentenceWindowNodeParser.

    Indexing strategy:
    - Each document is split into sentences by LlamaIndex's SentenceWindowNodeParser.
    - Each sentence node carries a metadata window of ±window_size surrounding sentences.
    - Embeddings are computed via the shared get_embeddings() bridge.

    Retrieval strategy:
    - Top-k sentence nodes are retrieved by cosine similarity.
    - MetadataReplacementPostProcessor expands each matched sentence to its full
      surrounding window before returning, giving richer context to the LLM.
    - Double-threshold: high_threshold for confident results, low_threshold fallback.

    Config keys (all optional):
        index_path          str     Storage path.                Default: ./data/llamaindex_indexes
        window_size         int     Sentence context window.     Default: 3
        similarity_top_k    int     Candidates before rerank.    Default: 10
        high_threshold      float   Primary similarity cutoff.   Default: 0.40
        low_threshold       float   Fallback similarity cutoff.  Default: 0.18
        model_name          str     Embedding model name.        Default: all-MiniLM-L6-v2
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__("llamaindex")
        self.description = (
            "LlamaIndex VectorStoreIndex with SentenceWindowNodeParser "
            "and MetadataReplacementPostProcessor"
        )

        config = config or {}

        self.index_path = Path(config.get("index_path", "./data/llamaindex_indexes"))
        self.index_path.mkdir(parents=True, exist_ok=True)

        self.window_size = config.get("window_size", 3)
        self.similarity_top_k = config.get("similarity_top_k", 10)
        self.high_threshold = config.get("high_threshold", 0.40)
        self.low_threshold = config.get("low_threshold", 0.18)

        # Add model name to track which model was used for embeddings
        self.model_name = config.get("model_name", "all-MiniLM-L6-v2")

        # Alias for benchmark compatibility
        self.similarity_threshold = self.high_threshold

        if not LLAMAINDEX_AVAILABLE:
            log("error",
                "LlamaIndex packages not installed. "
                "Run: pip install llama-index-core")
            self._available = False
            return

        self._available = True

        try:
            from shared.common import get_embedding
            self.dimension = len(get_embedding(""))
            log("info", f"LlamaIndex: embeddings initialized (dim: {self.dimension}, model: {self.model_name})")
        except Exception as e:
            log("error", f"LlamaIndex: failed to initialize embeddings: {str(e)}")
            self.dimension = None

        # Configure LlamaIndex global settings — use our bridge embedding,
        # disable the built-in LLM (we only use LlamaIndex for retrieval).
        Settings.embed_model = _BridgeEmbedding(dimension=self.dimension)
        Settings.llm = None

        # Per-user LlamaIndex VectorStoreIndex objects
        # {user_id: VectorStoreIndex}
        self._indices: Dict[str, Any] = {}

        # Lightweight metadata store for get_indexed_documents()
        # {user_id: [{filename, indexed_at, file_size}]}
        self._doc_registry: Dict[str, List[Dict]] = {}

        self._load_indices()

    # ------------------------------------------------------------------
    # Persistence with Model Metadata
    # ------------------------------------------------------------------

    def _user_path(self, user_id: str) -> Path:
        p = self.index_path / user_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _registry_path(self, user_id: str) -> Path:
        return self._user_path(user_id) / "registry.pkl"

    def _model_meta_path(self, user_id: str) -> Path:
        return self._user_path(user_id) / "model_meta.json"

    def _load_indices(self):
        """Load all persisted LlamaIndex indices from disk with dimension validation."""
        if self.dimension is None:
            log("error", "LlamaIndex: cannot load indices without embedding dimension")
            return

        for user_dir in self.index_path.iterdir():
            if not user_dir.is_dir():
                continue
            user_id = user_dir.name

            # Check model metadata first
            model_meta_file = self._model_meta_path(user_id)
            if model_meta_file.exists():
                try:
                    with open(model_meta_file, 'r') as f:
                        model_meta = json.load(f)

                    if model_meta.get('dimension') != self.dimension:
                        log("warning",
                            f"LlamaIndex: index for user {user_id} uses different model "
                            f"({model_meta.get('model_name')}, dim={model_meta.get('dimension')}). "
                            f"Current model: {self.model_name}, dim={self.dimension}. Skipping load.")
                        continue
                except Exception as e:
                    log("error", f"LlamaIndex: failed to read model metadata for {user_id}: {str(e)}")
                    continue

            storage_dir = user_dir / "storage"
            if not storage_dir.exists():
                continue

            try:
                storage_context = StorageContext.from_defaults(persist_dir=str(storage_dir))
                index = load_index_from_storage(storage_context)

                # Validate vector store dimensions
                if hasattr(index, '_vector_store') and isinstance(index._vector_store, SimpleVectorStore):
                    # Check a sample embedding to verify dimensions
                    if len(index._vector_store.data.embedding_dict) > 0:
                        sample_id = next(iter(index._vector_store.data.embedding_dict))
                        sample_emb = index._vector_store.data.embedding_dict[sample_id]
                        if len(sample_emb) != self.dimension:
                            log("warning",
                                f"LlamaIndex: vector store for user {user_id} has dimension {len(sample_emb)}, "
                                f"but current model expects {self.dimension}. Skipping load.")
                            continue

                self._indices[user_id] = index

                reg_file = self._registry_path(user_id)
                if reg_file.exists():
                    with open(reg_file, "rb") as f:
                        self._doc_registry[user_id] = pickle.load(f)

                log("info", f"LlamaIndex: loaded index for {user_id}")
            except Exception as e:
                log("error", f"LlamaIndex: failed to load index for {user_id}: {str(e)}")

    def _save_index(self, user_id: str):
        """Save index with model metadata."""
        if user_id not in self._indices:
            return
        try:
            storage_dir = self._user_path(user_id) / "storage"
            self._indices[user_id].storage_context.persist(persist_dir=str(storage_dir))

            with open(self._registry_path(user_id), "wb") as f:
                pickle.dump(self._doc_registry.get(user_id, []), f)

            # Save model metadata
            with open(self._model_meta_path(user_id), 'w') as f:
                json.dump({
                    'model_name': self.model_name,
                    'dimension': self.dimension,
                    'created_at': datetime.now().isoformat()
                }, f)

        except Exception as e:
            log("error", f"LlamaIndex: failed to save index for {user_id}: {str(e)}")

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
            self._indices.pop(user_id, None)
            self._doc_registry.pop(user_id, None)

            # Delete physical files
            user_dir = self.index_path / user_id
            if user_dir.exists():
                shutil.rmtree(str(user_dir))

            log("info", f"LlamaIndex: force rebuilt index for user {user_id}")
            return True
        except Exception as e:
            log("error", f"LlamaIndex: failed to force rebuild index: {str(e)}")
            return False

    def reset_all_indices(self) -> bool:
        """
        Completely reset all indices for all users.
        Use this when changing embedding models globally.
        """
        try:
            # Clear all memory
            self._indices.clear()
            self._doc_registry.clear()

            # Delete all files in index directory
            for item in self.index_path.iterdir():
                if item.is_dir():
                    shutil.rmtree(str(item))
                else:
                    item.unlink()

            log("info", "LlamaIndex: reset all indices successfully")
            return True
        except Exception as e:
            log("error", f"LlamaIndex: failed to reset all indices: {str(e)}")
            return False

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
        if not self._available or self.dimension is None:
            return False
        try:
            if content is None:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()

            # Wrap content in a LlamaIndex Document with source metadata
            document = Document(
                text=content,
                metadata={
                    "filename": filename,
                    "file_path": file_path,
                    "indexed_at": datetime.now().isoformat(),
                }
            )

            # SentenceWindowNodeParser — splits into sentences, attaches context window
            parser = SentenceWindowNodeParser.from_defaults(
                window_size=self.window_size,
                window_metadata_key="window",
                original_text_metadata_key="original_sentence",
            )
            nodes = parser.get_nodes_from_documents([document])

            if not nodes:
                log("warning", f"LlamaIndex: no nodes produced for {filename}")
                return False

            # Validate embedding dimensions before adding to index
            sample_embedding = self._get_text_embedding(nodes[0].text)
            if len(sample_embedding) != self.dimension:
                log("error",
                    f"LlamaIndex: embedding dimension mismatch: got {len(sample_embedding)}, "
                    f"expected {self.dimension}")
                return False

            if user_id in self._indices:
                # Check existing index dimension
                if hasattr(self._indices[user_id], '_vector_store') and isinstance(self._indices[user_id]._vector_store, SimpleVectorStore):
                    if len(self._indices[user_id]._vector_store.data.embedding_dict) > 0:
                        sample_id = next(iter(self._indices[user_id]._vector_store.data.embedding_dict))
                        existing_dim = len(self._indices[user_id]._vector_store.data.embedding_dict[sample_id])
                        if existing_dim != self.dimension:
                            log("warning",
                                f"LlamaIndex: existing index for {user_id} has dimension {existing_dim}, "
                                f"but current model expects {self.dimension}. Rebuilding index automatically.")
                            # Create new index instead of adding to old one
                            self._indices[user_id] = VectorStoreIndex(nodes)
                            self._doc_registry[user_id] = []
                        else:
                            # Add nodes to the existing index
                            self._indices[user_id].insert_nodes(nodes)
                    else:
                        self._indices[user_id].insert_nodes(nodes)
                else:
                    self._indices[user_id].insert_nodes(nodes)
            else:
                # Create a new index for this user
                self._indices[user_id] = VectorStoreIndex(nodes)
                self._doc_registry[user_id] = []

            # Update document registry
            file_size = os.path.getsize(file_path)
            # Remove any previous entry for this filename before re-adding
            self._doc_registry[user_id] = [
                r for r in self._doc_registry[user_id] if r["filename"] != filename
            ]
            self._doc_registry[user_id].append({
                "filename": filename,
                "file_size": file_size,
                "file_path": file_path,
                "indexed_at": datetime.now().isoformat(),
            })

            self._save_index(user_id)
            log("info", f"LlamaIndex: indexed {filename} ({len(nodes)} sentence nodes)")
            return True

        except Exception as e:
            log("error", f"LlamaIndex: failed to index {filename}: {str(e)}")
            return False

    def _get_text_embedding(self, text: str) -> List[float]:
        """Helper to get embedding for a single text."""
        from shared.common import get_embedding
        return get_embedding(text)

    def delete_document(self, user_id: str, filename: str) -> bool:
        """
        LlamaIndex does not expose a simple per-document delete on VectorStoreIndex.
        Strategy: rebuild the index from remaining registered documents.
        """
        if not self._available or user_id not in self._doc_registry or self.dimension is None:
            return False
        try:
            remaining = [r for r in self._doc_registry[user_id] if r["filename"] != filename]
            if len(remaining) == len(self._doc_registry[user_id]):
                return False  # Document was not registered

            if remaining:
                # Rebuild index from scratch with remaining documents
                parser = SentenceWindowNodeParser.from_defaults(
                    window_size=self.window_size,
                    window_metadata_key="window",
                    original_text_metadata_key="original_sentence",
                )
                all_nodes = []
                for reg in remaining:
                    try:
                        # Check if file_path exists, if not try to reconstruct
                        file_path = reg.get("file_path")
                        if not file_path or not os.path.exists(file_path):
                            log("warning", f"LlamaIndex: file not found for {reg['filename']}, skipping")
                            continue

                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()
                        doc = Document(
                            text=content,
                            metadata={
                                "filename": reg["filename"],
                                "file_path": file_path,
                                "indexed_at": reg["indexed_at"],
                            }
                        )
                        nodes = parser.get_nodes_from_documents([doc])
                        all_nodes.extend(nodes)
                    except Exception as e:
                        log("error", f"LlamaIndex: rebuild error for {reg['filename']}: {str(e)}")

                if all_nodes:
                    self._indices[user_id] = VectorStoreIndex(all_nodes)
                    self._doc_registry[user_id] = remaining
                else:
                    # No valid nodes left, clear the index
                    self._indices.pop(user_id, None)
                    self._doc_registry.pop(user_id, None)
            else:
                self._indices.pop(user_id, None)
                self._doc_registry.pop(user_id, None)

            self._save_index(user_id)
            return True

        except Exception as e:
            log("error", f"LlamaIndex: failed to delete {filename}: {str(e)}")
            return False

    def clear_user_index(self, user_id: str) -> bool:
        try:
            self._indices.pop(user_id, None)
            self._doc_registry.pop(user_id, None)
            user_dir = self.index_path / user_id
            if user_dir.exists():
                shutil.rmtree(str(user_dir))
            return True
        except Exception as e:
            log("error", f"LlamaIndex: failed to clear index for {user_id}: {str(e)}")
            return False

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, user_id: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Retrieve using LlamaIndex's retriever + MetadataReplacementPostProcessor.

        Double-threshold:
          Pass 1 — nodes with score >= high_threshold, up to limit
          Pass 2 — best node if score >= low_threshold (fallback)
        """
        if not self._available or user_id not in self._indices or self.dimension is None:
            return []

        # Validate embedding dimension before search
        try:
            query_embedding = self._get_text_embedding(query)
            if len(query_embedding) != self.dimension:
                log("error",
                    f"LlamaIndex: query embedding dimension mismatch: got {len(query_embedding)}, "
                    f"expected {self.dimension}")
                return self._empty_result(error=f"Dimension mismatch: query={len(query_embedding)}, expected={self.dimension}")
        except Exception as e:
            log("error", f"LlamaIndex: failed to get query embedding: {str(e)}")
            return self._empty_result()

        try:
            retriever = self._indices[user_id].as_retriever(
                similarity_top_k=self.similarity_top_k
            )
            postprocessor = MetadataReplacementPostProcessor(
                target_metadata_key="window"
            )

            raw_nodes = retriever.retrieve(query)
            processed_nodes = postprocessor.postprocess_nodes(raw_nodes)

            if not processed_nodes:
                return self._empty_result()

            max_score = max((n.score or 0.0) for n in processed_nodes)

            def build_result(node, pass_num: int) -> Dict:
                meta = node.node.metadata or {}
                return {
                    "filename": meta.get("filename"),
                    "score": float(node.score or 0.0),
                    "content": node.get_content(),
                    "threshold_used": self.high_threshold,
                    "low_threshold_used": self.low_threshold,
                    "max_score_reached": max_score,
                    "level": "sentence_window",
                    "chapter": "",
                    "section": "",
                    "retrieval_pass": pass_num,
                }

            # Pass 1: above high threshold
            results = [
                build_result(n, 1)
                for n in processed_nodes
                if (n.score or 0.0) >= self.high_threshold
            ][:limit]

            if results:
                log("debug", f"LlamaIndex pass 1: {len(results)} results")
                return results

            # Pass 2: fallback — best node above low threshold
            best = processed_nodes[0]
            if (best.score or 0.0) >= self.low_threshold:
                log("debug", f"LlamaIndex pass 2 fallback: score={best.score:.4f}")
                return [build_result(best, 2)]

            log("debug", f"LlamaIndex: no results above low_threshold (max={max_score:.4f})")
            return self._empty_result(max_score)

        except ValueError as e:
            if "inhomogeneous shape" in str(e):
                log("error",
                    f"LlamaIndex: dimension mismatch detected. This usually happens when mixing "
                    f"embeddings from different models. Please rebuild the index with: "
                    f"engine.force_rebuild_index('{user_id}')")
                return self._empty_result(error=f"Dimension mismatch - please rebuild index")
            log("error", f"LlamaIndex search failed: {str(e)}", stacktrace=True)
            return self._empty_result()
        except Exception as e:
            log("error", f"LlamaIndex search failed: {str(e)}", stacktrace=True)
            return self._empty_result()

    def _empty_result(self, max_score: float = 0.0, error: str = "") -> List[Dict]:
        result = {
            "filename": None,
            "score": 0.0,
            "content": "",
            "threshold_used": self.high_threshold,
            "low_threshold_used": self.low_threshold,
            "max_score_reached": max_score,
            "level": None,
            "chapter": None,
            "section": None,
            "retrieval_pass": 0,
            "no_results": True,
        }
        if error:
            result["error"] = error
        return [result]

    # ------------------------------------------------------------------
    # Stats / metadata
    # ------------------------------------------------------------------

    def get_indexed_documents(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        documents = []
        for uid in ([user_id] if user_id else self._doc_registry.keys()):
            for reg in self._doc_registry.get(uid, []):
                documents.append({
                    "user_id": uid,
                    "filename": reg["filename"],
                    "indexed_at": reg["indexed_at"],
                    "size": reg.get("file_size", 0),
                })
        return documents

    def is_available(self) -> bool:
        return self._available and self.dimension is not None

    def get_stats(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        if user_id:
            reg = self._doc_registry.get(user_id, [])
            index = self._indices.get(user_id)
            node_count = "n/a"
            if index and hasattr(index, '_vector_store') and isinstance(index._vector_store, SimpleVectorStore):
                node_count = len(index._vector_store.data.embedding_dict)
            return {
                "documents_indexed": len(reg),
                "total_nodes": node_count,
                "window_size": self.window_size,
                "engine_type": self.engine_type,
                "model_name": self.model_name,
                "dimension": self.dimension,
            }
        return {
            "total_documents_indexed": sum(len(v) for v in self._doc_registry.values()),
            "users_with_index": len(self._indices),
            "window_size": self.window_size,
            "engine_type": self.engine_type,
            "model_name": self.model_name,
            "dimension": self.dimension,
        }
