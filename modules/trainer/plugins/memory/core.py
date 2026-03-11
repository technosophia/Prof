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
from types import SimpleNamespace
import uuid
import asyncio

from sqlalchemy import Column, String, Text, DateTime, JSON, Integer
from sqlalchemy.orm.attributes import flag_modified

from shared.common import get_prompt, register_llm_context_callback, get_current_llm_id
from modules.trainer.plugin_base import PluginManifest
from modules.trainer.plugin_base_core import TrainerPluginCore

from core.logging import log
from core.database import Base
from core.thread import run_async_safely


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
            self.conversation_manager.register_conversation_created_callback(
                self._on_conversation_created
            )
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

    # ─────────────────────────────────────────────────────────────────────
    # Auto-analyze config (stored in PluginActivation.config per trainer)
    # ─────────────────────────────────────────────────────────────────────

    def get_auto_analyze_config(self, trainer_id: str) -> bool:
        """Return True if auto-analyze on new conversation is enabled for this trainer."""
        if self.trainer_manager is None:
            return False
        from modules.trainer.models import PluginActivation
        with self.db.get_session() as session:
            activation = session.query(PluginActivation).filter_by(
                trainer_id=trainer_id,
                plugin_id=self.id,
            ).first()
            if activation and activation.config:
                return activation.config.get("auto_analyze_on_new_conversation", False)
            return False

    def set_auto_analyze_config(self, trainer_id: str, enabled: bool) -> bool:
        """Enable or disable auto-analyze on new conversation for this trainer."""
        from modules.trainer.models import PluginActivation
        try:
            with self.db.get_session() as session:
                activation = session.query(PluginActivation).filter_by(
                    trainer_id=trainer_id,
                    plugin_id=self.id,
                ).first()
                if activation is None:
                    activation = PluginActivation(
                        trainer_id=trainer_id,
                        plugin_id=self.id,
                        is_active=True,
                        config={}
                    )
                    session.add(activation)
                cfg = dict(activation.config or {})
                cfg["auto_analyze_on_new_conversation"] = enabled
                activation.config = cfg
                flag_modified(activation, "config")
                session.commit()
                log("info", f"Memory plugin: auto_analyze_on_new_conversation={enabled} for trainer {trainer_id}")
                return True
        except Exception as e:
            log("error", f"Memory plugin: failed to save auto_analyze config: {e}", stacktrace=True)
            return False

    # ─────────────────────────────────────────────────────────────────────
    # Trigger — single entry point for both manual and automatic analysis
    # ─────────────────────────────────────────────────────────────────────

    def trigger_analysis(self, student_id: str, trainer_id: str,
                         conversation_id: Optional[str] = None) -> Dict:
        """
        Trigger a memory analysis for a student.

        Single entry point used by both the automatic conversation-created
        callback and the manual driver action.  Builds the context and
        delegates to _action_trigger_analysis.

        Args:
            student_id: The student's user ID.
            trainer_id: The trainer's user ID.
            conversation_id: Optional conversation that triggered the analysis.

        Returns:
            Result dict from _action_trigger_analysis.
        """
        context = SimpleNamespace(
            student_id=student_id,
            trainer_id=trainer_id,
            conversation_id=conversation_id,
            llm_id=None,
        )
        return self._action_trigger_analysis(context)

    # ─────────────────────────────────────────────────────────────────────
    # Conversation-created callback
    # ─────────────────────────────────────────────────────────────────────

    def _on_conversation_created(self, conversation_id: str, user_id: str) -> None:
        """
        Callback triggered when a new conversation is created.
        Only fires analysis if:
          - the user is a student (has a parent_id / trainer)
          - the plugin is active for that trainer
          - auto_analyze_on_new_conversation is enabled for that trainer
        """
        try:
            user = self.user_manager.get_user(user_id)
            if not user or not user.get("parent_id"):
                return  # Not a student — trainers/masters creating conversations are ignored

            trainer_id = user["parent_id"]

            if self.trainer_manager is None:
                return
            if not self.trainer_manager.is_plugin_active(trainer_id, self.id):
                return
            if not self.get_auto_analyze_config(trainer_id):
                return

            log("info", f"Memory plugin: auto-analyze triggered on new conversation "
                        f"(student={user_id}, trainer={trainer_id}, conv={conversation_id})")

            self.trigger_analysis(user_id, trainer_id, conversation_id)

        except Exception as e:
            log("error", f"Memory plugin: error in _on_conversation_created: {e}", stacktrace=True)

    # ─────────────────────────────────────────────────────────────────────
    # Data helpers
    # ─────────────────────────────────────────────────────────────────────

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
            log("error", f"Failed to save memory: {e}", stacktrace=True)
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

    async def _analyze_with_llm(
        self,
        trainer_id: str,
        student_id: str,
        old_memory: str,
        new_messages: List[Dict],
        program: str = "",
        rubrics: Dict = None,
    ) -> Optional[Tuple[str, str]]:
        """Use LLM to analyze conversations and update memory."""
        import yaml as _yaml

        conversations_text = ""
        for msg in new_messages:
            role_symbol = "👤 Student" if msg['role'] == 'user' else "🤖 Assistant"
            conversations_text += f"{role_symbol} ({msg['timestamp']}): {msg['content']}\n\n"

        rubrics_text = ""
        if rubrics:
            rubrics_text = _yaml.dump(rubrics, allow_unicode=True, default_flow_style=False)

        system_prompt = get_prompt('memory.analysis_system')
        user_prompt = get_prompt('memory.analysis_user').format(
            training_program=program or get_prompt('memory.empty_program'),
            rubrics=rubrics_text or get_prompt('memory.empty_rubrics'),
            old_memory=old_memory or get_prompt('memory.empty_memory'),
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
                {"role": "user", "content": user_prompt}
            ]

            response = await self.llm_manager.internal_response(
                llm_id if llm_id != "unknown" else None,
                messages
            )

            if response and not response.startswith("Error"):
                return response.strip(), source
            else:
                log("error", f"LLM analysis failed: {response}")
                return None, source
        except Exception as e:
            log("error", f"Error during LLM analysis: {e}", stacktrace=True)
            return None, source

    async def refresh_memory(self, trainer_id: str, student_id: str) -> bool:
        """
        Refresh memory by analyzing new conversations since last analysis.

        DATA LAYER — callable headless.
        """
        log("info", f"Memory refresh started (plugin={self.id}, trainer={trainer_id}, student={student_id})")

        last_analyzed = self._get_last_analyzed(student_id, trainer_id)
        log("info", f"Memory refresh last_analyzed={last_analyzed}")

        new_messages = self._get_new_conversations(student_id, last_analyzed)
        log("info", f"Memory refresh fetched {len(new_messages)} new messages")

        if not new_messages:
            log("info", f"No new messages for student {student_id} since last analysis")
            return True

        old_memory = self._get_current_memory(student_id, trainer_id)
        log("info", f"Memory refresh old_memory_present={bool(old_memory)}")

        # Fetch formation material for this trainer
        program = ""
        rubrics = {}
        if self.trainer_manager is None:
            log("warning", "Memory plugin: trainer_manager is None; using empty formation material")
        else:
            try:
                program = self.trainer_manager.get_program(trainer_id)
                rubrics = self.trainer_manager.get_rubrics(trainer_id)
            except Exception as e:
                log("warning", f"Memory plugin: could not load formation material: {e}")

        log("info", "Memory refresh calling _analyze_with_llm")
        result = await self._analyze_with_llm(
            trainer_id, student_id, old_memory, new_messages,
            program=program,
            rubrics=rubrics,
        )

        if result:
            new_memory, source = result
            log("info", f"Memory refresh analysis done (source={source}, chars={len(new_memory)})")

            metadata = {
                'messages_analyzed': len(new_messages),
                'conversations': len(set(m['conversation_id'] for m in new_messages)),
                'analysis_timestamp': datetime.utcnow().isoformat(),
                'last_analyzed': last_analyzed.isoformat() if last_analyzed else None,
                'first_message': new_messages[0]['timestamp'] if new_messages else None,
                'last_message': new_messages[-1]['timestamp'] if new_messages else None
            }

            log("info", "Memory refresh calling _save_memory")
            saved = self._save_memory(student_id, trainer_id, new_memory, source, metadata)
            log("info", f"Memory refresh save result={saved}")
            return saved

        log("warning", "Memory refresh analysis returned no result")
        return False

    def get_memory_context(self, user_id: str, messages: List[Dict]) -> Optional[Tuple[str, str, str]]:
        """
        LLM context callback — inject student memory into conversations.

        DATA LAYER: uses self.user_manager and self.db only.
        Returns: (context, role, position)
        """
        log("debug", f"[MEMORY_CALLBACK] ===== START get_memory_context for user {user_id} =====")

        # Vérification 1: user_manager disponible
        if self.user_manager is None:
            error_msg = "Memory plugin: user_manager is None in get_memory_context"
            log("error", error_msg)
            raise RuntimeError(error_msg)

        # Vérification 2: trouver trainer_id
        trainer_id = self._get_student_trainer_id(user_id)
        log("debug", f"[MEMORY_CALLBACK] Student {user_id} -> trainer_id: {trainer_id}")

        if not trainer_id:
            log("debug", f"[MEMORY_CALLBACK] User {user_id} is not a student (no parent_id), skipping")
            return None

        # Vérification 3: trainer_manager disponible
        if self.trainer_manager is None:
            error_msg = f"Memory plugin: trainer_manager is None in get_memory_context (trainer {trainer_id})"
            log("error", error_msg)
            raise RuntimeError(error_msg)

        # Vérification 4: état d'activation en mémoire
        memory_active = self.is_active()
        log("debug", f"[MEMORY_CALLBACK] Plugin memory.is_active() = {memory_active}")

        if not memory_active:
            log("debug", f"[MEMORY_CALLBACK] Plugin memory is not active in memory, skipping")
            return None

        # Vérification 5: état d'activation en base de données
        db_active = self.trainer_manager.is_plugin_active(trainer_id, self.id)
        log("debug", f"[MEMORY_CALLBACK] Database is_plugin_active({trainer_id}, {self.id}) = {db_active}")

        if not db_active:
            error_msg = (f"MEMORY INCONSISTENCY: Plugin memory active in memory ({memory_active}) "
                        f"but inactive in database ({db_active}) for trainer {trainer_id}")
            log("error", error_msg)
            # Option 1: Lever une exception pour détecter immédiatement
            raise RuntimeError(error_msg)
            # Option 2 (plus soft): self._mark_inactive() et return None
            # self._mark_inactive()
            # return None

        # Vérification 6: récupérer la mémoire
        memory = self._get_current_memory(user_id, trainer_id)
        log("debug", f"[MEMORY_CALLBACK] Memory content retrieved: {bool(memory)}")

        if not memory:
            log("debug", f"[MEMORY_CALLBACK] No memory found for student {user_id}")
            return None

        # Vérification 7: longueur de la mémoire
        if len(memory) < 10:
            log("warning", f"[MEMORY_CALLBACK] Memory content suspiciously short ({len(memory)} chars): '{memory[:50]}...'")

        # Vérification 8: obtenir le prompt
        try:
            context_prompt = get_prompt('memory.context_injection')
            log("debug", f"[MEMORY_CALLBACK] Got context prompt: {bool(context_prompt)}")
        except Exception as e:
            error_msg = f"Memory plugin: failed to get context_injection prompt: {e}"
            log("error", error_msg)
            raise RuntimeError(error_msg)

        # Vérification 9: formater le contexte
        try:
            context = context_prompt.format(memory=memory)
            log("debug", f"[MEMORY_CALLBACK] Formatted context ({len(context)} chars)")
        except Exception as e:
            error_msg = f"Memory plugin: failed to format context with memory: {e}"
            log("error", error_msg)
            raise RuntimeError(error_msg)

        # Vérification 10: snapshot final
        result = (context, "system", "top")
        log("debug", f"[MEMORY_CALLBACK] SUCCESS: Returning context for student {user_id}")
        log("debug", f"[MEMORY_CALLBACK] ===== END get_memory_context =====")

        return result

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
        Also called internally via trigger_analysis().
        DATA LAYER — no st.* here.
        """
        from shared.common import record_plugin_event

        log("debug", f"[MEMORY_ANALYSIS] ===== START trigger_analysis for student {context.student_id} =====")

        # Vérification 1: context valide
        if not context.student_id:
            error_msg = "Memory analysis triggered without student_id"
            log("error", error_msg)
            raise ValueError(error_msg)

        if not context.trainer_id:
            error_msg = "Memory analysis triggered without trainer_id"
            log("error", error_msg)
            raise ValueError(error_msg)

        # Vérification 2: plugin actif en mémoire
        if not self.is_active():
            error_msg = f"Memory analysis triggered but plugin is not active in memory (trainer {context.trainer_id})"
            log("error", error_msg)
            raise RuntimeError(error_msg)

        # Vérification 3: plugin actif en base
        if self.trainer_manager and not self.trainer_manager.is_plugin_active(context.trainer_id, self.id):
            error_msg = (f"MEMORY INCONSISTENCY: Memory analysis triggered but plugin is not active in database "
                        f"for trainer {context.trainer_id}")
            log("error", error_msg)
            raise RuntimeError(error_msg)

        # Vérification 4: vérifier l'état avant analyse
        old_memory = self._get_current_memory(context.student_id, context.trainer_id)
        log("debug", f"[MEMORY_ANALYSIS] Current memory exists: {bool(old_memory)}")
        if old_memory:
            log("debug", f"[MEMORY_ANALYSIS] Current memory length: {len(old_memory)} chars")

        # Exécuter l'analyse
        log("debug", f"[MEMORY_ANALYSIS] Calling refresh_memory...")
        success = run_async_safely(
            self.refresh_memory(context.trainer_id, context.student_id)
        )
        log("debug", f"[MEMORY_ANALYSIS] refresh_memory completed with success={success}")

        # Vérification 5: vérifier l'état après analyse
        new_memory = self._get_memory_with_metadata(context.student_id, context.trainer_id)
        log("debug", f"[MEMORY_ANALYSIS] After analysis - memory exists: {bool(new_memory)}")
        if new_memory:
            log("debug", f"[MEMORY_ANALYSIS] New memory version: {new_memory.get('version')}")
            log("debug", f"[MEMORY_ANALYSIS] New memory length: {len(new_memory.get('content', ''))} chars")
            log("debug", f"[MEMORY_ANALYSIS] New memory source: {new_memory.get('source')}")
        else:
            log("warning", f"[MEMORY_ANALYSIS] No memory found after analysis!")

        record_plugin_event("memory", "analysis_complete", {
            "success": success,
            "version": new_memory.get("version") if new_memory else None,
        })

        result = {
            "success": success,
            "plugin": "memory",
            "version": new_memory.get("version") if new_memory else None,
            "memory_content": new_memory.get("content", "") if new_memory else "",
        }

        log("debug", f"[MEMORY_ANALYSIS] ===== END trigger_analysis =====")
        return result

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
