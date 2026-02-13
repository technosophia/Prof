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
    # Only show for master users
    if not ("current_user" in st.session_state and st.session_state.current_user):
        return

    user_id = st.session_state.current_user['id']
    user_role = st.session_state.current_user['role']

    if user_role != UserRole.MASTER.value:
        return

    def render_trainer_admin():
        from shared.common import _
        st.header(_("🎓 Trainer Module"))

        trainer_id = st.session_state.current_user['id']
        trainer_manager = get_trainer_manager()
        plugin_manager = get_plugin_manager()

        # Create base tabs
        tab_names = [
            _("trainer.admin.dashboard"),
            _("trainer.admin.configuration"),
            _("trainer.admin.import_export"),
            _("trainer.admin.plugins")
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
            _render_dashboard_tab(trainer_id, trainer_manager)

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


def _render_dashboard_tab(trainer_id: str, trainer_manager):
    """Render the students dashboard."""
    st.subheader("trainer.dashboard.students")

    user_manager = get_user_manager()
    plugin_manager = get_plugin_manager()

    # Get students (list of user objects from get_children)
    student_objects = trainer_manager.get_trainer_students(trainer_id)

    if not student_objects:
        st.info("trainer.dashboard.no_students")
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
                    "trainer.dashboard.conversations",
                    student.get('conversation_count', 0)
                )

            with col3:
                st.metric(
                    "trainer.dashboard.total_messages",
                    student.get('total_messages', 0)
                )

            with col4:
                # Make key unique by including trainer_id
                if st.button("View", key=f"view_{trainer_id}_{student['id']}"):
                    st.session_state[f'selected_student_{trainer_id}'] = student['id']
                    # Also store the selected student info
                    st.session_state[f'selected_student_name_{trainer_id}'] = student.get('name', 'Unknown')
                    st.rerun()

            # Show student details if selected
            if st.session_state.get(f'selected_student_{trainer_id}') == student['id']:
                with st.expander(f"📝 Student: {st.session_state.get(f'selected_student_name_{trainer_id}', '')}", expanded=True):
                    # Create tabs for different views
                    detail_tab1, detail_tab2, detail_tab3 = st.tabs(["📋 Profile", "💬 Chat Pad", "📊 Analytics"])

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
                        st.write("**💬 Chat Pad / Notes**")

                        # Get existing note
                        note_content = trainer_manager.get_student_note(
                            student_id=student['id'],
                            trainer_id=trainer_id,
                            plugin_id="student_pad"
                        )

                        # Note editor
                        edited_note = st.text_area(
                            "Student notes and chat history",
                            value=note_content or "",
                            height=300,
                            key=f"note_{trainer_id}_{student['id']}",
                            placeholder="Enter notes, observations, or chat with the student here..."
                        )

                        # Save button
                        col_save, col_clear = st.columns([1, 4])
                        with col_save:
                            if st.button("💾 Save Notes", key=f"save_note_{trainer_id}_{student['id']}"):
                                if trainer_manager.save_student_note(
                                    student_id=student['id'],
                                    trainer_id=trainer_id,
                                    content=edited_note,
                                    plugin_id="core"
                                ):
                                    st.success("Notes saved successfully!")
                                    st.rerun()
                                else:
                                    st.error("Failed to save notes")

                        # Display note preview
                        if edited_note:
                            with st.expander("Preview"):
                                st.markdown(edited_note)

                    with detail_tab3:
                        st.write("**📊 Analytics & Progress**")

                        # Get conversation history
                        conversations = get_conversation_manager().get_user_conversations(student['id'])

                        if conversations:
                            st.write(f"Total Conversations: {len(conversations)}")

                            # Recent activity chart
                            recent_convos = sorted(
                                conversations,
                                key=lambda x: x.get('updated_at', ''),
                                reverse=True
                            )[:5]

                            st.write("**Recent Activity:**")
                            for conv in recent_convos:
                                updated = conv.get('updated_at', '')
                                if updated:
                                    updated = updated[:10] if 'T' in updated else updated
                                st.write(f"- {conv.get('title', 'Untitled')} ({updated})")
                        else:
                            st.info("No conversations yet")

                    # Plugin widgets
                    active_plugins = plugin_manager.get_active_plugins(trainer_id)
                    for plugin in active_plugins:
                        widgets = plugin.render_student_widgets(trainer_id, student)
                        for widget in widgets:
                            widget()

            st.divider()

    # Plugin dashboard widgets
    active_plugins = plugin_manager.get_active_plugins(trainer_id)
    for plugin in active_plugins:
        widgets = plugin.render_dashboard_widgets(trainer_id, students)
        for widget in widgets:
            widget()


def _render_configuration_tab():
    """Render the configuration tab."""
    st.subheader(_("trainer.config.system_prompt"))

    # Get current prompt
    config = get_config()
    prompt_key = config.get('trainer.system_prompt_key', 'teacher.system_prompt')
    current_prompt = get_prompt(prompt_key)

    # Display current prompt (read-only in UI, configured via import/export)
    st.info(current_prompt)
    st.caption(_("trainer.config.system_prompt_help"))


def _render_import_export_tab(trainer_id: str, trainer_manager):
    """Render the import/export tab."""
    st.subheader(_("trainer.import_export.export"))

    # Export section
    col1, col2 = st.columns(2)

    with col1:
        if st.button(_("trainer.import_export.export_yaml"), use_container_width=True):
            yaml_content = trainer_manager.export_configuration(trainer_id)
            st.download_button(
                label=_("Download YAML"),
                data=yaml_content,
                file_name=f"trainer_config_{trainer_id}.yaml",
                mime="text/yaml",
                use_container_width=True
            )

    # Import section
    with col2:
        uploaded_file = st.file_uploader(
            _("trainer.import_export.select_file"),
            type=['yaml', 'yml'],
            help=_("trainer.import_export.import_yaml")
        )

        if uploaded_file is not None:
            try:
                yaml_content = uploaded_file.read().decode('utf-8')
                if st.button(_("Import"), use_container_width=True):
                    if trainer_manager.import_configuration(trainer_id, yaml_content):
                        st.success(_("trainer.import_export.import_success"))
                    else:
                        st.error(_("trainer.import_export.import_error"))
            except Exception as e:
                st.error(f"{_('trainer.import_export.import_error')}: {str(e)}")


def _render_plugins_tab(trainer_id: str, trainer_manager, plugin_manager):
    """Render the plugins management tab."""
    st.subheader(_("trainer.plugins.title"))

    plugins = plugin_manager.get_all_plugins()

    if not plugins:
        st.info(_("trainer.plugins.no_plugins"))
        return

    for plugin in plugins:
        with st.container():
            col1, col2, col3 = st.columns([3, 1, 1])

            with col1:
                st.markdown(f"**{plugin.manifest.name}** v{plugin.manifest.version}")
                st.caption(plugin.manifest.description)

            with col2:
                is_active = trainer_manager.is_plugin_active(trainer_id, plugin.id)
                status_text = _("trainer.plugins.active") if is_active else _("trainer.plugins.inactive")
                st.write(_("trainer.plugins.status") + f": {status_text}")

            with col3:
                if is_active:
                    if st.button(_("trainer.plugins.deactivate"), key=f"deactivate_{plugin.id}"):
                        trainer_manager.set_plugin_active(trainer_id, plugin.id, False)
                        plugin.on_deactivate(trainer_id)
                        st.rerun()
                else:
                    if st.button(_("trainer.plugins.activate"), key=f"activate_{plugin.id}"):
                        trainer_manager.set_plugin_active(trainer_id, plugin.id, True)
                        plugin.on_activate(trainer_id)
                        st.rerun()

            st.divider()
