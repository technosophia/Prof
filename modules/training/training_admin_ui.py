"""
Training module UI injections.
"""
import asyncio
import streamlit as st
from datetime import datetime
from typing import List

from core.logging import log
from shared.common import get_section
from shared.common import get_user_manager, UserRole
from shared.common import register_llm_callback, unregister_llm_callback
from shared.common import get_prompt  # Added import

from modules.training.training_logic import get_training_manager, StudentStatus, StateHistoryEntry

def display_admin_tabs():
    """Main training interface."""
    if not ("current_user" in st.session_state and st.session_state.current_user):
        return

    user_id = st.session_state.current_user['id']
    user_role = st.session_state.current_user['role']

    if user_role != UserRole.MASTER.value:
        return

    training_manager = get_training_manager()

    # Set default tab if not set
    if "training_tab" not in st.session_state:
        st.session_state.training_tab = "dashboard"

    # Tab selection
    tab1, tab2, tab3 = st.tabs(["📊 Training Dashboard", "📜 State History", "⚙️ Configuration"])

    with tab1:
        render_training_dashboard(user_id, training_manager)

    with tab2:
        render_state_history(user_id, training_manager)

    with tab3:
        render_training_config(user_id, training_manager)

def inject_ui_admin_tab():
    return ("Training", display_admin_tabs)


def render_training_dashboard(master_id: str, training_manager):
    """Render the training dashboard."""
    st.header("🎓 Student Training Dashboard")

    # Get status board
    status_list = training_manager.get_student_status_board(master_id)

    if not status_list:
        st.info("No students found. Normal users assigned to you will appear here.")
        return

    # Dashboard metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Students", len(status_list))
    with col2:
        active_students = sum(1 for s in status_list if s.unanalyzed_messages > 0)
        st.metric("Active Students", active_students)
    with col3:
        total_unanalyzed = sum(s.unanalyzed_messages for s in status_list)
        st.metric("Unanalyzed Messages", total_unanalyzed)
    with col4:
        analyzed_students = sum(1 for s in status_list if s.last_analyzed is not None)
        st.metric("Analyzed Students", analyzed_students)

    st.divider()

    # Student status table
    for i, status in enumerate(status_list):
        with st.expander(f"📚 {status.student_name} ({status.student_id})", expanded=i==0):
            col1, col2, col3 = st.columns([3, 2, 1])

            with col1:
                st.write("**Current Learning State:**")

                # Make state editable
                edited_state = st.text_area(
                    "State",
                    value=status.current_state,
                    height=150,
                    key=f"state_edit_{status.student_id}",
                    disabled=False  # Changed to allow editing
                )

                # Save edited state button
                if edited_state != status.current_state:
                    if st.button("💾 Save State", key=f"save_state_{status.student_id}"):
                        if training_manager.update_student_state(master_id, status.student_id, edited_state):
                            st.success("State updated!")
                            st.rerun()
                        else:
                            st.error("Failed to update state")

            with col2:
                st.write("**Activity Info:**")
                if status.last_analyzed:
                    st.write(f"Last Analyzed: {status.last_analyzed.strftime('%Y-%m-%d %H:%M')}")
                else:
                    st.write("Last Analyzed: Never")

                st.write(f"Unanalyzed Messages: {status.unanalyzed_messages}")
                st.write(f"Total Conversations: {status.total_conversations}")

                if status.last_activity:
                    st.write(f"Last Activity: {status.last_activity.strftime('%Y-%m-%d %H:%M')}")

            with col3:
                st.write("**Actions:**")

                # Analyze button
                if st.button("🔍 Analyze", key=f"analyze_{status.student_id}"):
                    with st.spinner(f"Analyzing messages for {status.student_name}..."):
                        try:
                            # Run async analysis
                            async def analyze():
                                return await training_manager.analyze_student_messages(
                                    master_id, status.student_id
                                )

                            new_state, analyzed_msgs = asyncio.run(analyze())
                            st.success(f"Analyzed {len(analyzed_msgs)} messages!")
                            st.rerun()

                        except Exception as e:
                            st.error(f"Analysis failed: {str(e)}")

                # Clear button
                if st.button("🔄 Clear", key=f"clear_{status.student_id}"):
                    if training_manager.clear_student_state(master_id, status.student_id):
                        st.success("Student state cleared!")
                        st.rerun()

                # View details button
                if st.button("📋 Details", key=f"details_{status.student_id}"):
                    st.session_state.selected_student = status.student_id
                    st.rerun()

    # Student details view
    if "selected_student" in st.session_state:
        st.divider()
        selected_id = st.session_state.selected_student
        selected_student = next((s for s in status_list if s.student_id == selected_id), None)

        if selected_student:
            st.subheader(f"📋 Details for {selected_student.student_name}")

            # Show unanalyzed messages
            unanalyzed = training_manager.get_unanalyzed_messages(selected_id)
            if unanalyzed:
                st.write(f"**Unanalyzed Messages ({len(unanalyzed)}):**")
                for msg in unanalyzed[:10]:  # Show first 10
                    with st.expander(f"Message from {msg['timestamp'].strftime('%Y-%m-%d %H:%M')}"):
                        st.write(msg['message'])
            else:
                st.info("No unanalyzed messages.")

            if st.button("Close Details"):
                del st.session_state.selected_student
                st.rerun()


def render_state_history(master_id: str, training_manager):
    """Render state history interface."""
    st.header("📜 State History")

    # Get all students for this master
    students = training_manager.user_manager.get_children(master_id)

    if not students:
        st.info("No students found. Normal users assigned to you will appear here.")
        return

    # Student selection
    student_options = {s["id"]: f"{s['name']} ({s['id'][:8]}...)" for s in students}
    student_options[""] = "Select a student"

    selected_student_id = st.selectbox(
        "Select Student",
        options=list(student_options.keys()),
        format_func=lambda x: student_options[x],
        key="history_student_select"
    )

    if not selected_student_id:
        return

    # Get student info
    selected_student = next((s for s in students if s["id"] == selected_student_id), None)
    if not selected_student:
        st.error("Student not found")
        return

    st.subheader(f"History for {selected_student['name']}")

    # Get state history
    history_entries = training_manager.get_student_state_history(master_id, selected_student_id, limit=100)

    if not history_entries:
        st.info("No state history found for this student.")

        # Show current state
        current_state = training_manager.get_student_state(master_id, selected_student_id)
        if current_state:
            with st.expander("Current State"):
                st.text_area("Current Learning State", value=current_state.get("current_state", ""), height=200, disabled=True)

        return

    # History metrics
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total History Entries", len(history_entries))
    with col2:
        manual_updates = sum(1 for h in history_entries if h.metadata.get("update_type") == "manual")
        st.metric("Manual Updates", manual_updates)
    with col3:
        auto_updates = sum(1 for h in history_entries if h.metadata.get("update_type") == "auto_analysis")
        st.metric("Auto Analyses", auto_updates)

    st.divider()

    # Current state display
    current_state = training_manager.get_student_state(master_id, selected_student_id)
    if current_state:
        with st.expander("📋 Current State", expanded=True):
            st.text_area("Current Learning State",
                        value=current_state.get("current_state", ""),
                        height=200,
                        key="current_state_display",
                        disabled=True)

    st.divider()

    # History entries
    st.write("### 📜 State History Timeline")

    for i, entry in enumerate(history_entries):
        with st.expander(f"📅 {entry.created_at.strftime('%Y-%m-%d %H:%M:%S')} - {entry.change_reason}", expanded=i < 3):
            col1, col2 = st.columns(2)

            with col1:
                st.write("**Previous State:**")
                if entry.previous_state:
                    st.text_area("Previous",
                                value=entry.previous_state,
                                height=150,
                                key=f"prev_{entry.id}",
                                disabled=True)
                else:
                    st.info("No previous state (initial entry)")

            with col2:
                st.write("**New State:**")
                st.text_area("New",
                            value=entry.new_state,
                            height=150,
                            key=f"new_{entry.id}",
                            disabled=True)

            # Entry details
            col3, col4, col5 = st.columns(3)
            with col3:
                st.write(f"**Messages Analyzed:** {entry.analyzed_message_count}")
            with col4:
                update_type = entry.metadata.get("update_type", "unknown")
                st.write(f"**Type:** {update_type}")
            with col5:
                # Revert button for entries that aren't already reverts
                if update_type != "revert" and entry.previous_state:
                    if st.button("⏮️ Revert to This", key=f"revert_{entry.id}"):
                        with st.spinner(f"Reverting to state from {entry.created_at.strftime('%Y-%m-%d %H:%M')}..."):
                            success, reverted_state = training_manager.revert_to_previous_state(
                                master_id, selected_student_id, entry.id
                            )
                            if success:
                                st.success(f"Reverted to previous state!")
                                st.rerun()
                            else:
                                st.error("Failed to revert to previous state")

    # Clear history button
    st.divider()
    st.write("### 🗑️ History Management")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("🗑️ Clear All History", type="secondary"):
            if st.checkbox("I'm sure I want to clear all history for this student"):
                if training_manager.clear_student_state_history(master_id, selected_student_id):
                    st.success("History cleared!")
                    st.rerun()
                else:
                    st.error("Failed to clear history")

    with col2:
        # Export history button
        if st.button("📥 Export History"):
            import json
            from datetime import datetime

            # Prepare export data
            export_data = {
                "student_id": selected_student_id,
                "student_name": selected_student["name"],
                "exported_at": datetime.utcnow().isoformat(),
                "history_entries": [
                    {
                        "id": entry.id,
                        "previous_state": entry.previous_state,
                        "new_state": entry.new_state,
                        "change_reason": entry.change_reason,
                        "analyzed_message_count": entry.analyzed_message_count,
                        "created_at": entry.created_at.isoformat(),
                        "metadata": entry.metadata
                    }
                    for entry in history_entries
                ]
            }

            # Create download link
            st.download_button(
                label="Download JSON",
                data=json.dumps(export_data, indent=2, ensure_ascii=False),
                file_name=f"state_history_{selected_student_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json"
            )


def render_training_config(master_id: str, training_manager):
    """Render training configuration interface."""
    st.header("⚙️ Training Configuration")

    # Get current config
    current_config = training_manager.get_master_config(master_id)

    # Configuration form
    with st.form("training_config_form"):
        st.write("### System Prompt")
        system_prompt = st.text_area(
            "System prompt for student conversations",
            value=current_config["system_prompt"] if current_config else "",
            height=100,
            key="system_prompt"
        )

        st.write("### Learning Path")
        learning_path = st.text_area(
            "Learning path structure (can be hierarchical)",
            value=current_config["learning_path"] if current_config else "",
            height=100,
            key="learning_path"
        )

        st.write("### Analyzer Prompt")
        st.info("Fixed prompt from system configuration")
        analyzer_prompt = st.text_area(
            "Prompt for analyzing student messages",
            value=get_prompt("training.training.analyzer_prompt_default", "ERROR"),
            height=150,
            key="analyzer_prompt",
            disabled=True  # Not editable
        )

        st.write("### Merging Prompt")
        st.info("Fixed prompt from system configuration")
        merging_prompt = st.text_area(
            "Prompt for merging analysis with existing state",
            value=get_prompt("training.training.merging_prompt_default", "ERROR"),
            height=150,
            key="merging_prompt",
            disabled=True  # Not editable
        )

        # Submit button
        submitted = st.form_submit_button("💾 Save Configuration")

        if submitted:
            try:
                # Use the fixed prompts from get_prompt
                config_id = training_manager.save_master_config(
                    master_id,
                    system_prompt,
                    learning_path,
                    get_prompt("training.training.analyzer_prompt_default", "ERROR"),
                    get_prompt("training.training.merging_prompt_default", "ERROR")
                )
                st.success("Configuration saved successfully!")

            except Exception as e:
                st.error(f"Failed to save configuration: {str(e)}")

    # Configuration tips
    with st.expander("💡 Configuration Tips"):
        st.write("""
        **System Prompt:** Guides how the AI should interact with students.
        **Learning Path:** Defines the progression structure for students.
        **Analyzer Prompt:** Fixed system prompt for analyzing messages.
        **Merging Prompt:** Fixed system prompt for updating learning state.

        Note: Analyzer and Merging prompts are system-wide and cannot be modified.
        """)


def inject_student_context_callback(user_id: str, messages: List[dict]) -> str:
    """Callback to inject student learning state into LLM context."""
    training_manager = get_training_manager()
    return training_manager.get_student_state_for_injection(user_id)


def initialize():
    """Initialize the training module."""
    # Register cleanup callbacks
    training_manager = get_training_manager()
    user_manager = get_user_manager()

    # Register cleanup for when users are deleted
    user_manager.register_before_delete_callback(training_manager.cleanup_student_data)
    user_manager.register_before_delete_callback(training_manager.cleanup_master_data)

    # Register LLM context injection callback
    register_llm_callback(inject_student_context_callback)

    log("debug", "Training module initialized")

initialize()
