"""
Training Export/Import UI Module
================================

Provides UI components for exporting and importing training sessions.
Injects into training admin interface.
"""

import streamlit as st
import tempfile
import os
import asyncio
from datetime import datetime
from typing import List, Optional, Dict, Any

from shared.common import log, get_user_manager, UserRole, get_conversation_manager
from modules.training.training_logic import get_training_manager
from modules.training.training_export_import import (
    training_exporter, training_importer, training_replayer,
    export_training_session_to_file, import_training_session_from_file,
    replay_training_session_from_file
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
    return ("📤 Export/Import/Replay", render_training_export_tab)


def render_training_export_tab(master_id: str):
    """Render training export/import/replay interface."""
    training_manager = get_training_manager()
    user_manager = get_user_manager()

    st.header("📤 Training Session Export/Import/Replay")

    # Get all students for this master
    students = user_manager.get_children(master_id)

    if not students:
        st.info("No students found. Normal users assigned to you will appear here.")
        return

    # Create tabs for Export, Import, and Replay
    export_tab, import_tab, replay_tab = st.tabs([
        "📤 Export Training",
        "📥 Import Training",
        "🔁 Replay Training"  # NEW TAB
    ])

    with export_tab:
        render_export_section(master_id, students)

    with import_tab:
        render_import_section(master_id)

    with replay_tab:  # NEW: Replay tab
        render_replay_section(master_id)


def render_export_section(master_id: str, students: List[Dict]):
    """Render export interface."""
    st.subheader("Export Training Session")

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

    # Get session statistics
    training_manager = get_training_manager()

    # Get conversation count
    conv_manager = get_conversation_manager()
    conversations = conv_manager.get_user_conversations(selected_student_id, include_inactive=True)

    # Get state history count
    state_history = training_manager.get_student_state_history(master_id, selected_student_id, limit=1000)

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
        yaml_data = training_exporter.export_training_session(master_id, selected_student_id)
        if yaml_data:
            with st.expander("Export Preview", expanded=True):
                st.code(yaml_data, language="yaml")
        else:
            st.error("Failed to generate export preview")

    # Export button
    if st.button("📥 Download Export", type="primary"):
        yaml_data = training_exporter.export_training_session(master_id, selected_student_id)
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
                filename = f"training_{selected_student['name']}_{timestamp}.yaml"

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

    **Preserves original LLM responses and state updates.**
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
                    try:
                        # Run async import
                        async def run_import():
                            return await import_training_session_from_file(
                                file_path, master_id, target_student_id
                            )

                        result = asyncio.run(run_import())

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

                    except Exception as e:
                        st.error(f"❌ Import error: {str(e)}")
                    finally:
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


def render_replay_section(master_id: str):
    """Render replay interface."""
    st.subheader("🔁 Replay Training Session")

    st.info("""
    **Replay** a training session with the CURRENT LLM:

    1. Creates a new student for comparison
    2. Processes events in chronological order
    3. **Regenerates all LLM responses** using current LLM
    4. **Regenerates all state updates** using current LLM
    5. Perfect for comparing different LLMs on the same scenario

    ⚠️ **Note**: This will use API credits for the current LLM!
    """)

    # File uploader
    uploaded_file = st.file_uploader(
        "Choose a training session YAML file to replay",
        type=['yaml', 'yml'],
        key="training_replay_file"
    )

    if uploaded_file is not None:
        # Preview
        try:
            content = uploaded_file.getvalue().decode('utf-8')
            import yaml
            data = yaml.safe_load(content)

            st.success("✅ Valid training session file detected")

            # Get current LLM info
            from shared.common import get_current_llm_info
            current_llm = get_current_llm_info()
            current_llm_name = current_llm.get("name", "Unknown") if current_llm else "Unknown"

            # Display preview
            with st.expander("Replay Details", expanded=True):
                col1, col2 = st.columns(2)

                with col1:
                    st.write("**Original Session:**")
                    student_info = data.get("student_info", {})
                    st.write(f"Student: {student_info.get('student_name', 'Unknown')}")

                    # Count event types
                    events = data.get("training_session", [])
                    event_counts = {}
                    for event in events:
                        event_type = event.get("event_type", "unknown")
                        event_counts[event_type] = event_counts.get(event_type, 0) + 1

                    st.write(f"Conversations: {event_counts.get('conversation_start', 0)}")
                    st.write(f"User Messages: {event_counts.get('user_message', 0)}")
                    st.write(f"LLM Responses: {event_counts.get('llm_response', 0)}")
                    st.write(f"State Updates: {event_counts.get('state_update', 0)}")

                with col2:
                    st.write("**Replay Settings:**")
                    st.write(f"Current LLM: **{current_llm_name}**")
                    st.write("Mode: **Regenerate all LLM content**")
                    st.write("Order: **Chronological processing**")

                # Warning about costs
                if current_llm and current_llm.get("requires_api_key", False):
                    st.warning("⚠️ **API Costs Warning**: Replay will generate new LLM responses using the current API. This may incur costs.")

            # REPLAY OPTIONS - ADDED LIKE IMPORT HAS
            st.write("### Replay Options")

            col_opt1, col_opt2 = st.columns(2)

            with col_opt1:
                replay_option = st.radio(
                    "Replay as:",
                    ["New Student", "Existing Student"],
                    index=0,
                    key="replay_option"
                )

            with col_opt2:
                if replay_option == "Existing Student":
                    # Get existing students
                    user_manager = get_user_manager()
                    students = user_manager.get_children(master_id)

                    if students:
                        student_options = {s["id"]: s["name"] for s in students}
                        selected_existing = st.selectbox(
                            "Select existing student",
                            options=list(student_options.keys()),
                            format_func=lambda x: student_options[x],
                            key="replay_existing_student"
                        )
                        target_student_id = selected_existing
                    else:
                        st.warning("No existing students found")
                        target_student_id = None
                else:
                    target_student_id = None

            # Replay button
            if st.button("🔁 Start Replay", type="primary",
                        disabled=replay_option == "Existing Student" and not target_student_id,
                        key="start_replay_button"):
                # Save uploaded file temporarily
                with tempfile.NamedTemporaryFile(mode='wb', suffix='.yaml', delete=False) as tmp:
                    tmp.write(uploaded_file.getvalue())
                    file_path = tmp.name

                # Replay training session
                with st.spinner("Replaying training session with current LLM..."):
                    try:
                        # Run async replay
                        async def run_replay():
                            return await replay_training_session_from_file(
                                file_path, master_id, target_student_id
                            )

                        result = asyncio.run(run_replay())

                        if result.get("success"):
                            st.success("✅ Training session replayed successfully!")

                            # Show results
                            st.write("**Replay Results:**")
                            col_res1, col_res2, col_res3, col_res4 = st.columns(4)
                            with col_res1:
                                st.metric("Student", result.get("student_name", "Unknown"))
                            with col_res2:
                                st.metric("Conversations", result.get("conversations_created", 0))
                            with col_res3:
                                st.metric("LLM Responses", result.get("llm_responses_regenerated", 0))
                            with col_res4:
                                st.metric("State Updates", result.get("state_updates_regenerated", 0))

                            # Show comparison info
                            with st.expander("🔍 Comparison Notes", expanded=True):
                                st.write("""
                                **How to compare with original:**
                                1. Go to **Training Dashboard**
                                2. Find the new replay student (prefixed with "Replay:")
                                3. Compare responses and state updates with original
                                4. Use the **State History** tab to see regenerated states

                                **Key differences from import:**
                                - LLM responses regenerated with current LLM
                                - State updates recalculated based on new responses
                                - Perfect for A/B testing different LLMs
                                """)

                            log("info", f"Replayed training session for master {master_id}, student {result.get('student_id')}")

                            # Option to view the replayed student
                            if st.button("View Replay Student", key="view_replay_student"):
                                st.session_state.training_tab = "dashboard"
                                st.session_state.selected_student = result.get("student_id")
                                st.rerun()
                        else:
                            st.error(f"❌ Replay failed: {result.get('error', 'Unknown error')}")

                    except Exception as e:
                        st.error(f"❌ Replay error: {str(e)}")
                    finally:
                        # Clean up temp file
                        try:
                            os.unlink(file_path)
                        except:
                            pass
        except Exception as e:
            st.error(f"Error reading file: {str(e)}")

    # Clear button
    if st.button("Clear Replay File", key="clear_replay_file"):
        if "training_replay_file" in st.session_state:
            del st.session_state.training_replay_file
        st.rerun()
