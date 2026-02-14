"""
Student Pad Plugin for Trainer Module.
Allows each student to have a personal note-taking pad with version history.
Visible in dashboard and exportable/importable.
"""

from typing import List, Dict, Any, Optional, Callable, Tuple
import streamlit as st
from datetime import datetime
import uuid

from sqlalchemy import Column, String, Text, DateTime, JSON, ForeignKey, Integer, and_
from shared.common import Base, get_db_manager, get_prompt, register_llm_context_callback, log, _
from modules.trainer.plugin_base import TrainerPlugin, PluginManifest
from modules.trainer.manager import get_trainer_manager

# ============= DATABASE MODEL =============
class StudentNote(Base):
    """Store notes/pad for each student with version history."""
    __tablename__ = 'trainer_student_notes'
    __table_args__ = {'extend_existing': True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)  # Student ID
    trainer_id = Column(String, nullable=False, index=True)  # Trainer/Master ID
    content = Column(Text, default="")
    plugin_id = Column(String, default="core")  # Which plugin owns this note
    version = Column(Integer, default=1)  # Version number
    is_current = Column(Integer, default=1)  # 1 for current version, 0 for history
    updated_at = Column(DateTime, default=datetime.utcnow)
    note_metadata = Column(JSON, default={})
# ==========================================


class StudentPadPlugin(TrainerPlugin):
    """Plugin providing personal pads for students with version history."""

    def initialize(self) -> bool:
        """Initialize the plugin and register context callbacks."""
        # Ensure table exists - but don't try to create it in tests
        try:
            db = get_db_manager()
            if db.is_initialized() and not db._in_memory:
                # Create tables for this model if they don't exist
                Base.metadata.create_all(db._engine, tables=[StudentNote.__table__], checkfirst=True)
                log("info", "StudentNote table created/verified with version tracking")
        except Exception as e:
            log("error", f"Failed to create/update StudentNote table: {e}")
            # Continue anyway - table might already exist

        # Register context callbacks
        register_llm_context_callback(self.get_student_notes_context)
        register_llm_context_callback(self.get_teacher_notes_context)
        return True

    def _get_student_note(self, student_id: str, trainer_id: str, plugin_id: str = None) -> str:
        """Helper method to get current student note directly from database."""
        if plugin_id is None:
            plugin_id = self.id

        db = get_db_manager()
        with db.get_session() as session:
            note = session.query(StudentNote).filter_by(
                user_id=student_id,
                trainer_id=trainer_id,
                plugin_id=plugin_id,
                is_current=1
            ).first()
            return note.content if note else ""

    def _get_note_version_count(self, student_id: str, trainer_id: str, plugin_id: str = None) -> int:
        """Helper method to get the number of historical versions."""
        if plugin_id is None:
            plugin_id = self.id

        db = get_db_manager()
        with db.get_session() as session:
            # Count all versions including current
            total_count = session.query(StudentNote).filter_by(
                user_id=student_id,
                trainer_id=trainer_id,
                plugin_id=plugin_id
            ).count()

            # Return number of historical versions (total - 1 if current exists)
            return max(0, total_count - 1)

    def _save_student_note(self, student_id: str, trainer_id: str, content: str, plugin_id: str = None) -> bool:
        """Helper method to save student note with version history."""
        if plugin_id is None:
            plugin_id = self.id

        try:
            db = get_db_manager()
            with db.get_session() as session:
                # Get current note
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

    def get_student_notes_context(self, user_id: str, messages: List[Dict]) -> Optional[Tuple[str, str, str]]:
        """
        Context callback for student's personal notes.
        Returns tuple: (context, role, position)
        """
        # Get the student's trainer (parent)
        from shared.common import get_user_manager
        user_manager = get_user_manager()
        user = user_manager.get_user(user_id)

        if not user or not user.get('parent_id'):
            return None

        trainer_id = user['parent_id']
        student_notes = self._get_student_note(user_id, trainer_id)

        if not student_notes:
            return None

        # Get the appropriate prompt based on language
        context_prompt = get_prompt('trainer.plugins.student_pad.student_notes_context',
                                   _("The student's personal notes (their thoughts, questions, and learning progress):\n{student_notes}"))

        context = context_prompt.format(student_notes=student_notes)

        # Return as system message at the top of the context
        return (context, "system", "top")

    def get_teacher_notes_context(self, user_id: str, messages: List[Dict]) -> Optional[Tuple[str, str, str]]:
        """
        Context callback for teacher's private notes about the student.
        Returns tuple: (context, role, position)
        Teacher notes are only visible to the AI, not to the student.
        """
        # Get the student's trainer (parent)
        from shared.common import get_user_manager
        user_manager = get_user_manager()
        user = user_manager.get_user(user_id)

        if not user or not user.get('parent_id'):
            return None

        trainer_id = user['parent_id']
        teacher_notes = self._get_student_note(user_id, trainer_id, "teacher_notes")

        if not teacher_notes:
            return None

        # Get the appropriate prompt based on language
        context_prompt = get_prompt('trainer.plugins.student_pad.teacher_notes_context',
                                   _("Teacher's private notes about this student (use this to guide your teaching approach):\n{teacher_notes}"))

        context = context_prompt.format(teacher_notes=teacher_notes)

        # Return as system message at the top of the context
        return (context, "system", "top")

    def render_student_header_widgets(self, student_id: str, trainer_id: str) -> List[Callable]:
        """
        Render the student pad in the student's header area.
        This is the main textarea for students to edit their notes.
        """
        def render_student_pad():
            st.markdown("### " + _("trainer_plugin_student_pad.my_personal_notes"))

            # Get current pad content using helper
            current_content = self._get_student_note(student_id, trainer_id)

            # Get version count
            version_count = self._get_note_version_count(student_id, trainer_id)

            # Character count and version info
            col1, col2 = st.columns([3, 1])
            with col1:
                if current_content:
                    st.caption(f"📄 {len(current_content)} " + _("trainer_plugin_student_pad.characters"))
            with col2:
                if version_count > 0:
                    st.caption(f"📚 {version_count} " + _("trainer_plugin_student_pad.previous_versions"))

            # Editable text area - this is where students write their notes
            new_content = st.text_area(
                _("trainer_plugin_student_pad.write_your_notes_here"),
                value=current_content or "",
                height=250,
                key=f"student_pad_editor_{student_id}",
                placeholder=_("trainer_plugin_student_pad.take_notes_placeholder"),
                help=_("trainer_plugin_student_pad.auto_saves_for_students"),
                label_visibility="collapsed"
            )

            # Auto-save on change
            if new_content != current_content:
                if self._save_student_note(student_id, trainer_id, new_content):
                    st.success(_("trainer_plugin_student_pad.notes_saved_check"), icon="✅")
                    st.rerun()
                else:
                    st.error(_("trainer_plugin_student_pad.failed_to_save_notes"))

        return [render_student_pad]

    def render_student_widgets(self, trainer_id: str, student: Dict) -> List[Callable]:
        """Render student pad in the teacher's student detail view (read-only)."""
        def render_teacher_student_pad():
            student_id = student['id']

            st.markdown("### 📝 " + _("trainer_plugin_student_pad.student_notes"))

            # Get student notes using helper
            current_content = self._get_student_note(student_id, trainer_id)

            # Get version count for student notes
            student_version_count = self._get_note_version_count(student_id, trainer_id)

            # Get teacher notes using helper with different plugin_id
            teacher_notes = self._get_student_note(student_id, trainer_id, "teacher_notes")

            # Get version count for teacher notes
            teacher_version_count = self._get_note_version_count(student_id, trainer_id, "teacher_notes")

            # Metadata row
            col1, col2, col3 = st.columns([3, 1, 1])
            with col1:
                st.caption(_("trainer_plugin_student_pad.last_updated") + f" {datetime.now().strftime('%Y-%m-%d %H:%M')}")
            with col2:
                if current_content:
                    st.caption(f"📄 {len(current_content)} " + _("trainer_plugin_student_pad.characters"))
            with col3:
                if student_version_count > 0:
                    st.caption(f"📚 {student_version_count} " + _("trainer_plugin_student_pad.older_versions"))

            # Read-only display of student's notes
            if current_content:
                st.markdown("**" + _("trainer_plugin_student_pad.student_personal_notes") + "**")
                st.markdown(current_content)

                # Add a note about AI context and version count
                if student_version_count > 0:
                    st.caption(_("trainer_plugin_student_pad.version_history_note").format(count=student_version_count))
                else:
                    st.caption(_("trainer_plugin_student_pad.ai_context_note"))
            else:
                st.info(_("trainer_plugin_student_pad.no_student_notes_yet"))

            # Add a visual separator
            st.divider()

            # Teacher's private notes section (separate from student's pad)
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown("**" + _("trainer_plugin_student_pad.teacher_private_notes") + "**")
            with col2:
                if teacher_version_count > 0:
                    st.caption(f"📚 {teacher_version_count} " + _("trainer_plugin_student_pad.older_versions"))

            st.caption(_("trainer_plugin_student_pad.teacher_notes_visibility_note"))

            teacher_note_content = st.text_area(
                _("trainer_plugin_student_pad.teacher_notes_placeholder"),
                value=teacher_notes or "",
                height=150,
                key=f"teacher_notes_{student_id}",
                help=_("trainer_plugin_student_pad.teacher_notes_help")
            )

            if st.button(_("trainer_plugin_student_pad.save_private_notes"), key=f"save_teacher_notes_{student_id}"):
                if self._save_student_note(student_id, trainer_id, teacher_note_content, "teacher_notes"):
                    st.success(_("trainer_plugin_student_pad.teacher_notes_saved"))
                    st.rerun()
                else:
                    st.error(_("trainer_plugin_student_pad.failed_to_save_teacher_notes"))

        return [render_teacher_student_pad]

    def render_dashboard_widgets(self, trainer_id: str, students: List[Dict]) -> List[Callable]:
        """Add pad widget to dashboard overview."""
        def render_pad_overview():
            st.markdown("---")
            st.subheader("📝 " + _("trainer_plugin_student_pad.notes_overview"))

            for student in students[:3]:  # Show only first 3 to avoid clutter
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
                        st.caption(f"📝 " + _("trainer_plugin_student_pad.student") + f": {len(current_content)} " + _("trainer_plugin_student_pad.chars") + version_text)
                        if current_content:
                            preview = current_content[:100] + ("..." if len(current_content) > 100 else "")
                            st.markdown(preview)
                        else:
                            st.caption(_("trainer_plugin_student_pad.no_student_notes"))

                    with col2:
                        version_text = f" ({teacher_version_count} older)" if teacher_version_count > 0 else ""
                        st.caption(f"👨‍🏫 " + _("trainer_plugin_student_pad.teacher") + f": {len(teacher_notes)} " + _("trainer_plugin_student_pad.chars") + version_text)
                        if teacher_notes:
                            preview = teacher_notes[:100] + ("..." if len(teacher_notes) > 100 else "")
                            st.markdown(preview)
                        else:
                            st.caption(_("trainer_plugin_student_pad.no_teacher_notes"))

        return [render_pad_overview]

    def export_config(self, trainer_id: str) -> Optional[Dict]:
        """Export all student pads for this trainer (current versions only) with student_id."""
        trainer_manager = get_trainer_manager()
        students = trainer_manager.get_trainer_students(trainer_id)

        pads = {}
        for student in students:
            student_data = {
                'student_name': student.get('name', student['id']),
                'student_id': student['id'],  # Explicitly include student_id
                'updated_at': datetime.utcnow().isoformat()
            }

            # Export current student notes
            content = self._get_student_note(student['id'], trainer_id)
            if content:
                student_data['content'] = content
                # Add version count for metadata
                version_count = self._get_note_version_count(student['id'], trainer_id)
                if version_count > 0:
                    student_data['version_count'] = version_count

            # Export current teacher notes
            teacher_notes = self._get_student_note(student['id'], trainer_id, "teacher_notes")
            if teacher_notes:
                student_data['teacher_notes'] = teacher_notes
                # Add version count for metadata
                version_count = self._get_note_version_count(student['id'], trainer_id, "teacher_notes")
                if version_count > 0:
                    student_data['teacher_notes_version_count'] = version_count

            # Only add if there's any content
            if content or teacher_notes:
                pads[student['id']] = student_data

        return {'student_pads': pads} if pads else None

    def import_config(self, trainer_id: str, config: Dict) -> bool:
        """Import student pads from configuration (as new current versions)."""
        pads = config.get('student_pads', {})

        success = True
        for student_id, pad_data in pads.items():
            # Import student notes as new current version
            content = pad_data.get('content', '')
            if content:
                if not self._save_student_note(student_id, trainer_id, content):
                    success = False

            # Import teacher notes as new current version
            teacher_notes = pad_data.get('teacher_notes', '')
            if teacher_notes:
                if not self._save_student_note(student_id, trainer_id, teacher_notes, "teacher_notes"):
                    success = False

        return success


    def export_history(self, trainer_id: str, student_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Export all student pad history events in minimal format.
        Each version change becomes a separate event.
        """
        db = get_db_manager()
        events = []

        with db.get_session() as session:
            # Build query
            query = session.query(StudentNote).filter_by(trainer_id=trainer_id)

            if student_id:
                query = query.filter_by(user_id=student_id)

            # Get all notes (all versions)
            notes = query.order_by(StudentNote.updated_at).all()

            for note in notes:
                # Determine event type
                if note.plugin_id == self.id or note.plugin_id == "core":
                    event_type = 'plugin.student_pad.student_note'
                    note_type = 'student'
                elif note.plugin_id == "teacher_notes":
                    event_type = 'plugin.student_pad.teacher_note'
                    note_type = 'teacher'
                else:
                    continue

                # Minimal event - only essential fields
                event = {
                    'timestamp': note.updated_at.isoformat() if note.updated_at else datetime.utcnow().isoformat(),
                    'type': event_type,
                    'plugin_id': self.id,
                    'student_id': note.user_id,
                    'note_id': note.id,
                    'note_type': note_type,
                    'content': note.content,
                }

                # Only add version if not default (version 1)
                if note.version != 1:
                    event['version'] = note.version

                # Only add is_current if not default (default is false for history export)
                # In history export, we typically export all versions, so is_current is not needed
                # but if it's the current version, we might want to mark it
                if note.is_current == 1:
                    event['is_current'] = True

                # Only add metadata if present
                if note.note_metadata:
                    event['metadata'] = note.note_metadata

                events.append(event)

        return events

    def import_history(self, trainer_id: str, events: List[Dict[str, Any]], student_info: Dict = None) -> bool:
        """
        Import student pad history events, handling both legacy and minimal formats.

        Args:
            trainer_id: The trainer's ID
            events: List of event dictionaries to import
            student_info: Optional dictionary with student information for reconstruction
        """
        db = get_db_manager()

        try:
            with db.get_session() as session:
                # Filter events for this plugin
                pad_events = [e for e in events if e.get('plugin_id') == self.id]

                # Group events by student and note type
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

                    # Reconstruct full event data from minimal format
                    full_event = self._expand_minimal_event(event, student_info)
                    student_notes[key].append(full_event)

                # Process each student's notes
                for (student_id, plugin_id), note_events in student_notes.items():
                    # Sort events by timestamp
                    note_events.sort(key=lambda x: x.get('timestamp', ''))

                    # Mark all existing notes as historical
                    existing_notes = session.query(StudentNote).filter_by(
                        user_id=student_id,
                        trainer_id=trainer_id,
                        plugin_id=plugin_id
                    ).all()

                    for note in existing_notes:
                        note.is_current = 0

                    # Recreate all versions
                    for event in note_events:
                        # Parse timestamps - use timestamp for both created and updated
                        timestamp = None
                        try:
                            if event.get('timestamp'):
                                timestamp = datetime.fromisoformat(event['timestamp'].replace('Z', '+00:00'))
                        except (ValueError, TypeError):
                            timestamp = datetime.utcnow()

                        # Check if this note version already exists
                        note_id = event.get('note_id')
                        existing = None
                        if note_id:
                            existing = session.query(StudentNote).filter_by(id=note_id).first()

                        if not existing:
                            # Create new note version
                            note = StudentNote(
                                id=note_id or str(uuid.uuid4()),
                                user_id=student_id,
                                trainer_id=trainer_id,
                                content=event.get('content', ''),
                                plugin_id=plugin_id,
                                version=event.get('version', 1),
                                is_current=1 if event.get('is_current', False) else 0,
                                created_at=timestamp,  # Use timestamp for created_at
                                updated_at=timestamp,  # Use same timestamp for updated_at
                                note_metadata=event.get('metadata', {})
                            )
                            session.add(note)
                        else:
                            # Update existing note
                            existing.content = event.get('content', existing.content)
                            existing.version = event.get('version', existing.version)
                            existing.is_current = 1 if event.get('is_current', False) else 0
                            existing.updated_at = timestamp
                            if event.get('metadata'):
                                existing.note_metadata = event['metadata']

                    # Ensure exactly one current note
                    self._ensure_single_current_note(session, student_id, trainer_id, plugin_id, note_events)

                session.commit()
                return True

        except Exception as e:
            log("error", f"Failed to import student pad history: {e}", exc_info=True)
            return False

    def _expand_minimal_event(self, event: Dict, student_info: Dict = None) -> Dict:
        """
        Expand a minimal event to full event data for import.
        Reconstructs missing fields with defaults.
        """
        expanded = event.copy()

        # Ensure required fields exist
        if 'version' not in expanded:
            expanded['version'] = 1

        if 'is_current' not in expanded:
            expanded['is_current'] = False

        if 'metadata' not in expanded:
            expanded['metadata'] = {}

        # Use timestamp for created_at and updated_at if not present
        if 'timestamp' in expanded:
            if 'created_at' not in expanded:
                expanded['created_at'] = expanded['timestamp']
            if 'updated_at' not in expanded:
                expanded['updated_at'] = expanded['timestamp']

        # Add student_name from student_info if available
        if student_info and expanded.get('student_id') in student_info:
            if 'student_name' not in expanded:
                expanded['student_name'] = student_info[expanded['student_id']]['name']

        return expanded

    def _ensure_single_current_note(self, session, student_id: str, trainer_id: str, plugin_id: str, note_events: List[Dict]):
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

    def get_admin_tabs(self, trainer_id: str) -> List[Tuple[str, Callable]]:
        """Add a history viewer tab for teachers."""

        def render_history_viewer():
            st.subheader("📜 " + _("trainer_plugin_student_pad.notes_history"))

            trainer_manager = get_trainer_manager()
            students = trainer_manager.get_trainer_students(trainer_id)

            if not students:
                st.info(_("No students available."))
                return

            # Student selector - with unique key including plugin ID
            student_options = {student['id']: student.get('name', 'Unknown') for student in students}
            student_options['all'] = "All Students"

            selected_student = st.selectbox(
                _("Select Student"),
                options=list(student_options.keys()),
                format_func=lambda x: student_options[x],
                key=f"pad_history_student_select_{self.id}"
            )

            # Note type filter - with unique key
            note_type_filter = st.radio(
                _("Note Type"),
                options=['all', 'student', 'teacher'],
                format_func=lambda x: _("All Notes") if x == 'all' else (_("Student Notes") if x == 'student' else _("Teacher Notes")),
                horizontal=True,
                key=f"pad_history_note_type_{self.id}"
            )

            # Get history
            student_id = None if selected_student == 'all' else selected_student
            events = self.export_history(trainer_id, student_id)

            if not events:
                st.info(_("No history available for the selected criteria."))
                return

            # Filter by note type
            if note_type_filter != 'all':
                events = [e for e in events if e.get('note_type') == note_type_filter]

            # Display statistics
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric(_("Total Events"), len(events))
            with col2:
                student_count = len(set(e.get('student_id') for e in events))
                st.metric(_("Students"), student_count)
            with col3:
                version_count = sum(1 for e in events if not e.get('is_current', False))
                st.metric(_("Historical Versions"), version_count)

            # Display timeline
            st.subheader(_("Timeline"))

            for idx, event in enumerate(events):
                with st.container():
                    cols = st.columns([2, 1, 2, 3])

                    with cols[0]:
                        # Timestamp
                        try:
                            ts = datetime.fromisoformat(event['timestamp'].replace('Z', '+00:00'))
                            st.write(ts.strftime('%Y-%m-%d %H:%M'))
                        except:
                            st.write(event['timestamp'])

                    with cols[1]:
                        # Student name (truncated)
                        name = event.get('student_name', event.get('student_id', 'Unknown'))
                        st.write(name[:15] + "..." if len(name) > 15 else name)

                    with cols[2]:
                        # Note type and version
                        if event.get('note_type') == 'student':
                            icon = "📝"
                            label = _("Student")
                        else:
                            icon = "👨‍🏫"
                            label = _("Teacher")

                        version_info = f"v{event.get('version', 1)}"
                        if event.get('is_current'):
                            version_info += " ✓"

                        st.write(f"{icon} {label} {version_info}")

                    with cols[3]:
                        # Content preview
                        content = event.get('content', '')
                        if content:
                            preview = content[:50] + "..." if len(content) > 50 else content
                            st.caption(preview)

                st.divider()

        return [(_("Notes History"), render_history_viewer)]

# Plugin entry point - must be named 'plugin'
plugin = StudentPadPlugin
