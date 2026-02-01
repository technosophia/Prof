# [file name]: rag_caching.py
"""
Strategic caching for RAG models
"""

import streamlit as st
from typing import Optional, Dict, Any
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module=r"torch\.cuda")
from sentence_transformers import SentenceTransformer
from shared.logging import log

class RAGModelCache:
    """Manages caching of heavy model weights for RAG engines."""

    @staticmethod
    @st.cache_resource(show_spinner=False, max_entries=3, ttl=3600)
    def get_embedding_model_cached(model_name: str) -> SentenceTransformer:
        """
        Cache embedding models globally.
        Returns a cached instance of SentenceTransformer.
        """
        log("info", f"Loading embedding model (cached): {model_name}")
        try:
            model = SentenceTransformer(model_name, device="cpu")
            log("info", f"Model loaded successfully: {model_name}")
            return model
        except Exception as e:
            log("error", f"Failed to load model {model_name}: {str(e)}")
            raise

    @staticmethod
    def clear_embedding_cache():
        """Clear all cached embedding models."""
        cache_funcs = [RAGModelCache.get_embedding_model_cached]
        for func in cache_funcs:
            try:
                func.clear()
                log("debug", f"Cleared cache for {func.__name__}")
            except Exception as e:
                log("warning", f"Could not clear cache: {str(e)}")

    @staticmethod
    def get_model_dimension(model_name: str) -> int:
        """Get model dimension with caching."""
        model = RAGModelCache.get_embedding_model_cached(model_name)
        return model.get_sentence_embedding_dimension()
