"""
Trainer module admin UI injection.
Implements admin interface with role-based access control.
Must be in a file ending with _ui.py with inject_ui_admin_tab() function.
"""

import streamlit as st
import yaml
from typing import Optional, Dict, Any, List, Callable
from datetime import datetime

from shared.common import get_prompt, UserRole
from st_shared.cached import get_user_manager, get_config, get_db_manager, get_conversation_manager
from modules.trainer.manager import get_trainer_manager
from modules.trainer.plugin_base import get_plugin_manager

from core.logging import log, set_log_module_level
from st_shared.cached import _
def set_training_program(trainer_id: str, program_content: str):
    """Save training program using prompt manager."""
    from shared.common import save_prompt
    from st_shared.cached import get_prompt_manager

    try:
        # Save using the full prompt key
        success = save_prompt('trainer.teacher.training_program', program_content, language='en')

        if success:
            log("info", f"Training program saved successfully for trainer {trainer_id}")

            # Reload prompts to ensure all components see the update
            pm = get_prompt_manager()
            pm.reload_prompts()

            return True
        else:
            log("error", f"Failed to save training program for trainer {trainer_id}")
            return False

    except Exception as e:
        log("error", f"Error saving training program: {str(e)}")
        return False

def inject_ui_admin_tab():
    """
    Inject Trainer admin tab - only visible for masters.
    This is the required injection point for admin tabs.
    """
    if not ("current_user" in st.session_state and st.session_state.current_user):
        return

    user_id = st.session_state.current_user['id']
    user_role = st.session_state.current_user['role']

    if user_role != UserRole.MASTER.value:
        return

    def render_trainer_admin():
        st.header("🎓 Trainer Module")

        trainer_id = st.session_state.current_user['id']
        trainer_manager = get_trainer_manager()
        plugin_manager = get_plugin_manager()

        # Create base tabs
        tab_names = [
            "User Dashboard",
            "Plugin Dashboard",
            "Configuration",
            "Plugins"
        ]

        # Add plugin tabs from active plugins
        active_plugins = plugin_manager.get_active_ui_plugins(trainer_id)
        plugin_tabs = []
        for plugin in active_plugins:
            plugin_tabs.extend(plugin.render_get_admin_tabs(trainer_id))

        all_tab_names = tab_names + [name for name, _ in plugin_tabs]
        tabs = st.tabs(all_tab_names)

        # Dashboard tab
        with tabs[0]:
            _render_user_dashboard_tab(trainer_id, trainer_manager, plugin_manager)

        with tabs[1]:
            _render_plugin_dashboard_tab(trainer_id, trainer_manager, plugin_manager)

        # Configuration tab
        with tabs[2]:
            _render_configuration_tab(trainer_id, trainer_manager, plugin_manager)

        # Plugins management tab
        with tabs[3]:
            _render_plugins_tab(trainer_id, trainer_manager, plugin_manager)

        # Plugin tabs
        for idx, (_, render_func) in enumerate(plugin_tabs, start=len(tab_names)):
            with tabs[idx]:
                render_func()

    return ("Trainer", render_trainer_admin)


def _display_plugin_detailed_view(trainer_id: str, student: Dict[str, Any],
                                   plugin_manager, trainer_manager) -> None:
    """
    Display detailed views for all active plugins that provide student widgets.

    This function dynamically discovers and renders all plugin-specific student views,
    creating a tab for each plugin that implements render_student_widgets.

    Args:
        trainer_id: The trainer's ID
        student: The student dictionary with user information
        plugin_manager: The plugin manager instance
        trainer_manager: The trainer manager instance
    """
    # Get all active plugins that implement student widgets
    active_plugins = plugin_manager.get_ui_plugins_by_hook(trainer_id, "render_student_widgets")

    if not active_plugins:
        st.info("No active plugins provide student views. Activate plugins in the Plugins tab.")
        return

    # Create a tab for each plugin that provides student widgets
    plugin_tabs_data = []
    for plugin in active_plugins:
        # Get the plugin's student widgets
        widgets = plugin.render_student_widgets(trainer_id, student)
        if widgets:  # Only add tab if plugin actually returns widgets
            # Use plugin name from manifest for the tab title
            tab_name = plugin.manifest.name
            plugin_tabs_data.append((tab_name, widgets, plugin))

    if not plugin_tabs_data:
        st.info("Active plugins don't provide student views for this student.")
        return

    # Create tabs with plugin names
    tab_names = [name for name, _, _ in plugin_tabs_data]
    tabs = st.tabs(tab_names)

    # Render each plugin's widgets in its respective tab
    for idx, (_, widgets, plugin) in enumerate(plugin_tabs_data):
        with tabs[idx]:
            # Optional: Add plugin description or header
            st.markdown(f"### {plugin.manifest.name}")
            if plugin.manifest.description:
                st.caption(plugin.manifest.description)

            # Render all widgets from this plugin
            for widget in widgets:
                widget()


def _render_user_dashboard_tab(trainer_id: str, trainer_manager, plugin_manager):
    """Render the students dashboard."""
    st.subheader("Students")

    user_manager = get_user_manager()

    # Get students (list of user objects from get_children)
    student_objects = trainer_manager.get_trainer_students(trainer_id)

    if not student_objects:
        st.info("No students assigned yet.")
        return

    # Add conversation stats
    students = []
    for student in student_objects:
        student['conversation_count'] = trainer_manager.get_student_conversation_count(trainer_id, student['id'])
        student['total_messages'] = trainer_manager.get_student_message_count(trainer_id, student['id'])
        student['last_active'] = trainer_manager.get_student_last_active(student['id'])
        students.append(student)

    # Display student cards
    for student in students:
        with st.container():
            col1, col2, col3, col4 = st.columns([3, 2, 2, 1])

            with col1:
                st.markdown(f"**{student.get('name', 'Unknown')}**")
                email = student.get('email')
                if email:
                    st.caption(email)

            with col2:
                st.metric(
                    "Conversations",
                    student.get('conversation_count', 0)
                )

            with col3:
                st.metric(
                    "Messages",
                    student.get('total_messages', 0)
                )

            with col4:
                if st.button("View", key=f"view_{trainer_id}_{student['id']}"):
                    st.session_state[f'selected_student_{trainer_id}'] = student['id']
                    st.session_state[f'selected_student_name_{trainer_id}'] = student.get('name', 'Unknown')
                    st.rerun()

            # Show student details if selected
            if st.session_state.get(f'selected_student_{trainer_id}') == student['id']:
                # Use a generic expander title without plugin-specific knowledge
                student_name = st.session_state.get(f'selected_student_name_{trainer_id}', '')
                with st.expander(f"📋 {student_name} - Student Details", expanded=True):
                    # Create tabs for basic profile and plugin-specific views
                    tab_names = ["Profile"]

                    # Get active plugins that implement student widgets
                    active_plugins = plugin_manager.get_ui_plugins_by_hook(trainer_id, "render_student_widgets")
                    tab_names.extend([plugin.manifest.name for plugin in active_plugins if
                                    plugin.render_student_widgets(trainer_id, student)])

                    # Create all tabs
                    detail_tabs = st.tabs(tab_names)

                    # Profile tab (always first)
                    with detail_tabs[0]:
                        col1, col2 = st.columns(2)
                        with col1:
                            st.write("**Student Information:**")
                            st.write(f"ID: {student['id']}")
                            st.write(f"Email: {student.get('email', 'N/A')}")
                            if student.get('last_active'):
                                last_active = student['last_active']
                                if hasattr(last_active, 'strftime'):
                                    last_active = last_active.strftime('%Y-%m-%d %H:%M')
                                st.write(f"Last Active: {last_active}")

                        with col2:
                            st.write("**Statistics:**")
                            st.write(f"Conversations: {student.get('conversation_count', 0)}")
                            st.write(f"Total Messages: {student.get('total_messages', 0)}")

                    # Plugin-specific tabs (starting from index 1)
                    plugin_idx = 1
                    for plugin in active_plugins:
                        widgets = plugin.render_student_widgets(trainer_id, student)
                        if widgets:
                            with detail_tabs[plugin_idx]:
                                # Optional: Add plugin header
                                st.markdown(f"### {plugin.manifest.name}")
                                if plugin.manifest.description:
                                    st.caption(plugin.manifest.description)
                                st.divider()

                                # Render all widgets from this plugin
                                for widget in widgets:
                                    widget()
                            plugin_idx += 1


def _render_plugin_dashboard_tab(trainer_id: str, trainer_manager, plugin_manager):
    """Render the students dashboard."""
    st.subheader("Students")

    user_manager = get_user_manager()

    # Get students (list of user objects from get_children)
    student_objects = trainer_manager.get_trainer_students(trainer_id)

    if not student_objects:
        st.info("No students assigned yet.")
        return

    # Add conversation stats
    students = []
    for student in student_objects:
        student['conversation_count'] = trainer_manager.get_student_conversation_count(trainer_id, student['id'])
        student['total_messages'] = trainer_manager.get_student_message_count(trainer_id, student['id'])
        student['last_active'] = trainer_manager.get_student_last_active(student['id'])
        students.append(student)

    # Plugin dashboard widgets (non-student specific)
    active_plugins = plugin_manager.get_active_ui_plugins(trainer_id)
    for plugin in active_plugins:
        widgets = plugin.render_dashboard_widgets(trainer_id, students)
        for widget in widgets:
            widget()

def _render_configuration_tab(trainer_id: str, trainer_manager, plugin_manager):
    """Render the configuration tab with training program and student context."""

    st.subheader("System Prompt")

    current_prompt = get_prompt('trainer.teacher.system_prompt')
    st.info(current_prompt)

    st.divider()
    st.subheader("Training Program")

    # Get current training program
    current_program = get_prompt('trainer.teacher.training_program')

    # Editable text area for training program
    new_program = st.text_area(
        "Training Program Content",
        value=current_program,
        height=200,
        help="This program defines the training approach and will be available to all plugins"
    )

    # Save button
    col1, col2 = st.columns([1, 3])
    with col1:
        if st.button("Save Training Program", type="primary", use_container_width=True):
            set_training_program(trainer_id, new_program)
            st.success("Training program saved successfully!")
            st.rerun()

    with col2:
        if st.button("Reset to Default", use_container_width=True):
            default_program = get_prompt('teacher.training_program')
            set_training_program(trainer_id, default_program)
            st.success("Reset to default training program!")
            st.rerun()

    st.divider()
    st.subheader("Student Context Preview")
    st.caption("View the aggregated context information for a student from all active plugins.")

    # Get students for selection
    students = trainer_manager.get_trainer_students(trainer_id)

    if students:
        # Create a mapping of student IDs to display names
        student_options = {student['id']: student.get('name', 'Unknown') for student in students}

        selected_student_id = st.selectbox(
            "Select Student to View Context",
            options=list(student_options.keys()),
            format_func=lambda x: student_options[x],
            key="context_student_select"
        )

        if selected_student_id:
            # Get all contexts for the selected student
            contexts = trainer_manager.get_all_contexts(selected_student_id)

            if contexts:
                # Create tabs for each context source
                context_sources = list(contexts.keys())
                context_tabs = st.tabs(context_sources)

                for i, source in enumerate(context_sources):
                    with context_tabs[i]:
                        context_data = contexts[source]

                        # Display as a nice table
                        if context_data:
                            # Convert to list of dicts for table display
                            table_data = []
                            for key, value in context_data.items():
                                table_data.append({"Context Key": key, "Context Value": value})

                            st.table(table_data)
                        else:
                            st.info(f"No context data available from {source}")
            else:
                st.info("No context information available for this student.")
    else:
        st.info("No students available to view context.")

def _render_plugins_tab(trainer_id: str, trainer_manager, plugin_manager):
    """Render the plugins management tab."""
    st.subheader("Plugin Management")

    plugins = plugin_manager.get_all_plugins()

    if not plugins:
        st.info("No plugins available.")
        return

    for plugin in plugins:
        with st.container():
            col1, col2, col3 = st.columns([3, 1, 1])

            with col1:
                st.markdown(f"**{plugin.manifest.name}** v{plugin.manifest.version}")
                st.caption(plugin.manifest.description)

            with col2:
                is_active = trainer_manager.is_plugin_active(trainer_id, plugin.id)
                status_text = "Active" if is_active else "Inactive"
                st.write(f"Status: {status_text}")

            with col3:
                if is_active:
                    if st.button("Deactivate", key=f"deactivate_{plugin.id}"):
                        trainer_manager.set_plugin_active(trainer_id, plugin.id, False)
                        plugin.on_deactivate(trainer_id)
                        st.rerun()
                else:
                    if st.button("Activate", key=f"activate_{plugin.id}"):
                        trainer_manager.set_plugin_active(trainer_id, plugin.id, True)
                        plugin.on_activate(trainer_id)
                        st.rerun()

            st.divider()
