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

from shared.common import init_user_manager
from st_shared.cached import get_config
from shared.common import UserRole
from st_shared.cached import get_user_manager

from modules.rag_manager.rag_engine import RAGEngine
from modules.rag_manager.rag_simple import SimpleRAGEngine

from core.logging import log, set_log_module_level
from core.database import init_database
from st_shared.cached import _
user_manager = get_user_manager()

class RAGManager:
    """Manages RAG documents storage and operations with plugin-based engines."""

    def __init__(self):
        self.config = get_config()

        # NOW get the rag config
        rag_config = self.config.get("modules.rag_manager", {})

        # Set defaults with proper fallback chain
        self.data_dir = Path(rag_config.get("data_directory", "data/rag_documents"))
        log("info", f"Initializing RAG Manager in {self.data_dir}")
        self.allowed_extensions = rag_config.get("allowed_extensions", [".txt", ".pdf", ".md"])
        self.max_file_size_mb = rag_config.get("max_file_size_mb", 10)

        # CRITICAL FIX: Get default_engine from nested structure
        default_engine = rag_config.get("default_engine", "simple")

        # Check if it's in the engines config
        engines_config = rag_config.get("engines", {})
        if default_engine not in engines_config:
            # Fallback: check if "faiss_hierarchical" exists
            if "faiss_hierarchical" in engines_config:
                default_engine = "faiss_hierarchical"
            elif "faiss" in engines_config:
                default_engine = "faiss"
            else:
                default_engine = "simple"

        self.default_engine = default_engine

        # RAG engines
        self.engines = {}

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

        if not self.has_any_documents():
            log("info", "No existing documents found, running auto-import")
            self.run_auto_import()
        else:
            log("info", f"Existing documents found ({len(self.documents)}), skipping auto-import")

        log("info", f"RAG Manager initialized with default engine: {self.default_engine}")

    def _init_caching(self):
        """Backward-compatible no-op: embeddings are now managed by LLM manager."""
        return None

    def clear_model_cache(self):
        """Backward-compatible no-op: embedding cache is handled by LLM manager."""
        return False

    def get_cache_info(self) -> Dict[str, Any]:
        """Backward-compatible cache info for admin UI."""
        return {
            "caching_available": False,
            "cache_initialized": False,
            "cached_models": []
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
        from st_shared.cached import get_config
        self.config = get_config()
        rag_config = self.config.get("modules.rag_manager", {})
        self.rag_config = rag_config
        self.default_engine = rag_config.get("default_engine", "simple")

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
                                    log("debug", f"Registered RAG engine: {engine.engine_type}")
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

    def is_rag_enabled(self) -> bool:
        """Return whether RAG context injection is globally enabled in config."""
        rag_config = self.config.get("modules.rag_manager", {})
        return bool(rag_config.get("enabled", True))

    def is_engine_enabled(self, engine_type: str) -> bool:
        """Return whether a given engine is enabled in config."""
        rag_config = self.config.get("modules.rag_manager", {})
        engines_config = rag_config.get("engines", {})
        engine_cfg = engines_config.get(engine_type)
        if isinstance(engine_cfg, dict):
            return bool(engine_cfg.get("enabled", True))
        return True

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
        if user_info['role'] == UserRole.ADMIN.value:
            return True

        # Master can access their own and their children's documents
        if user_info['role'] == UserRole.MASTER.value:
            if owner_id == user_id:
                return True
            # Check if owner is a child of this master
            children = user_manager.get_children(user_id)
            return any(child['id'] == owner_id for child in children)

        # Normal users can access their master's documents
        if user_info['role'] == UserRole.NORMAL.value:
            parent_id = user_info.get('parent_id')
            if parent_id and owner_id == parent_id:
                return True

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
            if is_public and user_info['role'] == UserRole.NORMAL.value:
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
                if user_info['role'] == UserRole.MASTER.value:
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

            log("debug", f"Document uploaded: {original_filename} -> {unique_filename} by user {user_id}")
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

            log(
                "debug",
                f"Index request: engine={engine_type}, filename={filename}, requested_by={user_id}, indexed_owner={doc_info['uploaded_by']}"
            )

            if success:
                # Update metadata
                if 'indexed_in' not in doc_info:
                    doc_info['indexed_in'] = {}

                doc_info['indexed_in'][engine_type] = datetime.now().isoformat()
                self._save_metadata()

                log("debug", f"Document {filename} indexed with engine {engine_type}")
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

            log("debug", f"Document deleted: {filename}")
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

    def set_similarity_thresholds(self, thresholds: Dict[str, float]) -> Dict[str, Optional[float]]:
        """Set per-engine similarity thresholds and return previous values."""
        previous_values: Dict[str, Optional[float]] = {}

        for engine_type, threshold in thresholds.items():
            engine = self.get_engine(engine_type)
            if not engine or not hasattr(engine, 'similarity_threshold'):
                continue

            previous_values[engine_type] = getattr(engine, 'similarity_threshold', None)
            engine.similarity_threshold = threshold

        return previous_values

    def restore_similarity_thresholds(self, previous_values: Dict[str, Optional[float]]):
        """Restore per-engine similarity thresholds from a previous snapshot."""
        for engine_type, previous in previous_values.items():
            engine = self.get_engine(engine_type)
            if engine and hasattr(engine, 'similarity_threshold'):
                engine.similarity_threshold = previous

    def search(self, user_id: str, query: str, engine_type: Optional[str] = None,
               limit: int = 5, search_all: bool = False) -> Dict[str, Any]:
        """Search across RAG engines."""
        results = {}

        if not self.is_rag_enabled():
            log("debug", "RAG search skipped: modules.rag_manager.enabled is false")
            return results

        target_engine = engine_type
        if not target_engine and not search_all:
            target_engine = self.default_engine

        accessible_docs = self.get_user_documents(user_id)
        if not accessible_docs:
            log("warning", f"Search aborted: no accessible docs for user={user_id}, query={query!r}, engine={target_engine or 'ALL'}")
            return results

        allowed_filenames = {doc['filename'] for doc in accessible_docs}

        # Group by unique owner to avoid duplicate searches
        owners = {}
        for doc in accessible_docs:
            owner = doc['uploaded_by']
            owners.setdefault(owner, [])

        log(
            "debug",
            f"Search owner scope: requester={user_id}, engine={target_engine or 'ALL'}, query={query!r}, owners={list(owners.keys())}, accessible_docs={len(accessible_docs)}"
        )

        engine_types = [target_engine] if target_engine else list(self.engines.keys())
        engine_types = [eng for eng in engine_types if self.is_engine_enabled(eng)]

        if not engine_types:
            log("debug", "RAG search skipped: no enabled engines")
            return results

        for eng_type in engine_types:
            engine = self.get_engine(eng_type)
            if not engine:
                continue

            engine_results = []
            for owner in owners:
                log("debug", f"Search dispatch: engine={eng_type}, owner={owner}, query={query!r}")
                owner_results = engine.search(owner, query, limit * 5)
                for result in owner_results:
                    if result['filename'] in allowed_filenames:
                        engine_results.append(result)

            engine_results.sort(key=lambda x: x['score'], reverse=True)
            results[eng_type] = engine_results[:limit]

        return results

    def get_rag_context(self, user_id: str, query: str,
                       engine_type: Optional[str] = None) -> str:
        """Get RAG context for a query."""
        if not self.is_rag_enabled():
            return ""

        if not engine_type:
            engine_type = self.default_engine

        if not self.is_engine_enabled(engine_type):
            log("debug", f"RAG context skipped: engine {engine_type} disabled in config")
            return ""

        search_results = self.search(user_id, query, engine_type, limit=3)

        engine_results = search_results.get(engine_type, []) if search_results else []
        if not engine_results:
            log("warning", f"No RAG results found for query: {query!r}")
            return f"No result found for : '{query}'"

        # Format context from search results
        context_parts = []
        for result in engine_results:
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

            if user_info['role'] not in [UserRole.ADMIN.value, UserRole.MASTER.value]:
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

            log("debug", f"Cleared {len(docs_to_delete)} documents by user {user_id}")
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
                log("debug", f"Deleted {len(docs_to_delete)} documents for deleted user {user_id}")

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

    def run_auto_import(self):
        """
        Run auto-import for documents defined in config.
        This should be called once at application startup.
        """
        try:
            rag_config = self.config.get("modules.rag_manager", {})
            auto_import_configs = rag_config.get("auto_import", [])

            if not auto_import_configs:
                log("debug", "No auto-import configurations found")
                return

            if not user_manager.db.is_initialized():
                log("debug", "Database not initialized before RAG auto-import, initializing now")
                init_database()

            if user_manager.db.is_initialized():
                init_user_manager(create_default_users=True)
            else:
                log("warning", "Database still not initialized after init attempt, skipping RAG auto-import")
                return

            log("info", f"Running auto-import for {len(auto_import_configs)} user configurations")

            for user_config in auto_import_configs:
                user_id = user_config.get("user_id")
                files = user_config.get("files", [])

                if not user_id or not files:
                    log("warning", f"Invalid auto-import config: missing user_id or files: {user_config}")
                    continue

                # Check if user exists
                user_info = user_manager.get_user(user_id)
                if not user_info:
                    log("warning", f"User {user_id} not found for auto-import, skipping")
                    continue

                self._auto_import_for_user(user_id, files)

            log("info", "Auto-import completed")

        except Exception as e:
            log("error", f"Failed to run auto-import: {str(e)}", exc_info=True)

    def _auto_import_for_user(self, user_id: str, files: List[Dict]):
        """
        Auto-import files for a specific user.

        Two-pass process:
        1. Import documents that don't exist yet
        2. Index documents on specified engines if not already indexed
        """
        try:
            # Get existing documents for this user
            existing_docs = self.get_user_documents(user_id)
            existing_filenames = {doc['original_filename'] for doc in existing_docs}

            # First pass: Import new documents
            imported_files = []
            for file_config in files:
                source_path = file_config.get("source_path")
                original_filename = file_config.get("original_filename")
                is_public = file_config.get("is_public", False)

                if not source_path or not original_filename:
                    log("warning", f"Invalid file config missing source_path or original_filename: {file_config}")
                    continue

                # Check if document already exists
                if original_filename in existing_filenames:
                    log("debug", f"Document {original_filename} already exists for user {user_id}")
                    # Still track it for indexing pass
                    imported_files.append(file_config)
                    continue

                # Check if source file exists
                if not os.path.exists(source_path):
                    log("warning", f"Source file not found: {source_path}")
                    continue

                # Upload the document
                unique_filename = self.upload_document(
                    source_path=source_path,
                    original_filename=original_filename,
                    user_id=user_id,
                    is_public=is_public
                )

                if unique_filename:
                    log("info", f"Auto-imported document {original_filename} for user {user_id}")
                    imported_files.append(file_config)
                else:
                    log("error", f"Failed to auto-import document {original_filename} for user {user_id}")

            # Second pass: Index documents on specified engines
            for file_config in imported_files:
                original_filename = file_config.get("original_filename")
                engines_to_index = file_config.get("engines", [])

                # Find the actual stored filename
                stored_filename = None
                for filename, metadata in self.documents.items():
                    if (metadata.get('original_filename') == original_filename and
                        metadata.get('uploaded_by') == user_id):
                        stored_filename = filename
                        break

                if not stored_filename:
                    log("warning", f"Could not find stored filename for {original_filename} (user {user_id})")
                    continue

                doc_info = self.documents.get(stored_filename, {})
                existing_indexes = doc_info.get('indexed_in', {})

                for engine_type in engines_to_index:
                    # Check if already indexed with this engine
                    if engine_type in existing_indexes:
                        log("debug", f"Document {original_filename} already indexed with engine {engine_type}")
                        continue

                    # Check if engine exists and is enabled
                    engine_config = self.config.get("modules.rag_manager.engines", {}).get(engine_type, {})
                    if not engine_config.get("enabled", False):
                        log("warning", f"Engine {engine_type} is not enabled, skipping index for {original_filename}")
                        continue

                    # Index the document
                    success = self.index_document(stored_filename, engine_type, user_id)
                    if success:
                        log("info", f"Auto-indexed {original_filename} with engine {engine_type} for user {user_id}")
                    else:
                        log("error", f"Failed to auto-index {original_filename} with engine {engine_type} for user {user_id}")

        except Exception as e:
            log("error", f"Auto-import failed for user {user_id}: {str(e)}", exc_info=True)

    def has_any_documents(self, user_id: Optional[str] = None) -> bool:
        """
        Check if there are any documents in the system.
        If user_id is provided, check for that user only.
        """
        if user_id:
            return len(self.get_user_documents(user_id)) > 0
        return len(self.documents) > 0


# Create a singleton instance
rag_manager = RAGManager()
