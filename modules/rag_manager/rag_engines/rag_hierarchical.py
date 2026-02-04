"""
Hierarchical FAISS-based RAG Engine Plugin
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
from shared.common import get_config
# Import the caching module
try:
    from ..rag_caching import RAGModelCache
except ImportError:
    # Fallback if caching module not available
    RAGModelCache = None

class FaissHierarchicalRAGEngine(RAGEngine):
    """FAISS-based RAG engine with hierarchical chunking for structured markdown documents (chapter summary + subsections)."""

    def __init__(self):
        super().__init__("faiss_hierarchical")
        self.description = "FAISS vector store with hierarchical markdown parsing (chapter résumé + subsections)"

        # Load config - get from faiss_hierarchical section
        rag_config = get_config().get("modules.rag_manager", {})
        engines_config = rag_config.get("engines", {})

        # Get hierarchical-specific config
        hier_config = engines_config.get("faiss_hierarchical", {})
        if not hier_config:
            # Fallback to faiss config for compatibility
            hier_config = engines_config.get("faiss", {})
            log("warning", "Using faiss config as fallback for faiss_hierarchical engine")

        self.index_path = Path(hier_config.get("index_path", "./data/hierarchical_indexes"))
        self.index_path.mkdir(parents=True, exist_ok=True)

        self.embedding_model_name = hier_config.get("embedding_model", "sentence-transformers/all-MiniLM-L6-v2")
        self.similarity_threshold = hier_config.get("similarity_threshold", 0.5)

        # Log the actual config being used
        log("debug", f"Hierarchical RAG config: index_path={self.index_path}, model={self.embedding_model_name}")

        # Load embedding model WITH CACHING
        try:
            if RAGModelCache:
                # Use cached model loading
                self.model = RAGModelCache.get_embedding_model_cached(self.embedding_model_name)
                self.dimension = RAGModelCache.get_model_dimension(self.embedding_model_name)
            else:
                # Fallback to direct loading
                self.model = SentenceTransformer(self.embedding_model_name, device='cpu')
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

    def _load_indices(self):
        """Load all persisted FAISS indices and metadata on startup."""
        for index_file in self.index_path.glob("*_faiss_hier.index"):
            user_id = index_file.stem.replace("_faiss_hier", "")
            try:
                index = faiss.read_index(str(index_file))
                self.indices[user_id] = index

                meta_file = self.index_path / f"{user_id}_faiss_hier_meta.pkl"
                if meta_file.exists():
                    with open(meta_file, 'rb') as f:
                        self.metadata[user_id] = pickle.load(f)

                log("info", f"Loaded hierarchical FAISS index for user {user_id} with {index.ntotal} vectors")
            except Exception as e:
                log("error", f"Failed to load hierarchical FAISS index for user {user_id}: {str(e)}")

    def _save_user_index(self, user_id: str):
        """Save or remove a user's FAISS index and metadata."""
        index_file = self.index_path / f"{user_id}_faiss_hier.index"
        meta_file = self.index_path / f"{user_id}_faiss_hier_meta.pkl"

        if user_id in self.indices and self.indices[user_id].ntotal > 0:
            try:
                faiss.write_index(self.indices[user_id], str(index_file))
                with open(meta_file, 'wb') as f:
                    pickle.dump(self.metadata[user_id], f)
                log("debug", f"Saved hierarchical FAISS index for user {user_id}")
            except Exception as e:
                log("error", f"Failed to save hierarchical FAISS index for user {user_id}: {str(e)}")
        else:
            if index_file.exists():
                index_file.unlink()
            if meta_file.exists():
                meta_file.unlink()
            self.indices.pop(user_id, None)
            self.metadata.pop(user_id, None)

    def _extract_hierarchical_chunks(self, content: str) -> List[Dict[str, str]]:
        """Parse markdown with # chapters (with [!Résumé] and [!concepts]) and ## subsections."""
        lines = [line for line in content.splitlines()]
        chunks = []
        i = 0

        current_chapter = ""
        current_summary = ""
        current_concepts = []
        current_section = "Introduction"
        current_lines = []
        in_block = None  # 'summary' or 'concepts'

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            if stripped.startswith("# "):
                # Save previous section
                if current_lines and current_summary:
                    display_text = "\n".join(current_lines).strip()
                    embed_text = (
                        f"Chapitre : {current_chapter}\n"
                        f"Résumé : {current_summary.strip()}\n"
                        f"Concepts clés : {', '.join(current_concepts)}\n\n"
                        f"Section : {current_section}\n\n"
                        f"{display_text}"
                    )
                    chunks.append({
                        'embed_text': embed_text,
                        'display_text': f"{current_section}\n\n{display_text}",
                        'chapter': current_chapter,
                        'section': current_section
                    })
                    current_lines = []

                current_chapter = stripped[2:].strip()
                current_summary = ""
                current_concepts = []
                current_section = "Introduction"
                in_block = None

            elif stripped.startswith(">[!Résumé]"):
                in_block = "summary"
                current_summary = ""

            elif stripped.startswith(">[!concepts]"):
                in_block = "concepts"
                current_concepts = []

            elif stripped.startswith("## "):
                # Save current section
                if current_lines and current_summary:
                    display_text = "\n".join(current_lines).strip()
                    embed_text = (
                        f"Chapitre : {current_chapter}\n"
                        f"Résumé : {current_summary.strip()}\n"
                        f"Concepts clés : {', '.join(current_concepts)}\n\n"
                        f"Section : {current_section}\n\n"
                        f"{display_text}"
                    )
                    chunks.append({
                        'embed_text': embed_text,
                        'display_text': f"{current_section}\n\n{display_text}",
                        'chapter': current_chapter,
                        'section': current_section
                    })

                current_section = stripped[3:].strip()
                current_lines = []
                in_block = None

            else:
                if in_block == "summary":
                    if line.startswith(">"):
                        current_summary += line.lstrip(">").lstrip(" ").rstrip() + "\n"
                    else:
                        in_block = None

                elif in_block == "concepts":
                    if line.startswith(">"):
                        concepts_line = line.lstrip(">").lstrip(" ").rstrip()
                        current_concepts.extend([c.strip() for c in concepts_line.split(",") if c.strip()])
                    else:
                        in_block = None

                else:
                    if current_chapter:
                        current_lines.append(line)

            i += 1

        # Save last section
        if current_lines and current_summary:
            display_text = "\n".join(current_lines).strip()
            embed_text = (
                f"Chapitre : {current_chapter}\n"
                f"Résumé : {current_summary.strip()}\n"
                f"Concepts clés : {', '.join(current_concepts)}\n\n"
                f"Section : {current_section}\n\n"
                f"{display_text}"
            )
            chunks.append({
                'embed_text': embed_text,
                'display_text': f"{current_section}\n\n{display_text}",
                'chapter': current_chapter,
                'section': current_section
            })

        # Fallback: if no hierarchical structure detected, treat whole document as one chunk
        if not chunks and content.strip():
            chunks.append({
                'embed_text': content,
                'display_text': content,
                'chapter': "Document complet",
                'section': "Contenu principal"
            })

        return chunks

    def index_document(self, user_id: str, filename: str, file_path: str, content: Optional[str] = None) -> bool:
        """Index a document using hierarchical parsing."""
        if self.model is None:
            log("error", "Embedding model not available")
            return False

        try:
            if content is None:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

            chunks_data = self._extract_hierarchical_chunks(content)
            if not chunks_data:
                log("warning", f"No chunks created for document {filename}")
                return False

            embed_texts = [c['embed_text'] for c in chunks_data]
            embeddings = self.model.encode(embed_texts, normalize_embeddings=True)
            embeddings = np.array(embeddings, dtype=np.float32)

            file_size = os.path.getsize(file_path)

            # Create or retrieve index
            if user_id not in self.indices:
                index = faiss.IndexFlatIP(self.dimension)
                self.indices[user_id] = index
                self.metadata[user_id] = []
            else:
                index = self.indices[user_id]

            index.add(embeddings)

            # Append metadata
            for chunk in chunks_data:
                self.metadata[user_id].append({
                    'embed_text': chunk['embed_text'],
                    'content': chunk['display_text'],
                    'filename': filename,
                    'file_size': file_size,
                    'file_path': file_path,
                    'indexed_at': datetime.now().isoformat(),
                    'chapter': chunk['chapter'],
                    'section': chunk['section']
                })

            self._save_user_index(user_id)
            log("info", f"Indexed document {filename} for user {user_id} ({len(chunks_data)} hierarchical chunks) using faiss_hierarchical")
            return True

        except Exception as e:
            log("error", f"Failed to index document {filename}: {str(e)}")
            return False

    def delete_document(self, user_id: str, filename: str) -> bool:
        """Delete all chunks belonging to a document and rebuild the index."""
        if user_id not in self.metadata:
            return False

        try:
            current_meta = self.metadata[user_id]
            kept_meta = [m for m in current_meta if m['filename'] != filename]

            if len(kept_meta) == len(current_meta):
                return False  # Nothing removed

            if kept_meta:
                texts = [m['embed_text'] for m in kept_meta]
                embeddings = self.model.encode(texts, normalize_embeddings=True)
                embeddings = np.array(embeddings, dtype=np.float32)

                new_index = faiss.IndexFlatIP(self.dimension)
                new_index.add(embeddings)

                self.indices[user_id] = new_index
                self.metadata[user_id] = kept_meta
            else:
                self.indices.pop(user_id, None)
                self.metadata.pop(user_id, None)

            self._save_user_index(user_id)
            log("info", f"Deleted document {filename} from hierarchical FAISS index for user {user_id}")
            return True

        except Exception as e:
            log("error", f"Failed to delete document {filename}: {str(e)}")
            return False

    def search(self, user_id: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search using vector similarity."""
        if self.model is None or user_id not in self.indices or self.indices[user_id].ntotal == 0:
            return []

        try:
            query_emb = self.model.encode([query], normalize_embeddings=True)
            query_emb = np.array(query_emb, dtype=np.float32)

            D, I = self.indices[user_id].search(query_emb, limit * 3)

            results = []
            for dist, idx in zip(D[0], I[0]):
                if idx == -1:
                    break
                if dist < self.similarity_threshold:
                    continue

                meta = self.metadata[user_id][idx]
                formatted_content = (
                    f"**{meta['chapter']}**\n"
                    f"**{meta['section']}**\n\n"
                    f"{meta['content']}"
                )

                results.append({
                    'filename': meta['filename'],
                    'score': float(dist),
                    'content': formatted_content
                })
                if len(results) >= limit:
                    break

            return results

        except Exception as e:
            log("error", f"Hierarchical FAISS search failed: {str(e)}")
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
            log("info", f"Cleared hierarchical FAISS index for user {user_id}")
            return True
        except Exception as e:
            log("error", f"Failed to clear hierarchical FAISS index for user {user_id}: {str(e)}")
            return False

    def is_available(self) -> bool:
        """Check if the engine is functional."""
        return self.model is not None and self.dimension is not None

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
