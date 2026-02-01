# [file name]: rag_classic.py (modified sections)
"""
FAISS-based RAG Engine Plugin (classic vector search)
"""

import os
import numpy as np
import faiss
import pickle
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path

from sentence_transformers import SentenceTransformer

from ..rag_engine import RAGEngine
from shared.logging import log
from shared.config import get_config
# Import the caching module
try:
    from ..rag_caching import RAGModelCache
except ImportError:
    # Fallback if caching module not available
    RAGModelCache = None


class ClassicRAGEngine(RAGEngine):
    """FAISS-based RAG engine using sentence embeddings and vector similarity search."""

    def __init__(self):
        super().__init__("classic")
        self.description = "Classic vector store with embeddings"

        # Load FAISS-specific config
        rag_config = get_config().get("rag_manager", {})
        engines_config = rag_config.get("engines", {})

        # Try to get from "faiss" config first, then fallback to general
        faiss_config = engines_config.get("faiss", {})
        if not faiss_config:
            # Fallback: try to get from "classic" or use defaults
            faiss_config = engines_config.get("classic", {})

        self.index_path = Path(faiss_config.get("faiss_index_path", "./data/classic_indexes"))
        self.index_path.mkdir(parents=True, exist_ok=True)

        self.embedding_model_name = faiss_config.get("embedding_model", "sentence-transformers/all-MiniLM-L6-v2")
        self.chunk_size = faiss_config.get("chunk_size", 500)
        self.chunk_overlap = faiss_config.get("chunk_overlap", 50)
        self.similarity_threshold = faiss_config.get("similarity_threshold", 0.5)

        # Log the actual config being used
        log("debug", f"Classic RAG config: index_path={self.index_path}, model={self.embedding_model_name}")

        # Load embedding model WITH CACHING
        try:
            if RAGModelCache:
                # Use cached model loading
                self.model = RAGModelCache.get_embedding_model_cached(self.embedding_model_name)
                self.dimension = RAGModelCache.get_model_dimension(self.embedding_model_name)
            else:
                # Fallback to direct loading
                self.model = SentenceTransformer(self.embedding_model_name)
                self.dimension = self.model.get_sentence_embedding_dimension()

            log("info", f"Loaded embedding model: {self.embedding_model_name} (dim: {self.dimension})")
        except Exception as e:
            log("error", f"Failed to load embedding model {self.embedding_model_name}: {str(e)}")
            self.model = None
            self.dimension = None

        # In-memory indices and metadata
        self.indices: Dict[str, faiss.IndexFlatIP] = {}  # user_id -> FAISS index
        self.metadata: Dict[str, List[Dict[str, Any]]] = {}  # user_id -> list of chunk metadata dicts

        self._load_indices()

    # ... rest of the class remains the same ...
