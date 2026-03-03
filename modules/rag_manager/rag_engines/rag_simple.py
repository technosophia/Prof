"""
Simple RAG Engine Plugin

No Streamlit dependency. Config is injected at construction time.
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

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Args:
            config: The 'engines.simple' section of the rag_manager config dict.
                    If None, defaults to an empty engine-specific config dict.
        """
        super().__init__("simple")
        self.description = "Simple text-based RAG engine using keyword matching"

        config = config or {}

        self.index_path = Path(config.get("index_path", "data/simple_indexes"))
        self.indices: Dict[str, Dict] = {}
        self.index_path.mkdir(parents=True, exist_ok=True)
        self._load_indices()

    def _load_indices(self):
        for pkl_file in self.index_path.glob("*_simple.pkl"):
            user_id = pkl_file.stem.replace("_simple", "")
            try:
                with open(pkl_file, 'rb') as f:
                    self.indices[user_id] = pickle.load(f)
                log("info", f"Loaded simple index for user {user_id} with {len(self.indices[user_id])} documents")
            except Exception as e:
                log("error", f"Failed to load simple index for user {user_id}: {str(e)}")

    def _save_user_index(self, user_id: str):
        user_data = self.indices.get(user_id)
        file_path = self.index_path / f"{user_id}_simple.pkl"
        if user_data:
            try:
                with open(file_path, 'wb') as f:
                    pickle.dump(user_data, f)
            except Exception as e:
                log("error", f"Failed to save simple index for user {user_id}: {str(e)}")
        else:
            if file_path.exists():
                try:
                    file_path.unlink()
                except Exception as e:
                    log("error", f"Failed to delete empty simple index file for {user_id}: {str(e)}")

    def index_document(self, user_id: str, filename: str, file_path: str, content: Optional[str] = None) -> bool:
        try:
            if content is None:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

            if user_id not in self.indices:
                self.indices[user_id] = {}

            self.indices[user_id][filename] = {
                'content': content,
                'metadata': {
                    'indexed_at': datetime.now().isoformat(),
                    'file_path': file_path,
                    'size': os.path.getsize(file_path),
                },
            }
            self._save_user_index(user_id)
            return True
        except Exception as e:
            log("error", f"Failed to index document {filename}: {str(e)}")
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
            log("error", f"Failed to delete document {filename}: {str(e)}")
            return False

    def search(self, user_id: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        results = []
        if user_id not in self.indices:
            return results

        query_lower = query.lower()
        max_score_reached = 0.0
        threshold = getattr(self, 'similarity_threshold', 0)  # Simple engine doesn't use threshold

        for filename, data in self.indices[user_id].items():
            content = data['content'].lower()
            score = sum(content.count(word) for word in query_lower.split())

            # Track max score
            if score > max_score_reached:
                max_score_reached = score

            if score > 0:
                context = self._extract_context(data['content'], query_lower)
                results.append({
                    'filename': filename,
                    'score': score,
                    'content': context,
                    'metadata': data['metadata'],
                    'threshold_used': None,
                    'max_score_reached': None  # Will be set after loop
                })

        results.sort(key=lambda x: x['score'], reverse=True)

        # Add max_score_reached to results
        for result in results[:limit]:
            result['max_score_reached'] = max_score_reached

        # If no results, return max score info
        if not results:
            return [{
                'filename': None,
                'score': 0,
                'content': '',
                'threshold_used': None,
                'max_score_reached': 0,
                'no_results': True
            }]

        return results[:limit]

    def _extract_context(self, content: str, query: str, context_size: int = 200) -> str:
        content_lower = content.lower()
        pos = content_lower.find(query)

        if pos == -1:
            stop_words = {
                "the", "and", "for", "with", "that", "this", "from", "have", "what", "when",
                "where", "who", "also", "just", "about", "into", "your", "you", "are", "how",
                "is", "it", "to", "of", "in", "on", "a", "an", "i", "im", "i'm",
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
            return (content[:context_size] + "...") if len(content) > context_size else content

        start = max(0, pos - context_size // 2)
        end = min(len(content), pos + context_size // 2)
        context = content[start:end]
        if start > 0:
            context = "..." + context
        if end < len(content):
            context = context + "..."
        return context

    def get_indexed_documents(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        documents = []
        for uid in ([user_id] if user_id else self.indices.keys()):
            if uid in self.indices:
                for filename, data in self.indices[uid].items():
                    documents.append({
                        'user_id': uid,
                        'filename': filename,
                        'indexed_at': data['metadata']['indexed_at'],
                        'size': data['metadata']['size'],
                    })
        return documents

    def clear_user_index(self, user_id: str) -> bool:
        try:
            if user_id in self.indices:
                del self.indices[user_id]
            self._save_user_index(user_id)
            return True
        except Exception as e:
            log("error", f"Failed to clear index for user {user_id}: {str(e)}")
            return False

    def is_available(self) -> bool:
        return True

    def get_stats(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        if user_id:
            return {
                'documents_indexed': len(self.indices.get(user_id, {})),
                'engine_type': self.engine_type,
            }
        return {
            'total_documents_indexed': sum(len(docs) for docs in self.indices.values()),
            'users_with_index': len(self.indices),
            'engine_type': self.engine_type,
        }
