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

from modules.training.training_logic import get_training_manager, StudentStatus


def inject_ui_sidebar():
    """Inject training options into sidebar for master users."""
    user_manager = get_user_manager()

    if "current_user" in st.session_state and st.session_state.current_user:
        user_id = st.session_state.current_user['id']
        user_role = st.session_state.current_user['role']

        if user_role == UserRole.MASTER.value:
            st.sidebar.divider()
            st.sidebar.subheader("🎓 Training Module")

            if st.sidebar.button("Training Dashboard", key="training_dashboard"):
                st.session_state.training_tab = "dashboard"
                st.rerun()

            if st.sidebar.button("Training Configuration", key="training_config"):
                st.session_state.training_tab = "config"
                st.rerun()


def inject_ui_main_content():
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
    tab1, tab2 = st.tabs(["📊 Training Dashboard", "⚙️ Configuration"])

    with tab1:
        render_training_dashboard(user_id, training_manager)

    with tab2:
        render_training_config(user_id, training_manager)


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
                st.text_area(
                    "State",
                    value=status.current_state,
                    height=150,
                    key=f"state_view_{status.student_id}",
                    disabled=True
                )

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


def render_training_config(master_id: str, training_manager):
    """Render training configuration interface."""
    st.header("⚙️ Training Configuration")

    # Get current config
    current_config = training_manager.get_master_config(master_id)
    config_section = get_section("training")

    # Configuration form
    with st.form("training_config_form"):
        st.write("### System Prompt")
        system_prompt = st.text_area(
            "System prompt for student conversations",
            value=current_config["system_prompt"] if current_config else config_section.get("default_system_prompt", ""),
            height=100,
            key="system_prompt"
        )

        st.write("### Learning Path")
        learning_path = st.text_area(
            "Learning path structure (can be hierarchical)",
            value=current_config["learning_path"] if current_config else config_section.get("default_learning_path", ""),
            height=100,
            key="learning_path"
        )

        st.write("### Analyzer Prompt")
        analyzer_prompt = st.text_area(
            "Prompt for analyzing student messages",
            value=current_config["analyzer_prompt"] if current_config else config_section.get("default_analyzer_prompt", ""),
            height=150,
            key="analyzer_prompt"
        )

        st.write("### Merging Prompt")
        merging_prompt = st.text_area(
            "Prompt for merging analysis with existing state",
            value=current_config["merging_prompt"] if current_config else config_section.get("default_merging_prompt", ""),
            height=150,
            key="merging_prompt"
        )

        # Auto-analysis settings
        st.write("### Auto-analysis Settings")
        auto_analyze = st.checkbox(
            "Enable automatic analysis",
            value=True,
            help="Automatically analyze messages periodically"
        )

        if auto_analyze:
            interval = st.slider(
                "Analysis interval (messages)",
                min_value=1,
                max_value=20,
                value=config_section.get("auto_analyze_interval", 5),
                help="Analyze after this many unanalyzed messages"
            )

        # Submit button
        submitted = st.form_submit_button("💾 Save Configuration")

        if submitted:
            try:
                config_id = training_manager.save_master_config(
                    master_id,
                    system_prompt,
                    learning_path,
                    analyzer_prompt,
                    merging_prompt
                )
                st.success("Configuration saved successfully!")

                # Update session state
                if auto_analyze:
                    st.session_state.auto_analyze = True
                    st.session_state.analyze_interval = interval

            except Exception as e:
                st.error(f"Failed to save configuration: {str(e)}")

    # Configuration tips
    with st.expander("💡 Configuration Tips"):
        st.write("""
        **System Prompt:** Guides how the AI should interact with students.
        **Learning Path:** Defines the progression structure for students.
        **Analyzer Prompt:** Specifies what to look for in student messages.
        **Merging Prompt:** Determines how to update the student's learning state.

        Best practices:
        1. Be specific in your analyzer prompt about what constitutes learning
        2. Keep learning paths flexible to accommodate different paces
        3. Test your prompts with sample student messages
        4. Review merged states regularly for accuracy
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

    log("info", "Training module initialized")
