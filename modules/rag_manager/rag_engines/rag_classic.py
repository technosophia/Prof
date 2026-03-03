"""
FAISS-based RAG Engine Plugin (classic vector search)

No Streamlit dependency. Config is injected at construction time.
"""

import os
import numpy as np
import faiss
import pickle
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path

from ..rag_engine import RAGEngine
from shared.common import get_embedding, get_embeddings
from core.logging import log


class ClassicRAGEngine(RAGEngine):
    """FAISS-based RAG engine using sentence embeddings and vector similarity search."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Args:
            config: The 'engines.classic' section of the rag_manager config dict.
                    If None, falls back to st_shared.cached for backward compatibility.
        """
        super().__init__("classic")
        self.description = "Classic vector store with embeddings"

        if config is None:
            # Backward-compat: fetch from Streamlit-cached config
            from st_shared.cached import get_config as _get_config
            rag_config = _get_config().get("modules.rag_manager", {})
            config = rag_config.get("engines", {}).get("classic", {})

        self.index_path = Path(config.get("index_path", "data/classic_indexes"))
        self.index_path.mkdir(parents=True, exist_ok=True)

        self.chunk_size = config.get("chunk_size", 500)
        self.chunk_overlap = config.get("chunk_overlap", 50)
        self.similarity_threshold = config.get("similarity_threshold", 0.5)

        log("debug", f"Classic RAG config: index_path={self.index_path}")

        try:
            self.dimension = len(get_embedding(""))
            log("info", f"Initialized embeddings via LLM manager (dim: {self.dimension})")
        except Exception as e:
            log("error", f"Failed to initialize embeddings via LLM manager: {str(e)}")
            self.dimension = None

        self.indices: Dict[str, faiss.IndexFlatIP] = {}
        self.metadata: Dict[str, List[Dict[str, Any]]] = {}

        self._load_indices()

    def _load_indices(self):
        for index_file in self.index_path.glob("*_faiss.index"):
            user_id = index_file.stem.replace("_faiss", "")
            try:
                index = faiss.read_index(str(index_file))
                self.indices[user_id] = index
                meta_file = self.index_path / f"{user_id}_faiss_meta.pkl"
                if meta_file.exists():
                    with open(meta_file, 'rb') as f:
                        self.metadata[user_id] = pickle.load(f)
                log("debug", f"Loaded FAISS index for user {user_id} with {index.ntotal} vectors")
            except Exception as e:
                log("error", f"Failed to load FAISS index for user {user_id}: {str(e)}")

    def _save_user_index(self, user_id: str):
        index_file = self.index_path / f"{user_id}_faiss.index"
        meta_file = self.index_path / f"{user_id}_faiss_meta.pkl"

        if user_id in self.indices and self.indices[user_id].ntotal > 0:
            try:
                faiss.write_index(self.indices[user_id], str(index_file))
                with open(meta_file, 'wb') as f:
                    pickle.dump(self.metadata[user_id], f)
            except Exception as e:
                log("error", f"Failed to save FAISS index for user {user_id}: {str(e)}")
        else:
            if index_file.exists():
                index_file.unlink()
            if meta_file.exists():
                meta_file.unlink()
            self.indices.pop(user_id, None)
            self.metadata.pop(user_id, None)

    def _chunk_text(self, text: str) -> List[str]:
        if not text.strip():
            return []
        chunks = []
        start = 0
        while start < len(text):
            end = start + self.chunk_size
            chunk = text[start:end]
            chunks.append(chunk.strip())
            if end >= len(text):
                break
            start = end - self.chunk_overlap
        return [c for c in chunks if len(c) > 50]

    def _encode_texts(self, texts: List[str]) -> np.ndarray:
        embeddings = np.array(get_embeddings(texts), dtype=np.float32)
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return embeddings / norms

    def index_document(self, user_id: str, filename: str, file_path: str, content: Optional[str] = None) -> bool:
        if self.dimension is None:
            return False
        try:
            if content is None:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

            chunks = self._chunk_text(content)
            if not chunks:
                return False

            embeddings = self._encode_texts(chunks)
            file_size = os.path.getsize(file_path)

            if user_id not in self.indices:
                self.indices[user_id] = faiss.IndexFlatIP(self.dimension)
                self.metadata[user_id] = []

            self.indices[user_id].add(embeddings)
            for chunk_text in chunks:
                self.metadata[user_id].append({
                    'chunk_text': chunk_text,
                    'filename': filename,
                    'file_size': file_size,
                    'file_path': file_path,
                    'indexed_at': datetime.now().isoformat(),
                })
            self._save_user_index(user_id)
            return True
        except Exception as e:
            log("error", f"Failed to index document {filename}: {str(e)}", stacktrace=True)
            return False

    def delete_document(self, user_id: str, filename: str) -> bool:
        if user_id not in self.metadata:
            return False
        try:
            kept_meta = [m for m in self.metadata[user_id] if m['filename'] != filename]
            if len(kept_meta) == len(self.metadata[user_id]):
                return False

            if kept_meta:
                embeddings = self._encode_texts([m['chunk_text'] for m in kept_meta])
                new_index = faiss.IndexFlatIP(self.dimension)
                new_index.add(embeddings)
                self.indices[user_id] = new_index
                self.metadata[user_id] = kept_meta
            else:
                self.indices.pop(user_id, None)
                self.metadata.pop(user_id, None)

            self._save_user_index(user_id)
            return True
        except Exception as e:
            log("error", f"Failed to delete document {filename}: {str(e)}")
            return False

    def search(self, user_id: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        if self.dimension is None or user_id not in self.indices or self.indices[user_id].ntotal == 0:
            return []
        try:
            query_emb = self._encode_texts([query])
            D, I = self.indices[user_id].search(query_emb, limit * 3)
            results = []
            for dist, idx in zip(D[0], I[0]):
                if idx == -1:
                    break
                if dist < self.similarity_threshold:
                    continue
                meta = self.metadata[user_id][idx]
                results.append({'filename': meta['filename'], 'score': float(dist), 'content': meta['chunk_text']})
                if len(results) >= limit:
                    break
            return results
        except Exception as e:
            log("error", f"Classic search failed: {str(e)}", stacktrace=True)
            return []

    def get_indexed_documents(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        documents = []
        for uid in ([user_id] if user_id else self.metadata.keys()):
            if uid in self.metadata:
                seen = set()
                for meta in self.metadata[uid]:
                    fn = meta['filename']
                    if fn not in seen:
                        seen.add(fn)
                        documents.append({'user_id': uid, 'filename': fn, 'indexed_at': meta['indexed_at'], 'size': meta.get('file_size', 0)})
        return documents

    def clear_user_index(self, user_id: str) -> bool:
        try:
            self.indices.pop(user_id, None)
            self.metadata.pop(user_id, None)
            self._save_user_index(user_id)
            return True
        except Exception as e:
            log("error", f"Failed to clear FAISS index for user {user_id}: {str(e)}")
            return False

    def is_available(self) -> bool:
        return self.dimension is not None

    def get_stats(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        if user_id:
            return {
                'documents_indexed': len({m['filename'] for m in self.metadata.get(user_id, [])}),
                'total_chunks': len(self.metadata.get(user_id, [])),
                'engine_type': self.engine_type,
            }
        total_docs = sum(len({m['filename'] for m in chunks}) for chunks in self.metadata.values())
        total_chunks = sum(len(chunks) for chunks in self.metadata.values())
        return {
            'total_documents_indexed': total_docs,
            'total_chunks': total_chunks,
            'users_with_index': len(self.metadata),
            'engine_type': self.engine_type,
        }
