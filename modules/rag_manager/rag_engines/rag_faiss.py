"""
FAISS RAG Engine Plugin
"""

import os
import pickle
import numpy as np
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import hashlib

from ..rag_engine import RAGEngine
from shared.logging import log
from shared.config import get_config

# Try to import FAISS and sentence-transformers
try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    log("warning", "FAISS not installed. Install with: pip install faiss-cpu")

try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    log("warning", "SentenceTransformers not installed. Install with: pip install sentence-transformers")


class FaissRAGEngine(RAGEngine):
    """FAISS-based RAG engine using vector embeddings."""

    def __init__(self):
        super().__init__("faiss")
        self.description = "FAISS vector store with semantic search capabilities"

        # Get configuration
        self.config = get_config()
        rag_config = self.config.get("rag_manager", {})
        faiss_config = rag_config.get("engines", {}).get("faiss", {})

        # Configuration
        self.index_path = Path(faiss_config.get("faiss_index_path", "./data/faiss_indexes"))
        self.embedding_model_name = faiss_config.get("embedding_model", "sentence-transformers/all-MiniLM-L6-v2")
        self.chunk_size = faiss_config.get("chunk_size", 500)
        self.chunk_overlap = faiss_config.get("chunk_overlap", 50)
        self.similarity_threshold = faiss_config.get("similarity_threshold", 0.7)
        self.dimension = 384  # Default for all-MiniLM-L6-v2

        # Initialize
        self.indices = {}  # user_id -> faiss_index
        self.metadata = {}  # user_id -> {vector_id: {filename, chunk_index, text}}
        self.embedding_model = None

        # Create index directory
        self.index_path.mkdir(parents=True, exist_ok=True)

        # Load existing indices
        self._load_existing_indices()

    def is_available(self) -> bool:
        """Check if FAISS engine is available."""
        if not FAISS_AVAILABLE:
            log("error", "FAISS is not installed. Please install faiss-cpu")
            return False
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            log("error", "SentenceTransformers is not installed")
            return False
        return True

    def _load_existing_indices(self):
        """Load existing FAISS indices from disk."""
        if not self.is_available():
            return

        try:
            index_files = list(self.index_path.glob("*_faiss.index"))
            metadata_files = list(self.index_path.glob("*_metadata.pkl"))

            for idx_file in index_files:
                # Extract user_id from filename
                user_id = idx_file.name.replace("_faiss.index", "")

                # Load FAISS index
                index = faiss.read_index(str(idx_file))
                self.indices[user_id] = index

                # Load metadata
                metadata_file = self.index_path / f"{user_id}_metadata.pkl"
                if metadata_file.exists():
                    with open(metadata_file, 'rb') as f:
                        self.metadata[user_id] = pickle.load(f)

                log("info", f"Loaded FAISS index for user {user_id} with {index.ntotal} vectors")

        except Exception as e:
            log("error", f"Failed to load existing FAISS indices: {str(e)}")

    def _get_embedding_model(self):
        """Get or create embedding model."""
        if self.embedding_model is None and self.is_available():
            try:
                self.embedding_model = SentenceTransformer(self.embedding_model_name)
                # Update dimension based on model
                test_embedding = self.embedding_model.encode(["test"])
                self.dimension = test_embedding.shape[1]
                log("info", f"Loaded embedding model: {self.embedding_model_name}, dimension: {self.dimension}")
            except Exception as e:
                log("error", f"Failed to load embedding model: {str(e)}")
                return None
        return self.embedding_model

    def _chunk_text(self, text: str) -> List[str]:
        """Split text into overlapping chunks."""
        words = text.split()
        chunks = []

        for i in range(0, len(words), self.chunk_size - self.chunk_overlap):
            chunk = ' '.join(words[i:i + self.chunk_size])
            if chunk:
                chunks.append(chunk)

        return chunks

    def _get_document_hash(self, file_path: str) -> str:
        """Generate hash for document to detect changes."""
        try:
            with open(file_path, 'rb') as f:
                content = f.read()
            return hashlib.md5(content).hexdigest()[:16]
        except:
            return str(os.path.getmtime(file_path))

    def index_document(self, user_id: str, filename: str, file_path: str, content: Optional[str] = None) -> bool:
        """Index a document using FAISS embeddings."""
        try:
            if not self.is_available():
                log("error", "FAISS engine is not available")
                return False

            # Get embedding model
            model = self._get_embedding_model()
            if model is None:
                return False

            # Read content if not provided
            if content is None:
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                except:
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                    except Exception as e:
                        log("error", f"Cannot read file {file_path}: {str(e)}")
                        return False

            if not content or len(content.strip()) == 0:
                log("warning", f"Empty content for file {filename}")
                return False

            # Delete existing document first (re-index)
            self.delete_document(user_id, filename)

            # Chunk the content
            chunks = self._chunk_text(content)

            if not chunks:
                log("warning", f"No chunks generated for {filename}")
                return False

            # Generate embeddings
            embeddings = model.encode(chunks, show_progress_bar=False)

            # Initialize or get user's index
            if user_id not in self.indices:
                # Create new index
                index = faiss.IndexFlatIP(self.dimension)  # Inner product for cosine similarity
                self.indices[user_id] = index
                self.metadata[user_id] = {}
            else:
                index = self.indices[user_id]

            # Add embeddings to index
            start_idx = index.ntotal
            index.add(embeddings.astype('float32'))

            # Store metadata
            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                vector_id = start_idx + i
                self.metadata[user_id][vector_id] = {
                    'filename': filename,
                    'chunk_index': i,
                    'text': chunk,
                    'embedding': embedding.tolist(),
                    'document_hash': self._get_document_hash(file_path),
                    'indexed_at': datetime.now().isoformat()
                }

            # Save to disk
            self._save_user_index(user_id)

            log("info", f"Indexed document {filename} for user {user_id} with {len(chunks)} chunks")
            return True

        except Exception as e:
            log("error", f"Failed to index document {filename}: {str(e)}", exc_info=True)
            return False

    def delete_document(self, user_id: str, filename: str) -> bool:
        """Delete a document from the FAISS index."""
        try:
            if user_id not in self.metadata:
                return True  # Document not indexed

            # Find all vectors for this document
            vectors_to_delete = []
            for vector_id, meta in list(self.metadata[user_id].items()):
                if meta['filename'] == filename:
                    vectors_to_delete.append(vector_id)

            if not vectors_to_delete:
                return True  # Document not found

            # Remove from metadata
            for vector_id in vectors_to_delete:
                del self.metadata[user_id][vector_id]

            # Rebuild index without deleted vectors
            self._rebuild_user_index(user_id)

            log("info", f"Deleted document {filename} from FAISS index for user {user_id}")
            return True

        except Exception as e:
            log("error", f"Failed to delete document {filename}: {str(e)}")
            return False

    def _rebuild_user_index(self, user_id: str):
        """Rebuild FAISS index from metadata."""
        if user_id not in self.metadata or not self.metadata[user_id]:
            # No vectors, create empty index
            self.indices[user_id] = faiss.IndexFlatIP(self.dimension)
            return

        # Collect all embeddings
        embeddings = []
        metadata_items = []

        for vector_id, meta in sorted(self.metadata[user_id].items()):
            if 'embedding' in meta:
                embeddings.append(meta['embedding'])
                metadata_items.append((vector_id, meta))

        if not embeddings:
            self.indices[user_id] = faiss.IndexFlatIP(self.dimension)
            return

        # Create new index
        embeddings_array = np.array(embeddings, dtype='float32')
        index = faiss.IndexFlatIP(self.dimension)
        index.add(embeddings_array)
        self.indices[user_id] = index

        # Update metadata with new vector IDs
        new_metadata = {}
        for new_id, (old_vector_id, meta) in enumerate(metadata_items):
            new_metadata[new_id] = meta

        self.metadata[user_id] = new_metadata

        # Save
        self._save_user_index(user_id)

    def _save_user_index(self, user_id: str):
        """Save user's FAISS index and metadata to disk."""
        try:
            if user_id in self.indices:
                index_file = self.index_path / f"{user_id}_faiss.index"
                faiss.write_index(self.indices[user_id], str(index_file))

            if user_id in self.metadata:
                metadata_file = self.index_path / f"{user_id}_metadata.pkl"
                with open(metadata_file, 'wb') as f:
                    pickle.dump(self.metadata[user_id], f)

            log("debug", f"Saved FAISS index for user {user_id}")

        except Exception as e:
            log("error", f"Failed to save FAISS index for user {user_id}: {str(e)}")

    def search(self, user_id: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Semantic search using FAISS."""
        results = []

        try:
            if not self.is_available():
                return results

            if user_id not in self.indices or self.indices[user_id].ntotal == 0:
                return results

            # Get embedding model
            model = self._get_embedding_model()
            if model is None:
                return results

            # Encode query
            query_embedding = model.encode([query])

            # Search in FAISS index
            index = self.indices[user_id]
            k = min(limit * 2, index.ntotal)  # Get more results for filtering

            if k == 0:
                return results

            distances, indices = index.search(query_embedding.astype('float32'), k)

            # Convert to results
            for distance, vector_id in zip(distances[0], indices[0]):
                if vector_id == -1:  # No more results
                    continue

                if vector_id in self.metadata.get(user_id, {}):
                    meta = self.metadata[user_id][vector_id]

                    # Calculate cosine similarity (from inner product)
                    # Assuming embeddings are normalized
                    similarity = float(distance)

                    if similarity >= self.similarity_threshold:
                        results.append({
                            'filename': meta['filename'],
                            'score': similarity,
                            'content': meta['text'],
                            'metadata': {
                                'chunk_index': meta['chunk_index'],
                                'similarity': similarity,
                                'indexed_at': meta.get('indexed_at', '')
                            }
                        })

                        if len(results) >= limit:
                            break

            # Sort by score descending
            results.sort(key=lambda x: x['score'], reverse=True)

        except Exception as e:
            log("error", f"FAISS search error: {str(e)}", exc_info=True)

        return results

    def get_indexed_documents(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get list of indexed documents."""
        documents = []

        users_to_check = [user_id] if user_id else list(self.metadata.keys())

        for uid in users_to_check:
            if uid in self.metadata:
                # Collect unique documents
                unique_docs = {}
                for vector_id, meta in self.metadata[uid].items():
                    filename = meta['filename']
                    if filename not in unique_docs:
                        unique_docs[filename] = {
                            'user_id': uid,
                            'filename': filename,
                            'chunks_count': 0,
                            'indexed_at': meta.get('indexed_at', '')
                        }
                    unique_docs[filename]['chunks_count'] += 1

                documents.extend(unique_docs.values())

        return documents

    def clear_user_index(self, user_id: str) -> bool:
        """Clear all indexed documents for a user."""
        try:
            # Remove from memory
            if user_id in self.indices:
                del self.indices[user_id]
            if user_id in self.metadata:
                del self.metadata[user_id]

            # Remove from disk
            index_file = self.index_path / f"{user_id}_faiss.index"
            metadata_file = self.index_path / f"{user_id}_metadata.pkl"

            if index_file.exists():
                index_file.unlink()
            if metadata_file.exists():
                metadata_file.unlink()

            log("info", f"Cleared FAISS index for user {user_id}")
            return True

        except Exception as e:
            log("error", f"Failed to clear FAISS index for user {user_id}: {str(e)}")
            return False

    def get_stats(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Get engine statistics."""
        stats = {
            'engine_type': self.engine_type,
            'embedding_model': self.embedding_model_name,
            'dimension': self.dimension
        }

        if user_id:
            if user_id in self.indices:
                stats['documents_indexed'] = len(set(
                    meta['filename'] for meta in self.metadata.get(user_id, {}).values()
                ))
                stats['total_chunks'] = self.indices[user_id].ntotal
                stats['index_size_mb'] = self._get_index_size(user_id)
            else:
                stats['documents_indexed'] = 0
                stats['total_chunks'] = 0
                stats['index_size_mb'] = 0
        else:
            # Global stats
            total_docs = 0
            total_chunks = 0
            total_size_mb = 0

            for uid in self.indices:
                unique_docs = set(
                    meta['filename'] for meta in self.metadata.get(uid, {}).values()
                )
                total_docs += len(unique_docs)
                total_chunks += self.indices[uid].ntotal
                total_size_mb += self._get_index_size(uid)

            stats['total_users'] = len(self.indices)
            stats['total_documents_indexed'] = total_docs
            stats['total_chunks'] = total_chunks
            stats['total_index_size_mb'] = round(total_size_mb, 2)

        return stats

    def _get_index_size(self, user_id: str) -> float:
        """Calculate index size in MB."""
        try:
            index_file = self.index_path / f"{user_id}_faiss.index"
            metadata_file = self.index_path / f"{user_id}_metadata.pkl"

            total_bytes = 0
            if index_file.exists():
                total_bytes += index_file.stat().st_size
            if metadata_file.exists():
                total_bytes += metadata_file.stat().st_size

            return total_bytes / (1024 * 1024)
        except:
            return 0.0
