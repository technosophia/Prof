"""
Student Pad Plugin for Trainer Module.
Allows each student to have a personal note-taking pad.
Visible in dashboard and exportable/importable.
"""

from typing import List, Dict, Any, Optional, Callable
import streamlit as st
from datetime import datetime

from modules.trainer.plugin_base import TrainerPlugin, PluginManifest
from modules.trainer.manager import get_trainer_manager
from modules.trainer.models import StudentNote
from shared.common import _, get_db_manager


class StudentPadPlugin(TrainerPlugin):
    """Plugin providing personal pads for students."""

    def initialize(self) -> bool:
        """Initialize the plugin."""
        return True

    def _get_student_note(self, student_id: str, trainer_id: str, plugin_id: str = None) -> str:
        """Helper method to get student note directly from database."""
        if plugin_id is None:
            plugin_id = self.id

        db = get_db_manager()
        with db.get_session() as session:
            note = session.query(StudentNote).filter_by(
                user_id=student_id,
                trainer_id=trainer_id,
                plugin_id=plugin_id
            ).first()
            return note.content if note else ""

    def _save_student_note(self, student_id: str, trainer_id: str, content: str, plugin_id: str = None) -> bool:
        """Helper method to save student note directly to database."""
        if plugin_id is None:
            plugin_id = self.id

        try:
            db = get_db_manager()
            with db.get_session() as session:
                note = session.query(StudentNote).filter_by(
                    user_id=student_id,
                    trainer_id=trainer_id,
                    plugin_id=plugin_id
                ).first()

                if note:
                    note.content = content
                    note.updated_at = datetime.utcnow()
                else:
                    note = StudentNote(
                        user_id=student_id,
                        trainer_id=trainer_id,
                        content=content,
                        plugin_id=plugin_id
                    )
                    session.add(note)
                session.commit()
                return True
        except Exception as e:
            from shared.common import log
            log("error", f"Failed to save student note: {e}", exc_info=True)
            return False

    def render_student_header_widgets(self, student_id: str, trainer_id: str) -> List[Callable]:
        """
        Render the student pad in the student's header area.
        This is the main textarea for students to edit their notes.
        """
        def render_student_pad():
            st.markdown("### " + _("My Personal Notes"))

            # Get current pad content using helper
            current_content = self._get_student_note(student_id, trainer_id)

            # Character count
            if current_content:
                st.caption(f"📄 {len(current_content)} " + _("characters"))

            # Editable text area - this is where students write their notes
            new_content = st.text_area(
                _("Write your notes here..."),
                value=current_content or "",
                height=250,
                key=f"student_pad_editor_{student_id}",
                placeholder=_("Take notes, write down questions, or keep track of what you've learned..."),
                help=_("Auto-saves when you type"),
                label_visibility="collapsed"
            )

            # Auto-save on change
            if new_content != current_content:
                if self._save_student_note(student_id, trainer_id, new_content):
                    st.success(_("✓ Notes saved"), icon="✅")
                else:
                    st.error(_("Failed to save notes"))

        return [render_student_pad]

    def render_student_widgets(self, trainer_id: str, student: Dict) -> List[Callable]:
        """Render student pad in the teacher's student detail view (read-only)."""
        def render_teacher_student_pad():
            student_id = student['id']

            st.markdown("### 📝 " + _("Student Notes"))

            # Get student notes using helper
            current_content = self._get_student_note(student_id, trainer_id)

            # Get teacher notes using helper with different plugin_id
            teacher_notes = self._get_student_note(student_id, trainer_id, "teacher_notes")

            # Metadata row
            col1, col2 = st.columns([4, 1])
            with col1:
                st.caption(_("Last updated: ") + datetime.now().strftime('%Y-%m-%d %H:%M'))
            with col2:
                st.caption(f"📄 {len(current_content)} " + _("chars"))

            # Read-only display of student's notes
            if current_content:
                st.markdown("**" + _("Student's personal notes:") + "**")
                st.markdown(current_content)
            else:
                st.info(_("This student hasn't written any notes yet."))

            # Add a visual separator
            st.divider()

            # Teacher's private notes section (separate from student's pad)
            st.markdown("**" + _("Teacher's private notes:") + "**")

            teacher_note_content = st.text_area(
                _("Private notes (only visible to you)"),
                value=teacher_notes or "",
                height=150,
                key=f"teacher_notes_{student_id}"
            )

            if st.button(_("Save private notes"), key=f"save_teacher_notes_{student_id}"):
                if self._save_student_note(student_id, trainer_id, teacher_note_content, "teacher_notes"):
                    st.success(_("Private notes saved!"))
                else:
                    st.error(_("Failed to save private notes"))

        return [render_teacher_student_pad]

    def render_dashboard_widgets(self, trainer_id: str, students: List[Dict]) -> List[Callable]:
        """Add pad widget to dashboard overview."""
        def render_pad_overview():
            st.markdown("---")
            st.subheader(_("📝 Student Notes Overview"))

            for student in students[:3]:  # Show only first 3 to avoid clutter
                student_id = student['id']
                student_name = student.get('name', student_id)

                with st.expander(f"{student_name}", expanded=False):
                    current_content = self._get_student_note(student_id, trainer_id)
                    st.caption(f"📄 {len(current_content)} " + _("characters"))

                    if current_content:
                        st.markdown("**" + _("Latest notes:") + "**")
                        # Show preview with ellipsis
                        preview = current_content[:200] + ("..." if len(current_content) > 200 else "")
                        st.markdown(preview)
                    else:
                        st.caption(_("No notes yet"))

        return [render_pad_overview]

    def export_config(self, trainer_id: str) -> Optional[Dict]:
        """Export all student pads for this trainer."""
        trainer_manager = get_trainer_manager()
        students = trainer_manager.get_trainer_students(trainer_id)

        pads = {}
        for student in students:
            # Export student notes
            content = self._get_student_note(student['id'], trainer_id)
            if content:
                pads[student['id']] = {
                    'student_name': student.get('name', student['id']),
                    'content': content,
                    'updated_at': datetime.utcnow().isoformat()
                }

            # Also export teacher notes if they exist
            teacher_notes = self._get_student_note(student['id'], trainer_id, "teacher_notes")
            if teacher_notes:
                if student['id'] not in pads:
                    pads[student['id']] = {
                        'student_name': student.get('name', student['id']),
                        'updated_at': datetime.utcnow().isoformat()
                    }
                pads[student['id']]['teacher_notes'] = teacher_notes

        return {'student_pads': pads} if pads else None

    def import_config(self, trainer_id: str, config: Dict) -> bool:
        """Import student pads from configuration."""
        pads = config.get('student_pads', {})

        success = True
        for student_id, pad_data in pads.items():
            # Import student notes
            content = pad_data.get('content', '')
            if content:
                if not self._save_student_note(student_id, trainer_id, content):
                    success = False

            # Import teacher notes if they exist
            teacher_notes = pad_data.get('teacher_notes', '')
            if teacher_notes:
                if not self._save_student_note(student_id, trainer_id, teacher_notes, "teacher_notes"):
                    success = False

        return success


# Plugin entry point - must be named 'plugin'
plugin = StudentPadPlugin
