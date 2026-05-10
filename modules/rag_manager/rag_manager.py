"""
RAG Manager Module — Functional Core

NO STREAMLIT DEPENDENCY. This module must remain importable without Streamlit.

Dependencies are injected at construction time:
    RAGManager(config, user_manager, cache_fn=None)

where:
    config       — plain dict or dict-like object (NOT st_shared.cached)
    user_manager — plain user manager instance
    cache_fn     — optional caching decorator (e.g. st.cache_resource).
                   If None, no caching is applied (headless / tests).

The module-level singleton is built by rag_factory.py which bridges the
Streamlit-cached world to this pure layer.
"""

import os
import json
from pathlib import Path
import shutil
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Any, Callable
import importlib
import pkgutil
import sys

from modules.rag_manager.rag_engine import RAGEngine
from core.logging import log

from modules.rag_manager.rag_result_limits import ResultLimitManager, ResultLimitContext
import uuid


# ---------------------------------------------------------------------------
# Per-engine stable cached factories
#
# These are MODULE-LEVEL functions so that st.cache_resource sees the same
# function object on every Streamlit rerun and returns the cached instance
# instead of re-constructing (and re-loading indices for) each engine.
#
# Pattern: one @cache_fn-decorated factory per engine type, keyed by
# (engine_class, frozenset(config_items)) so config changes bust the cache.
# ---------------------------------------------------------------------------

_ENGINE_CACHE: Dict[str, RAGEngine] = {}  # fallback when cache_fn is None


def _make_cached_engine_factory(cache_fn: Callable):
    """
    Return a cache_fn-decorated factory that constructs an engine exactly once
    per (module_name, config_fingerprint) pair across Streamlit reruns.

    We define the inner function here at call-time so cache_fn can decorate it,
    but we store the result on this module so the decorated object is stable
    for the lifetime of the Python process (i.e. across reruns).
    """
    @cache_fn
    def _cached_build_engine(full_module_name: str, attr_name: str,
                              config_fingerprint: tuple) -> Optional[RAGEngine]:
        """
        Instantiate one RAGEngine. Called at most once per unique set of
        arguments thanks to st.cache_resource.

        Args:
            full_module_name:    e.g. "modules.rag_manager.rag_engines.rag_classic"
            attr_name:           class name inside that module, e.g. "ClassicRAGEngine"
            config_fingerprint:  hashable snapshot of the engine's config dict
        """
        try:
            module = importlib.import_module(full_module_name)
            attr = getattr(module, attr_name, None)
            if attr is None:
                log("error", f"Cannot find {attr_name} in {full_module_name}")
                return None

            engine_config = dict(config_fingerprint)
            try:
                engine = attr(config=engine_config)
            except TypeError:
                engine = attr()

            log("info", f"Built RAG engine '{engine.engine_type}' (cached)")
            return engine
        except Exception as e:
            log("error", f"Failed to instantiate engine {attr_name} from {full_module_name}: {e}")
            return None

    return _cached_build_engine


# Holds the decorated factory after the first call to discover_engines().
# Stable across reruns once set.
_CACHED_ENGINE_FACTORY: Optional[Callable] = None


class RAGManager:
    """Manages RAG documents storage and operations with plugin-based engines.

    All dependencies are injected. No calls to st_shared.cached here.
    """

    def __init__(self, config: Any, user_manager: Any, cache_fn: Optional[Callable] = None):
        """
        Args:
            config:       A dict-like config object. Must support
                          config.get("rag_manager", {}).
            user_manager: User manager instance with get_user(), get_children(),
                          and register_before_delete_callback() methods.
            cache_fn:     Optional caching decorator (e.g. st.cache_resource).
                          If None, engine discovery runs uncached.
        """
        self._config = config
        self._user_manager = user_manager
        self._cache_fn = cache_fn

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
        self.instantiate_engines()

        embedding_config = self._config.get("embedding", {})
        if embedding_config:
            model_name = embedding_config.get("model_name")
            dimension = embedding_config.get("vector_dimension")
            if model_name and dimension:
                for engine in self.engines.values():
                    if hasattr(engine, 'model_name'):
                        engine.model_name = model_name
                    if hasattr(engine, 'dimension'):
                        engine.dimension = dimension
                log("info", f"Applied global embedding model to all engines: {model_name}")

        self._user_manager.register_before_delete_callback(self._handle_user_deletion)

        self.limit_manager = ResultLimitManager(rag_config)

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
        return self._config.get("rag_manager", {})

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

    @staticmethod
    def _config_fingerprint(engine_config: dict) -> tuple:
        """Convert an engine config dict to a hashable tuple for cache keying."""
        def _make_hashable(v):
            if isinstance(v, dict):
                return tuple(sorted((k, _make_hashable(vv)) for k, vv in v.items()))
            if isinstance(v, list):
                return tuple(_make_hashable(i) for i in v)
            return v

        return tuple(sorted((k, _make_hashable(val)) for k, val in engine_config.items()))

    def get_engine_ids(self) -> list:
        """Return all registered engine_ids in declaration order."""
        return list(self.engines.keys())

    def discover_engines(self):
        """
        Discover all RAGEngine subclasses from the rag_engines/ directory.
        Populates self._engine_classes  {engine_type: class}  — NOT instances yet.
        Instances are created by instantiate_engines() which reads the config.
        """
        import os, sys, importlib, pkgutil
        from modules.rag_manager.rag_engine import RAGEngine

        self._engine_classes = {}   # engine_type → class
        engines_dir = os.path.join(os.path.dirname(__file__), "rag_engines")

        if not os.path.isdir(engines_dir):
            log("error", f"RAGManager: rag_engines/ directory not found at {engines_dir}")
            return

        parent = os.path.dirname(os.path.dirname(__file__))  # project root
        if parent not in sys.path:
            sys.path.insert(0, parent)

        for _, module_name, is_pkg in pkgutil.iter_modules([engines_dir]):
            if is_pkg:
                continue
            try:
                full = f"modules.rag_manager.rag_engines.{module_name}"
                mod = importlib.import_module(full)
                for attr_name in dir(mod):
                    attr = getattr(mod, attr_name)
                    if (isinstance(attr, type)
                            and issubclass(attr, RAGEngine)
                            and attr is not RAGEngine
                            and not getattr(attr, "__abstractmethods__", None)):
                        # Use the class's default engine_type as the registry key.
                        dummy = object.__new__(attr)
                        dummy.engine_type = "unknown"
                        try:
                            # Peek at what engine_type the class would use.
                            # We call __init__ with empty config to sniff engine_type.
                            # For classes that don't accept config kwarg, just
                            # instantiate normally — they'll read nothing from config.
                            import re as _re
                            import inspect as _inspect
                            etype = None
                            # 1. Cheapest: class-level constant ENGINE_TYPE = "..."
                            etype = getattr(attr, "ENGINE_TYPE", None)
                            # 2. Parse super().__init__("engine_type_here") from source
                            if etype is None:
                                try:
                                    src = _inspect.getsource(attr.__init__)
                                    m = _re.search(
                                        r'super\(\)\.__init__\s*\(\s*["\'](\w+)["\']', src
                                    )
                                    if m:
                                        etype = m.group(1)
                                except Exception:
                                    pass
                            # 3. Strip "rag_" prefix from module filename as last resort
                            if etype is None:
                                etype = (
                                    module_name[4:]
                                    if module_name.startswith("rag_")
                                    else module_name
                                )
                        except Exception:
                            etype = module_name  # fallback
                        self._engine_classes[etype] = attr
                        log("info", f"RAGManager: registered engine class '{etype}' from {module_name}")
                        break
            except Exception as e:
                log("error", f"RAGManager: failed to load {module_name}: {e}")

        log("debug", f"RAGManager: engine classes = {list(self._engine_classes.keys())}")

    def instantiate_engines(self) -> None:
        """
        Read rag_manager.engines from config and create one named instance per block.

        engine_id   = config key  (e.g. "hybrid_no_hyde")  — display name / bench key
        engine_type = config["type"] or engine_id           — selects which class to use

        Skips engine_ids already present in self.engines (so engines built by the
        old explicit construction path are preserved and not double-instantiated).
        """
        import inspect
        try:
            rag_cfg = self._get_rag_config()
        except Exception as e:
            log("error",
                f"RAGManager.instantiate_engines: failed to read rag_manager config — {e}. "
                f"Check config.json for JSON syntax errors in the rag_manager section. "
                f"No additional engines will be loaded.")
            return
        engines_cfg = rag_cfg.get("engines", {})
        if not engines_cfg:
            log("warning",
                "RAGManager.instantiate_engines: 'engines' section is empty or missing "
                "from rag_manager config. Check config.json for syntax errors.")
            return

        global_embedding_config = self._config.get("embedding", {})
        for engine_id, ecfg in engines_cfg.items():
            if not isinstance(ecfg, dict):
                continue
            if not ecfg.get("enabled", True):
                log("debug", f"RAGManager.instantiate_engines: skipping disabled '{engine_id}'")
                continue
            if engine_id in self.engines:
                # Already built by the explicit construction path — don't overwrite.
                log("debug", f"RAGManager.instantiate_engines: '{engine_id}' already exists, skipping")
                continue

            engine_type = ecfg.get("type", engine_id)   # fallback = engine_id (backward compat)
            cls = self._engine_classes.get(engine_type)
            if cls is None:
                log("warning", f"RAGManager.instantiate_engines: no class for "
                               f"engine_type='{engine_type}' (id='{engine_id}') — skipping")
                continue

            try:
                sig = inspect.signature(cls.__init__)
                params = list(sig.parameters.keys())
                kwargs = {}
                if "config" in params:
                    # Merge engine config with global embedding config
                    merged_config = ecfg.copy()
                    # Only add global embedding settings if not already in engine config
                    if "model_name" not in merged_config and "model_name" in global_embedding_config:
                        merged_config["model_name"] = global_embedding_config["model_name"]
                    if "vector_dimension" not in merged_config and "vector_dimension" in global_embedding_config:
                        merged_config["dimension"] = global_embedding_config["vector_dimension"]

                    kwargs["config"] = merged_config
                if "engine_id" in params:
                    kwargs["engine_id"] = engine_id
                instance = cls(**kwargs)
                self.engines[engine_id] = instance
                # Inject manager reference into compositional engines (e.g. RRF)
                # that need to resolve sibling engines at search time.
                # Uses hasattr so non-RRF engines are unaffected.
                if hasattr(instance, 'set_manager'):
                    instance.set_manager(self)
                log("debug", f"RAGManager.instantiate_engines: created '{engine_id}' "
                            f"(type={engine_type})")
            except Exception as e:
                log("error", f"RAGManager.instantiate_engines: failed to create "
                             f"'{engine_id}': {e}", stacktrace=True)

        log("debug", f"RAGManager: engines = {list(self.engines.keys())}")


    def register_engine(self, engine: RAGEngine):
        self.engines[engine.engine_type] = engine

    def get_engine(self, engine_type: str) -> Optional[RAGEngine]:
        return self.engines.get(engine_type)

    def get_default_engine(self) -> Optional[RAGEngine]:
        return self.get_engine(self.default_engine)

    def get_default_engine_id(self, user_id: Optional[str] = None) -> str:
        """Get the effective default engine ID, checking system_settings first.

        Resolution order:
        1. User's personal override (if user_id provided and has setting)
        2. Master's override (if user_id provided and has a master)
        3. System-level setting
        4. Config default

        Args:
            user_id: Optional user ID to resolve user-specific override from their master

        Returns:
            Engine ID string
        """
        if user_id:
            user_settings_key = f"rag_manager.default_engine.{user_id}"
            user_override = self._user_manager.get_system_setting(user_settings_key)
            if user_override and user_override in self.engines:
                log("debug", f"Using user override for {user_id}: {user_override}")
                return user_override

            user_info = self._user_manager.get_user(user_id)
            if user_info:
                parent_id = user_info.get("parent_id")
                if parent_id:
                    master_settings_key = f"rag_manager.default_engine.{parent_id}"
                    master_override = self._user_manager.get_system_setting(master_settings_key)
                    if master_override and master_override in self.engines:
                        log("debug", f"Using master {parent_id} override for user {user_id}: {master_override}")
                        return master_override

        system_setting = self._user_manager.get_system_setting("rag_manager.default_engine")
        if system_setting and system_setting in self.engines:
            log("debug", f"Using system setting: {system_setting}")
            return system_setting

        return self.default_engine

    def set_default_engine_id(self, engine_id: str, target: Optional[str] = None) -> bool:
        """Set the default engine for system or a specific user/master.

        Args:
            engine_id: The engine ID to set as default
            target: Optional user_id to set user-specific default. If None, sets system default.

        Returns:
            True if successful
        """
        if engine_id not in self.engines:
            log("warning", f"Cannot set default engine: '{engine_id}' not found in available engines")
            return False

        if target:
            key = f"rag_manager.default_engine.{target}"
            log("info", f"Setting default engine for {target}: {engine_id}")
        else:
            key = "rag_manager.default_engine"
            log("info", f"Setting system default engine: {engine_id}")

        return self._user_manager.set_system_setting(key, engine_id)

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
            if user_id == owner_id:
                return True
            children = self._user_manager.get_children(user_id)
            return any(child['id'] == owner_id for child in children)

        if user_info['role'] == normal_val:
            profile = user_info.get('profile') or {}
            effective_master_id = profile.get('active_master_id') or user_info.get('parent_id')
            if effective_master_id and owner_id == effective_master_id:
                return True
        return False

    def _clean_wiki_content(self, content: str, wiki_section: str) -> str:
        lines = content.split('\n')
        result_lines = []
        in_frontmatter = False
        frontmatter_count = 0
        found_section = False

        for line in lines:
            if line.strip() == '---':
                frontmatter_count += 1
                if frontmatter_count == 1:
                    in_frontmatter = True
                elif frontmatter_count == 2:
                    in_frontmatter = False
                continue

            if in_frontmatter:
                continue

            if wiki_section and line.strip().startswith(wiki_section):
                found_section = True
                break

            if not found_section:
                result_lines.append(line)

        while result_lines and result_lines[-1].strip() == '':
            result_lines.pop()

        return '\n'.join(result_lines)

    # ------------------------------------------------------------------
    # Upload / delete
    # ------------------------------------------------------------------

    def upload_document(
        self,
        source_path: str,
        original_filename: str,
        user_id: str,
        is_public: bool = False,
        clean_wiki: bool = False,
        wiki_section: str = "## Voir aussi",
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

            if clean_wiki and file_ext == ".md":
                with open(dest_path, "r", encoding="utf-8") as f:
                    content = f.read()
                cleaned = self._clean_wiki_content(content, wiki_section)
                with open(dest_path, "w", encoding="utf-8") as f:
                    f.write(cleaned)

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
            log("error", f"Failed to upload document {original_filename}: {str(e)}", stacktrace=True)
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
            log("error", f"Failed to index document {filename}: {str(e)}", stacktrace=True)
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
            log("error", f"Failed to delete document {filename}: {str(e)}", stacktrace=True)
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
        limit: Optional[int] = None,  # ← Made optional
        search_all: bool = False,
        query_id: Optional[str] = None,  # ← New parameter for dynamic override
    ) -> Dict[str, Any]:
        """Search for documents across one or all engines."""
        results: Dict[str, Any] = {}

        log("debug", f"[RAG Search] ========== SEARCH START ==========")
        log("debug", f"[RAG Search] user_id={user_id}, query='{query}', engine_type={engine_type}, search_all={search_all}")

        # Determine effective limit
        if limit is None:
            limit = self.limit_manager.get_limit(
                context=ResultLimitContext.SEARCH,
                user_id=user_id,
                engine_type=engine_type,
                query_id=query_id
            )
        else:
            # Validate explicit limit
            limit = self.limit_manager.validate_limit(limit)

        log("debug", f"[RAG Search] Using result limit: {limit}")

        if not self.is_rag_enabled():
            log("debug", "[RAG Search] RAG disabled, returning empty")
            return results

        target_engine = engine_type
        if not target_engine and not search_all:
            target_engine = self.get_default_engine_id(user_id)
            log("debug", f"[RAG Search] Using default engine for user {user_id}: {target_engine}")

        # Get accessible documents for this user
        accessible_docs = self.get_user_documents(user_id)
        log("debug", f"[RAG Search] User {user_id} has {len(accessible_docs)} accessible documents total")

        if not accessible_docs:
            log("warning", f"[RAG Search] No accessible docs for user={user_id}")
            return results

        # Log document details for debugging
        for i, doc in enumerate(accessible_docs[:5]):  # Log first 5 docs
            log("debug", f"[RAG Search] Doc {i}: filename={doc['filename']}, owner={doc['uploaded_by']}, indexed_in={doc.get('indexed_in', [])}")

        allowed_filenames = {doc['filename'] for doc in accessible_docs}
        owners = {doc['uploaded_by'] for doc in accessible_docs}
        log("debug", f"[RAG Search] Allowed filenames: {allowed_filenames}")
        log("debug", f"[RAG Search] Owners: {owners}")

        # Determine which engines to search
        if search_all:
            engine_types = list(self.engines.keys())
            log("debug", f"[RAG Search] Searching ALL engines: {engine_types}")
        elif target_engine:
            engine_types = [target_engine]
            log("debug", f"[RAG Search] Searching single engine: {target_engine}")
        else:
            engine_types = []
            log("debug", f"[RAG Search] No engines to search")

        # Filter by enabled status
        engine_types = [e for e in engine_types if self.is_engine_enabled(e)]
        log("debug", f"[RAG Search] Enabled engines: {engine_types}")

        if not engine_types:
            log("debug", f"[RAG Search] No enabled engines found")
            return results

        for eng_type in engine_types:
            log("debug", f"[RAG Search] ====== Processing engine: {eng_type} ======")

            engine = self.get_engine(eng_type)
            if not engine:
                log("debug", f"[RAG Search] Engine {eng_type} not found in self.engines. Available engines: {list(self.engines.keys())}")
                continue

            # Check if engine is available
            if not engine.is_available():
                log("debug", f"[RAG Search] Engine {eng_type} reports is_available()=False")
                results[eng_type] = []
                continue

            log("debug", f"[RAG Search] Engine {eng_type} description: {engine.description}")
            log("debug", f"[RAG Search] Engine {eng_type} similarity_threshold: {getattr(engine, 'similarity_threshold', 'N/A')}")

            engine_results = []

            for owner in owners:
                log("debug", f"[RAG Search] Searching for owner: {owner}")

                # Check what documents this engine has for this owner
                indexed_docs = engine.get_indexed_documents(owner)
                log("debug", f"[RAG Search] Engine {eng_type} has {len(indexed_docs)} indexed docs for owner {owner}")

                if indexed_docs:
                    for i, doc in enumerate(indexed_docs[:3]):  # Log first 3
                        log("debug", f"[RAG Search]   Indexed doc {i}: {doc.get('filename')}")
                else:
                    log("debug", f"[RAG Search]   No indexed documents for owner {owner}")

                # Perform the search - PASS THE LIMIT
                owner_results = engine.search(owner, query, limit * 3)  # Get more for blending
                log("debug", f"[RAG Search] Engine {eng_type} returned {len(owner_results)} raw results for owner {owner}")

                if owner_results:
                    for i, r in enumerate(owner_results[:3]):  # Log first 3
                        log("debug", f"[RAG Search]   Raw result {i}: file={r.get('filename')}, score={r.get('score', 0):.4f}")
                else:
                    log("debug", f"[RAG Search]   No raw results for owner {owner}")

                # Filter results to only include accessible documents
                pre_filter_count = len(owner_results)
                filtered_for_owner = []

                for result in owner_results:
                    if result['filename'] in allowed_filenames:
                        filtered_for_owner.append(result)
                        log("debug", f"[RAG Search]   ✓ Result kept: {result['filename']}")
                    else:
                        log("debug", f"[RAG Search]   ✗ Result filtered out: {result['filename']} (not in allowed_filenames)")

                engine_results.extend(filtered_for_owner)
                log("debug", f"[RAG Search] Engine {eng_type}: {pre_filter_count} raw, {len(filtered_for_owner)} kept for owner {owner}")

            # Sort by score and limit to FINAL limit
            engine_results.sort(key=lambda x: x['score'], reverse=True)
            final_results = engine_results[:limit]

            log("debug", f"[RAG Search] Engine {eng_type} final results count: {len(final_results)} (requested limit: {limit})")

            if final_results:
                for i, r in enumerate(final_results):
                    log("debug", f"[RAG Search]   Final {i}: {r['filename']} (score: {r['score']:.4f})")
            else:
                log("debug", f"[RAG Search] No final results for engine {eng_type}")

                # Diagnostic info
                log("debug", f"[RAG Search]   Diagnostic for {eng_type}:")
                log("debug", f"[RAG Search]     - Engine type: {type(engine).__name__}")
                log("debug", f"[RAG Search]     - Owners searched: {owners}")
                log("debug", f"[RAG Search]     - Query: '{query}'")

                # Check if engine has any indexed documents at all
                total_indexed = 0
                for owner in owners:
                    indexed_docs = engine.get_indexed_documents(owner)
                    total_indexed += len(indexed_docs)
                log("debug", f"[RAG Search]     - Total indexed docs for these owners: {total_indexed}")

                if total_indexed == 0:
                    log("debug", f"[RAG Search]     - REASON: No documents indexed for any owner")

                # Check similarity threshold
                threshold = getattr(engine, 'similarity_threshold', 'N/A')
                log("debug", f"[RAG Search]     - Similarity threshold: {threshold}")

            results[eng_type] = final_results

        log("debug", f"[RAG Search] ========== SEARCH COMPLETE ==========")
        log("debug", f"[RAG Search] Final results summary: { {k: len(v) for k, v in results.items()} }")

        return results

    def get_rag_context(
        self,
        user_id: str,
        query: str,
        engine_type: Optional[str] = None,
        query_id: Optional[str] = None,  # ← New parameter
    ) -> str:
        """Get RAG context for a query."""
        if not self.is_rag_enabled():
            log("debug", "[RAG Context] RAG disabled, returning empty context")
            return ""

        if not engine_type:
            engine_type = self.get_default_engine_id(user_id)
            log("debug", f"[RAG Context] Using default engine for user {user_id}: {engine_type}")

        if not self.is_engine_enabled(engine_type):
            log("debug", f"[RAG Context] Engine {engine_type} disabled in config, returning empty context")
            return ""

        log("debug", f"[RAG Context] Getting context for user={user_id}, engine={engine_type}, query='{query}'")

        # Get the appropriate limit for context injection
        limit = self.limit_manager.get_limit(
            context=ResultLimitContext.CONTEXT_INJECTION,
            user_id=user_id,
            engine_type=engine_type,
            query_id=query_id
        )

        log("debug", f"[RAG Context] Using result limit: {limit}")

        search_results = self.search(user_id, query, engine_type, limit=limit, query_id=query_id)
        engine_results = search_results.get(engine_type, []) if search_results else []

        if not engine_results:
            log("warning", f"[RAG Context] No results found for query: '{query}' with engine {engine_type}")
            # Check if user has any documents indexed in this engine
            accessible_docs = self.get_user_documents(user_id)
            docs_in_engine = []
            for doc in accessible_docs:
                if engine_type in doc.get('indexed_in', []):
                    docs_in_engine.append(doc['original_filename'])

            if docs_in_engine:
                log("debug", f"[RAG Context] User has {len(docs_in_engine)} docs indexed in {engine_type}: {docs_in_engine[:5]}")
                log("debug", f"[RAG Context] Query '{query}' didn't match any content in these documents")
            else:
                log("debug", f"[RAG Context] User has no documents indexed in engine {engine_type}")

            return f"No result found for : '{query}'"

        context_parts = [
            f"From document '{r['filename']}':\n{r['content']}\n"
            for r in engine_results
        ]

        log("debug", f"[RAG Context] Returning {len(context_parts)} context chunks (limit was {limit})")
        return "Relevant context from documents:\n" + "\n".join(context_parts)


    def refresh_result_limits(self) -> None:
        """Reload result limits from config (called when config changes)"""
        rag_config = self._get_rag_config()
        self.limit_manager.update_config(rag_config.get("result_limits", {}))
        log("debug", "Result limits refreshed from config")


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
            log("error", f"Failed to clear all documents: {str(e)}", stacktrace=True)
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
            log("error", f"Failed to run auto-import: {str(e)}", stacktrace=True)

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
            log("error", f"Auto-import failed for user {user_id}: {str(e)}", stacktrace=True)

    def reindex_all_documents(
        self,
        target_engines: Optional[List[str]] = None,
        progress_callback: Optional[Callable[[float, str, int, int], None]] = None
    ) -> Dict[str, Any]:
        """
        Re-index all documents across all users and specified engines.

        Args:
            target_engines: List of engine types to re-index. If None, uses all available engines.
            progress_callback: Optional callback function(percentage, filename, current, total) called after each document.

        Returns:
            Dictionary with re-indexing statistics
        """
        log("info", "========== STARTING FULL RE-INDEX ==========")

        stats = {
            "total_documents": 0,
            "total_users": 0,
            "engines_processed": {},
            "successful": 0,
            "failed": 0,
            "skipped": 0,
            "errors": []
        }

        # Determine which engines to use
        if target_engines is None:
            target_engines = list(self.engines.keys())

        # Filter to available engines
        available_engines = [e for e in target_engines if e in self.engines and self.engines[e].is_available()]

        if not available_engines:
            log("warning", "No available engines found for re-indexing")
            stats["errors"].append("No available engines found")
            return stats

        log("info", f"Re-indexing with engines: {available_engines}")

        # Group documents by user
        documents_by_user: Dict[str, List[Tuple[str, Dict]]] = {}

        for filename, doc_info in self.documents.items():
            user_id = doc_info.get('uploaded_by')
            if not user_id:
                log("warning", f"Document {filename} has no owner, skipping")
                stats["skipped"] += 1
                continue

            if user_id not in documents_by_user:
                documents_by_user[user_id] = []
            documents_by_user[user_id].append((filename, doc_info))

        stats["total_users"] = len(documents_by_user)
        stats["total_documents"] = sum(len(docs) for docs in documents_by_user.values())

        log("info", f"Found {stats['total_documents']} documents across {stats['total_users']} users")

        # Initialize engine stats
        for engine_type in available_engines:
            stats["engines_processed"][engine_type] = {
                "successful": 0,
                "failed": 0,
                "skipped": 0
            }

        # Re-index each document for each engine
        for user_id, documents in documents_by_user.items():
            log("debug", f"Processing user: {user_id} ({len(documents)} documents)")

            for filename, doc_info in documents:
                file_path = doc_info.get('file_path')

                # Verify file still exists
                if not file_path or not os.path.exists(file_path):
                    log("warning", f"File not found for {filename}, skipping")
                    stats["skipped"] += 1
                    for engine_type in available_engines:
                        stats["engines_processed"][engine_type]["skipped"] += 1
                    stats["errors"].append(f"File not found: {filename}")
                    continue

                # Try to read content (for engines that need it)
                content = None
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                except Exception as e:
                    log("warning", f"Could not read file {filename}: {str(e)}")
                    # Continue anyway - engine might handle it

                # Index in each target engine
                for engine_type in available_engines:
                    engine = self.engines[engine_type]

                    try:
                        # Delete existing index first (optional - ensures clean state)
                        try:
                            engine.delete_document(user_id, filename)
                        except:
                            pass  # Ignore if document wasn't indexed

                        # Index the document
                        success = engine.index_document(
                            user_id,
                            filename,
                            file_path,
                            content
                        )

                        if success:
                            stats["successful"] += 1
                            stats["engines_processed"][engine_type]["successful"] += 1

                            # Update metadata
                            if 'indexed_in' not in doc_info:
                                doc_info['indexed_in'] = {}
                            doc_info['indexed_in'][engine_type] = datetime.now().isoformat()

                            log("debug", f"Successfully re-indexed {filename} with {engine_type}")
                        else:
                            stats["failed"] += 1
                            stats["engines_processed"][engine_type]["failed"] += 1
                            stats["errors"].append(f"Failed to index {filename} with {engine_type}")

                    except Exception as e:
                        stats["failed"] += 1
                        stats["engines_processed"][engine_type]["failed"] += 1
                        error_msg = f"Error indexing {filename} with {engine_type}: {str(e)}"
                        stats["errors"].append(error_msg)
                        log("error", error_msg)

                # Call progress callback after each document
                if progress_callback:
                    total_docs = stats["total_documents"]
                    current = stats["successful"] + stats["failed"] + stats["skipped"]
                    percentage = (current / total_docs * 100) if total_docs > 0 else 0
                    progress_callback(percentage, filename, current, total_docs)

        # Save updated metadata
        self._save_metadata()

        log("info", "========== RE-INDEX COMPLETE ==========")
        log("info", f"Successfully re-indexed: {stats['successful']} documents")
        log("info", f"Failed: {stats['failed']} documents")
        log("info", f"Skipped: {stats['skipped']} documents")

        return stats

    def clear_all_engine_indices(self) -> Dict[str, Any]:
        """
        Clear all indices across all engines for all users.
        Use this before re-indexing with a new embedding model.

        Returns:
            Dictionary with clearing statistics
        """
        log("info", "========== CLEARING ALL ENGINE INDICES ==========")

        stats = {
            "engines_cleared": [],
            "engines_failed": [],
            "documents_updated": 0
        }

        # Clear each engine's indices
        for engine_type, engine in self.engines.items():
            try:
                # Get all users that have indices in this engine
                users_with_indices = []

                # Different engines store users differently
                if hasattr(engine, 'indices'):
                    users_with_indices = list(engine.indices.keys())
                elif hasattr(engine, 'metadata'):
                    users_with_indices = list(engine.metadata.keys())
                elif hasattr(engine, '_indices'):
                    users_with_indices = list(engine._indices.keys())

                # Clear each user's index
                cleared_count = 0
                for user_id in users_with_indices:
                    if engine.clear_user_index(user_id):
                        cleared_count += 1

                stats["engines_cleared"].append({
                    "engine": engine_type,
                    "users_cleared": cleared_count
                })

                log("info", f"Cleared {engine_type} indices for {cleared_count} users")

            except Exception as e:
                stats["engines_failed"].append(engine_type)
                log("error", f"Failed to clear {engine_type} indices: {str(e)}")

        # Update document metadata to reflect cleared indices
        for filename, doc_info in self.documents.items():
            if 'indexed_in' in doc_info:
                # Clear all engine entries
                doc_info['indexed_in'] = {}
                stats["documents_updated"] += 1

        self._save_metadata()

        log("info", f"Cleared indices for {len(stats['engines_cleared'])} engines")
        log("info", f"Updated metadata for {stats['documents_updated']} documents")

        return stats
