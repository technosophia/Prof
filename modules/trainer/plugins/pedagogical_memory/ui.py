"""UI layer for pedagogical_memory plugin."""

import streamlit as st

from modules.trainer.plugin_base_ui import TrainerPluginUI
from .core import *
from .core import PedagogicalMemoryPluginCore


class PedagogicalMemoryPluginUI(TrainerPluginUI):

    def render_student_widgets(self, trainer_id: str, student: Dict) -> List[Callable]:
        def render_student_memory():
            student_id = student["id"]
            cfg = self._get_plugin_config()
            fact_types = cfg["fact_types"]
            type_colors = cfg["fact_type_colors"]
            embedding_dim = self._get_embedding_dimension()

            st.markdown("### 🧠 Pedagogical Memory")

            active_facts = self._get_active_facts(trainer_id, student_id)
            last_analysis = self._get_last_analysis_date(trainer_id, student_id)

            with self.db.get_session() as session:
                version_count = (
                    session.query(PedagogicalAnalysisLog)
                    .filter_by(trainer_id=trainer_id, student_id=student_id)
                    .count()
                )

            st.markdown("#### Stats")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Active facts", len(active_facts))
            with col2:
                st.caption(f"Last analysis: {last_analysis.strftime('%Y-%m-%d %H:%M') if last_analysis else 'Never'}")
            with col3:
                st.caption(f"Analysis versions: {version_count}")

            pills = []
            for fact_type in fact_types.keys():
                count = sum(1 for f in active_facts if f["fact_type"] == fact_type)
                if count > 0:
                    pills.append(f"`{fact_type}: {count}`")
            if pills:
                st.markdown(" ".join(pills))

            st.markdown("#### Facts")
            if not active_facts:
                st.info("No active pedagogical facts.")

            for fact in active_facts:
                color = type_colors.get(fact["fact_type"], "#6C757D")
                st.markdown(f"<span style='color:{color};font-weight:700;'>● {fact['fact_type']}</span>", unsafe_allow_html=True)
                edit_key = f"{self._core.id}_content_{fact['id']}"
                if edit_key not in st.session_state:
                    st.session_state[edit_key] = fact["content"]

                st.text_input("Content", key=edit_key)
                st.progress(max(0.0, min(1.0, float(fact["confidence"]))))
                st.caption(
                    f"Last reinforced: {fact['last_reinforced_at'].strftime('%Y-%m-%d %H:%M') if fact['last_reinforced_at'] else 'Never'}"
                )
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Save", key=f"save_fact_{fact['id']}"):
                        try:
                            new_content = st.session_state.get(edit_key, "").strip()
                            if new_content:
                                with self.db.get_session() as session:
                                    db_fact = session.query(PedagogicalFact).filter_by(id=fact["id"]).first()
                                    if db_fact:
                                        db_fact.content = new_content
                                        db_fact.embedding = self._serialize_embedding(get_embedding(new_content))
                                        db_fact.embedding_dim = embedding_dim
                                        db_fact.updated_at = datetime.utcnow()
                                        db_fact.fact_metadata = {**(db_fact.fact_metadata or {}), "source": "manual_edit"}
                                        session.commit()
                                        st.success("Fact updated")
                                        st.rerun()
                        except Exception as e:
                            log("error", f"Failed to save fact edits: {e}", stacktrace=True)
                            st.error("Failed to save fact")
                with c2:
                    if st.button("Delete", key=f"delete_fact_{fact['id']}"):
                        try:
                            with self.db.get_session() as session:
                                db_fact = session.query(PedagogicalFact).filter_by(id=fact["id"]).first()
                                if db_fact:
                                    db_fact.is_active = 0
                                    db_fact.updated_at = datetime.utcnow()
                                    session.commit()
                                    st.success("Fact deleted")
                                    st.rerun()
                        except Exception as e:
                            log("error", f"Failed to delete fact: {e}", stacktrace=True)
                            st.error("Failed to delete fact")
                st.divider()

            with st.expander("+ Add fact manually"):
                new_type = st.selectbox(
                    "Fact type",
                    options=list(fact_types.keys()),
                    key=f"manual_fact_type_{student_id}",
                )
                new_content = st.text_area("Content", key=f"manual_fact_content_{student_id}")
                if st.button("Save manual fact", key=f"save_manual_fact_{student_id}"):
                    try:
                        content = (new_content or "").strip()
                        if content:
                            with self.db.get_session() as session:
                                session.add(
                                    PedagogicalFact(
                                        student_id=student_id,
                                        trainer_id=trainer_id,
                                        fact_type=new_type,
                                        content=content,
                                        embedding=self._serialize_embedding(get_embedding(content)),
                                        embedding_dim=embedding_dim,
                                        confidence=1.0,
                                        is_active=1,
                                        source_version=self._get_next_analysis_version(trainer_id, student_id),
                                        fact_metadata={"source": "manual"},
                                    )
                                )
                                session.commit()
                            st.success("Manual fact added")
                            st.rerun()
                    except Exception as e:
                        log("error", f"Failed to add manual fact: {e}", stacktrace=True)
                        st.error("Failed to add manual fact")

            st.markdown("#### Analysis")
            if st.button("🔬 Run Analysis", key=f"run_pedagogical_analysis_{student_id}"):
                with st.spinner("Running pedagogical analysis..."):
                    result = _run_async(self.refresh_memory(trainer_id, student_id))
                st.success(
                    f"Created {result['created']} · Updated {result['updated']} · "
                    f"Reinforced {result['reinforced']} · Discarded {result['discarded']}"
                )
                st.rerun()

            with st.expander("Raw conversation preview"):
                preview = self._get_new_conversations(student_id, last_analysis)
                if not preview:
                    st.caption("No new messages to analyse.")
                for msg in preview:
                    st.caption(f"[{msg['timestamp']}] {msg['role']}: {msg['content']}")

        return [render_student_memory]

    def render_dashboard_widgets(self, trainer_id: str, students: List[Dict]) -> List[Callable]:
        def render_dashboard():
            st.markdown("### 🧠 Pedagogical Memory Overview")

            if st.button("Run all analyses", key=f"{self._core.id}_run_all"):
                progress = st.progress(0)
                status = st.empty()
                total = len(students)
                for idx, student in enumerate(students):
                    status.caption(f"Running analysis for {student.get('name', student['id'])}...")
                    try:
                        _run_async(self.refresh_memory(trainer_id, student["id"]))
                    except Exception as e:
                        log("error", f"Run-all analysis failed for {student['id']}: {e}", stacktrace=True)
                    progress.progress((idx + 1) / max(1, total))
                status.caption("All analyses completed")
                st.rerun()

            for student in students:
                facts = self._get_active_facts(trainer_id, student["id"])
                last_analysis = self._get_last_analysis_date(trainer_id, student["id"])
                top_two = facts[:2]

                with st.container():
                    st.markdown(f"**{student.get('name', student['id'])}**")
                    st.caption(f"Active facts: {len(facts)}")
                    if top_two:
                        for fact in top_two:
                            st.caption(f"- [{fact['fact_type']}] {fact['content'][:120]}")
                    st.caption(
                        f"Last analysis: {last_analysis.strftime('%Y-%m-%d %H:%M') if last_analysis else 'Never'}"
                    )
                    st.divider()

        return [render_dashboard]

    def render_get_admin_tabs(self, trainer_id: str) -> List[Tuple[str, Callable]]:
        def render_history_viewer():
            st.subheader("📜 Memory History")

            if self._core.trainer_manager is None:
                st.warning("Trainer manager unavailable.")
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
                        event_type = event.get('type', '')
                        if 'fact' in event_type:
                            st.write("🔹 Fact")
                        elif 'analysis' in event_type:
                            st.write("🔬 Analysis")
                        else:
                            st.write(event_type)

                    with cols[2]:
                        if event.get('fact_type'):
                            st.write(event['fact_type'])
                        elif event.get('version'):
                            st.write(f"v{event['version']}")
                        else:
                            st.write("-")

                    with cols[3]:
                        content = event.get('content', '')
                        if content:
                            preview = content[:50] + "..." if len(content) > 50 else content
                            st.caption(preview)
                        elif event.get('messages_analyzed'):
                            st.caption(f"📊 {event['messages_analyzed']} msgs, +{event.get('facts_created', 0)} facts")
                        else:
                            st.caption("-")

                st.divider()

        return [("Memory History", render_history_viewer)]
