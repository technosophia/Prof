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
import streamlit as st
from datetime import datetime
import uuid
import asyncio

from sqlalchemy import Column, String, Text, DateTime, JSON, Integer

from shared.common import get_prompt, register_llm_context_callback, get_current_llm_id
from modules.trainer.plugin_base import TrainerPlugin, PluginManifest
from modules.trainer.manager import get_trainer_manager

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


class MemoryPlugin(TrainerPlugin):
    """Plugin that maintains pedagogical memory of student conversations."""

    # ─────────────────────────────────────────────────────────────────────
    # Lifecycle — DATA LAYER
    # ─────────────────────────────────────────────────────────────────────

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
            trainer_manager = get_trainer_manager()
            students = trainer_manager.get_trainer_students(trainer_id)

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
    # Data helpers — DATA LAYER (use self.db only)
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
            log("error", f"Failed to save memory: {e}", exc_info=True)
            return False

    def _get_student_trainer_id(self, student_id: str) -> Optional[str]:
        """Return the trainer_id (parent_id) for a student. DATA LAYER helper."""
        user = self.user_manager.get_user(student_id)
        if not user:
            return None
        return user.get('parent_id')

    # ─────────────────────────────────────────────────────────────────────
    # Conversation analysis — DATA LAYER
    # ─────────────────────────────────────────────────────────────────────

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

    async def _analyze_with_llm(self, trainer_id: str, student_id: str,
                                 old_memory: str, new_messages: List[Dict]) -> Optional[Tuple[str, str]]:
        """Use LLM to analyze conversations and update memory."""
        training_program = get_prompt('trainer.teacher.training_program')

        conversations_text = ""
        for msg in new_messages:
            role_symbol = "👤 Student" if msg['role'] == 'user' else "🤖 Assistant"
            conversations_text += f"{role_symbol} ({msg['timestamp']}): {msg['content']}\n\n"

        system_prompt = get_prompt('trainer.plugins.memory.analysis_system')
        user_prompt = get_prompt('trainer.plugins.memory.analysis_user').format(
            training_program=training_program,
            old_memory=old_memory or get_prompt('trainer.plugins.memory.empty_memory'),
            conversations=conversations_text
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
            log("error", f"Error during LLM analysis: {e}", exc_info=True)
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

        log("info", "Memory refresh calling _analyze_with_llm")
        result = await self._analyze_with_llm(trainer_id, student_id, old_memory, new_messages)

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

    # ─────────────────────────────────────────────────────────────────────
    # Context injection — DATA LAYER
    # ─────────────────────────────────────────────────────────────────────

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

    # ─────────────────────────────────────────────────────────────────────
    # Driver action handler — DATA LAYER
    # ─────────────────────────────────────────────────────────────────────

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

    # ─────────────────────────────────────────────────────────────────────
    # Export / import — DATA LAYER
    # ─────────────────────────────────────────────────────────────────────

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

    # ─────────────────────────────────────────────────────────────────────
    # UI LAYER — render methods
    # Rules: call self.<data_method>() for data; use st.* freely.
    # Future split: self.xxx() → self._logic.xxx(). No logic changes needed.
    # ─────────────────────────────────────────────────────────────────────

    def render_student_widgets(self, trainer_id: str, student: Dict) -> List[Callable]:
        """Render memory panel in teacher's student detail view."""
        def render_teacher_memory():
            student_id = student['id']

            st.markdown("### 🧠 Pedagogical Memory")

            # DATA: all via data methods
            memory_data = self._get_memory_with_metadata(student_id, trainer_id)
            version_count = self._get_version_count(student_id, trainer_id)

            col1, col2, col3 = st.columns([2, 1, 1])
            with col1:
                if memory_data:
                    last_updated = memory_data['updated_at'].strftime('%Y-%m-%d %H:%M')
                    st.caption(f"Last updated: {last_updated}")
            with col2:
                if version_count > 0:
                    st.caption(f"📚 {version_count} older versions")
            with col3:
                if memory_data and memory_data['source'].startswith('llm:'):
                    llm_id = memory_data['source'].split(':')[1]
                    st.caption(f"🤖 {llm_id}")

            if memory_data and memory_data['content']:
                st.markdown("**Current Memory**")
                st.info(memory_data['content'])

                if memory_data['metadata']:
                    with st.expander("Analysis Details"):
                        meta = memory_data['metadata']
                        st.caption(f"📊 Messages analyzed: {meta.get('messages_analyzed', 0)}")
                        st.caption(f"💬 Conversations: {meta.get('conversations', 0)}")
                        if meta.get('first_message') and meta.get('last_message'):
                            st.caption(f"📅 Period: {meta['first_message'][:10]} → {meta['last_message'][:10]}")
            else:
                st.info("No pedagogical memory yet. Click 'Refresh with LLM' to analyze conversations.")

            col1, col2 = st.columns(2)
            with col1:
                if st.button("🔄 Refresh with LLM",
                             key=f"refresh_memory_{student_id}",
                             use_container_width=True):
                    log("info", f"Refresh button clicked (plugin={self.id}, trainer={trainer_id}, student={student_id})")
                    with st.spinner("Analyzing conversations..."):
                        # DATA: calls data method
                        success = asyncio.run(self.refresh_memory(trainer_id, student_id))

                        if success:
                            log("info", f"Refresh succeeded (plugin={self.id}, student={student_id})")
                            st.success("✅ Memory updated successfully!")
                            st.rerun()
                        else:
                            log("error", f"Refresh failed (plugin={self.id}, student={student_id})")
                            st.error("❌ Failed to update memory")

            with col2:
                if st.button("✏️ Edit Manually",
                             key=f"edit_memory_{student_id}",
                             use_container_width=True):
                    st.session_state[f"editing_memory_{student_id}"] = True

            if st.session_state.get(f"editing_memory_{student_id}", False):
                with st.form(key=f"manual_memory_form_{student_id}"):
                    st.markdown("**Edit Pedagogical Memory**")

                    new_memory = st.text_area(
                        "Memory content",
                        value=memory_data['content'] if memory_data else "",
                        height=200
                    )

                    col1, col2 = st.columns(2)
                    with col1:
                        if st.form_submit_button("💾 Save"):
                            # DATA: calls data method
                            if self._save_memory(student_id, trainer_id, new_memory, "manual"):
                                st.success("✅ Memory saved!")
                                st.session_state[f"editing_memory_{student_id}"] = False
                                st.rerun()
                    with col2:
                        if st.form_submit_button("Cancel"):
                            st.session_state[f"editing_memory_{student_id}"] = False
                            st.rerun()

        return [render_teacher_memory]

    def render_dashboard_widgets(self, trainer_id: str, students: List[Dict]) -> List[Callable]:
        """Add memory overview to dashboard."""
        def render_memory_overview():
            st.markdown("---")
            st.subheader("🧠 Memory Overview")

            if st.button("🔄 Refresh All Memories",
                         key=f"{self.id}_refresh_all_memories",
                         use_container_width=True):
                with st.spinner("Refreshing all memories..."):
                    st.info("This would refresh all memories asynchronously in production")

            for student in students[:5]:
                student_id = student['id']
                student_name = student.get('name', student_id)

                # DATA: calls data methods
                memory_data = self._get_memory_with_metadata(student_id, trainer_id)
                version_count = self._get_version_count(student_id, trainer_id)

                with st.expander(f"{student_name}", expanded=False):
                    col1, col2 = st.columns([3, 1])

                    with col1:
                        if memory_data and memory_data['content']:
                            preview = memory_data['content'][:150] + "..."
                            st.markdown(preview)
                        else:
                            st.caption("No memory")

                    with col2:
                        if memory_data:
                            st.caption(f"📚 v{memory_data['version']}")
                            if version_count > 0:
                                st.caption(f"📜 +{version_count} older")

                            if st.button("🔄 Refresh", key=f"dash_refresh_{student_id}"):
                                st.info("Refresh triggered (async in production)")

        return [render_memory_overview]

    def render_get_admin_tabs(self, trainer_id: str) -> List[Tuple[str, Callable]]:
        """Add memory history viewer tab."""
        def render_history_viewer():
            st.subheader("📜 Memory History")

            trainer_manager = get_trainer_manager()
            students = trainer_manager.get_trainer_students(trainer_id)

            if not students:
                st.info("No students available.")
                return

            student_options = {student['id']: student.get('name', 'Unknown') for student in students}
            student_options['all'] = "All Students"

            selected = st.selectbox(
                "Select Student",
                options=list(student_options.keys()),
                format_func=lambda x: student_options[x],
                key=f"{self.id}_memory_history_select"
            )

            student_id = None if selected == 'all' else selected
            # DATA: calls data method
            events = self.export_history(trainer_id, student_id)

            if not events:
                st.info("No memory history available.")
                return

            for event in events:
                with st.container():
                    cols = st.columns([2, 1, 1, 3])

                    with cols[0]:
                        try:
                            ts = datetime.fromisoformat(event['timestamp'].replace('Z', '+00:00'))
                            st.write(ts.strftime('%Y-%m-%d %H:%M'))
                        except Exception:
                            st.write(event['timestamp'])

                    with cols[1]:
                        source = event.get('source', 'unknown')
                        if source.startswith('llm:'):
                            st.write(f"🤖 {source.split(':')[1]}")
                        elif source == 'manual':
                            st.write("👤 Manual")
                        else:
                            st.write(source)

                    with cols[2]:
                        version = f"v{event.get('version', 1)}"
                        if event.get('is_current'):
                            version += " ✓"
                        st.write(version)

                    with cols[3]:
                        content = event.get('content', '')
                        preview = content[:50] + "..." if len(content) > 50 else content
                        st.caption(preview)

                st.divider()

        return [("Memory History", render_history_viewer)]


# Plugin entry point
plugin = MemoryPlugin
