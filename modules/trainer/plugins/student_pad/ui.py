"""UI layer for student_pad plugin."""

import streamlit as st

from modules.trainer.plugin_base_ui import TrainerPluginUI
from .core import *
from .core import StudentPadPluginCore


class StudentPadPluginUI(TrainerPluginUI):

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
                key=f"pad_history_student_select_{self._core.id}"
            )

            note_type_filter = st.radio(
                "Note Type",
                options=['all', 'student', 'teacher'],
                format_func=lambda x: "All Notes" if x == 'all' else ("Student Notes" if x == 'student' else "Teacher Notes"),
                horizontal=True,
                key=f"pad_history_note_type_{self._core.id}"
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
