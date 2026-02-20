"""
Mem0-backed Memory Plugin for Trainer Module.
Maintains pedagogical memory of student conversations for personalized teaching.
"""

from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from pathlib import Path
import inspect
import re
import shutil

from shared.common import (
    get_prompt,
    register_llm_context_callback,
    log,
    get_config,
    get_llm_manager,
    get_current_llm_id,
    get_user_manager,
)
from modules.trainer.plugins.memory import MemoryPlugin
from modules.trainer.manager import get_trainer_manager

try:
    from mem0 import Memory as Mem0MemoryClient
except Exception:
    Mem0MemoryClient = None


class Mem0MemoryPlugin(MemoryPlugin):
    """Memory plugin variant backed by Mem0 OSS/local storage."""

    def __init__(self, manifest):
        super().__init__(manifest)
        self._mem0_client = None
        self._mem0_cfg: Dict[str, Any] = {}
        self._storage_dir: Optional[Path] = None
        self._vector_store_path: Optional[Path] = None
        self._history_db_path: Optional[Path] = None

    def initialize(self) -> bool:
        """Initialize local Mem0 client and register context callback."""
        try:
            if Mem0MemoryClient is None:
                log("error", "mem0 package is not installed; mem0_memory plugin disabled")
                return False

            self._mem0_cfg = self._build_local_mem0_config()
            self._mem0_client = self._create_mem0_client(self._mem0_cfg)
            register_llm_context_callback(self.get_memory_context)
            log("info", "mem0_memory plugin initialized with local OSS backend")
            return True
        except Exception as e:
            log("error", f"Failed to initialize mem0 memory plugin: {e}", exc_info=True)
            return False

    def _resolve_app_ollama_model(self) -> Optional[str]:
        """Return the currently configured app Ollama model when available."""
        try:
            llm_manager = get_llm_manager()

            current = llm_manager.get_current_llm_info()
            if current and current.get("type") == "ollama" and current.get("model"):
                return current["model"]

            for llm in llm_manager.get_available_llms():
                if llm.get("enabled") and llm.get("type") == "ollama" and llm.get("model"):
                    return llm["model"]
        except Exception as e:
            log("warning", f"Could not resolve app Ollama model: {e}")

        return None

    def _build_local_mem0_config(self) -> Dict[str, Any]:
        """Build a local-first Mem0 OSS configuration (no cloud API key)."""
        config = get_config()
        mem0_cfg = config.get("modules.trainer.plugins.mem0_memory", {}) or {}

        self._storage_dir = Path(mem0_cfg.get("storage_dir", "data/mem0_memory")).resolve()
        self._storage_dir.mkdir(parents=True, exist_ok=True)

        ollama_base_url = mem0_cfg.get("ollama_base_url", "http://127.0.0.1:11434")
        embed_model = mem0_cfg.get("embedding_model", "nomic-embed-text")

        app_model = self._resolve_app_ollama_model()
        llm_model = app_model or mem0_cfg.get("llm_model", "qwen2.5:7b")

        embed_slug = re.sub(r"[^a-zA-Z0-9_.-]", "_", embed_model)
        self._vector_store_path = self._storage_dir / f"faiss_{embed_slug}"
        self._history_db_path = self._storage_dir / f"history_{embed_slug}.db"

        self._vector_store_path.mkdir(parents=True, exist_ok=True)

        if app_model:
            log("info", f"mem0_memory using app Ollama model: {app_model}")

        return {
            "llm": {
                "provider": "ollama",
                "config": {
                    "model": llm_model,
                    "ollama_base_url": ollama_base_url,
                },
            },
            "embedder": {
                "provider": "ollama",
                "config": {
                    "model": embed_model,
                    "ollama_base_url": ollama_base_url,
                },
            },
            "vector_store": {
                "provider": "faiss",
                "config": {
                    "path": str(self._vector_store_path),
                },
            },
            "history_db_path": str(self._history_db_path),
            "version": "v1.1",
        }

    def _create_mem0_client(self, cfg: Dict[str, Any]):
        """Create Mem0 client for local mode, across API variants."""
        if hasattr(Mem0MemoryClient, "from_config"):
            return Mem0MemoryClient.from_config(cfg)

        ctor_sig = inspect.signature(Mem0MemoryClient)
        if "config" in ctor_sig.parameters:
            return Mem0MemoryClient(config=cfg)
        return Mem0MemoryClient(cfg)

    def _recreate_local_store(self) -> None:
        """Reset local Mem0 files to recover from FAISS dimension mismatch."""
        paths_to_reset = []

        if self._vector_store_path:
            paths_to_reset.append(self._vector_store_path)

        # Some mem0 versions ignore custom FAISS path and fallback to ./faiss_index
        if self._storage_dir:
            paths_to_reset.append(self._storage_dir / "faiss_index")

        for path in paths_to_reset:
            if path.exists() and path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            path.mkdir(parents=True, exist_ok=True)

        # Remove stray FAISS artifacts under storage_dir
        if self._storage_dir and self._storage_dir.exists():
            for artifact in self._storage_dir.rglob("*.faiss"):
                artifact.unlink(missing_ok=True)
            for artifact in self._storage_dir.rglob("*.pkl"):
                artifact.unlink(missing_ok=True)

        if self._history_db_path and self._history_db_path.exists():
            self._history_db_path.unlink(missing_ok=True)

        # Also remove default history path for mem0 versions using implicit names
        if self._storage_dir:
            default_history = self._storage_dir / "history.db"
            default_history.unlink(missing_ok=True)

        self._mem0_client = self._create_mem0_client(self._mem0_cfg)

    def _is_faiss_dimension_error(self, exc: Exception) -> bool:
        msg = str(exc)
        return (
            "assert d == self.d" in msg
            or "dimension" in msg.lower()
            or exc.__class__.__name__ == "AssertionError"
        )

    def _user_key(self, student_id: str, trainer_id: str) -> str:
        return f"trainer:{trainer_id}:student:{student_id}"

    def _normalize_memories(self, raw: Any) -> List[Dict[str, Any]]:
        if isinstance(raw, dict):
            if isinstance(raw.get("results"), list):
                return raw["results"]
            if isinstance(raw.get("memories"), list):
                return raw["memories"]
            return []
        if isinstance(raw, list):
            return raw
        return []

    def _extract_content(self, item: Dict[str, Any]) -> str:
        metadata = item.get("metadata") or {}
        return (
            metadata.get("content")
            or item.get("memory")
            or item.get("content")
            or item.get("text")
            or ""
        )

    def _extract_version(self, item: Dict[str, Any], fallback: int = 1) -> int:
        metadata = item.get("metadata") or {}
        version = metadata.get("version", item.get("version", fallback))
        try:
            return int(version)
        except Exception:
            return fallback

    def _list_memories(self, student_id: str, trainer_id: str) -> List[Dict[str, Any]]:
        if not self._mem0_client:
            return []

        try:
            raw = self._mem0_client.get_all(user_id=self._user_key(student_id, trainer_id))
            items = self._normalize_memories(raw)
            items.sort(key=lambda item: self._extract_version(item, 0))
            return items
        except Exception as e:
            log("error", f"Failed to read mem0 memories: {e}")
            return []

    def _get_current_memory(self, student_id: str, trainer_id: str) -> Optional[str]:
        items = self._list_memories(student_id, trainer_id)
        if not items:
            return None
        return self._extract_content(items[-1])

    def _get_memory_with_metadata(self, student_id: str, trainer_id: str) -> Optional[Dict]:
        items = self._list_memories(student_id, trainer_id)
        if not items:
            return None

        current = items[-1]
        metadata = current.get("metadata") or {}
        updated_at = metadata.get("updated_at") or current.get("updated_at") or current.get("created_at")

        parsed_updated_at = datetime.utcnow()
        if isinstance(updated_at, str):
            try:
                parsed_updated_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            except Exception:
                pass

        last_analyzed = metadata.get("last_analyzed_at")
        parsed_last_analyzed = None
        if isinstance(last_analyzed, str):
            try:
                parsed_last_analyzed = datetime.fromisoformat(last_analyzed.replace("Z", "+00:00"))
            except Exception:
                parsed_last_analyzed = None

        return {
            "content": self._extract_content(current),
            "version": self._extract_version(current, len(items)),
            "source": metadata.get("source", current.get("source", "auto")),
            "last_analyzed_at": parsed_last_analyzed,
            "updated_at": parsed_updated_at,
            "metadata": metadata,
        }

    def _get_version_count(self, student_id: str, trainer_id: str) -> int:
        return max(0, len(self._list_memories(student_id, trainer_id)) - 1)

    def _get_last_analyzed(self, student_id: str, trainer_id: str) -> Optional[datetime]:
        memory = self._get_memory_with_metadata(student_id, trainer_id)
        return memory.get("last_analyzed_at") if memory else None

    def _save_memory(
        self,
        student_id: str,
        trainer_id: str,
        content: str,
        source: str,
        metadata: Dict = None,
    ) -> bool:
        if not self._mem0_client:
            return False

        def _add_once() -> bool:
            current = self._get_current_memory(student_id, trainer_id)
            if current == content:
                return True

            existing = self._list_memories(student_id, trainer_id)
            version = (self._extract_version(existing[-1], 0) + 1) if existing else 1

            memory_metadata = metadata.copy() if metadata else {}
            memory_metadata.update(
                {
                    "plugin_id": self.id,
                    "trainer_id": trainer_id,
                    "student_id": student_id,
                    "version": version,
                    "source": source,
                    "updated_at": datetime.utcnow().isoformat(),
                    "content": content,
                }
            )
            if source.startswith("llm:"):
                memory_metadata["last_analyzed_at"] = datetime.utcnow().isoformat()

            add_sig = inspect.signature(self._mem0_client.add)
            if "metadata" in add_sig.parameters:
                self._mem0_client.add(
                    content,
                    user_id=self._user_key(student_id, trainer_id),
                    metadata=memory_metadata,
                )
            else:
                self._mem0_client.add(content, user_id=self._user_key(student_id, trainer_id))
            return True

        try:
            return _add_once()
        except Exception as e:
            if self._is_faiss_dimension_error(e):
                log(
                    "warning",
                    f"Mem0 FAISS mismatch detected ({type(e).__name__}), recreating local store and retrying once",
                )
                try:
                    self._recreate_local_store()
                    return _add_once()
                except Exception as retry_error:
                    log("error", f"Failed to save mem0 memory after index reset: {retry_error}", exc_info=True)
                    return False

            log("error", f"Failed to save mem0 memory: {e}", exc_info=True)
            return False

    async def _analyze_with_llm(
        self,
        trainer_id: str,
        student_id: str,
        old_memory: str,
        new_messages: List[Dict],
    ):
        """Use plugin-specific prompt namespace for mem0 memory analysis."""
        training_program = get_prompt("trainer.teacher.training_program")

        conversations_text = ""
        for msg in new_messages:
            role_symbol = "👤 Student" if msg["role"] == "user" else "🤖 Assistant"
            conversations_text += f"{role_symbol} ({msg['timestamp']}): {msg['content']}\n\n"

        system_prompt = get_prompt("trainer.plugins.mem0_memory.analysis_system")
        user_prompt = get_prompt("trainer.plugins.mem0_memory.analysis_user").format(
            training_program=training_program,
            old_memory=old_memory or get_prompt("trainer.plugins.mem0_memory.empty_memory"),
            conversations=conversations_text,
        )

        try:
            llm_id = get_current_llm_id()
            source = f"llm:{llm_id}"
        except ValueError:
            source = "auto"
            llm_id = "unknown"

        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            response = await get_llm_manager().internal_response(
                llm_id if llm_id != "unknown" else None,
                messages,
            )
            if response and not response.startswith("Error"):
                return response.strip(), source
            log("error", f"LLM analysis failed: {response}")
            return None, source
        except Exception as e:
            log("error", f"Error during LLM analysis: {e}", exc_info=True)
            return None, source

    def get_memory_context(self, user_id: str, messages: List[Dict]) -> Optional[Tuple[str, str, str]]:
        user = get_user_manager().get_user(user_id)
        if not user or not user.get("parent_id"):
            return None

        trainer_id = user["parent_id"]
        memory = self._get_current_memory(user_id, trainer_id)
        if not memory:
            return None

        context_prompt = get_prompt("trainer.plugins.mem0_memory.context_injection")
        return (context_prompt.format(memory=memory), "system", "top")

    def export_history(self, trainer_id: str, student_id: Optional[str] = None) -> List[Dict[str, Any]]:
        students = [{"id": student_id}] if student_id else get_trainer_manager().get_trainer_students(trainer_id)

        events = []
        for student in students:
            sid = student["id"]
            student_memories = self._list_memories(sid, trainer_id)
            current_item = student_memories[-1] if student_memories else None

            for item in student_memories:
                metadata = item.get("metadata") or {}
                timestamp = metadata.get("updated_at") or item.get("created_at") or datetime.utcnow().isoformat()
                events.append(
                    {
                        "timestamp": timestamp,
                        "type": "plugin.memory.updated",
                        "plugin_id": self.id,
                        "student_id": sid,
                        "memory_id": item.get("id") or item.get("memory_id"),
                        "content": self._extract_content(item),
                        "source": metadata.get("source", "auto"),
                        "version": self._extract_version(item),
                        "metadata": metadata,
                        "is_current": item == current_item,
                    }
                )

        events.sort(key=lambda e: e.get("timestamp", ""))
        return events

    def import_history(self, trainer_id: str, events: List[Dict[str, Any]], student_info: Dict = None) -> bool:
        """Import memory history into Mem0 backend."""
        try:
            plugin_events = [e for e in events if e.get("plugin_id") == self.id]
            plugin_events.sort(key=lambda e: e.get("timestamp", ""))

            for event in plugin_events:
                student_id = event.get("student_id")
                if not student_id:
                    continue

                metadata = event.get("metadata", {}).copy() if event.get("metadata") else {}
                if event.get("timestamp"):
                    metadata.setdefault("updated_at", event["timestamp"])

                self._save_memory(
                    student_id=student_id,
                    trainer_id=trainer_id,
                    content=event.get("content", ""),
                    source=event.get("source", "import"),
                    metadata=metadata,
                )

            return True
        except Exception as e:
            log("error", f"Failed to import mem0 memory history: {e}", exc_info=True)
            return False


# Plugin entry point
plugin = Mem0MemoryPlugin
