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

from ..rag_engine import RAGEngine
from shared.common import log, get_embedding, get_embeddings
from shared.cached import get_config


class ClassicRAGEngine(RAGEngine):
    """FAISS-based RAG engine using sentence embeddings and vector similarity search."""

    def __init__(self):
        super().__init__("classic")
        self.description = "Classic vector store with embeddings"

        # Load FAISS-specific config
        rag_config = get_config().get("modules.rag_manager", {})
        engines_config = rag_config.get("engines", {})

        # Try to get from "faiss" config first, then fallback to general
        faiss_config = engines_config.get("classic", {})

        self.index_path = Path(faiss_config.get("index_path", "data/classic_indexes"))
        self.index_path.mkdir(parents=True, exist_ok=True)

        self.embedding_model_name = faiss_config.get("embedding_model", "sentence-transformers/all-MiniLM-L6-v2")
        self.chunk_size = faiss_config.get("chunk_size", 500)
        self.chunk_overlap = faiss_config.get("chunk_overlap", 50)
        self.similarity_threshold = faiss_config.get("similarity_threshold", 0.5)

        # Log the actual config being used
        log("debug", f"Classic RAG config: index_path={self.index_path}, model={self.embedding_model_name}")

        # Use shared LLM manager embeddings
        try:
            # Keep config compatibility while relying on centralized embedding API.
            self.dimension = len(get_embedding(""))
            log("info", f"Initialized embeddings via LLM manager (configured model hint: {self.embedding_model_name}, dim: {self.dimension})")
        except Exception as e:
            log("error", f"Failed to initialize embeddings via LLM manager: {str(e)}")
            self.dimension = None

        # In-memory indices and metadata
        self.indices: Dict[str, faiss.IndexFlatIP] = {}  # user_id -> FAISS index
        self.metadata: Dict[str, List[Dict[str, Any]]] = {}  # user_id -> list of chunk metadata dicts

        self._load_indices()

    def _load_indices(self):
        """Load all persisted FAISS indices and metadata on startup."""
        for index_file in self.index_path.glob("*_faiss.index"):
            user_id = index_file.stem.replace("_faiss", "")
            try:
                index = faiss.read_index(str(index_file))
                self.indices[user_id] = index

                meta_file = self.index_path / f"{user_id}_faiss_meta.pkl"
                if meta_file.exists():
                    with open(meta_file, 'rb') as f:
                        self.metadata[user_id] = pickle.load(f)

                log("info", f"Loaded FAISS index for user {user_id} with {index.ntotal} vectors")
            except Exception as e:
                log("error", f"Failed to load FAISS index for user {user_id}: {str(e)}")

    def _save_user_index(self, user_id: str):
        """Save or remove a user's FAISS index and metadata."""
        index_file = self.index_path / f"{user_id}_faiss.index"
        meta_file = self.index_path / f"{user_id}_faiss_meta.pkl"

        if user_id in self.indices and self.indices[user_id].ntotal > 0:
            try:
                faiss.write_index(self.indices[user_id], str(index_file))
                with open(meta_file, 'wb') as f:
                    pickle.dump(self.metadata[user_id], f)
                log("debug", f"Saved FAISS index for user {user_id}")
            except Exception as e:
                log("error", f"Failed to save FAISS index for user {user_id}: {str(e)}")
        else:
            # Clean up files if index is empty or removed
            if index_file.exists():
                index_file.unlink()
            if meta_file.exists():
                meta_file.unlink()
            self.indices.pop(user_id, None)
            self.metadata.pop(user_id, None)

    def _chunk_text(self, text: str) -> List[str]:
        """Simple character-based chunking with overlap."""
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

        # Filter out very small chunks
        return [c for c in chunks if len(c) > 50]

    def _encode_texts(self, texts: List[str]) -> np.ndarray:
        """Embed texts via shared LLM manager and normalize for cosine similarity."""
        embeddings = np.array(get_embeddings(texts), dtype=np.float32)
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return embeddings / norms

    def index_document(self, user_id: str, filename: str, file_path: str, content: Optional[str] = None) -> bool:
        """Index a document by chunking, embedding, and adding to FAISS."""
        if self.dimension is None:
            log("error", "Embedding model not available")
            return False

        try:
            if content is None:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

            chunks = self._chunk_text(content)
            if not chunks:
                log("warning", f"No chunks created for document {filename}")
                return False

            embeddings = self._encode_texts(chunks)

            file_size = os.path.getsize(file_path)
            log("info", f"Indexed 1")
            # Create or retrieve index
            if user_id not in self.indices:
                index = faiss.IndexFlatIP(self.dimension)
                self.indices[user_id] = index
                self.metadata[user_id] = []
            else:
                index = self.indices[user_id]

            index.add(embeddings)
            log("info", f"Indexed 2")
            # Append metadata (order matches vector order)
            for i, chunk_text in enumerate(chunks):
                self.metadata[user_id].append({
                    'chunk_text': chunk_text,
                    'filename': filename,
                    'file_size': file_size,
                    'file_path': file_path,
                    'indexed_at': datetime.now().isoformat()
                })
            log("info", f"Indexed 3")
            self._save_user_index(user_id)
            log("info", f"Indexed document {filename} for user {user_id} ({len(chunks)} chunks) using FAISS")
            return True

        except Exception as e:
            log("error", f"Failed to index document {filename}: {str(e)}", exc_info=True)
            return False

    def delete_document(self, user_id: str, filename: str) -> bool:
        """Delete all chunks belonging to a document and rebuild the index."""
        if user_id not in self.metadata:
            return False

        try:
            current_meta = self.metadata[user_id]
            kept_meta = [m for m in current_meta if m['filename'] != filename]

            if len(kept_meta) == len(current_meta):
                return False  # No chunks removed

            if kept_meta:
                texts = [m['chunk_text'] for m in kept_meta]
                embeddings = self._encode_texts(texts)

                new_index = faiss.IndexFlatIP(self.dimension)
                new_index.add(embeddings)

                self.indices[user_id] = new_index
                self.metadata[user_id] = kept_meta
            else:
                # No chunks left for this user
                self.indices.pop(user_id, None)
                self.metadata.pop(user_id, None)

            self._save_user_index(user_id)
            log("info", f"Deleted document {filename} from FAISS index for user {user_id}")
            return True

        except Exception as e:
            log("error", f"Failed to delete document {filename}: {str(e)}")
            return False

    def search(self, user_id: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search using vector similarity."""
        if self.dimension is None or user_id not in self.indices or self.indices[user_id].ntotal == 0:
            return []

        try:
            query_emb = self._encode_texts([query])

            # Search more candidates to allow threshold filtering
            D, I = self.indices[user_id].search(query_emb, limit * 3)

            results = []
            for dist, idx in zip(D[0], I[0]):
                if idx == -1:
                    break
                if dist < self.similarity_threshold:
                    continue

                meta = self.metadata[user_id][idx]
                results.append({
                    'filename': meta['filename'],
                    'score': float(dist),
                    'content': meta['chunk_text']
                })
                if len(results) >= limit:
                    break

            return results

        except Exception as e:
            log("error", f"FAISS search failed: {str(e)}")
            return []

    def get_indexed_documents(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get list of indexed documents (unique filenames)."""
        documents = []
        users_to_check = [user_id] if user_id else self.metadata.keys()

        for uid in users_to_check:
            if uid in self.metadata:
                seen = set()
                for meta in self.metadata[uid]:
                    fn = meta['filename']
                    if fn not in seen:
                        seen.add(fn)
                        documents.append({
                            'user_id': uid,
                            'filename': fn,
                            'indexed_at': meta['indexed_at'],
                            'size': meta.get('file_size', 0)
                        })

        return documents

    def clear_user_index(self, user_id: str) -> bool:
        """Clear all indexed data for a user."""
        try:
            self.indices.pop(user_id, None)
            self.metadata.pop(user_id, None)
            self._save_user_index(user_id)
            log("info", f"Cleared FAISS index for user {user_id}")
            return True
        except Exception as e:
            log("error", f"Failed to clear FAISS index for user {user_id}: {str(e)}")
            return False

    def is_available(self) -> bool:
        """Check if the engine is functional."""
        return self.dimension is not None

    def get_stats(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Get engine statistics."""
        if user_id:
            doc_count = len({m['filename'] for m in self.metadata.get(user_id, [])})
            chunk_count = len(self.metadata.get(user_id, []))
            return {
                'documents_indexed': doc_count,
                'total_chunks': chunk_count,
                'engine_type': self.engine_type
            }
        else:
            total_docs = 0
            total_chunks = 0
            users = 0
            for uid in self.metadata:
                total_docs += len({m['filename'] for m in self.metadata[uid]})
                total_chunks += len(self.metadata[uid])
                users += 1
            return {
                'total_documents_indexed': total_docs,
                'total_chunks': total_chunks,
                'users_with_index': users,
                'engine_type': self.engine_type
            }
