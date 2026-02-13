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
        """Export all student pads for this trainer (current versions only)."""
        trainer_manager = get_trainer_manager()
        students = trainer_manager.get_trainer_students(trainer_id)

        pads = {}
        for student in students:
            student_data = {
                'student_name': student.get('name', student['id']),
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


# Plugin entry point - must be named 'plugin'
plugin = StudentPadPlugin
