"""
Trainer module admin UI injection.
Implements admin interface with role-based access control.
Must be in a file ending with _ui.py with inject_ui_admin_tab() function.
"""

import streamlit as st
import yaml
from typing import Optional, Dict, Any, List, Callable

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
            "User Dashboard",
            "Plugin Dashboard",
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
            _render_user_dashboard_tab(trainer_id, trainer_manager, plugin_manager)

        with tabs[1]:
            _render_plugin_dashboard_tab(trainer_id, trainer_manager, plugin_manager)

        # Configuration tab
        with tabs[2]:
            _render_configuration_tab()

        # Import/Export tab
        with tabs[3]:
            _render_import_export_tab(trainer_id, trainer_manager)

        # Plugins management tab
        with tabs[4]:
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
    active_plugins = plugin_manager.get_plugins_by_hook(trainer_id, "render_student_widgets")

    if not active_plugins:
        st.info(_("No active plugins provide student views. Activate plugins in the Plugins tab."))
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
        st.info(_("Active plugins don't provide student views for this student."))
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
                with st.expander(f"📋 {student_name} - " + _("Student Details"), expanded=True):
                    # Create tabs for basic profile and plugin-specific views
                    tab_names = [_("Profile")]

                    # Get active plugins that implement student widgets
                    active_plugins = plugin_manager.get_plugins_by_hook(trainer_id, "render_student_widgets")
                    tab_names.extend([plugin.manifest.name for plugin in active_plugins if
                                    plugin.render_student_widgets(trainer_id, student)])

                    # Create all tabs
                    detail_tabs = st.tabs(tab_names)

                    # Profile tab (always first)
                    with detail_tabs[0]:
                        col1, col2 = st.columns(2)
                        with col1:
                            st.write("**" + _("Student Information") + ":**")
                            st.write(f"ID: {student['id']}")
                            st.write(f"Email: {student.get('email', 'N/A')}")
                            if student.get('last_active'):
                                last_active = student['last_active']
                                if hasattr(last_active, 'strftime'):
                                    last_active = last_active.strftime('%Y-%m-%d %H:%M')
                                st.write(f"{_('Last Active')}: {last_active}")

                        with col2:
                            st.write("**" + _("Statistics") + ":**")
                            st.write(f"{_('Conversations')}: {student.get('conversation_count', 0)}")
                            st.write(f"{_('Total Messages')}: {student.get('total_messages', 0)}")

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
    """Render the import/export tab with history support and preview."""

    st.subheader("Configuration Export")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Export Configuration", key="export_config", use_container_width=True):
            yaml_content = trainer_manager.export_configuration(trainer_id)
            st.download_button(
                label="Download Configuration YAML",
                data=yaml_content,
                file_name=f"trainer_config_{trainer_id}.yaml",
                mime="text/yaml",
                use_container_width=True,
                key="download_config_btn"
            )

    with col2:
        uploaded_config = st.file_uploader(
            "Select Configuration YAML",
            type=['yaml', 'yml'],
            key="config_upload_trainer",
            help="Upload a previously exported configuration YAML"
        )

        if uploaded_config is not None:
            try:
                yaml_content = uploaded_config.read().decode('utf-8')

                # Preview configuration
                with st.expander("Preview Configuration", expanded=False):
                    try:
                        preview_data = yaml.safe_load(yaml_content)
                        st.json(preview_data)
                    except:
                        st.text(yaml_content[:500] + "...")

                if st.button("Import Configuration", key="import_config_btn", use_container_width=True):
                    if trainer_manager.import_configuration(trainer_id, yaml_content):
                        st.success("Configuration imported successfully!")
                    else:
                        st.error("Failed to import configuration")
            except Exception as e:
                st.error(f"Import error: {str(e)}")

    st.divider()
    st.subheader("History Export")

    # Get students for selection
    students = trainer_manager.get_trainer_students(trainer_id)

    if students:
        student_options = {student['id']: student.get('name', 'Unknown') for student in students}
        student_options['all'] = "All Students"

        selected_student = st.selectbox(
            "Select Student for History Export",
            options=list(student_options.keys()),
            format_func=lambda x: student_options[x],
            key="history_student_select_export"
        )

        col1, col2 = st.columns(2)

        with col1:
            # Add preview checkbox
            preview_before_export = st.checkbox(
                "Preview before export",
                value=True,
                key="preview_history_checkbox"
            )

            if st.button("Generate History Export", key="generate_history_btn", use_container_width=True):
                with st.spinner("Generating history export..."):
                    student_id = None if selected_student == 'all' else selected_student
                    yaml_content = trainer_manager.export_history(trainer_id, student_id)

                    # Store in session state for preview and download
                    st.session_state['history_export_content'] = yaml_content
                    st.session_state['history_export_student'] = student_id
                    st.session_state['history_export_student_name'] = student_options.get(student_id, 'all') if student_id else 'all'
                    st.rerun()

        with col2:
            uploaded_history = st.file_uploader(
                "Select History YAML",
                type=['yaml', 'yml'],
                key="history_upload_trainer",
                help="Upload a previously exported history YAML"
            )

            if uploaded_history is not None:
                try:
                    yaml_content = uploaded_history.read().decode('utf-8')
                    st.session_state['history_import_preview'] = yaml_content
                    st.rerun()
                except Exception as e:
                    st.error(f"Upload error: {str(e)}")

        # Show preview if available
        if 'history_export_content' in st.session_state:
            with st.expander("📋 Preview History Export", expanded=True):
                yaml_content = st.session_state['history_export_content']

                try:
                    preview_data = yaml.safe_load(yaml_content)

                    # Display summary stats
                    st.subheader("Export Summary")
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("Total Events", preview_data.get('event_count', 0))
                    with col2:
                        # Count unique event types
                        event_types = set(e.get('type') for e in preview_data.get('events', []))
                        st.metric("Event Types", len(event_types))
                    with col3:
                        # Count students
                        students_in_export = set(e.get('student_id') for e in preview_data.get('events', []) if e.get('student_id'))
                        st.metric("Students", len(students_in_export))
                    with col4:
                        # Date range
                        events = preview_data.get('events', [])
                        if events:
                            first_date = events[0].get('timestamp', '')[:10]
                            last_date = events[-1].get('timestamp', '')[:10]
                            st.metric("Date Range", f"{first_date} to {last_date}")

                    # Show sample of events
                    st.subheader("Sample Events (First 5)")
                    sample_events = preview_data.get('events', [])[:5]

                    for i, event in enumerate(sample_events):
                        with st.container():
                            cols = st.columns([2, 1, 2, 3])

                            with cols[0]:
                                # Timestamp
                                try:
                                    ts = datetime.fromisoformat(event.get('timestamp', '').replace('Z', '+00:00'))
                                    st.write(ts.strftime('%Y-%m-%d %H:%M'))
                                except:
                                    st.write(event.get('timestamp', '')[:16])

                            with cols[1]:
                                # Type
                                event_type = event.get('type', 'unknown')
                                if 'user_message' in event_type:
                                    st.write("👤 User")
                                elif 'assistant_message' in event_type:
                                    st.write("🤖 Assistant")
                                elif 'student_note' in event_type:
                                    st.write("📝 Student Note")
                                elif 'teacher_note' in event_type:
                                    st.write("👨‍🏫 Teacher Note")
                                else:
                                    st.write(event_type[:15])

                            with cols[2]:
                                # Student/Plugin
                                if event.get('student_name'):
                                    st.write(event.get('student_name'))
                                elif event.get('plugin_id') and event.get('plugin_id') != 'core.conversation':
                                    st.write(f"Plugin: {event.get('plugin_id')}")

                            with cols[3]:
                                # Preview
                                content = event.get('content', '')
                                if content:
                                    preview = content[:50] + "..." if len(content) > 50 else content
                                    st.caption(preview)
                                elif event.get('content_preview'):
                                    st.caption(event.get('content_preview'))

                        st.divider()

                    if len(preview_data.get('events', [])) > 5:
                        st.caption(f"... and {len(preview_data.get('events', [])) - 5} more events")

                    # Download button
                    student_name = st.session_state.get('history_export_student_name', 'all')
                    filename = f"trainer_history_{trainer_id}"
                    if student_name != 'all':
                        filename += f"_{student_name.replace(' ', '_').lower()}"
                    filename += ".yaml"

                    st.download_button(
                        label="📥 Download History YAML",
                        data=yaml_content,
                        file_name=filename,
                        mime="text/yaml",
                        use_container_width=True,
                        key="download_history_preview_btn"
                    )

                    if st.button("Clear Preview", key="clear_history_preview"):
                        del st.session_state['history_export_content']
                        st.rerun()

                except Exception as e:
                    st.error(f"Preview error: {str(e)}")
                    st.code(yaml_content[:1000])

        # Show import preview if available
        if 'history_import_preview' in st.session_state:
            with st.expander("📋 Preview Import File", expanded=True):
                yaml_content = st.session_state['history_import_preview']

                try:
                    preview_data = yaml.safe_load(yaml_content)

                    # Display summary
                    st.subheader("Import Summary")
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Events to Import", preview_data.get('event_count', 0))
                    with col2:
                        st.metric("Exported At", preview_data.get('exported_at', '')[:10])
                    with col3:
                        if preview_data.get('student_id'):
                            st.metric("Student", "Single Student")
                        else:
                            st.metric("Student", "All Students")

                    # Warning about duplicates
                    st.warning("⚠️ Importing history may create duplicate conversations and events. Please review before proceeding.")

                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("✅ Confirm Import", key="confirm_import_btn", use_container_width=True):
                            with st.spinner("Importing history..."):
                                if trainer_manager.import_history(trainer_id, yaml_content):
                                    st.success("History imported successfully!")
                                    if 'history_import_preview' in st.session_state:
                                        del st.session_state['history_import_preview']
                                    st.rerun()
                                else:
                                    st.error("Failed to import history")
                    with col2:
                        if st.button("❌ Cancel", key="cancel_import_btn", use_container_width=True):
                            del st.session_state['history_import_preview']
                            st.rerun()

                except Exception as e:
                    st.error(f"Preview error: {str(e)}")
                    st.code(yaml_content[:1000])

    else:
        st.info("No students available to export history.")

    # History statistics
    st.divider()
    st.subheader("History Statistics")

    col1, col2, col3 = st.columns(3)

    # Get total conversations across all students
    total_conversations = 0
    total_messages = 0

    for student in students:
        conversations = trainer_manager.conversation_manager.get_user_conversations(student['id'])
        total_conversations += len(conversations)

        for conv in conversations:
            full_conv = trainer_manager.conversation_manager.get_conversation(conv["id"])
            if full_conv and full_conv.messages:
                total_messages += len(full_conv.messages)

    with col1:
        st.metric("Total Students", len(students))
    with col2:
        st.metric("Total Conversations", total_conversations)
    with col3:
        st.metric("Total Messages", total_messages)


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
