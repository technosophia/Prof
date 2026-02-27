"""
Student Pad Plugin for Trainer Module.
Allows each student to have a personal note-taking pad with version history.
Visible in dashboard and exportable/importable.

Migration status: COMPLETE
  - initialize() calls self._resolve_services(services)
  - Added legacy fallback for when services=None
  - All data methods use self.db, self.user_manager, self.conversation_manager,
    self.llm_manager, self.config — no st_shared.cached imports elsewhere
  - All render methods call self.<data_method>() only — no db/cache access inline
  - When splitting into two classes: replace self.xxx() with self._logic.xxx()
    in every render method. No logic rewrite needed.
"""

from typing import List, Dict, Any, Optional, Callable, Tuple
import streamlit as st
from datetime import datetime
import uuid

from sqlalchemy import Column, String, Text, DateTime, JSON, Integer, and_

from core.logging import log
from core.database import Base
from shared.common import get_prompt, register_llm_context_callback
from modules.trainer.plugin_base import TrainerPlugin, PluginManifest


class StudentNote(Base):
    """Store notes/pad for each student with version history."""
    __tablename__ = 'trainer_student_notes'
    __table_args__ = {'extend_existing': True}

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), nullable=False, index=True)  # Student ID
    trainer_id = Column(String(36), nullable=False, index=True)  # Trainer/Master ID
    content = Column(Text, default="")
    plugin_id = Column(String(36), default="core")  # Which plugin owns this note
    version = Column(Integer, default=1)  # Version number
    is_current = Column(Integer, default=1)  # 1 for current version, 0 for history
    updated_at = Column(DateTime, default=datetime.utcnow)
    note_metadata = Column(JSON, default={})


class StudentPadPlugin(TrainerPlugin):
    """Plugin providing personal pads for students with version history."""

    # ─────────────────────────────────────────────────────────────────────
    # Lifecycle — DATA LAYER
    # ─────────────────────────────────────────────────────────────────────

    def initialize(self, services=None) -> bool:
        """Initialize the plugin, tables, and context callbacks."""
        try:
            self._resolve_services(services)

            # Ensure table exists - but don't try to create it in tests
            if self.db and self.db.is_initialized() and not self.db._in_memory:
                Base.metadata.create_all(
                    self.db._engine,
                    tables=[StudentNote.__table__],
                    checkfirst=True
                )
                log("info", "StudentNote table created/verified with version tracking")

            # Register context callbacks
            register_llm_context_callback(self.get_student_notes_context)
            register_llm_context_callback(self.get_teacher_notes_context)
            return True
        except Exception as e:
            log("error", f"Failed to initialize student_pad plugin: {e}", exc_info=True)
            return False

    def on_activate(self, trainer_id: str) -> None:
        """Called when plugin is activated for a trainer."""
        log("info", f"Student pad plugin activated for trainer {trainer_id}")

    def on_deactivate(self, trainer_id: str) -> None:
        """Called when plugin is deactivated for a trainer."""
        log("info", f"Student pad plugin deactivated for trainer {trainer_id}")

    # ─────────────────────────────────────────────────────────────────────
    # Data helpers — DATA LAYER (use self.service attributes only)
    # ─────────────────────────────────────────────────────────────────────

    def _get_student_note(self, student_id: str, trainer_id: str, plugin_id: str = None) -> str:
        """Get current student note directly from database."""
        if plugin_id is None:
            plugin_id = self.id

        with self.db.get_session() as session:
            note = session.query(StudentNote).filter_by(
                user_id=student_id,
                trainer_id=trainer_id,
                plugin_id=plugin_id,
                is_current=1
            ).first()
            return note.content if note else ""

    def _get_note_version_count(self, student_id: str, trainer_id: str, plugin_id: str = None) -> int:
        """Get the number of historical versions."""
        if plugin_id is None:
            plugin_id = self.id

        with self.db.get_session() as session:
            total_count = session.query(StudentNote).filter_by(
                user_id=student_id,
                trainer_id=trainer_id,
                plugin_id=plugin_id
            ).count()
            return max(0, total_count - 1)

    def _save_student_note(self, student_id: str, trainer_id: str, content: str, plugin_id: str = None) -> bool:
        """Save student note with version history."""
        if plugin_id is None:
            plugin_id = self.id

        try:
            with self.db.get_session() as session:
                current_note = session.query(StudentNote).filter_by(
                    user_id=student_id,
                    trainer_id=trainer_id,
                    plugin_id=plugin_id,
                    is_current=1
                ).first()

                # If content hasn't changed, don't create new version
                if current_note and current_note.content == content:
                    return True

                # Mark current note as historical if it exists
                if current_note:
                    current_note.is_current = 0
                    session.add(current_note)

                # Get the next version number
                max_version = session.query(StudentNote.version).filter_by(
                    user_id=student_id,
                    trainer_id=trainer_id,
                    plugin_id=plugin_id
                ).order_by(StudentNote.version.desc()).first()

                next_version = (max_version[0] + 1) if max_version else 1

                # Create new note as current version
                new_note = StudentNote(
                    user_id=student_id,
                    trainer_id=trainer_id,
                    content=content,
                    plugin_id=plugin_id,
                    version=next_version,
                    is_current=1,
                    updated_at=datetime.utcnow()
                )
                session.add(new_note)
                session.commit()
                return True
        except Exception as e:
            log("error", f"Failed to save student note: {e}", exc_info=True)
            return False

    def _ensure_single_current_note(self, session, student_id: str, trainer_id: str,
                                    plugin_id: str, note_events: List[Dict]):
        """Ensure exactly one note is marked as current after import."""
        current_notes = session.query(StudentNote).filter_by(
            user_id=student_id,
            trainer_id=trainer_id,
            plugin_id=plugin_id,
            is_current=1
        ).all()

        if len(current_notes) > 1:
            # If multiple current notes, keep the most recent one
            current_notes.sort(key=lambda x: x.updated_at or datetime.min, reverse=True)
            for i, note in enumerate(current_notes):
                if i == 0:
                    continue
                note.is_current = 0
        elif len(current_notes) == 0 and note_events:
            # If no current note, set the most recent as current
            most_recent = max(note_events, key=lambda x: x.get('timestamp', ''))
            note_id = most_recent.get('note_id')
            if note_id:
                note = session.query(StudentNote).filter_by(id=note_id).first()
                if note:
                    note.is_current = 1

    def _expand_minimal_event(self, event: Dict, student_info: Dict = None) -> Dict:
        """Expand a minimal event to full event data for import."""
        expanded = event.copy()

        if 'version' not in expanded:
            expanded['version'] = 1
        if 'is_current' not in expanded:
            expanded['is_current'] = False
        if 'metadata' not in expanded:
            expanded['metadata'] = {}

        if 'timestamp' in expanded:
            if 'created_at' not in expanded:
                expanded['created_at'] = expanded['timestamp']
            if 'updated_at' not in expanded:
                expanded['updated_at'] = expanded['timestamp']

        if student_info and expanded.get('student_id') in student_info:
            if 'student_name' not in expanded:
                expanded['student_name'] = student_info[expanded['student_id']]['name']

        return expanded

    # ─────────────────────────────────────────────────────────────────────
    # Context callbacks — DATA LAYER
    # ─────────────────────────────────────────────────────────────────────

    def get_student_notes_context(self, user_id: str, messages: List[Dict]) -> Optional[Tuple[str, str, str]]:
        """Context callback for student's personal notes."""
        if not self._is_active:
            return None

        user = self.user_manager.get_user(user_id)
        if not user or not user.get('parent_id'):
            return None

        trainer_id = user['parent_id']
        student_notes = self._get_student_note(user_id, trainer_id)

        if not student_notes:
            return None

        context_prompt = get_prompt('trainer.plugins.student_pad.student_notes_context',
                                   "Student's personal notes:\n{student_notes}")
        context = context_prompt.format(student_notes=student_notes)

        return (context, "system", "top")

    def get_teacher_notes_context(self, user_id: str, messages: List[Dict]) -> Optional[Tuple[str, str, str]]:
        """Context callback for teacher's private notes about the student."""
        if not self._is_active:
            return None

        user = self.user_manager.get_user(user_id)
        if not user or not user.get('parent_id'):
            return None

        trainer_id = user['parent_id']
        teacher_notes = self._get_student_note(user_id, trainer_id, "teacher_notes")

        if not teacher_notes:
            return None

        context_prompt = get_prompt('trainer.plugins.student_pad.teacher_notes_context',
                                   "Teacher's private notes about this student (use this to guide your teaching approach):\n{teacher_notes}")
        context = context_prompt.format(teacher_notes=teacher_notes)

        return (context, "system", "top")

    def get_memory_context(self, user_id: str, messages: List[Dict]) -> Optional[Tuple[str, str, str]]:
        """Legacy callback - delegates to student notes."""
        if not self._is_active:
            return None
        return self.get_student_notes_context(user_id, messages)

    def get_context(self, student_id: str) -> Dict[str, str]:
        """Get plugin-specific context information for a student."""
        user = self.user_manager.get_user(student_id)
        if not user or not user.get('parent_id'):
            return {}

        trainer_id = user['parent_id']
        student_notes = self._get_student_note(student_id, trainer_id)
        teacher_notes = self._get_student_note(student_id, trainer_id, "teacher_notes")

        context = {}
        if student_notes:
            context["📝 Student's Personal Notes"] = student_notes
        if teacher_notes:
            context["👨‍🏫 Teacher's Private Notes"] = teacher_notes

        return context

    # ─────────────────────────────────────────────────────────────────────
    # Public actions — DATA LAYER
    # ─────────────────────────────────────────────────────────────────────

    def add_note(self, student_id: str, content: str, topic: str = "") -> Dict:
        """Append a note to the student's pad."""
        user = self.user_manager.get_user(student_id)
        if not user or not user.get("parent_id"):
            return {"saved": False, "reason": "trainer_not_found"}

        trainer_id = user["parent_id"]
        existing = self._get_student_note(student_id, trainer_id)
        line = content.strip() if not topic else f"[{topic}] {content.strip()}"
        merged = f"{existing}\n{line}".strip() if existing else line

        saved = self._save_student_note(student_id, trainer_id, merged)
        return {"saved": bool(saved)}

    def _action_trigger_analysis(self, context, **params) -> Dict:
        """Unsupported action."""
        log("warning", "student_pad: trigger_memory_analysis not supported")
        return {"success": False, "reason": "unsupported", "plugin": "student_pad"}

    # ─────────────────────────────────────────────────────────────────────
    # Export / import — DATA LAYER
    # ─────────────────────────────────────────────────────────────────────

    def export_config(self, trainer_id: str) -> Optional[Dict]:
        """Export all student pads for this trainer (current versions only)."""
        students = self.user_manager.get_children(trainer_id)

        pads = {}
        for student in students:
            student_data = {
                'student_name': student.get('name', student['id']),
                'student_id': student['id'],
                'updated_at': datetime.utcnow().isoformat()
            }

            content = self._get_student_note(student['id'], trainer_id)
            if content:
                student_data['content'] = content
                version_count = self._get_note_version_count(student['id'], trainer_id)
                if version_count > 0:
                    student_data['version_count'] = version_count

            teacher_notes = self._get_student_note(student['id'], trainer_id, "teacher_notes")
            if teacher_notes:
                student_data['teacher_notes'] = teacher_notes
                version_count = self._get_note_version_count(student['id'], trainer_id, "teacher_notes")
                if version_count > 0:
                    student_data['teacher_notes_version_count'] = version_count

            if content or teacher_notes:
                pads[student['id']] = student_data

        return {'student_pads': pads} if pads else None

    def import_config(self, trainer_id: str, config: Dict) -> bool:
        """Import student pads from configuration."""
        pads = config.get('student_pads', {})
        success = True

        for student_id, pad_data in pads.items():
            content = pad_data.get('content', '')
            if content:
                if not self._save_student_note(student_id, trainer_id, content):
                    success = False

            teacher_notes = pad_data.get('teacher_notes', '')
            if teacher_notes:
                if not self._save_student_note(student_id, trainer_id, teacher_notes, "teacher_notes"):
                    success = False

        return success

    def export_history(self, trainer_id: str, student_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Export all student pad history events in minimal format."""
        events = []

        with self.db.get_session() as session:
            query = session.query(StudentNote).filter_by(trainer_id=trainer_id)
            if student_id:
                query = query.filter_by(user_id=student_id)

            notes = query.order_by(StudentNote.updated_at).all()

            for note in notes:
                if note.plugin_id == self.id or note.plugin_id == "core":
                    event_type = 'plugin.student_pad.student_note'
                    note_type = 'student'
                elif note.plugin_id == "teacher_notes":
                    event_type = 'plugin.student_pad.teacher_note'
                    note_type = 'teacher'
                else:
                    continue

                event = {
                    'timestamp': note.updated_at.isoformat() if note.updated_at else datetime.utcnow().isoformat(),
                    'type': event_type,
                    'plugin_id': self.id,
                    'student_id': note.user_id,
                    'note_id': note.id,
                    'note_type': note_type,
                    'content': note.content,
                }

                if note.version != 1:
                    event['version'] = note.version
                if note.is_current == 1:
                    event['is_current'] = True
                if note.note_metadata:
                    event['metadata'] = note.note_metadata

                events.append(event)

        return events

    def import_history(self, trainer_id: str, events: List[Dict[str, Any]],
                      student_info: Dict = None) -> bool:
        """Import student pad history events."""
        try:
            with self.db.get_session() as session:
                pad_events = [e for e in events if e.get('plugin_id') == self.id]

                student_notes = {}  # (student_id, plugin_id) -> list of events

                for event in pad_events:
                    student_id = event.get('student_id')
                    if not student_id:
                        continue

                    note_type = event.get('note_type', 'student')
                    plugin_id = self.id if note_type == 'student' else 'teacher_notes'
                    key = (student_id, plugin_id)

                    if key not in student_notes:
                        student_notes[key] = []

                    full_event = self._expand_minimal_event(event, student_info)
                    student_notes[key].append(full_event)

                for (student_id, plugin_id), note_events in student_notes.items():
                    note_events.sort(key=lambda x: x.get('timestamp', ''))

                    existing_notes = session.query(StudentNote).filter_by(
                        user_id=student_id,
                        trainer_id=trainer_id,
                        plugin_id=plugin_id
                    ).all()

                    for note in existing_notes:
                        note.is_current = 0

                    for event in note_events:
                        timestamp = None
                        try:
                            if event.get('timestamp'):
                                timestamp = datetime.fromisoformat(event['timestamp'].replace('Z', '+00:00'))
                        except (ValueError, TypeError):
                            timestamp = datetime.utcnow()

                        note_id = event.get('note_id')
                        existing = None
                        if note_id:
                            existing = session.query(StudentNote).filter_by(id=note_id).first()

                        if not existing:
                            note = StudentNote(
                                id=note_id or str(uuid.uuid4()),
                                user_id=student_id,
                                trainer_id=trainer_id,
                                content=event.get('content', ''),
                                plugin_id=plugin_id,
                                version=event.get('version', 1),
                                is_current=1 if event.get('is_current', False) else 0,
                                created_at=timestamp,
                                updated_at=timestamp,
                                note_metadata=event.get('metadata', {})
                            )
                            session.add(note)
                        else:
                            existing.content = event.get('content', existing.content)
                            existing.version = event.get('version', existing.version)
                            existing.is_current = 1 if event.get('is_current', False) else 0
                            existing.updated_at = timestamp
                            if event.get('metadata'):
                                existing.note_metadata = event['metadata']

                    self._ensure_single_current_note(session, student_id, trainer_id, plugin_id, note_events)

                session.commit()
                return True

        except Exception as e:
            log("error", f"Failed to import student pad history: {e}", exc_info=True)
            return False

    # ─────────────────────────────────────────────────────────────────────
    # UI LAYER — render methods
    # Rules: call self.<data_method>() for data; use st.* freely.
    # Future split: self.xxx() → self._logic.xxx(). No logic rewrite needed.
    # ─────────────────────────────────────────────────────────────────────

    def render_student_header_widgets(self, student_id: str, trainer_id: str) -> List[Callable]:
        """Render the student pad in the student's header area."""
        def render_student_pad():
            st.markdown("### 📝 My Personal Notes")

            current_content = self._get_student_note(student_id, trainer_id)
            version_count = self._get_note_version_count(student_id, trainer_id)

            col1, col2 = st.columns([3, 1])
            with col1:
                if current_content:
                    st.caption(f"📄 {len(current_content)} characters")
            with col2:
                if version_count > 0:
                    st.caption(f"📚 {version_count} previous versions")

            new_content = st.text_area(
                "Write your notes here",
                value=current_content or "",
                height=250,
                key=f"student_pad_editor_{student_id}",
                placeholder="Take notes, jot down ideas, or record what you've learned...",
                help="These notes are automatically saved and shared with your AI teacher",
                label_visibility="collapsed"
            )

            if new_content != current_content:
                if self._save_student_note(student_id, trainer_id, new_content):
                    st.success("Notes saved!", icon="✅")
                    st.rerun()
                else:
                    st.error("Failed to save notes")

        return [render_student_pad]

    def render_student_widgets(self, trainer_id: str, student: Dict) -> List[Callable]:
        """Render student pad in the teacher's student detail view (read-only)."""
        def render_teacher_student_pad():
            student_id = student['id']

            st.markdown("### 📝 Student Notes")

            current_content = self._get_student_note(student_id, trainer_id)
            student_version_count = self._get_note_version_count(student_id, trainer_id)
            teacher_notes = self._get_student_note(student_id, trainer_id, "teacher_notes")
            teacher_version_count = self._get_note_version_count(student_id, trainer_id, "teacher_notes")

            col1, col2, col3 = st.columns([3, 1, 1])
            with col1:
                st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
            with col2:
                if current_content:
                    st.caption(f"📄 {len(current_content)} characters")
            with col3:
                if student_version_count > 0:
                    st.caption(f"📚 {student_version_count} older versions")

            if current_content:
                st.markdown("**Student's personal notes:**")
                st.markdown(current_content)
                if student_version_count > 0:
                    st.caption(f"There are {student_version_count} previous versions available in history.")
                else:
                    st.caption("✨ These notes are automatically shared with the AI teacher.")
            else:
                st.info("This student hasn't written any notes yet.")

            st.divider()

            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown("**Teacher's private notes:**")
            with col2:
                if teacher_version_count > 0:
                    st.caption(f"📚 {teacher_version_count} older versions")

            st.caption("These notes are only visible to you and the AI teacher.")

            teacher_note_content = st.text_area(
                "Private notes (visible to AI, not to student)",
                value=teacher_notes or "",
                height=150,
                key=f"teacher_notes_{student_id}",
                help="These notes will guide the AI teacher's responses to this student"
            )

            if st.button("Save private notes", key=f"save_teacher_notes_{student_id}"):
                if self._save_student_note(student_id, trainer_id, teacher_note_content, "teacher_notes"):
                    st.success("Private notes saved!")
                    st.rerun()
                else:
                    st.error("Failed to save private notes")

        return [render_teacher_student_pad]

    def render_dashboard_widgets(self, trainer_id: str, students: List[Dict]) -> List[Callable]:
        """Add pad widget to dashboard overview."""
        def render_pad_overview():
            st.markdown("---")
            st.subheader("📝 Student Notes Overview")

            for student in students[:3]:
                student_id = student['id']
                student_name = student.get('name', student_id)

                with st.expander(f"{student_name}", expanded=False):
                    current_content = self._get_student_note(student_id, trainer_id)
                    teacher_notes = self._get_student_note(student_id, trainer_id, "teacher_notes")

                    student_version_count = self._get_note_version_count(student_id, trainer_id)
                    teacher_version_count = self._get_note_version_count(student_id, trainer_id, "teacher_notes")

                    col1, col2 = st.columns(2)
                    with col1:
                        version_text = f" ({student_version_count} older)" if student_version_count > 0 else ""
                        st.caption(f"📝 Student: {len(current_content)} chars" + version_text)
                        if current_content:
                            preview = current_content[:100] + ("..." if len(current_content) > 100 else "")
                            st.markdown(preview)
                        else:
                            st.caption("No student notes")

                    with col2:
                        version_text = f" ({teacher_version_count} older)" if teacher_version_count > 0 else ""
                        st.caption(f"👨‍🏫 Teacher: {len(teacher_notes)} chars" + version_text)
                        if teacher_notes:
                            preview = teacher_notes[:100] + ("..." if len(teacher_notes) > 100 else "")
                            st.markdown(preview)
                        else:
                            st.caption("No teacher notes")

        return [render_pad_overview]

    def render_get_admin_tabs(self, trainer_id: str) -> List[Tuple[str, Callable]]:
        """Add a history viewer tab for teachers."""
        def render_history_viewer():
            st.subheader("📜 Notes History")

            students = self.user_manager.get_children(trainer_id)

            if not students:
                st.info("No students available.")
                return

            student_options = {student['id']: student.get('name', 'Unknown') for student in students}
            student_options['all'] = "All Students"

            selected_student = st.selectbox(
                "Select Student",
                options=list(student_options.keys()),
                format_func=lambda x: student_options[x],
                key=f"pad_history_student_select_{self.id}"
            )

            note_type_filter = st.radio(
                "Note Type",
                options=['all', 'student', 'teacher'],
                format_func=lambda x: "All Notes" if x == 'all' else ("Student Notes" if x == 'student' else "Teacher Notes"),
                horizontal=True,
                key=f"pad_history_note_type_{self.id}"
            )

            student_id = None if selected_student == 'all' else selected_student
            events = self.export_history(trainer_id, student_id)

            if not events:
                st.info("No history available for the selected criteria.")
                return

            if note_type_filter != 'all':
                events = [e for e in events if e.get('note_type') == note_type_filter]

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Events", len(events))
            with col2:
                student_count = len(set(e.get('student_id') for e in events))
                st.metric("Students", student_count)
            with col3:
                version_count = sum(1 for e in events if not e.get('is_current', False))
                st.metric("Historical Versions", version_count)

            st.subheader("Timeline")

            for event in events:
                with st.container():
                    cols = st.columns([2, 1, 2, 3])

                    with cols[0]:
                        try:
                            ts = datetime.fromisoformat(event['timestamp'].replace('Z', '+00:00'))
                            st.write(ts.strftime('%Y-%m-%d %H:%M'))
                        except:
                            st.write(event['timestamp'])

                    with cols[1]:
                        name = event.get('student_name', event.get('student_id', 'Unknown'))
                        st.write(name[:15] + "..." if len(name) > 15 else name)

                    with cols[2]:
                        if event.get('note_type') == 'student':
                            icon = "📝"
                            label = "Student"
                        else:
                            icon = "👨‍🏫"
                            label = "Teacher"

                        version_info = f"v{event.get('version', 1)}"
                        if event.get('is_current'):
                            version_info += " ✓"

                        st.write(f"{icon} {label} {version_info}")

                    with cols[3]:
                        content = event.get('content', '')
                        if content:
                            preview = content[:50] + "..." if len(content) > 50 else content
                            st.caption(preview)

                st.divider()

        return [("Notes History", render_history_viewer)]


# Plugin entry point
plugin = StudentPadPlugin
