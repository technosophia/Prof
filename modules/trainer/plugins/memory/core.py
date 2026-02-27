"""
Memory Plugin for Trainer Module.
Maintains pedagogical memory of student conversations for personalized teaching.

Migration status: COMPLETE
  - initialize() calls self._resolve_services(services)
  - All data methods use self.db, self.user_manager, self.conversation_manager,
    self.llm_manager — no st_shared.cached imports
  - All render methods call self.<data_method>() only — no db/cache access inline
  - When splitting into two classes: replace self.xxx() with self._logic.xxx()
    in every render method. No logic rewrite needed.
"""

from typing import List, Dict, Any, Optional, Callable, Tuple
from datetime import datetime
import uuid
import asyncio

from sqlalchemy import Column, String, Text, DateTime, JSON, Integer

from shared.common import get_prompt, register_llm_context_callback, get_current_llm_id
from modules.trainer.plugin_base import PluginManifest
from modules.trainer.plugin_base_core import TrainerPluginCore

from core.logging import log
from core.database import Base


class StudentMemory(Base):
    """Store pedagogical memory for each student with version history."""
    __tablename__ = 'trainer_student_memories'
    __table_args__ = {'extend_existing': True}

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), nullable=False, index=True)
    trainer_id = Column(String(36), nullable=False, index=True)
    content = Column(Text, default="")
    version = Column(Integer, default=1)
    is_current = Column(Integer, default=1)
    source = Column(String(255), nullable=False)
    last_analyzed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    memory_metadata = Column(JSON, default={})



class MemoryPluginCore(TrainerPluginCore):

    def initialize(self, services=None) -> bool:
        """
        Initialize the plugin and ensure database tables exist.

        Resolves all services via _resolve_services so that data methods
        never need to touch st_shared.cached.
        """
        try:
            self._resolve_services(services)

            if self.db and self.db.is_initialized() and not self.db._in_memory:
                Base.metadata.create_all(
                    self.db._engine,
                    tables=[StudentMemory.__table__],
                    checkfirst=True,
                )
                log("info", "StudentMemory table created/verified")

            register_llm_context_callback(self.get_memory_context)
            return True
        except Exception as e:
            log("error", f"Failed to initialize memory plugin: {e}")
            return False

    def on_activate(self, trainer_id: str) -> None:
        """Called when the memory plugin is activated for a trainer."""
        log("info", f"Memory plugin activated for trainer {trainer_id}")

        try:
            if self.trainer_manager is None:
                log("warning", "Memory plugin activated without trainer_manager")
                return
            students = self.trainer_manager.get_trainer_students(trainer_id)

            for student in students:
                existing = self._get_current_memory(student['id'], trainer_id)
                if existing is None:
                    self._save_memory(
                        student['id'],
                        trainer_id,
                        "",
                        "system",
                        {'initialized_at': datetime.utcnow().isoformat()}
                    )
                    log("info", f"Initialized empty memory for student {student['id']}")
        except Exception as e:
            log("error", f"Error during memory plugin activation: {e}")

    def on_deactivate(self, trainer_id: str) -> None:
        """Called when the memory plugin is deactivated for a trainer."""
        log("info", f"Memory plugin deactivated for trainer {trainer_id}")

    def _get_current_memory(self, student_id: str, trainer_id: str) -> Optional[str]:
        """Get the current memory content for a student."""
        with self.db.get_session() as session:
            memory = session.query(StudentMemory).filter_by(
                user_id=student_id,
                trainer_id=trainer_id,
                is_current=1
            ).first()
            return memory.content if memory else None

    def _get_memory_with_metadata(self, student_id: str, trainer_id: str) -> Optional[Dict]:
        """Get current memory with all metadata."""
        with self.db.get_session() as session:
            memory = session.query(StudentMemory).filter_by(
                user_id=student_id,
                trainer_id=trainer_id,
                is_current=1
            ).first()
            if memory:
                return {
                    'content': memory.content,
                    'version': memory.version,
                    'source': memory.source,
                    'last_analyzed_at': memory.last_analyzed_at,
                    'updated_at': memory.updated_at,
                    'metadata': memory.memory_metadata
                }
            return None

    def _get_version_count(self, student_id: str, trainer_id: str) -> int:
        """Get number of historical (non-current) versions."""
        with self.db.get_session() as session:
            total = session.query(StudentMemory).filter_by(
                user_id=student_id,
                trainer_id=trainer_id
            ).count()
            return max(0, total - 1)

    def _get_last_analyzed(self, student_id: str, trainer_id: str) -> Optional[datetime]:
        """Get the timestamp of the last conversation analysis."""
        with self.db.get_session() as session:
            memory = session.query(StudentMemory).filter_by(
                user_id=student_id,
                trainer_id=trainer_id,
                is_current=1
            ).first()
            return memory.last_analyzed_at if memory else None

    def _save_memory(self, student_id: str, trainer_id: str, content: str,
                     source: str, metadata: Dict = None) -> bool:
        """Save a new memory version, creating a history entry from the previous one."""
        try:
            with self.db.get_session() as session:
                current = session.query(StudentMemory).filter_by(
                    user_id=student_id,
                    trainer_id=trainer_id,
                    is_current=1
                ).first()

                if current and current.content == content:
                    return True

                if current:
                    current.is_current = 0
                    session.add(current)

                max_version = session.query(StudentMemory.version).filter_by(
                    user_id=student_id,
                    trainer_id=trainer_id
                ).order_by(StudentMemory.version.desc()).first()
                next_version = (max_version[0] + 1) if max_version else 1

                new_memory = StudentMemory(
                    user_id=student_id,
                    trainer_id=trainer_id,
                    content=content,
                    version=next_version,
                    is_current=1,
                    source=source,
                    last_analyzed_at=datetime.utcnow() if source.startswith('llm:') else None,
                    memory_metadata=metadata or {}
                )
                session.add(new_memory)
                session.commit()
                return True
        except Exception as e:
            log("error", f"Failed to save memory: {e}", exc_info=True)
            return False

    def _get_student_trainer_id(self, student_id: str) -> Optional[str]:
        """Return the trainer_id (parent_id) for a student. DATA LAYER helper."""
        user = self.user_manager.get_user(student_id)
        if not user:
            return None
        return user.get('parent_id')

    def _get_new_conversations(self, student_id: str, since: Optional[datetime]) -> List[Dict]:
        """Get all conversation messages for a student since a given timestamp."""
        conversations = self.conversation_manager.get_user_conversations(student_id)
        new_messages = []

        for conv in conversations:
            full_conv = self.conversation_manager.get_conversation(conv["id"])
            if not full_conv or not full_conv.messages:
                continue

            for msg in full_conv.messages:
                if msg.role not in ['user', 'assistant']:
                    continue

                msg_time = msg.timestamp
                if msg_time and (not since or msg_time > since):
                    new_messages.append({
                        'role': msg.role,
                        'content': msg.content,
                        'timestamp': msg_time.isoformat() if msg_time else None,
                        'conversation_id': conv["id"],
                        'conversation_title': conv.get('title', 'Untitled')
                    })

        new_messages.sort(key=lambda x: x.get('timestamp', ''))
        return new_messages

    def get_memory_context(self, user_id: str, messages: List[Dict]) -> Optional[Tuple[str, str, str]]:
        """
        LLM context callback — inject student memory into conversations.

        DATA LAYER: uses self.user_manager and self.db only.
        Returns: (context, role, position)
        """
        if not self._is_active:
            return None

        trainer_id = self._get_student_trainer_id(user_id)
        if not trainer_id:
            return None

        memory = self._get_current_memory(user_id, trainer_id)
        if not memory:
            return None

        context_prompt = get_prompt('trainer.plugins.memory.context_injection')
        context = context_prompt.format(memory=memory)
        return (context, "system", "top")

    def get_context(self, student_id: str) -> Dict[str, str]:
        """
        Get plugin-specific context for a student.

        DATA LAYER: uses self.user_manager and self.db only.
        """
        trainer_id = self._get_student_trainer_id(student_id)
        if not trainer_id:
            return {}

        memory = self._get_current_memory(student_id, trainer_id)
        if memory:
            return {"🧠 Pedagogical Memory": memory}
        return {}

    def _action_trigger_analysis(self, context, **params) -> Dict:
        """
        Called by the driver action 'trigger_memory_analysis'.
        DATA LAYER — no st.* here.
        """
        from shared.common import record_plugin_event

        success = asyncio.run(
            self.refresh_memory(context.trainer_id, context.student_id)
        )
        memory = self._get_memory_with_metadata(context.student_id, context.trainer_id)
        record_plugin_event("memory", "analysis_complete", {
            "success": success,
            "version": memory.get("version") if memory else None,
        })
        return {
            "success": success,
            "plugin": "memory",
            "version": memory.get("version") if memory else None,
        }

    def export_history(self, trainer_id: str, student_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Export all memory updates as events."""
        events = []

        with self.db.get_session() as session:
            query = session.query(StudentMemory).filter_by(trainer_id=trainer_id)
            if student_id:
                query = query.filter_by(user_id=student_id)

            memories = query.order_by(StudentMemory.created_at).all()

            for memory in memories:
                event = {
                    'timestamp': memory.created_at.isoformat(),
                    'type': 'plugin.memory.updated',
                    'plugin_id': self.id,
                    'student_id': memory.user_id,
                    'memory_id': memory.id,
                    'content': memory.content,
                    'source': memory.source,
                    'version': memory.version,
                }

                if memory.memory_metadata:
                    event['metadata'] = memory.memory_metadata

                if memory.is_current:
                    event['is_current'] = True

                events.append(event)

        return events
