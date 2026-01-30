"""
Simple RAG Engine Plugin
"""

import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from ..rag_manager import RAGEngine
from shared.logging import log


class SimpleRAGEngine(RAGEngine):
    """Simple RAG engine using basic text matching."""

    def __init__(self):
        super().__init__("simple")
        self.description = "Simple text-based RAG engine using keyword matching"
        self.indices = {}  # user_id -> {filename: {content, metadata}}

    def index_document(self, user_id: str, filename: str, file_path: str, content: Optional[str] = None) -> bool:
        """Index a document by reading its content."""
        try:
            if content is None:
                # Read file content
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

            if user_id not in self.indices:
                self.indices[user_id] = {}

            self.indices[user_id][filename] = {
                'content': content,
                'metadata': {
                    'indexed_at': datetime.now().isoformat(),
                    'file_path': file_path,
                    'size': os.path.getsize(file_path)
                }
            }

            log("info", f"Indexed document {filename} for user {user_id} using simple engine")
            return True

        except Exception as e:
            log("error", f"Failed to index document {filename}: {str(e)}")
            return False

    def delete_document(self, user_id: str, filename: str) -> bool:
        """Delete a document from the index."""
        try:
            if user_id in self.indices and filename in self.indices[user_id]:
                del self.indices[user_id][filename]
                log("info", f"Deleted document {filename} from index for user {user_id}")
                return True
            return False
        except Exception as e:
            log("error", f"Failed to delete document {filename}: {str(e)}")
            return False

    def search(self, user_id: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Simple keyword search."""
        results = []

        if user_id not in self.indices:
            return results

        query_lower = query.lower()

        for filename, data in self.indices[user_id].items():
            content = data['content'].lower()

            # Simple relevance scoring based on keyword frequency
            score = 0
            for word in query_lower.split():
                score += content.count(word)

            if score > 0:
                # Extract context around first match
                context = self._extract_context(data['content'], query_lower)

                results.append({
                    'filename': filename,
                    'score': score,
                    'content': context,
                    'metadata': data['metadata']
                })

        # Sort by score descending
        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:limit]

    def _extract_context(self, content: str, query: str, context_size: int = 200) -> str:
        """Extract context around the query match."""
        content_lower = content.lower()
        pos = content_lower.find(query)

        if pos == -1:
            # If exact query not found, find any word
            for word in query.split():
                pos = content_lower.find(word)
                if pos != -1:
                    break

        if pos == -1:
            return content[:context_size] + "..." if len(content) > context_size else content

        start = max(0, pos - context_size // 2)
        end = min(len(content), pos + context_size // 2)

        context = content[start:end]
        if start > 0:
            context = "..." + context
        if end < len(content):
            context = context + "..."

        return context

    def get_indexed_documents(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get list of indexed documents."""
        documents = []

        if user_id:
            users_to_check = [user_id]
        else:
            users_to_check = list(self.indices.keys())

        for uid in users_to_check:
            if uid in self.indices:
                for filename, data in self.indices[uid].items():
                    documents.append({
                        'user_id': uid,
                        'filename': filename,
                        'indexed_at': data['metadata']['indexed_at'],
                        'size': data['metadata']['size']
                    })

        return documents

    def clear_user_index(self, user_id: str) -> bool:
        """Clear all indexed documents for a user."""
        try:
            if user_id in self.indices:
                del self.indices[user_id]
                log("info", f"Cleared index for user {user_id}")
                return True
            return True  # Already empty
        except Exception as e:
            log("error", f"Failed to clear index for user {user_id}: {str(e)}")
            return False

    def is_available(self) -> bool:
        """Simple engine is always available."""
        return True

    def get_stats(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Get engine statistics."""
        if user_id:
            count = len(self.indices.get(user_id, {}))
            return {
                'documents_indexed': count,
                'engine_type': self.engine_type
            }
        else:
            total = sum(len(docs) for docs in self.indices.values())
            return {
                'total_documents_indexed': total,
                'users_with_index': len(self.indices),
                'engine_type': self.engine_type
            }
