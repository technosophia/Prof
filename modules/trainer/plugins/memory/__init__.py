"""
Memory Plugin for Trainer Module.
Maintains pedagogical memory of student conversations for personalized teaching.
"""

from typing import List, Dict, Any, Optional, Callable, Tuple
import streamlit as st
from datetime import datetime, timedelta
import uuid
import asyncio

from sqlalchemy import Column, String, Text, DateTime, JSON, Integer, and_, desc
from shared.common import (
    Base, get_db_manager, get_prompt, register_llm_context_callback,
    log, _, get_conversation_manager, get_llm_manager, get_current_llm_id
)
from modules.trainer.plugin_base import TrainerPlugin, PluginManifest
from modules.trainer.manager import get_trainer_manager
from modules.trainer.training_context import get_training_context


# Database model (will be created by plugin initialization)
class StudentMemory(Base):
    """Store pedagogical memory for each student with version history."""
    __tablename__ = 'trainer_student_memories'
    __table_args__ = {'extend_existing': True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    trainer_id = Column(String, nullable=False, index=True)
    content = Column(Text, default="")
    version = Column(Integer, default=1)
    is_current = Column(Integer, default=1)
    source = Column(String, nullable=False)  # 'auto' or 'manual' or 'llm:llm_id'
    last_analyzed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    memory_metadata = Column(JSON, default={})


class MemoryPlugin(TrainerPlugin):
    """Plugin that maintains pedagogical memory of student conversations."""

    def initialize(self) -> bool:
        """Initialize the plugin and ensure database tables exist."""
        try:
            db = get_db_manager()
            if db.is_initialized() and not db._in_memory:
                Base.metadata.create_all(db._engine, tables=[StudentMemory.__table__], checkfirst=True)
                log("info", "StudentMemory table created/verified")

            # Register context callback for memory injection
            register_llm_context_callback(self.get_memory_context)
            return True
        except Exception as e:
            log("error", f"Failed to initialize memory plugin: {e}")
            return False

    def on_activate(self, trainer_id: str) -> None:
        """
        Called when the memory plugin is activated for a trainer.
        Performs initial setup and logs activation.
        """
        log("info", f"Memory plugin activated for trainer {trainer_id}")

        # Optional: Initialize default empty memories for all existing students
        try:
            trainer_manager = get_trainer_manager()
            students = trainer_manager.get_trainer_students(trainer_id)

            for student in students:
                # Check if memory already exists
                existing = self._get_current_memory(student['id'], trainer_id)
                if existing is None:
                    # Create initial empty memory
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
        """
        Called when the memory plugin is deactivated for a trainer.
        Performs cleanup and logs deactivation.
        """
        log("info", f"Memory plugin deactivated for trainer {trainer_id}")

    # ============= DATABASE HELPERS =============

    def _get_current_memory(self, student_id: str, trainer_id: str) -> Optional[str]:
        """Get the current memory for a student."""
        db = get_db_manager()
        with db.get_session() as session:
            memory = session.query(StudentMemory).filter_by(
                user_id=student_id,
                trainer_id=trainer_id,
                is_current=1
            ).first()
            return memory.content if memory else None

    def _get_memory_with_metadata(self, student_id: str, trainer_id: str) -> Optional[Dict]:
        """Get current memory with all metadata."""
        db = get_db_manager()
        with db.get_session() as session:
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
        """Get number of historical versions."""
        db = get_db_manager()
        with db.get_session() as session:
            total = session.query(StudentMemory).filter_by(
                user_id=student_id,
                trainer_id=trainer_id
            ).count()
            return max(0, total - 1)  # Subtract current version

    def _get_last_analyzed(self, student_id: str, trainer_id: str) -> Optional[datetime]:
        """Get the timestamp of the last conversation analysis."""
        db = get_db_manager()
        with db.get_session() as session:
            memory = session.query(StudentMemory).filter_by(
                user_id=student_id,
                trainer_id=trainer_id,
                is_current=1
            ).first()
            return memory.last_analyzed_at if memory else None

    def _save_memory(self, student_id: str, trainer_id: str, content: str,
                     source: str, metadata: Dict = None) -> bool:
        """Save a new memory version."""
        try:
            db = get_db_manager()
            with db.get_session() as session:
                # Get current memory
                current = session.query(StudentMemory).filter_by(
                    user_id=student_id,
                    trainer_id=trainer_id,
                    is_current=1
                ).first()

                # If content hasn't changed, don't create new version
                if current and current.content == content:
                    return True

                # Mark current as historical
                if current:
                    current.is_current = 0
                    session.add(current)

                # Get next version number
                max_version = session.query(StudentMemory.version).filter_by(
                    user_id=student_id,
                    trainer_id=trainer_id
                ).order_by(StudentMemory.version.desc()).first()
                next_version = (max_version[0] + 1) if max_version else 1

                # Create new memory
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

    # ============= CONVERSATION ANALYSIS =============

    def _get_new_conversations(self, student_id: str, since: Optional[datetime]) -> List[Dict]:
        """Get all conversations for a student since a given timestamp."""
        conv_manager = get_conversation_manager()
        conversations = conv_manager.get_user_conversations(student_id)
        new_messages = []

        for conv in conversations:
            full_conv = conv_manager.get_conversation(conv["id"])
            if not full_conv or not full_conv.messages:
                continue

            for msg in full_conv.messages:
                # Only consider user and assistant messages
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

        # Sort by timestamp
        new_messages.sort(key=lambda x: x.get('timestamp', ''))
        return new_messages

    async def _analyze_with_llm(self, trainer_id: str, student_id: str,
                                old_memory: str, new_messages: List[Dict]) -> Optional[str]:
        """Use LLM to analyze conversations and update memory."""
        # Get training context for the program
        training_context = get_training_context(trainer_id)
        training_program = training_context.training_program

        # Format conversations for prompt
        conversations_text = ""
        for msg in new_messages:
            role_symbol = "👤 Student" if msg['role'] == 'user' else "🤖 Assistant"
            conversations_text += f"{role_symbol} ({msg['timestamp']}): {msg['content']}\n\n"

        # Get prompts (no fallback - will raise KeyError if missing)
        system_prompt = get_prompt('trainer.plugins.memory.analysis_system')
        user_prompt = get_prompt('trainer.plugins.memory.analysis_user').format(
            training_program=training_program,
            old_memory=old_memory or get_prompt('trainer.plugins.memory.empty_memory'),
            conversations=conversations_text
        )

        # Get current LLM ID for source tracking
        try:
            llm_id = get_current_llm_id()
            source = f"llm:{llm_id}"
        except ValueError:
            source = "auto"
            llm_id = "unknown"

        # Generate new memory
        try:
            llm_manager = get_llm_manager()
            # Prepare messages for LLM
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

            response = await llm_manager.generate_response(
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
        This is the main method called by the teacher.
        """
        # Get last analysis timestamp
        last_analyzed = self._get_last_analyzed(student_id, trainer_id)

        # Get new messages
        new_messages = self._get_new_conversations(student_id, last_analyzed)

        if not new_messages:
            log("info", f"No new messages for student {student_id} since last analysis")
            return True

        # Get old memory
        old_memory = self._get_current_memory(student_id, trainer_id)

        # Analyze with LLM
        result = await self._analyze_with_llm(trainer_id, student_id, old_memory, new_messages)

        if result:
            new_memory, source = result

            # Create metadata with stats
            metadata = {
                'messages_analyzed': len(new_messages),
                'conversations': len(set(m['conversation_id'] for m in new_messages)),
                'analysis_timestamp': datetime.utcnow().isoformat(),
                'last_analyzed': last_analyzed.isoformat() if last_analyzed else None,
                'first_message': new_messages[0]['timestamp'] if new_messages else None,
                'last_message': new_messages[-1]['timestamp'] if new_messages else None
            }

            # Save new memory
            return self._save_memory(student_id, trainer_id, new_memory, source, metadata)

        return False

    # ============= LLM CONTEXT INJECTION =============

    def get_memory_context(self, user_id: str, messages: List[Dict]) -> Optional[Tuple[str, str, str]]:
        """
        Context callback to inject student memory into conversations.
        Returns: (context, role, position)
        """
        # Get student's trainer
        from shared.common import get_user_manager
        user_manager = get_user_manager()
        user = user_manager.get_user(user_id)

        if not user or not user.get('parent_id'):
            return None

        trainer_id = user['parent_id']
        memory = self._get_current_memory(user_id, trainer_id)

        if not memory:
            return None

        # Get the appropriate prompt (no fallback - will raise KeyError if missing)
        context_prompt = get_prompt('trainer.plugins.memory.context_injection')
        context = context_prompt.format(memory=memory)

        # Return as system message at the top of context
        return (context, "system", "top")

    # ============= UI RENDERING =============

    def render_student_widgets(self, trainer_id: str, student: Dict) -> List[Callable]:
        """Render memory in teacher's student detail view."""
        def render_teacher_memory():
            student_id = student['id']
            student_name = student.get('name', student_id)

            st.markdown("### 🧠 " + _("trainer_plugin_memory.pedagogical_memory"))

            # Get current memory and stats
            memory_data = self._get_memory_with_metadata(student_id, trainer_id)
            version_count = self._get_version_count(student_id, trainer_id)

            # Header with stats
            col1, col2, col3 = st.columns([2, 1, 1])
            with col1:
                if memory_data:
                    last_updated = memory_data['updated_at'].strftime('%Y-%m-%d %H:%M')
                    st.caption(_("trainer_plugin_memory.last_updated").format(time=last_updated))
            with col2:
                if version_count > 0:
                    st.caption(f"📚 {version_count} " + _("trainer_plugin_memory.older_versions"))
            with col3:
                if memory_data and memory_data['source'].startswith('llm:'):
                    llm_id = memory_data['source'].split(':')[1]
                    st.caption(f"🤖 {llm_id}")

            # Display current memory
            if memory_data and memory_data['content']:
                st.markdown("**" + _("trainer_plugin_memory.current_memory") + "**")
                st.info(memory_data['content'])

                # Show metadata if available
                if memory_data['metadata']:
                    with st.expander(_("trainer_plugin_memory.analysis_details")):
                        meta = memory_data['metadata']
                        st.caption(f"📊 {_('trainer_plugin_memory.messages_analyzed')}: {meta.get('messages_analyzed', 0)}")
                        st.caption(f"💬 {_('trainer_plugin_memory.conversations')}: {meta.get('conversations', 0)}")
                        if meta.get('first_message') and meta.get('last_message'):
                            st.caption(f"📅 {_('trainer_plugin_memory.period')}: {meta['first_message'][:10]} → {meta['last_message'][:10]}")
            else:
                st.info(_("trainer_plugin_memory.no_memory_yet"))

            # Action buttons
            col1, col2 = st.columns(2)
            with col1:
                if st.button(_("trainer_plugin_memory.refresh_with_llm"),
                            key=f"refresh_memory_{student_id}",
                            use_container_width=True):
                    with st.spinner(_("trainer_plugin_memory.analyzing_conversations")):
                        # Run async refresh in sync context
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        success = loop.run_until_complete(
                            self.refresh_memory(trainer_id, student_id)
                        )
                        loop.close()

                        if success:
                            st.success(_("trainer_plugin_memory.memory_updated"))
                            st.rerun()
                        else:
                            st.error(_("trainer_plugin_memory.failed_to_update"))

            with col2:
                if st.button(_("trainer_plugin_memory.edit_manually"),
                            key=f"edit_memory_{student_id}",
                            use_container_width=True):
                    st.session_state[f"editing_memory_{student_id}"] = True

            # Manual editing form
            if st.session_state.get(f"editing_memory_{student_id}", False):
                with st.form(key=f"manual_memory_form_{student_id}"):
                    st.markdown("**" + _("trainer_plugin_memory.edit_memory") + "**")

                    new_memory = st.text_area(
                        _("trainer_plugin_memory.memory_content"),
                        value=memory_data['content'] if memory_data else "",
                        height=200
                    )

                    col1, col2 = st.columns(2)
                    with col1:
                        if st.form_submit_button(_("trainer_plugin_memory.save")):
                            if self._save_memory(student_id, trainer_id, new_memory, "manual"):
                                st.success(_("trainer_plugin_memory.memory_saved"))
                                st.session_state[f"editing_memory_{student_id}"] = False
                                st.rerun()
                    with col2:
                        if st.form_submit_button(_("trainer_plugin_memory.cancel")):
                            st.session_state[f"editing_memory_{student_id}"] = False
                            st.rerun()

        return [render_teacher_memory]

    def render_dashboard_widgets(self, trainer_id: str, students: List[Dict]) -> List[Callable]:
        """Add memory overview to dashboard."""
        def render_memory_overview():
            st.markdown("---")
            st.subheader("🧠 " + _("trainer_plugin_memory.memory_overview"))

            # Quick refresh all button
            if st.button(_("trainer_plugin_memory.refresh_all_memories"),
                        key="refresh_all_memories",
                        use_container_width=True):
                with st.spinner(_("trainer_plugin_memory.refreshing_all")):
                    # This would be async in production - simplified for demo
                    st.info(_("trainer_plugin_memory.refresh_all_placeholder"))

            # Show memory status for each student
            for student in students[:5]:  # Limit to 5 for dashboard
                student_id = student['id']
                student_name = student.get('name', student_id)

                memory_data = self._get_memory_with_metadata(student_id, trainer_id)
                version_count = self._get_version_count(student_id, trainer_id)

                with st.expander(f"{student_name}", expanded=False):
                    col1, col2 = st.columns([3, 1])

                    with col1:
                        if memory_data and memory_data['content']:
                            preview = memory_data['content'][:150] + "..."
                            st.markdown(preview)
                        else:
                            st.caption(_("trainer_plugin_memory.no_memory"))

                    with col2:
                        if memory_data:
                            st.caption(f"📚 v{memory_data['version']}")
                            if version_count > 0:
                                st.caption(f"📜 +{version_count} " + _("trainer_plugin_memory.older"))

                            # Quick refresh button for this student
                            if st.button(_("trainer_plugin_memory.refresh"),
                                        key=f"dash_refresh_{student_id}"):
                                # Simplified - would be async
                                st.info(_("trainer_plugin_memory.refresh_triggered"))

        return [render_memory_overview]

    # ============= EXPORT/IMPORT =============

    def export_config(self, trainer_id: str) -> Optional[Dict]:
        """Export current memories for all students."""
        trainer_manager = get_trainer_manager()
        students = trainer_manager.get_trainer_students(trainer_id)

        memories = {}
        for student in students:
            memory_data = self._get_memory_with_metadata(student['id'], trainer_id)
            if memory_data:
                memories[student['id']] = {
                    'student_name': student.get('name', student['id']),
                    'content': memory_data['content'],
                    'version': memory_data['version'],
                    'source': memory_data['source'],
                    'last_analyzed_at': memory_data['last_analyzed_at'].isoformat() if memory_data['last_analyzed_at'] else None,
                    'updated_at': memory_data['updated_at'].isoformat(),
                    'metadata': memory_data['metadata']
                }

        return {'student_memories': memories} if memories else None

    def import_config(self, trainer_id: str, config: Dict) -> bool:
        """Import memories from configuration."""
        memories = config.get('student_memories', {})

        success = True
        for student_id, memory_data in memories.items():
            content = memory_data.get('content', '')
            source = memory_data.get('source', 'import')
            if content:
                if not self._save_memory(student_id, trainer_id, content, source):
                    success = False

        return success

    def export_history(self, trainer_id: str, student_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Export all memory updates as events."""
        db = get_db_manager()
        events = []

        with db.get_session() as session:
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

                # Add metadata if present
                if memory.memory_metadata:
                    event['metadata'] = memory.memory_metadata

                # Mark current version
                if memory.is_current:
                    event['is_current'] = True

                events.append(event)

        return events

    def import_history(self, trainer_id: str, events: List[Dict[str, Any]],
                      student_info: Dict = None) -> bool:
        """Import memory history events."""
        db = get_db_manager()

        try:
            with db.get_session() as session:
                memory_events = [e for e in events if e.get('plugin_id') == self.id]

                # Group by student
                student_events = {}
                for event in memory_events:
                    student_id = event.get('student_id')
                    if not student_id:
                        continue

                    if student_id not in student_events:
                        student_events[student_id] = []
                    student_events[student_id].append(event)

                # Import each student's memories
                for student_id, evts in student_events.items():
                    # Sort by timestamp
                    evts.sort(key=lambda x: x.get('timestamp', ''))

                    # Mark all existing as historical
                    existing = session.query(StudentMemory).filter_by(
                        user_id=student_id,
                        trainer_id=trainer_id
                    ).all()
                    for mem in existing:
                        mem.is_current = 0

                    # Recreate all versions
                    for event in evts:
                        timestamp = None
                        try:
                            if event.get('timestamp'):
                                timestamp = datetime.fromisoformat(event['timestamp'].replace('Z', '+00:00'))
                        except:
                            timestamp = datetime.utcnow()

                        memory = StudentMemory(
                            id=event.get('memory_id', str(uuid.uuid4())),
                            user_id=student_id,
                            trainer_id=trainer_id,
                            content=event.get('content', ''),
                            version=event.get('version', 1),
                            is_current=1 if event.get('is_current', False) else 0,
                            source=event.get('source', 'import'),
                            created_at=timestamp,
                            updated_at=timestamp,
                            memory_metadata=event.get('metadata', {})
                        )
                        session.add(memory)

                    # Ensure single current
                    current_ones = session.query(StudentMemory).filter_by(
                        user_id=student_id,
                        trainer_id=trainer_id,
                        is_current=1
                    ).all()

                    if len(current_ones) > 1:
                        current_ones.sort(key=lambda x: x.updated_at or datetime.min, reverse=True)
                        for i, mem in enumerate(current_ones):
                            if i == 0:
                                continue
                            mem.is_current = 0

                session.commit()
                return True

        except Exception as e:
            log("error", f"Failed to import memory history: {e}", exc_info=True)
            return False

    def get_admin_tabs(self, trainer_id: str) -> List[Tuple[str, Callable]]:
        """Add memory history viewer."""
        def render_history_viewer():
            st.subheader("📜 " + _("trainer_plugin_memory.memory_history"))

            trainer_manager = get_trainer_manager()
            students = trainer_manager.get_trainer_students(trainer_id)

            if not students:
                st.info(_("No students available."))
                return

            # Student selector
            student_options = {student['id']: student.get('name', 'Unknown') for student in students}
            student_options['all'] = "All Students"

            selected = st.selectbox(
                _("Select Student"),
                options=list(student_options.keys()),
                format_func=lambda x: student_options[x],
                key="memory_history_select"
            )

            student_id = None if selected == 'all' else selected
            events = self.export_history(trainer_id, student_id)

            if not events:
                st.info(_("No memory history available."))
                return

            # Display timeline
            for event in events:
                with st.container():
                    cols = st.columns([2, 1, 1, 3])

                    with cols[0]:
                        try:
                            ts = datetime.fromisoformat(event['timestamp'].replace('Z', '+00:00'))
                            st.write(ts.strftime('%Y-%m-%d %H:%M'))
                        except:
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

        return [(_("Memory History"), render_history_viewer)]


# Plugin entry point
plugin = MemoryPlugin
