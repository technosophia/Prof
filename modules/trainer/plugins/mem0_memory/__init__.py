"""
Mem0-backed Memory Plugin for Trainer Module.
Maintains pedagogical memory of student conversations for personalized teaching.
"""

from typing import List, Dict, Any, Optional, Callable, Tuple
from datetime import datetime
import os
import inspect

from shared.common import (
    get_prompt,
    register_llm_context_callback,
    log,
    get_config,
)
from modules.trainer.plugins.memory import MemoryPlugin

try:
    from mem0 import Memory as Mem0MemoryClient
except Exception:
    Mem0MemoryClient = None


class Mem0MemoryPlugin(MemoryPlugin):
    """Memory plugin variant backed by Mem0 instead of SQL storage."""

    def __init__(self, manifest):
        super().__init__(manifest)
        self._mem0_client = None

    def initialize(self) -> bool:
        """Initialize Mem0 client and register context callback."""
        try:
            if Mem0MemoryClient is None:
                log("error", "mem0 package is not installed; mem0_memory plugin disabled")
                return False

            config = get_config()
            mem0_cfg = config.get("modules.trainer.plugins.mem0_memory", {}) or {}

            api_key = mem0_cfg.get("api_key") or os.getenv("MEM0_API_KEY")
            if not api_key:
                log("error", "MEM0_API_KEY is missing; mem0_memory plugin disabled")
                return False

            client_config = {
                "api_key": api_key,
            }

            if mem0_cfg.get("org_id"):
                client_config["org_id"] = mem0_cfg["org_id"]
            if mem0_cfg.get("project_id"):
                client_config["project_id"] = mem0_cfg["project_id"]

            self._mem0_client = Mem0MemoryClient(client_config)
            register_llm_context_callback(self.get_memory_context)
            return True
        except Exception as e:
            log("error", f"Failed to initialize mem0 memory plugin: {e}")
            return False

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

        try:
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
                self._mem0_client.add(content, user_id=self._user_key(student_id, trainer_id), metadata=memory_metadata)
            else:
                self._mem0_client.add(content, user_id=self._user_key(student_id, trainer_id))

            return True
        except Exception as e:
            log("error", f"Failed to save mem0 memory: {e}", exc_info=True)
            return False

    async def _analyze_with_llm(self, trainer_id: str, student_id: str, old_memory: str, new_messages: List[Dict]):
        """Use plugin-specific prompt namespace for mem0 memory analysis."""
        training_program = get_prompt('trainer.teacher.training_program')

        conversations_text = ""
        for msg in new_messages:
            role_symbol = "👤 Student" if msg['role'] == 'user' else "🤖 Assistant"
            conversations_text += f"{role_symbol} ({msg['timestamp']}): {msg['content']}\n\n"

        system_prompt = get_prompt('trainer.plugins.mem0_memory.analysis_system')
        user_prompt = get_prompt('trainer.plugins.mem0_memory.analysis_user').format(
            training_program=training_program,
            old_memory=old_memory or get_prompt('trainer.plugins.mem0_memory.empty_memory'),
            conversations=conversations_text
        )

        from shared.common import get_llm_manager, get_current_llm_id

        try:
            llm_id = get_current_llm_id()
            source = f"llm:{llm_id}"
        except ValueError:
            source = "auto"
            llm_id = "unknown"

        try:
            llm_manager = get_llm_manager()
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
            response = await llm_manager.internal_response(llm_id if llm_id != "unknown" else None, messages)
            if response and not response.startswith("Error"):
                return response.strip(), source
            log("error", f"LLM analysis failed: {response}")
            return None, source
        except Exception as e:
            log("error", f"Error during LLM analysis: {e}", exc_info=True)
            return None, source

    def get_memory_context(self, user_id: str, messages: List[Dict]) -> Optional[Tuple[str, str, str]]:
        from shared.common import get_user_manager

        user = get_user_manager().get_user(user_id)
        if not user or not user.get('parent_id'):
            return None

        trainer_id = user['parent_id']
        memory = self._get_current_memory(user_id, trainer_id)
        if not memory:
            return None

        context_prompt = get_prompt('trainer.plugins.mem0_memory.context_injection')
        return (context_prompt.format(memory=memory), 'system', 'top')

    def export_history(self, trainer_id: str, student_id: Optional[str] = None) -> List[Dict[str, Any]]:
        trainer_manager = __import__('modules.trainer.manager', fromlist=['get_trainer_manager']).get_trainer_manager()
        students = [
            {'id': student_id}
        ] if student_id else trainer_manager.get_trainer_students(trainer_id)

        events = []
        for student in students:
            sid = student['id']
            for item in self._list_memories(sid, trainer_id):
                metadata = item.get('metadata') or {}
                timestamp = metadata.get('updated_at') or item.get('created_at') or datetime.utcnow().isoformat()
                events.append({
                    'timestamp': timestamp,
                    'type': 'plugin.memory.updated',
                    'plugin_id': self.id,
                    'student_id': sid,
                    'memory_id': item.get('id') or item.get('memory_id'),
                    'content': self._extract_content(item),
                    'source': metadata.get('source', 'auto'),
                    'version': self._extract_version(item),
                    'metadata': metadata,
                    'is_current': item == self._list_memories(sid, trainer_id)[-1],
                })

        events.sort(key=lambda e: e.get('timestamp', ''))
        return events


# Plugin entry point
plugin = Mem0MemoryPlugin
