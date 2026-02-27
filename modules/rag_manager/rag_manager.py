"""
RAG Manager Module — Functional Core

NO STREAMLIT DEPENDENCY. This module must remain importable without Streamlit.

Dependencies are injected at construction time:
    RAGManager(config, user_manager)

where:
    config      — plain dict or dict-like object (NOT st_shared.cached)
    user_manager — plain user manager instance

The module-level singleton `rag_manager` is built by rag_factory.py which
bridges the Streamlit-cached world to this pure layer.
"""

import os
import json
from pathlib import Path
import shutil
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Any
import importlib
import pkgutil
import sys

from modules.rag_manager.rag_engine import RAGEngine
from modules.rag_manager.rag_simple import SimpleRAGEngine
from core.logging import log


class RAGManager:
    """Manages RAG documents storage and operations with plugin-based engines.

    All dependencies are injected. No calls to st_shared.cached here.
    """

    def __init__(self, config: Any, user_manager: Any):
        """
        Args:
            config:       A dict-like config object. Must support
                          config.get("modules.rag_manager", {}).
            user_manager: User manager instance with get_user(), get_children(),
                          and register_before_delete_callback() methods.
        """
        self._config = config
        self._user_manager = user_manager

        rag_config = self._get_rag_config()

        self.data_dir = Path(rag_config.get("data_directory", "data/rag_documents"))
        log("info", f"Initializing RAG Manager in {self.data_dir}")
        self.allowed_extensions = rag_config.get("allowed_extensions", [".txt", ".pdf", ".md"])
        self.max_file_size_mb = rag_config.get("max_file_size_mb", 10)

        default_engine = rag_config.get("default_engine", "simple")
        engines_config = rag_config.get("engines", {})
        if default_engine not in engines_config:
            if "faiss_hierarchical" in engines_config:
                default_engine = "faiss_hierarchical"
            elif "faiss" in engines_config:
                default_engine = "faiss"
            else:
                default_engine = "simple"

        self.default_engine = default_engine
        self.engines: Dict[str, RAGEngine] = {}
        self.rag_config = rag_config

        self._init_data_directory()
        self.metadata_file = self.data_dir / "metadata.json"
        self.documents = self._load_metadata()

        self.discover_engines()

        self._user_manager.register_before_delete_callback(self._handle_user_deletion)

        if not self.has_any_documents():
            log("info", "No existing documents found, running auto-import")
            self.run_auto_import()
        else:
            log("info", f"Existing documents found ({len(self.documents)}), skipping auto-import")

        log("info", f"RAG Manager initialized with default engine: {self.default_engine}")

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def _get_rag_config(self) -> Dict:
        """Extract the rag_manager section from config."""
        return self._config.get("modules.rag_manager", {})

    def refresh_config(self) -> None:
        """Re-read config from the injected config object."""
        self.rag_config = self._get_rag_config()
        self.default_engine = self.rag_config.get("default_engine", self.default_engine)
        log("debug", f"RAG manager config refreshed, default engine: {self.default_engine}")

    # ------------------------------------------------------------------
    # Backward-compat cache stubs (embedding cache moved to llm_manager)
    # ------------------------------------------------------------------

    def _init_caching(self):
        return None

    def clear_model_cache(self):
        return False

    def get_cache_info(self) -> Dict[str, Any]:
        return {"caching_available": False, "cache_initialized": False, "cached_models": []}

    # ------------------------------------------------------------------
    # Data directory
    # ------------------------------------------------------------------

    def _init_data_directory(self):
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            log("info", f"RAG data directory initialized: {self.data_dir}")
        except Exception as e:
            log("error", f"Failed to initialize RAG data directory: {str(e)}")
            raise

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def _load_metadata(self) -> Dict:
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)

                updated = False
                for filename, doc_info in metadata.items():
                    if "uploaded_by" not in doc_info:
                        parts = filename.split('_', 2)
                        if len(parts) >= 3:
                            doc_info["uploaded_by"] = parts[0]
                            updated = True
                        else:
                            log("warning", f"Could not determine user for old document: {filename}")
                            continue

                    if "is_public" not in doc_info:
                        doc_info["is_public"] = False
                    if "visible_to" not in doc_info:
                        doc_info["visible_to"] = []
                    if "indexed_in" not in doc_info:
                        doc_info["indexed_in"] = {}

                if updated:
                    self._save_metadata()
                    log("info", "Converted old metadata format to new format")

                return metadata
            except Exception as e:
                log("error", f"Failed to load metadata: {str(e)}")
                return {}
        return {}

    def _save_metadata(self):
        try:
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(self.documents, f, indent=2)
            log("debug", f"Metadata saved: {len(self.documents)} documents")
        except Exception as e:
            log("error", f"Failed to save metadata: {str(e)}")

    # ------------------------------------------------------------------
    # Engine discovery
    # ------------------------------------------------------------------

    def discover_engines(self):
        self.register_engine(SimpleRAGEngine())

        engines_dir = Path(__file__).parent / "rag_engines"
        if engines_dir.exists():
            if str(engines_dir.parent) not in sys.path:
                sys.path.insert(0, str(engines_dir.parent))

            for _, module_name, is_pkg in pkgutil.iter_modules([str(engines_dir)]):
                if not is_pkg and module_name.startswith('rag_'):
                    try:
                        full_module_name = f"modules.rag_manager.rag_engines.{module_name}"
                        module = importlib.import_module(full_module_name)

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
        self.engines[engine.engine_type] = engine

    def get_engine(self, engine_type: str) -> Optional[RAGEngine]:
        return self.engines.get(engine_type)

    def get_default_engine(self) -> Optional[RAGEngine]:
        return self.get_engine(self.default_engine)

    # ------------------------------------------------------------------
    # Enable/disable checks
    # ------------------------------------------------------------------

    def is_rag_enabled(self) -> bool:
        return bool(self._get_rag_config().get("enabled", True))

    def is_engine_enabled(self, engine_type: str) -> bool:
        engines_config = self._get_rag_config().get("engines", {})
        engine_cfg = engines_config.get(engine_type)
        if isinstance(engine_cfg, dict):
            return bool(engine_cfg.get("enabled", True))
        return True

    # ------------------------------------------------------------------
    # Engine listing
    # ------------------------------------------------------------------

    def get_available_engines(self) -> List[Dict[str, Any]]:
        return [
            {
                'type': engine_type,
                'description': engine.description,
                'available': engine.is_available(),
                'default': (engine_type == self.default_engine),
            }
            for engine_type, engine in self.engines.items()
        ]

    # ------------------------------------------------------------------
    # File validation
    # ------------------------------------------------------------------

    def is_valid_file(self, file_path: str) -> Tuple[bool, str]:
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

    # ------------------------------------------------------------------
    # Permissions
    # ------------------------------------------------------------------

    def _check_user_permission(self, user_id: str, owner_id: str) -> bool:
        if user_id == owner_id:
            return True

        # Import UserRole lazily to avoid hard dependency on specific enum location
        try:
            from shared.common import UserRole
        except ImportError:
            UserRole = None

        user_info = self._user_manager.get_user(user_id)
        owner_info = self._user_manager.get_user(owner_id)

        if not user_info or not owner_info:
            return False

        admin_val = UserRole.ADMIN.value if UserRole else "admin"
        master_val = UserRole.MASTER.value if UserRole else "master"
        normal_val = UserRole.NORMAL.value if UserRole else "normal"

        if user_info['role'] == admin_val:
            return True

        if user_info['role'] == master_val:
            if owner_id == user_id:
                return True
            children = self._user_manager.get_children(user_id)
            return any(child['id'] == owner_id for child in children)

        if user_info['role'] == normal_val:
            parent_id = user_info.get('parent_id')
            if parent_id and owner_id == parent_id:
                return True

        return False

    # ------------------------------------------------------------------
    # Upload / delete
    # ------------------------------------------------------------------

    def upload_document(
        self,
        source_path: str,
        original_filename: str,
        user_id: str,
        is_public: bool = False,
    ) -> Optional[str]:
        try:
            is_valid, error_msg = self.is_valid_file(source_path)
            if not is_valid:
                log("warning", f"File validation failed: {error_msg}")
                return None

            try:
                from shared.common import UserRole
                normal_val = UserRole.NORMAL.value
            except ImportError:
                normal_val = "normal"

            user_info = self._user_manager.get_user(user_id)
            if not user_info:
                log("error", f"User {user_id} not found")
                return None

            if is_public and user_info['role'] == normal_val:
                log("warning", f"Normal user {user_id} cannot upload public documents")
                return None

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_ext = os.path.splitext(original_filename)[1]
            unique_filename = f"{user_id}_{timestamp}_{original_filename}"
            dest_path = self.data_dir / unique_filename

            shutil.copy2(source_path, dest_path)

            if is_public:
                visible_to = ["admin", "master", "normal"]
            else:
                try:
                    from shared.common import UserRole
                    master_val = UserRole.MASTER.value
                except ImportError:
                    master_val = "master"
                visible_to = [user_info['role']]
                if user_info['role'] == master_val:
                    visible_to.append("normal")

            file_size = os.path.getsize(dest_path)
            file_size_mb = file_size / (1024 * 1024)

            self.documents[unique_filename] = {
                "original_filename": original_filename,
                "uploaded_by": user_id,
                "uploaded_at": datetime.now().isoformat(),
                "file_size": file_size,
                "file_size_mb": round(file_size_mb, 2),
                "file_extension": file_ext,
                "file_path": str(dest_path),
                "is_public": is_public,
                "visible_to": visible_to,
                "indexed_in": {},
            }

            self._save_metadata()
            log("debug", f"Document uploaded: {original_filename} -> {unique_filename} by user {user_id}")
            return unique_filename

        except Exception as e:
            log("error", f"Failed to upload document {original_filename}: {str(e)}", exc_info=True)
            return None

    def index_document(self, filename: str, engine_type: str, user_id: str) -> bool:
        try:
            if filename not in self.documents:
                log("error", f"Document {filename} not found")
                return False

            doc_info = self.documents[filename]

            if not self._check_user_permission(user_id, doc_info['uploaded_by']):
                log("warning", f"User {user_id} cannot index document {filename}")
                return False

            engine = self.get_engine(engine_type)
            if not engine:
                log("error", f"Engine {engine_type} not found")
                return False

            success = engine.index_document(
                doc_info['uploaded_by'],
                filename,
                doc_info['file_path'],
            )

            if success:
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
        try:
            if filename not in self.documents:
                log("warning", f"Document not found in metadata: {filename}")
                return False

            doc_info = self.documents[filename]

            if not self._check_user_permission(user_id, doc_info['uploaded_by']):
                log("warning", f"User {user_id} cannot delete document {filename}")
                return False

            for engine_type in self.engines:
                engine = self.get_engine(engine_type)
                if engine:
                    engine.delete_document(doc_info['uploaded_by'], filename)

            file_path = Path(doc_info["file_path"])
            if file_path.exists():
                file_path.unlink()

            del self.documents[filename]
            self._save_metadata()
            log("debug", f"Document deleted: {filename}")
            return True

        except Exception as e:
            log("error", f"Failed to delete document {filename}: {str(e)}", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # Document listing
    # ------------------------------------------------------------------

    def get_user_documents(self, user_id: str) -> List[Dict]:
        result = []
        for filename, metadata in self.documents.items():
            uploaded_by = metadata.get("uploaded_by")
            if uploaded_by is None:
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
                    "indexed_in": list(metadata.get("indexed_in", {}).keys()),
                })
        result.sort(key=lambda x: x["uploaded_at"], reverse=True)
        return result

    # ------------------------------------------------------------------
    # Similarity threshold helpers (used by admin UI search test)
    # ------------------------------------------------------------------

    def set_similarity_thresholds(self, thresholds: Dict[str, float]) -> Dict[str, Optional[float]]:
        previous: Dict[str, Optional[float]] = {}
        for engine_type, threshold in thresholds.items():
            engine = self.get_engine(engine_type)
            if not engine or not hasattr(engine, 'similarity_threshold'):
                continue
            previous[engine_type] = getattr(engine, 'similarity_threshold', None)
            engine.similarity_threshold = threshold
        return previous

    def restore_similarity_thresholds(self, previous: Dict[str, Optional[float]]):
        for engine_type, value in previous.items():
            engine = self.get_engine(engine_type)
            if engine and hasattr(engine, 'similarity_threshold'):
                engine.similarity_threshold = value

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        user_id: str,
        query: str,
        engine_type: Optional[str] = None,
        limit: int = 5,
        search_all: bool = False,
    ) -> Dict[str, Any]:
        results: Dict[str, Any] = {}

        if not self.is_rag_enabled():
            log("debug", "RAG search skipped: modules.rag_manager.enabled is false")
            return results

        target_engine = engine_type
        if not target_engine and not search_all:
            target_engine = self.default_engine

        accessible_docs = self.get_user_documents(user_id)
        if not accessible_docs:
            log("warning", f"Search aborted: no accessible docs for user={user_id}")
            return results

        allowed_filenames = {doc['filename'] for doc in accessible_docs}
        owners = {doc['uploaded_by'] for doc in accessible_docs}

        engine_types = [target_engine] if target_engine else list(self.engines.keys())
        engine_types = [e for e in engine_types if self.is_engine_enabled(e)]

        if not engine_types:
            return results

        for eng_type in engine_types:
            engine = self.get_engine(eng_type)
            if not engine:
                continue

            engine_results = []
            for owner in owners:
                owner_results = engine.search(owner, query, limit * 5)
                for result in owner_results:
                    if result['filename'] in allowed_filenames:
                        engine_results.append(result)

            engine_results.sort(key=lambda x: x['score'], reverse=True)
            results[eng_type] = engine_results[:limit]

        return results

    def get_rag_context(
        self,
        user_id: str,
        query: str,
        engine_type: Optional[str] = None,
    ) -> str:
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
            log("warning", f"No RAG ({engine_type}) results found for query: {query!r}")
            return f"No result found for : '{query}'"

        context_parts = [
            f"From document '{r['filename']}':\n{r['content']}\n"
            for r in engine_results
        ]
        return "Relevant context from documents:\n" + "\n".join(context_parts)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_document_count(self, user_id: Optional[str] = None) -> int:
        if user_id:
            return len(self.get_user_documents(user_id))
        return len(self.documents)

    def get_total_size_mb(self, user_id: Optional[str] = None) -> float:
        total = 0.0
        for filename, metadata in self.documents.items():
            if not user_id or self._check_user_permission(user_id, metadata.get('uploaded_by', '')):
                total += metadata.get('file_size_mb', 0)
        return round(total, 2)

    def clear_all_documents(self, user_id: str) -> bool:
        try:
            try:
                from shared.common import UserRole
                admin_val = UserRole.ADMIN.value
                master_val = UserRole.MASTER.value
            except ImportError:
                admin_val, master_val = "admin", "master"

            user_info = self._user_manager.get_user(user_id)
            if not user_info:
                return False

            if user_info['role'] not in [admin_val, master_val]:
                return False

            docs_to_delete = [
                filename for filename, metadata in self.documents.items()
                if 'uploaded_by' in metadata
                and self._check_user_permission(user_id, metadata['uploaded_by'])
            ]
            for filename in docs_to_delete:
                self.delete_document(filename, user_id)

            log("debug", f"Cleared {len(docs_to_delete)} documents by user {user_id}")
            return True

        except Exception as e:
            log("error", f"Failed to clear all documents: {str(e)}", exc_info=True)
            return False

    def _handle_user_deletion(self, user_id: str) -> bool:
        try:
            docs_to_delete = [
                filename for filename, metadata in self.documents.items()
                if metadata.get('uploaded_by') == user_id
            ]
            for filename in docs_to_delete:
                doc_info = self.documents[filename]
                file_path = Path(doc_info["file_path"])
                if file_path.exists():
                    file_path.unlink()
                for engine in self.engines.values():
                    engine.delete_document(user_id, filename)
                del self.documents[filename]

            if docs_to_delete:
                self._save_metadata()
            return True
        except Exception as e:
            log("error", f"Failed to handle user deletion for {user_id}: {str(e)}")
            return False

    def get_engine_stats(self, engine_type: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        engine = self.get_engine(engine_type)
        if not engine:
            return {}
        stats = engine.get_stats(user_id)
        stats['engine_type'] = engine_type
        return stats

    def has_any_documents(self, user_id: Optional[str] = None) -> bool:
        if user_id:
            return len(self.get_user_documents(user_id)) > 0
        return len(self.documents) > 0

    # ------------------------------------------------------------------
    # Auto-import
    # ------------------------------------------------------------------

    def run_auto_import(self):
        try:
            auto_import_configs = self._get_rag_config().get("auto_import", [])
            if not auto_import_configs:
                return

            from core.database import init_database
            from shared.common import init_user_manager

            if not self._user_manager.db.is_initialized():
                init_database()

            if self._user_manager.db.is_initialized():
                init_user_manager(create_default_users=True)
            else:
                log("warning", "Database not initialized, skipping RAG auto-import")
                return

            for user_config in auto_import_configs:
                user_id = user_config.get("user_id")
                files = user_config.get("files", [])
                if not user_id or not files:
                    continue
                user_info = self._user_manager.get_user(user_id)
                if not user_info:
                    log("warning", f"User {user_id} not found for auto-import")
                    continue
                self._auto_import_for_user(user_id, files)

        except Exception as e:
            log("error", f"Failed to run auto-import: {str(e)}", exc_info=True)

    def _auto_import_for_user(self, user_id: str, files: List[Dict]):
        try:
            existing_docs = self.get_user_documents(user_id)
            existing_filenames = {doc['original_filename'] for doc in existing_docs}

            imported_files = []
            for file_config in files:
                source_path = file_config.get("source_path")
                original_filename = file_config.get("original_filename")
                is_public = file_config.get("is_public", False)

                if not source_path or not original_filename:
                    continue

                if original_filename in existing_filenames:
                    imported_files.append(file_config)
                    continue

                if not os.path.exists(source_path):
                    log("warning", f"Source file not found: {source_path}")
                    continue

                unique_filename = self.upload_document(source_path, original_filename, user_id, is_public)
                if unique_filename:
                    imported_files.append(file_config)
                else:
                    log("error", f"Failed to auto-import {original_filename}")

            for file_config in imported_files:
                original_filename = file_config.get("original_filename")
                engines_to_index = file_config.get("engines", [])

                stored_filename = next(
                    (fn for fn, md in self.documents.items()
                     if md.get('original_filename') == original_filename
                     and md.get('uploaded_by') == user_id),
                    None,
                )
                if not stored_filename:
                    continue

                doc_info = self.documents.get(stored_filename, {})
                existing_indexes = doc_info.get('indexed_in', {})

                for engine_type in engines_to_index:
                    if engine_type in existing_indexes:
                        continue
                    engine_config = self._get_rag_config().get("engines", {}).get(engine_type, {})
                    if not engine_config.get("enabled", False):
                        continue
                    self.index_document(stored_filename, engine_type, user_id)

        except Exception as e:
            log("error", f"Auto-import failed for user {user_id}: {str(e)}", exc_info=True)
