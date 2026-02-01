"""
RAG Manager Module with Plugin-based Engine System
"""

import os
import json
from abc import ABC, abstractmethod
from pathlib import Path
import shutil
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Any, Callable
import importlib
import pkgutil
import sys

from shared.logging import log
from shared.config import get_config
from shared.users import UserRole, user_manager

from .rag_engine import RAGEngine
from .rag_simple import SimpleRAGEngine
# Import caching module
try:
    from .rag_caching import RAGModelCache
    HAS_CACHING = True
except ImportError:
    HAS_CACHING = False
    RAGModelCache = None


class RAGManager:
    """Manages RAG documents storage and operations with plugin-based engines."""

    def __init__(self):
        self.config = get_config()
        rag_config = self.config.get("rag_manager", {})
        self.data_dir = Path(rag_config.get("data_directory", "./data/rag_documents"))
        self.allowed_extensions = rag_config.get("allowed_extensions", [".txt", ".pdf", ".md"])
        self.max_file_size_mb = rag_config.get("max_file_size_mb", 10)
        self._cache_initialized = False
        self._init_caching()

        # RAG engines
        self.engines = {}
        self.default_engine = rag_config.get("default_engine", "simple")

        # Store config
        self.rag_config = rag_config

        # Initialize
        self._init_data_directory()
        self.metadata_file = self.data_dir / "metadata.json"
        self.documents = self._load_metadata()

        # Discover and register engines
        self.discover_engines()

        # Register callback for user deletion
        user_manager.register_before_delete_callback(self._handle_user_deletion)

    def _init_caching(self):
        """Initialize caching for model weights."""
        if HAS_CACHING:
            try:
                # Test cache availability
                RAGModelCache.get_embedding_model_cached("sentence-transformers/all-MiniLM-L6-v2")
                self._cache_initialized = True
                log("info", "RAG model caching initialized successfully")
            except Exception as e:
                log("warning", f"Failed to initialize caching: {str(e)}")
                self._cache_initialized = False
        else:
            log("warning", "RAG caching module not available")
            self._cache_initialized = False

    def clear_model_cache(self):
        """Clear all cached model weights."""
        if HAS_CACHING and self._cache_initialized:
            try:
                RAGModelCache.clear_embedding_cache()
                log("info", "Cleared RAG model cache")
                return True
            except Exception as e:
                log("error", f"Failed to clear cache: {str(e)}")
                return False
        return False

    def get_cache_info(self) -> Dict[str, Any]:
        """Get information about the cache status."""
        return {
            "caching_available": HAS_CACHING,
            "cache_initialized": self._cache_initialized,
            "cached_models": ["embedding_models"] if self._cache_initialized else []
        }

    def _init_data_directory(self):
        """Initialize the data directory structure."""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            log("info", f"RAG data directory initialized: {self.data_dir}")
        except Exception as e:
            log("error", f"Failed to initialize RAG data directory: {str(e)}")
            raise

    def _load_metadata(self) -> Dict:
        """Load documents metadata from JSON file, converting old format if needed."""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)

                # Convert old format to new format if needed
                updated = False
                for filename, doc_info in metadata.items():
                    if "uploaded_by" not in doc_info:
                        # This is an old format document
                        # Try to extract user_id from filename pattern: userid_timestamp_filename
                        parts = filename.split('_', 2)  # Split on first two underscores
                        if len(parts) >= 3:
                            # Assume the first part is user_id
                            doc_info["uploaded_by"] = parts[0]
                            updated = True
                        else:
                            # Can't determine user, skip or use default
                            log("warning", f"Could not determine user for old document: {filename}")
                            # Skip this document for user-based operations
                            continue

                    # Ensure other required fields exist with defaults
                    if "is_public" not in doc_info:
                        doc_info["is_public"] = False
                    if "visible_to" not in doc_info:
                        doc_info["visible_to"] = []
                    if "indexed_in" not in doc_info:
                        doc_info["indexed_in"] = {}

                if updated:
                    # Save the updated metadata
                    self._save_metadata()
                    log("info", "Converted old metadata format to new format")

                return metadata

            except Exception as e:
                log("error", f"Failed to load metadata: {str(e)}")
                return {}
        return {}

    def _save_metadata(self):
        """Save documents metadata to JSON file."""
        try:
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(self.documents, f, indent=2)
            log("debug", f"Metadata saved: {len(self.documents)} documents")
        except Exception as e:
            log("error", f"Failed to save metadata: {str(e)}")

    def refresh_config(self):
        """Refresh configuration from config file."""
        from shared.config import get_config
        self.config = get_config()
        rag_config = self.config.get("rag_manager", {})
        self.default_engine = rag_config.get("default_engine", "simple")

        # Clear cache if config changed significantly
        old_embedding_model = getattr(self, '_last_embedding_model', None)
        new_embedding_model = rag_config.get("embedding_model")

        if old_embedding_model != new_embedding_model and HAS_CACHING:
            self.clear_model_cache()
            self._last_embedding_model = new_embedding_model

        log("debug", f"RAG manager config refreshed, default engine: {self.default_engine}")


    def discover_engines(self):
        """Discover and register RAG engines."""
        # First register built-in engines
        self.register_engine(SimpleRAGEngine())

        # Look for engine modules
        engines_dir = Path(__file__).parent / "rag_engines"

        if engines_dir.exists():
            log("debug", f"Looking for RAG engines in: {engines_dir}")

            # Ensure the directory is in Python path
            if str(engines_dir.parent) not in sys.path:
                sys.path.insert(0, str(engines_dir.parent))

            # Discover modules
            for _, module_name, is_pkg in pkgutil.iter_modules([str(engines_dir)]):
                if not is_pkg and module_name.startswith('rag_'):
                    try:
                        full_module_name = f"modules.rag_manager.rag_engines.{module_name}"
                        module = importlib.import_module(full_module_name)

                        # Find engine classes
                        for attr_name in dir(module):
                            attr = getattr(module, attr_name)
                            if (isinstance(attr, type) and
                                issubclass(attr, RAGEngine) and
                                attr != RAGEngine):
                                try:
                                    engine = attr()
                                    self.register_engine(engine)
                                    log("info", f"Registered RAG engine: {engine.engine_type}")
                                except Exception as e:
                                    log("error", f"Failed to instantiate engine {attr_name}: {e}")
                    except Exception as e:
                        log("error", f"Failed to load RAG engine module {module_name}: {e}")

        log("info", f"Registered {len(self.engines)} RAG engines: {list(self.engines.keys())}")

    def register_engine(self, engine: RAGEngine):
        """Register a RAG engine."""
        self.engines[engine.engine_type] = engine

    def get_engine(self, engine_type: str) -> Optional[RAGEngine]:
        """Get engine by type."""
        return self.engines.get(engine_type)

    def get_default_engine(self) -> Optional[RAGEngine]:
        """Get the default RAG engine."""
        return self.get_engine(self.default_engine)

    def get_available_engines(self) -> List[Dict[str, Any]]:
        """Get list of available RAG engines."""
        engines_list = []
        for engine_type, engine in self.engines.items():
            engines_list.append({
                'type': engine_type,
                'description': engine.description,
                'available': engine.is_available(),
                'default': (engine_type == self.default_engine)
            })
        return engines_list

    def is_valid_file(self, file_path: str) -> Tuple[bool, str]:
        """Validate if a file can be uploaded."""
        try:
            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)

            if file_size_mb > self.max_file_size_mb:
                return False, f"File too large ({file_size_mb:.2f}MB > {self.max_file_size_mb}MB)"

            file_ext = os.path.splitext(file_path)[1].lower()
            if file_ext not in self.allowed_extensions:
                return False, f"Unsupported file extension: {file_ext}"

            return True, ""
        except Exception as e:
            return False, f"Error validating file: {str(e)}"

    def _check_user_permission(self, user_id: str, owner_id: str) -> bool:
        """Check if user has permission to access document."""
        if user_id == owner_id:
            return True

        user_info = user_manager.get_user(user_id)
        owner_info = user_manager.get_user(owner_id)

        if not user_info or not owner_info:
            return False

        # Admin can access all documents
        if user_info['role'] == UserRole.ADMIN:
            return True

        # Master can access their own and their children's documents
        if user_info['role'] == UserRole.MASTER:
            if owner_id == user_id:
                return True
            # Check if owner is a child of this master
            children = user_manager.get_children(user_id)
            return any(child['id'] == owner_id for child in children)

        # Normal users can only access their own documents
        return False

    def upload_document(self, source_path: str, original_filename: str,
                       user_id: str, is_public: bool = False) -> Optional[str]:
        """Upload a document to the RAG storage."""
        try:
            # Validate file
            is_valid, error_msg = self.is_valid_file(source_path)
            if not is_valid:
                log("warning", f"File validation failed: {error_msg}")
                return None

            # Check user permissions
            user_info = user_manager.get_user(user_id)
            if not user_info:
                log("error", f"User {user_id} not found")
                return None

            # Normal users cannot upload public documents
            if is_public and user_info['role'] == UserRole.NORMAL:
                log("warning", f"Normal user {user_id} cannot upload public documents")
                return None

            # Generate unique filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_ext = os.path.splitext(original_filename)[1]
            unique_filename = f"{user_id}_{timestamp}_{original_filename}"
            dest_path = self.data_dir / unique_filename

            # Copy file
            shutil.copy2(source_path, dest_path)

            # Determine visibility
            if is_public:
                visible_to = ["admin", "master", "normal"]  # All users
            else:
                visible_to = [user_info['role']]
                if user_info['role'] == UserRole.MASTER:
                    visible_to.append("normal")  # Master's docs visible to their normal users

            # Add to metadata - ensure ALL required fields are present
            file_size = os.path.getsize(dest_path)
            file_size_mb = file_size / (1024 * 1024)

            self.documents[unique_filename] = {
                "original_filename": original_filename,
                "uploaded_by": user_id,  # This is the critical field
                "uploaded_at": datetime.now().isoformat(),
                "file_size": file_size,
                "file_size_mb": round(file_size_mb, 2),
                "file_extension": file_ext,
                "file_path": str(dest_path),
                "is_public": is_public,
                "visible_to": visible_to,
                "indexed_in": {}  # engine_type -> indexed_at
            }

            # Save metadata
            self._save_metadata()

            log("info", f"Document uploaded: {original_filename} -> {unique_filename} by user {user_id}")
            return unique_filename

        except Exception as e:
            log("error", f"Failed to upload document {original_filename}: {str(e)}", exc_info=True)
            return None

    def index_document(self, filename: str, engine_type: str, user_id: str) -> bool:
        """Index a document with a specific engine."""
        try:
            if filename not in self.documents:
                log("error", f"Document {filename} not found")
                return False

            doc_info = self.documents[filename]

            # Check permissions
            if not self._check_user_permission(user_id, doc_info['uploaded_by']):
                log("warning", f"User {user_id} cannot index document {filename}")
                return False

            # Get engine
            engine = self.get_engine(engine_type)
            if not engine:
                log("error", f"Engine {engine_type} not found")
                return False

            # Index document
            success = engine.index_document(
                doc_info['uploaded_by'],  # Index under document owner
                filename,
                doc_info['file_path']
            )

            if success:
                # Update metadata
                if 'indexed_in' not in doc_info:
                    doc_info['indexed_in'] = {}

                doc_info['indexed_in'][engine_type] = datetime.now().isoformat()
                self._save_metadata()

                log("info", f"Document {filename} indexed with engine {engine_type}")
                return True

            return False

        except Exception as e:
            log("error", f"Failed to index document {filename}: {str(e)}", exc_info=True)
            return False

    def delete_document(self, filename: str, user_id: str) -> bool:
        """Delete a document from RAG storage."""
        try:
            if filename not in self.documents:
                log("warning", f"Document not found in metadata: {filename}")
                return False

            doc_info = self.documents[filename]

            # Check permissions
            if not self._check_user_permission(user_id, doc_info['uploaded_by']):
                log("warning", f"User {user_id} cannot delete document {filename}")
                return False

            # Delete from all engines
            for engine_type in self.engines:
                engine = self.get_engine(engine_type)
                if engine:
                    engine.delete_document(doc_info['uploaded_by'], filename)

            # Delete file
            file_path = Path(doc_info["file_path"])
            if file_path.exists():
                file_path.unlink()
                log("debug", f"File deleted: {file_path}")

            # Remove from metadata
            del self.documents[filename]
            self._save_metadata()

            log("info", f"Document deleted: {filename}")
            return True

        except Exception as e:
            log("error", f"Failed to delete document {filename}: {str(e)}", exc_info=True)
            return False

    def get_user_documents(self, user_id: str) -> List[Dict]:
        """Get documents accessible by a user."""
        result = []

        for filename, metadata in self.documents.items():
            # Handle backward compatibility: documents uploaded before user system
            uploaded_by = metadata.get("uploaded_by")
            if uploaded_by is None:
                # Old format document - skip or handle differently
                # For now, skip documents without uploaded_by field
                continue

            if self._check_user_permission(user_id, uploaded_by):
                result.append({
                    "filename": filename,
                    "original_filename": metadata["original_filename"],
                    "uploaded_by": uploaded_by,
                    "uploaded_at": metadata["uploaded_at"],
                    "file_size_mb": metadata["file_size_mb"],
                    "file_extension": metadata["file_extension"],
                    "is_public": metadata.get("is_public", False),
                    "indexed_in": list(metadata.get("indexed_in", {}).keys())
                })

        # Sort by upload date (newest first)
        result.sort(key=lambda x: x["uploaded_at"], reverse=True)
        return result

    def search(self, user_id: str, query: str, engine_type: Optional[str] = None,
               limit: int = 5) -> Dict[str, Any]:
        """Search across RAG engines."""
        results = {}

        # If no engine specified, use current default
        if not engine_type:
            engine_type = self.default_engine

        accessible_docs = self.get_user_documents(user_id)
        if not accessible_docs:
            return results

        allowed_filenames = {doc['filename'] for doc in accessible_docs}

        # Group by unique owner to avoid duplicate searches
        owners = {}
        for doc in accessible_docs:
            owner = doc['uploaded_by']
            owners.setdefault(owner, [])

        if engine_type:
            engine = self.get_engine(engine_type)
            if not engine:
                return results

            engine_results = []
            for owner in owners:
                owner_results = engine.search(owner, query, limit * 5)  # Get more candidates per owner
                for result in owner_results:
                    if result['filename'] in allowed_filenames:
                        engine_results.append(result)

            # Optional: sort globally and take top limit (better relevance across owners)
            engine_results.sort(key=lambda x: x['score'], reverse=True)
            if engine_type not in results:
                results[engine_type] = []
            results[engine_type].extend(engine_results[:limit])

        else:
            # All engines branch - same fix
            for eng_type, engine in self.engines.items():
                engine_results = []
                for owner in owners:
                    owner_results = engine.search(owner, query, limit * 5)
                    for result in owner_results:
                        if result['filename'] in allowed_filenames:
                            engine_results.append(result)

                if engine_results:
                    engine_results.sort(key=lambda x: x['score'], reverse=True)
                    results[eng_type] = engine_results[:limit]

        return results

    def get_rag_context(self, user_id: str, query: str,
                       engine_type: Optional[str] = None) -> str:
        """Get RAG context for a query."""
        if not engine_type:
            engine_type = self.default_engine

        search_results = self.search(user_id, query, engine_type, limit=3)

        if not search_results or engine_type not in search_results:
            return ""

        # Format context from search results
        context_parts = []
        for result in search_results[engine_type]:
            context_parts.append(
                f"From document '{result['filename']}':\n"
                f"{result['content']}\n"
            )

        context = "\n".join(context_parts)
        return f"Relevant context from documents:\n{context}"

    def get_document_count(self, user_id: Optional[str] = None) -> int:
        """Get total number of documents."""
        if user_id:
            return len(self.get_user_documents(user_id))
        return len(self.documents)

    def get_total_size_mb(self, user_id: Optional[str] = None) -> float:
        """Get total size of documents in MB."""
        total = 0
        for filename, metadata in self.documents.items():
            if not user_id or self._check_user_permission(user_id, metadata['uploaded_by']):
                total += metadata['file_size_mb']
        return round(total, 2)

    def clear_all_documents(self, user_id: str) -> bool:
        """Clear all documents (admin/master function)."""
        try:
            # Check if user has permission (admin or master)
            user_info = user_manager.get_user(user_id)
            if not user_info:
                return False

            if user_info['role'] not in [UserRole.ADMIN, UserRole.MASTER]:
                log("warning", f"User {user_id} cannot clear all documents")
                return False

            # Delete all files accessible by user
            docs_to_delete = []
            for filename, metadata in self.documents.items():
                # Skip documents without uploaded_by field (old format)
                if 'uploaded_by' not in metadata:
                    continue

                if self._check_user_permission(user_id, metadata['uploaded_by']):
                    docs_to_delete.append(filename)

            for filename in docs_to_delete:
                self.delete_document(filename, user_id)

            log("info", f"Cleared {len(docs_to_delete)} documents by user {user_id}")
            return True

        except Exception as e:
            log("error", f"Failed to clear all documents: {str(e)}", exc_info=True)
            return False

    def _handle_user_deletion(self, user_id: str) -> bool:
        """Handle user deletion by removing their documents."""
        try:
            # Find and delete all documents uploaded by this user
            docs_to_delete = []
            for filename, metadata in self.documents.items():
                if metadata['uploaded_by'] == user_id:
                    docs_to_delete.append(filename)

            for filename in docs_to_delete:
                # Delete from storage
                doc_info = self.documents[filename]
                file_path = Path(doc_info["file_path"])
                if file_path.exists():
                    file_path.unlink()

                # Delete from all engines
                for engine_type, engine in self.engines.items():
                    engine.delete_document(user_id, filename)

                # Remove from metadata
                del self.documents[filename]

            if docs_to_delete:
                self._save_metadata()
                log("info", f"Deleted {len(docs_to_delete)} documents for deleted user {user_id}")

            return True
        except Exception as e:
            log("error", f"Failed to handle user deletion for {user_id}: {str(e)}")
            return False

    def get_engine_stats(self, engine_type: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Get statistics for a specific engine."""
        engine = self.get_engine(engine_type)
        if not engine:
            return {}

        stats = engine.get_stats(user_id)
        stats['engine_type'] = engine_type
        return stats


# Create a singleton instance
rag_manager = RAGManager()
