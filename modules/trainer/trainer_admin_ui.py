"""
Trainer module admin UI injection.
Implements admin interface with role-based access control.
Must be in a file ending with _ui.py with inject_ui_admin_tab() function.
"""

import streamlit as st
import yaml
from typing import Optional

from shared.common import (
    _, get_user_manager, get_config, get_prompt, get_db_manager,
    log, UserRole, get_conversation_manager
)
from modules.trainer.manager import get_trainer_manager
from modules.trainer.plugin_base import get_plugin_manager


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
            "Dashboard",
            "Configuration",
            "Import/Export",
            "Plugins"
        ]

        # Add plugin tabs from active plugins
        active_plugins = plugin_manager.get_active_plugins(trainer_id)
        plugin_tabs = []
        for plugin in active_plugins:
            plugin_tabs.extend(plugin.get_admin_tabs(trainer_id))

        all_tab_names = tab_names + [name for name, _ in plugin_tabs]
        tabs = st.tabs(all_tab_names)

        # Dashboard tab
        with tabs[0]:
            _render_dashboard_tab(trainer_id, trainer_manager, plugin_manager)

        # Configuration tab
        with tabs[1]:
            _render_configuration_tab()

        # Import/Export tab
        with tabs[2]:
            _render_import_export_tab(trainer_id, trainer_manager)

        # Plugins management tab
        with tabs[3]:
            _render_plugins_tab(trainer_id, trainer_manager, plugin_manager)

        # Plugin tabs
        for idx, (_, render_func) in enumerate(plugin_tabs, start=len(tab_names)):
            with tabs[idx]:
                render_func()

    return ("Trainer", render_trainer_admin)


def _render_dashboard_tab(trainer_id: str, trainer_manager, plugin_manager):
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
                with st.expander(f"📝 Student: {st.session_state.get(f'selected_student_name_{trainer_id}', '')}", expanded=True):
                    # Create tabs for different views
                    detail_tab1, detail_tab2 = st.tabs(["📋 Profile", "📝 Student Notes"])

                    with detail_tab1:
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

                    with detail_tab2:
                        st.write("**Student Notes & Teacher Feedback**")
                        st.divider()

                        # Get the student pad plugin specifically
                        student_pad_plugin = plugin_manager.get_plugin("student_pad")

                        # Use trainer_manager to check if plugin is active, not plugin_manager
                        if student_pad_plugin and trainer_manager.is_plugin_active(trainer_id, "student_pad"):
                            # Render the student pad widget directly
                            widgets = student_pad_plugin.render_student_widgets(trainer_id, student)
                            for widget in widgets:
                                widget()
                        else:
                            st.info("The Student Pad plugin is not active. Activate it in the Plugins tab to view and manage student notes.")

            st.divider()

    # Plugin dashboard widgets (non-student specific)
    active_plugins = plugin_manager.get_active_plugins(trainer_id)
    for plugin in active_plugins:
        widgets = plugin.render_dashboard_widgets(trainer_id, students)
        for widget in widgets:
            widget()


def _render_configuration_tab():
    """Render the configuration tab."""
    st.subheader("System Prompt")

    current_prompt = get_prompt('trainer.teacher.system_prompt')

    st.info(current_prompt)
    st.caption("System prompt is configured via import/export or configuration files.")


def _render_import_export_tab(trainer_id: str, trainer_manager):
    """Render the import/export tab."""
    st.subheader("Export Configuration")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Export YAML", use_container_width=True):
            yaml_content = trainer_manager.export_configuration(trainer_id)
            st.download_button(
                label="Download YAML",
                data=yaml_content,
                file_name=f"trainer_config_{trainer_id}.yaml",
                mime="text/yaml",
                use_container_width=True
            )

    with col2:
        uploaded_file = st.file_uploader(
            "Select YAML file",
            type=['yaml', 'yml'],
            help="Upload a previously exported YAML configuration"
        )

        if uploaded_file is not None:
            try:
                yaml_content = uploaded_file.read().decode('utf-8')
                if st.button("Import", use_container_width=True):
                    if trainer_manager.import_configuration(trainer_id, yaml_content):
                        st.success("Configuration imported successfully!")
                    else:
                        st.error("Failed to import configuration")
            except Exception as e:
                st.error(f"Import error: {str(e)}")


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
