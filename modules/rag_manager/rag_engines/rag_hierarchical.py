"""
Hierarchical FAISS-based RAG Engine Plugin

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


class FaissHierarchicalRAGEngine(RAGEngine):
    """FAISS-based RAG engine with hierarchical chunking for structured markdown."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Args:
            config: The 'engines.faiss_hierarchical' section of the rag_manager config.
                    If None, defaults to an empty engine-specific config dict.
        """
        super().__init__("faiss_hierarchical")
        self.description = "FAISS vector store with hierarchical markdown parsing (chapter résumé + subsections)"

        config = config or {}

        self.index_path = Path(config.get("index_path", "./data/hierarchical_indexes"))
        self.index_path.mkdir(parents=True, exist_ok=True)

        self.similarity_threshold = config.get("similarity_threshold", 0.5)

        log("debug", f"Hierarchical RAG config: index_path={self.index_path}")

        try:
            self.dimension = len(get_embedding(""))
            log("info", f"Initialized embeddings via LLM manager (dim: {self.dimension})")
        except Exception as e:
            log("error", f"Failed to initialize embeddings: {str(e)}")
            self.dimension = None

        self.indices: Dict[str, faiss.IndexFlatIP] = {}
        self.metadata: Dict[str, List[Dict[str, Any]]] = {}

        self._load_indices()

    def _load_indices(self):
        for index_file in self.index_path.glob("*_faiss_hier.index"):
            user_id = index_file.stem.replace("_faiss_hier", "")
            try:
                index = faiss.read_index(str(index_file))
                self.indices[user_id] = index
                meta_file = self.index_path / f"{user_id}_faiss_hier_meta.pkl"
                if meta_file.exists():
                    with open(meta_file, 'rb') as f:
                        self.metadata[user_id] = pickle.load(f)
                log("info", f"Loaded hierarchical FAISS index for user {user_id} ({index.ntotal} vectors)")
            except Exception as e:
                log("error", f"Failed to load hierarchical FAISS index for {user_id}: {str(e)}")

    def _save_user_index(self, user_id: str):
        index_file = self.index_path / f"{user_id}_faiss_hier.index"
        meta_file = self.index_path / f"{user_id}_faiss_hier_meta.pkl"

        if user_id in self.indices and self.indices[user_id].ntotal > 0:
            try:
                faiss.write_index(self.indices[user_id], str(index_file))
                with open(meta_file, 'wb') as f:
                    pickle.dump(self.metadata[user_id], f)
            except Exception as e:
                log("error", f"Failed to save hierarchical FAISS index for {user_id}: {str(e)}")
        else:
            if index_file.exists():
                index_file.unlink()
            if meta_file.exists():
                meta_file.unlink()
            self.indices.pop(user_id, None)
            self.metadata.pop(user_id, None)

    def _extract_hierarchical_chunks(self, content: str) -> List[Dict[str, str]]:
        lines = content.splitlines()
        chunks = []
        i = 0
        current_chapter = ""
        current_summary = ""
        current_concepts: List[str] = []
        current_section = "Introduction"
        current_lines: List[str] = []
        in_block = None

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            if stripped.startswith("# "):
                if current_lines and current_summary:
                    chunks.append(self._make_chunk(current_chapter, current_summary, current_concepts, current_section, current_lines))
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
                if current_lines and current_summary:
                    chunks.append(self._make_chunk(current_chapter, current_summary, current_concepts, current_section, current_lines))
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

        if current_lines and current_summary:
            chunks.append(self._make_chunk(current_chapter, current_summary, current_concepts, current_section, current_lines))

        if not chunks and content.strip():
            chunks.append({
                'embed_text': content,
                'display_text': content,
                'chapter': "Document complet",
                'section': "Contenu principal",
            })

        return chunks

    def _make_chunk(self, chapter, summary, concepts, section, lines) -> Dict[str, str]:
        display_text = "\n".join(lines).strip()
        embed_text = (
            f"Chapitre : {chapter}\n"
            f"Résumé : {summary.strip()}\n"
            f"Concepts clés : {', '.join(concepts)}\n\n"
            f"Section : {section}\n\n"
            f"{display_text}"
        )
        return {
            'embed_text': embed_text,
            'display_text': f"{section}\n\n{display_text}",
            'chapter': chapter,
            'section': section,
        }

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

            chunks_data = self._extract_hierarchical_chunks(content)
            if not chunks_data:
                return False

            embeddings = self._encode_texts([c['embed_text'] for c in chunks_data])
            file_size = os.path.getsize(file_path)

            if user_id not in self.indices:
                self.indices[user_id] = faiss.IndexFlatIP(self.dimension)
                self.metadata[user_id] = []

            self.indices[user_id].add(embeddings)
            for chunk in chunks_data:
                self.metadata[user_id].append({
                    'embed_text': chunk['embed_text'],
                    'content': chunk['display_text'],
                    'filename': filename,
                    'file_size': file_size,
                    'file_path': file_path,
                    'indexed_at': datetime.now().isoformat(),
                    'chapter': chunk['chapter'],
                    'section': chunk['section'],
                })

            self._save_user_index(user_id)
            return True
        except Exception as e:
            log("error", f"Failed to index document {filename}: {str(e)}")
            return False

    def delete_document(self, user_id: str, filename: str) -> bool:
        if user_id not in self.metadata:
            return False
        try:
            kept_meta = [m for m in self.metadata[user_id] if m['filename'] != filename]
            if len(kept_meta) == len(self.metadata[user_id]):
                return False

            if kept_meta:
                embeddings = self._encode_texts([m['embed_text'] for m in kept_meta])
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
            threshold = getattr(self, 'similarity_threshold', 0.5)
            max_score_reached = 0.0  # Track highest score

            for dist, idx in zip(D[0], I[0]):
                if idx == -1:
                    break

                # Track max score regardless of threshold
                if dist > max_score_reached:
                    max_score_reached = dist

                if dist < threshold:
                    continue

                meta = self.metadata[user_id][idx]
                formatted = f"**{meta['chapter']}**\n**{meta['section']}**\n\n{meta['content']}"
                results.append({
                    'filename': meta['filename'],
                    'score': float(dist),
                    'content': formatted,
                    'threshold_used': threshold,
                    'max_score_reached': None  # Will be set after loop
                })
                if len(results) >= limit:
                    break

            # Add max_score_reached to all results
            for result in results:
                result['max_score_reached'] = max_score_reached

            # If no results, still return info about max score
            if not results:
                return [{
                    'filename': None,
                    'score': 0,
                    'content': '',
                    'threshold_used': threshold,
                    'max_score_reached': max_score_reached,
                    'no_results': True
                }]

            return results
        except Exception as e:
            log("error", f"Hierarchical FAISS search failed: {str(e)}")
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
            log("error", f"Failed to clear hierarchical FAISS index for {user_id}: {str(e)}")
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
