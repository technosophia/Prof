"""
Training Export/Import UI Module
================================

Provides UI components for exporting and importing training sessions.
Injects into training admin interface.
"""

import streamlit as st
import tempfile
import os
from datetime import datetime
from typing import List, Optional, Dict, Any

from shared.common import log, get_user_manager, UserRole, get_conversation_manager
from modules.training.training_logic import get_training_manager
from modules.training.training_export_import import (
    training_exporter, training_importer,
    export_training_session_to_file, import_training_session_from_file
)


def inject_training_export_tab():
    """Add export/import tab to training interface."""
    if not st.session_state.get("current_user"):
        return None

    user_id = st.session_state.current_user['id']
    user_role = st.session_state.current_user['role']

    if user_role != UserRole.MASTER.value:
        return None

    # Add as a tab in the training interface
    # This would be integrated into the existing tab structure
    return ("📤 Export/Import", render_training_export_tab)


def render_training_export_tab(master_id: str):
    """Render training export/import interface."""
    training_manager = get_training_manager()
    user_manager = get_user_manager()

    st.header("📤 Training Session Export/Import")

    # Get all students for this master
    students = user_manager.get_children(master_id)

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
        key="export_student_select"
    )

    if not selected_student_id:
        return

    selected_student = next((s for s in students if s["id"] == selected_student_id), None)
    if not selected_student:
        st.error("Student not found")
        return

    # Create tabs for Export and Import
    export_tab, import_tab = st.tabs(["📤 Export Training", "📥 Import Training"])

    with export_tab:
        render_export_section(master_id, selected_student_id, selected_student)

    with import_tab:
        render_import_section(master_id)


def render_export_section(master_id: str, student_id: str, student_info: Dict[str, Any]):
    """Render export interface."""
    st.subheader(f"Export Training Session for {student_info['name']}")

    # Get session statistics
    training_manager = get_training_manager()

    # Get conversation count
    conv_manager = get_conversation_manager()
    conversations = conv_manager.get_user_conversations(student_id, include_inactive=True)

    # Get state history count
    state_history = training_manager.get_student_state_history(master_id, student_id, limit=1000)

    # Display statistics
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Conversations", len(conversations))
    with col2:
        st.metric("State Updates", len(state_history))
    with col3:
        total_messages = sum(conv.get("message_count", 0) for conv in conversations)
        st.metric("Total Messages", total_messages)

    # Export options
    with st.expander("Export Options", expanded=True):
        col_opt1, col_opt2 = st.columns(2)

        with col_opt1:
            include_inactive = st.checkbox("Include inactive conversations", value=True)
            include_metadata = st.checkbox("Include metadata", value=True)

        with col_opt2:
            export_format = st.selectbox(
                "Export Format",
                ["YAML", "JSON"],
                index=0
            )

    # Preview button
    if st.button("👁️ Preview Export", type="secondary"):
        yaml_data = training_exporter.export_training_session(master_id, student_id)
        if yaml_data:
            with st.expander("Export Preview", expanded=True):
                st.code(yaml_data, language="yaml")
        else:
            st.error("Failed to generate export preview")

    # Export button
    if st.button("📥 Download Export", type="primary"):
        yaml_data = training_exporter.export_training_session(master_id, student_id)
        if yaml_data:
            # Create temporary file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp:
                file_path = tmp.name

            # Save to file
            if training_exporter.save_to_file(yaml_data, file_path):
                # Read file and create download button
                with open(file_path, 'rb') as f:
                    file_data = f.read()

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"training_{student_info['name']}_{timestamp}.yaml"

                st.download_button(
                    label="Click to download",
                    data=file_data,
                    file_name=filename,
                    mime="application/x-yaml",
                    key="download_training_export"
                )

                # Clean up temp file
                try:
                    os.unlink(file_path)
                except:
                    pass
            else:
                st.error("Failed to save export file")
        else:
            st.error("Failed to generate export data")


def render_import_section(master_id: str):
    """Render import interface."""
    st.subheader("Import Training Session")

    st.info("""
    Import a training session export file. This will:
    1. Create a new student (or use existing)
    2. Import all conversations with messages
    3. Import all state updates
    4. Re-link messages to their analyzed states
    """)

    # File uploader
    uploaded_file = st.file_uploader(
        "Choose a training session YAML file",
        type=['yaml', 'yml'],
        key="training_import_file"
    )

    if uploaded_file is not None:
        # Preview
        try:
            content = uploaded_file.getvalue().decode('utf-8')
            import yaml
            data = yaml.safe_load(content)

            st.success("✅ Valid training session file detected")

            # Display preview
            with st.expander("Preview Import Details", expanded=True):
                col1, col2 = st.columns(2)

                with col1:
                    st.write("**Master Configuration:**")
                    master_config = data.get("master_config", {})
                    st.write(f"System Prompt: {len(master_config.get('system_prompt', ''))} chars")
                    st.write(f"Learning Path: {len(master_config.get('learning_path', ''))} chars")

                with col2:
                    st.write("**Student Information:**")
                    student_info = data.get("student_info", {})
                    st.write(f"Name: {student_info.get('student_name', 'Unknown')}")
                    st.write(f"Original ID: {student_info.get('student_id', 'Unknown')}")

                st.write("**Session Statistics:**")
                events = data.get("training_session", [])

                # Count event types
                event_counts = {}
                for event in events:
                    event_type = event.get("event_type", "unknown")
                    event_counts[event_type] = event_counts.get(event_type, 0) + 1

                col_stat1, col_stat2, col_stat3, col_stat4 = st.columns(4)
                with col_stat1:
                    st.metric("Conversations", event_counts.get("conversation_start", 0))
                with col_stat2:
                    st.metric("User Messages", event_counts.get("user_message", 0))
                with col_stat3:
                    st.metric("LLM Responses", event_counts.get("llm_response", 0))
                with col_stat4:
                    st.metric("State Updates", event_counts.get("state_update", 0))

            # Import options
            st.write("### Import Options")

            col_opt1, col_opt2 = st.columns(2)

            with col_opt1:
                import_option = st.radio(
                    "Import as:",
                    ["New Student", "Existing Student"],
                    index=0
                )

            with col_opt2:
                if import_option == "Existing Student":
                    # Get existing students
                    user_manager = get_user_manager()
                    students = user_manager.get_children(master_id)

                    if students:
                        student_options = {s["id"]: s["name"] for s in students}
                        selected_existing = st.selectbox(
                            "Select existing student",
                            options=list(student_options.keys()),
                            format_func=lambda x: student_options[x]
                        )
                        target_student_id = selected_existing
                    else:
                        st.warning("No existing students found")
                        target_student_id = None
                else:
                    target_student_id = None

            # Import button
            if st.button("📥 Import Training Session", type="primary",
                        disabled=import_option == "Existing Student" and not target_student_id):
                # Save uploaded file temporarily
                with tempfile.NamedTemporaryFile(mode='wb', suffix='.yaml', delete=False) as tmp:
                    tmp.write(uploaded_file.getvalue())
                    file_path = tmp.name

                # Import training session
                with st.spinner("Importing training session..."):
                    result = import_training_session_from_file(
                        file_path, master_id, target_student_id
                    )

                    if result.get("success"):
                        st.success("✅ Training session imported successfully!")

                        # Show results
                        st.write("**Import Results:**")
                        col_res1, col_res2, col_res3 = st.columns(3)
                        with col_res1:
                            st.metric("Student", result.get("student_name", "Unknown"))
                        with col_res2:
                            st.metric("Conversations", result.get("conversations_created", 0))
                        with col_res3:
                            st.metric("State Updates", result.get("state_updates_imported", 0))

                        log("info", f"Imported training session for master {master_id}, student {result.get('student_id')}")

                        # Option to view the imported student
                        if st.button("View Imported Student"):
                            st.session_state.training_tab = "dashboard"
                            st.session_state.selected_student = result.get("student_id")
                            st.rerun()
                    else:
                        st.error(f"❌ Import failed: {result.get('error', 'Unknown error')}")

                # Clean up temp file
                try:
                    os.unlink(file_path)
                except:
                    pass

        except Exception as e:
            st.error(f"Error reading file: {str(e)}")

    # Clear button
    if st.button("Clear Upload"):
        if "training_import_file" in st.session_state:
            del st.session_state.training_import_file
        st.rerun()
