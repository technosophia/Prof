"""UI layer for memory plugin."""

import streamlit as st

from modules.trainer.plugin_base_ui import TrainerPluginUI
from .core import *
from .core import MemoryPluginCore


class MemoryPluginUI(TrainerPluginUI):

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
                             width='stretch'):
                    log("info", f"Refresh button clicked (plugin={self._core.id}, trainer={trainer_id}, student={student_id})")
                    with st.spinner("Analyzing conversations..."):
                        # DATA: calls trigger_analysis which delegates to _action_trigger_analysis
                        result = self._core.trigger_analysis(student_id, trainer_id)

                        if result.get("success"):
                            log("info", f"Refresh succeeded (plugin={self._core.id}, student={student_id})")
                            st.success("✅ Memory updated successfully!")
                            st.rerun()
                        else:
                            log("error", f"Refresh failed (plugin={self._core.id}, student={student_id})")
                            st.error("❌ Failed to update memory")

            with col2:
                if st.button("✏️ Edit Manually",
                             key=f"edit_memory_{student_id}",
                             width='stretch'):
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
                         key=f"{self._core.id}_refresh_all_memories",
                         width='stretch'):
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

            # ── Auto-analyze on new conversation toggle ──────────────────
            st.markdown("#### ⚙️ Automatic Analysis")
            current = self._core.get_auto_analyze_config(trainer_id)
            new_val = st.toggle(
                "Automatically analyze memory when a student starts a new conversation",
                value=current,
                key=f"{self._core.id}_auto_analyze_toggle",
            )
            if new_val != current:
                self._core.set_auto_analyze_config(trainer_id, new_val)
                st.rerun()
            st.divider()
            # ─────────────────────────────────────────────────────────────

            if self._core.trainer_manager is None:
                log("warning", "Memory plugin activated without trainer_manager")
                return
            students = self._core.trainer_manager.get_trainer_students(trainer_id)

            if not students:
                st.info("No students available.")
                return

            student_options = {student['id']: student.get('name', 'Unknown') for student in students}
            student_options['all'] = "All Students"

            selected = st.selectbox(
                "Select Student",
                options=list(student_options.keys()),
                format_func=lambda x: student_options[x],
                key=f"{self._core.id}_memory_history_select"
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
