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
from shared.common import _, get_db_manager


class StudentPadPlugin(TrainerPlugin):
    """Plugin providing personal pads for students."""

    def initialize(self) -> bool:
        """Initialize the plugin."""
        return True

    def render_dashboard_widgets(self, trainer_id: str, students: List[Dict]) -> List[Callable]:
        """Add pad widget to dashboard."""
        def render_pad_widget():
            st.markdown("---")
            st.subheader(_("📝 Student Pads"))

            trainer_manager = get_trainer_manager()

            for student in students:
                student_id = student['id']
                student_name = student.get('name', student_id)

                with st.expander(f"{student_name}", expanded=False):
                    # Get current pad content
                    current_content = trainer_manager.get_student_note(
                        student_id, trainer_id, self.id
                    )

                    # Display with character count
                    st.caption(f"📄 {len(current_content)} characters")

                    # Editable text area
                    new_content = st.text_area(
                        _("Notes"),
                        value=current_content,
                        height=150,
                        key=f"pad_{student_id}_{self.id}",
                        label_visibility="collapsed"
                    )

                    # Save button
                    col1, col2, col3 = st.columns([1, 1, 3])
                    with col1:
                        if st.button(_("💾 Save"), key=f"save_{student_id}_{self.id}"):
                            if trainer_manager.save_student_note(
                                student_id, trainer_id, new_content, self.id
                            ):
                                st.success(_("Notes saved!"))
                            else:
                                st.error(_("Failed to save notes"))

                    with col2:
                        # Last updated indicator
                        st.caption(_("Auto-saves for students"))

        return [render_pad_widget]

    def render_student_widgets(self, trainer_id: str, student: Dict) -> List[Callable]:
        """Add individual student pad view."""
        def render_student_pad():
            student_id = student['id']
            trainer_manager = get_trainer_manager()

            st.markdown("### 📝 Student Notes")

            # Get current content
            current_content = trainer_manager.get_student_note(
                student_id, trainer_id, self.id
            )

            # Display with metadata
            col1, col2 = st.columns([4, 1])
            with col1:
                st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
            with col2:
                st.caption(f"📄 {len(current_content)} chars")

            # Editable area for teacher
            new_content = st.text_area(
                _("Notes for this student"),
                value=current_content,
                height=200
            )

            if st.button(_("Update Notes"), key=f"update_{student_id}"):
                if trainer_manager.save_student_note(
                    student_id, trainer_id, new_content, self.id
                ):
                    st.success(_("Notes updated!"))

        return [render_student_pad]

    def export_config(self, trainer_id: str) -> Optional[Dict]:
        """Export all student pads for this trainer."""
        trainer_manager = get_trainer_manager()
        students = trainer_manager.get_trainer_students(trainer_id)

        pads = {}
        for student in students:
            content = trainer_manager.get_student_note(
                student['id'], trainer_id, self.id
            )
            if content:  # Only export non-empty pads
                pads[student['id']] = {
                    'student_name': student.get('name', student['id']),
                    'content': content,
                    'updated_at': datetime.utcnow().isoformat()
                }

        return {'student_pads': pads} if pads else None

    def import_config(self, trainer_id: str, config: Dict) -> bool:
        """Import student pads from configuration."""
        trainer_manager = get_trainer_manager()
        pads = config.get('student_pads', {})

        success = True
        for student_id, pad_data in pads.items():
            content = pad_data.get('content', '')
            if content:
                if not trainer_manager.save_student_note(
                    student_id, trainer_id, content, self.id
                ):
                    success = False

        return success


# Plugin entry point - must be named 'plugin'
plugin = StudentPadPlugin
