"""
Conversation Export/Import UI Module
====================================

Provides UI components for exporting and importing conversations.
Injects into sidebar, conversation interface, and settings.
"""

import streamlit as st
import tempfile
import os
from datetime import datetime
from typing import List, Optional, Dict, Any

from shared.common import _, log, get_conversation_manager, get_user_manager
from shared.common import get_conversation_manager, get_user_manager
from shared.export_import import (
    export_conversation_to_file, import_conversation_from_file,
    export_all_conversations_to_file, import_bulk_conversations_from_file,
    exporter, importer
)


def inject_ui_sidebar():
    """Add export/import buttons to conversation sidebar."""
    # Only show if user is logged in and has a current conversation
    if not st.session_state.get("current_user"):
        return None

    if not st.session_state.get("current_conversation_id"):
        return None

    st.divider()
    st.subheader("📁 Export/Import")

    # Export current conversation
    if st.button("💾 Export Current",
                help="Export current conversation to YAML file",
                width='stretch'):
        st.session_state.show_export_dialog = True
        st.rerun()

    # Import conversation
    if st.button("📂 Import Conversation",
                help="Import conversation from YAML file",
                width='stretch'):
        st.session_state.show_import_dialog = True
        st.rerun()


def inject_ui_inside_conversation():
    """Add export button inside conversation interface."""
    # Only show if we're in a conversation
    if not st.session_state.get("current_conversation_id"):
        return None

    # Export button in conversation header
    col1, col2, col3, col4, col5 = st.columns([3, 1, 1, 1, 1])
    with col5:
        if st.button("💾 Export",
                    help="Export this conversation to YAML file",
                    key="export_conversation_header"):
            st.session_state.show_export_dialog = True
            st.rerun()


def inject_ui_settings_content():
    """Legacy method - keep for backward compatibility but not used in new tab system."""
    # This can be removed or kept as a placeholder
    pass


def inject_ui_settings_tab():
    """Register the Export/Import settings tab using the new injection mechanism.
    Returns: (tab_name, render_function) tuple."""

    def render_export_import_tab():
        """Render the Export/Import tab content."""
        current_user = st.session_state.get("current_user")
        if not current_user:
            st.info("Please log in to access export/import features.")
            return

        user_id = current_user.get("id")

        st.header("📁 Export/Import Conversations")

        # Create two columns for Export and Import sections
        col_export, col_import = st.columns(2)

        with col_export:
            st.subheader("💾 Export")

            # Single conversation export (if there's a current conversation)
            if st.session_state.get("current_conversation_id"):
                st.write("**Current Conversation**")
                if st.button("Export Current Conversation", use_container_width=True):
                    st.session_state.show_export_dialog = True
                    st.rerun()

            # Bulk export
            st.write("**All Conversations**")
            st.caption("Export all your conversations to a single YAML file")

            if st.button("📦 Export All Conversations", type="secondary", use_container_width=True):
                # Create temporary file
                with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp:
                    file_path = tmp.name

                # Export to file
                success = export_all_conversations_to_file(user_id, file_path)

                if success:
                    # Read file and create download button
                    with open(file_path, 'rb') as f:
                        yaml_data = f.read()

                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"conversations_{current_user.get('name', 'user')}_{timestamp}.yaml"

                    st.download_button(
                        label="⬇️ Download Export File",
                        data=yaml_data,
                        file_name=filename,
                        mime="application/x-yaml",
                        key="bulk_export_download"
                    )

                    # Clean up temp file
                    try:
                        os.unlink(file_path)
                    except:
                        pass
                else:
                    st.error("Failed to export conversations")

        with col_import:
            st.subheader("📂 Import")

            # Single conversation import
            st.write("**Import Conversation**")
            uploaded_file = st.file_uploader(
                "Choose a conversation file",
                type=['yaml', 'yml'],
                key="settings_import_file"
            )

            if uploaded_file is not None:
                # Preview
                try:
                    content = uploaded_file.getvalue().decode('utf-8')
                    import yaml
                    data = yaml.safe_load(content)

                    with st.expander("Preview"):
                        if "conversations" in data:
                            st.write(f"**Bulk import:** {len(data['conversations'])} conversations")
                        else:
                            st.write(f"**Title:** {data.get('title', 'Untitled')}")
                            st.write(f"**Messages:** {len(data.get('messages', []))}")

                    # Import button
                    if st.button("📥 Import", type="primary", key="settings_import_btn"):
                        # Save uploaded file temporarily
                        with tempfile.NamedTemporaryFile(mode='wb', suffix='.yaml', delete=False) as tmp:
                            tmp.write(uploaded_file.getvalue())
                            file_path = tmp.name

                        with st.spinner("Importing..."):
                            # Try as single conversation first
                            conv_id = import_conversation_from_file(file_path, user_id)

                            if conv_id:
                                st.success(f"✅ Conversation imported successfully!")
                                if st.button("Open Imported Conversation", key="open_imported"):
                                    st.session_state.current_conversation_id = conv_id
                                    st.rerun()
                            else:
                                # Try as bulk
                                imported_ids = import_bulk_conversations_from_file(file_path, user_id)
                                if imported_ids:
                                    st.success(f"✅ Successfully imported {len(imported_ids)} conversations!")
                                else:
                                    st.error("❌ Failed to import conversation")

                        # Clean up temp file
                        try:
                            os.unlink(file_path)
                        except:
                            pass

                except Exception as e:
                    st.error(f"Error reading file: {str(e)}")

            st.divider()

            # Bulk import
            st.write("**Bulk Import**")
            st.caption("Import multiple conversations from a YAML export file")

            bulk_file = st.file_uploader(
                "Choose export file",
                type=['yaml', 'yml'],
                key="settings_bulk_import_file"
            )

            if bulk_file is not None:
                if st.button("📥 Import All", type="primary", key="settings_bulk_import_btn"):
                    with tempfile.NamedTemporaryFile(mode='wb', suffix='.yaml', delete=False) as tmp:
                        tmp.write(bulk_file.getvalue())
                        file_path = tmp.name

                    with st.spinner("Importing conversations..."):
                        imported_ids = import_bulk_conversations_from_file(file_path, user_id)

                        if imported_ids:
                            st.success(f"✅ Successfully imported {len(imported_ids)} conversations!")
                            log("info", f"Imported {len(imported_ids)} conversations for user {user_id}")
                            st.rerun()
                        else:
                            st.error("❌ Failed to import conversations")

                    # Clean up temp file
                    try:
                        os.unlink(file_path)
                    except:
                        pass

        # Delete All section at the bottom
        st.divider()
        st.subheader("🗑️ Delete All Conversations")
        st.warning("This action cannot be undone!")
        st.caption("This will permanently delete ALL your conversations")

        if st.button("Delete All My Conversations", type="secondary"):
            st.session_state.show_delete_all_dialog = True
            st.rerun()

        # Render delete all dialog if needed
        if st.session_state.get("show_delete_all_dialog"):
            render_delete_all_dialog(user_id)

        # Render export/import dialogs if needed
        if st.session_state.get("show_export_dialog"):
            render_export_dialog(user_id)

        if st.session_state.get("show_import_dialog"):
            render_import_dialog(user_id)

    return ("📁 Export/Import", render_export_import_tab)


def inject_ui_main_content():
    """Handle export/import dialogs for main chat page."""
    current_user = st.session_state.get("current_user")
    if not current_user:
        return None

    # Only handle export/import dialogs for chat page
    if st.session_state.get('current_page') != 'chat':
        return None

    # Export dialog (for single conversation export from chat)
    if st.session_state.get("show_export_dialog"):
        render_export_dialog(current_user.get('id'))

    # Import dialog (for single conversation import from chat)
    if st.session_state.get("show_import_dialog"):
        render_import_dialog(current_user.get('id'))

    return None


def render_export_dialog(user_id: str):
    """Render export dialog."""
    conversation_id = st.session_state.get("current_conversation_id")
    if not conversation_id:
        st.error("No conversation selected")
        st.session_state.show_export_dialog = False
        st.rerun()
        return

    manager = get_conversation_manager()
    conversation = manager.get_conversation(conversation_id, include_messages=False)

    if not conversation:
        st.error("Conversation not found")
        st.session_state.show_export_dialog = False
        st.rerun()
        return

    st.divider()
    st.subheader(f"💾 Export: {conversation.title}")

    # Export options
    col1, col2 = st.columns(2)

    with col1:
        include_metadata = st.checkbox("Include metadata", value=True)
        include_timestamps = st.checkbox("Include timestamps", value=True)

    with col2:
        format_choice = st.selectbox(
            "Format",
            ["YAML", "JSON"],
            index=0
        )

    # Preview
    if st.button("👁️ Preview Export"):
        yaml_data = exporter.export_single_conversation(conversation_id)
        if yaml_data:
            with st.expander("Export Preview"):
                st.code(yaml_data, language="yaml")

    # Export buttons
    col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 2])

    with col_btn1:
        if st.button("⬇️ Download", type="primary"):
            # Create temporary file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp:
                file_path = tmp.name

            # Export to file
            success = export_conversation_to_file(conversation_id, file_path)

            if success:
                # Read file and create download button
                with open(file_path, 'rb') as f:
                    yaml_data = f.read()

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"conversation_{conversation.title}_{timestamp}.yaml"

                st.download_button(
                    label="Click to download",
                    data=yaml_data,
                    file_name=filename,
                    mime="application/x-yaml",
                    key="download_export"
                )

                # Clean up temp file
                try:
                    os.unlink(file_path)
                except:
                    pass
            else:
                st.error("Failed to export conversation")

    with col_btn2:
        if st.button("📋 Copy to Clipboard"):
            yaml_data = exporter.export_single_conversation(conversation_id)
            if yaml_data:
                st.code(yaml_data, language="yaml")
                st.success("YAML copied to clipboard (simulated)")
                # Note: Streamlit doesn't directly support clipboard in cloud
                # In a real app, you might use JavaScript or another method

    with col_btn3:
        if st.button("❌ Cancel"):
            st.session_state.show_export_dialog = False
            st.rerun()


def render_import_dialog(user_id: str):
    """Render import dialog."""
    st.divider()
    st.subheader("📂 Import Conversation")

    uploaded_file = st.file_uploader(
        "Choose a YAML conversation file",
        type=['yaml', 'yml'],
        key="import_conversation_file"
    )

    if uploaded_file is not None:
        # Preview
        try:
            content = uploaded_file.getvalue().decode('utf-8')
            import yaml
            data = yaml.safe_load(content)

            st.info("### Preview")
            st.write(f"**Title:** {data.get('title', 'Untitled')}")
            st.write(f"**Original user:** {data.get('user_id', 'Unknown')}")
            st.write(f"**Messages:** {len(data.get('messages', []))}")

            if data.get('system_prompt'):
                with st.expander("System Prompt"):
                    st.text(data['system_prompt'])

            # Import options
            col_opt1, col_opt2 = st.columns(2)
            with col_opt1:
                new_title = st.text_input(
                    "New title (optional)",
                    value=data.get('title', 'Imported Conversation')
                )

            with col_opt2:
                preserve_timestamps = st.checkbox("Preserve original timestamps", value=True)

            # Import button
            col_imp1, col_imp2 = st.columns(2)

            with col_imp1:
                if st.button("📥 Import", type="primary"):
                    # Save uploaded file temporarily
                    with tempfile.NamedTemporaryFile(mode='wb', suffix='.yaml', delete=False) as tmp:
                        tmp.write(uploaded_file.getvalue())
                        file_path = tmp.name

                    # Import conversation
                    with st.spinner("Importing conversation..."):
                        new_conversation_id = import_conversation_from_file(file_path, user_id)

                        if new_conversation_id:
                            # Update title if changed
                            if new_title != data.get('title'):
                                manager = get_conversation_manager()
                                manager.update_conversation_title(new_conversation_id, new_title)

                            st.success(f"✅ Conversation imported successfully!")
                            st.info(f"New conversation ID: {new_conversation_id}")

                            # Option to open the new conversation
                            if st.button("Open Imported Conversation"):
                                st.session_state.current_conversation_id = new_conversation_id
                                st.session_state.show_import_dialog = False
                                st.rerun()

                            log("info", f"Imported conversation for user {user_id}, new ID: {new_conversation_id}")
                        else:
                            st.error("❌ Failed to import conversation")

                    # Clean up temp file
                    try:
                        os.unlink(file_path)
                    except:
                        pass

            with col_imp2:
                if st.button("Clear Upload"):
                    st.session_state.import_conversation_file = None
                    st.rerun()

        except Exception as e:
            st.error(f"Error reading file: {str(e)}")

    # Cancel button
    if st.button("❌ Cancel Import"):
        st.session_state.show_import_dialog = False
        st.rerun()


def render_delete_all_dialog(user_id: str):
    """Render delete all conversations confirmation dialog."""
    st.divider()
    st.error("### 🗑️ Delete All Conversations")

    manager = get_conversation_manager()
    conversations = manager.get_user_conversations(user_id, include_inactive=True)

    if not conversations:
        st.info("You don't have any conversations to delete.")
        st.session_state.show_delete_all_dialog = False
        st.rerun()
        return

    st.warning(f"⚠️ **This will permanently delete ALL {len(conversations)} of your conversations!**")
    st.warning("This action cannot be undone!")

    # Show conversation list
    with st.expander("Show conversations that will be deleted"):
        for conv in conversations[:10]:  # Show first 10
            st.write(f"- **{conv['title']}** ({conv['message_count']} messages)")

        if len(conversations) > 10:
            st.write(f"... and {len(conversations) - 10} more")

    # Confirmation
    confirmation = st.text_input(
        "Type 'DELETE ALL' to confirm",
        placeholder="DELETE ALL",
        key="delete_all_confirmation"
    )

    col_del1, col_del2 = st.columns(2)

    with col_del1:
        if st.button("✅ Confirm Delete",
                    type="primary",
                    disabled=confirmation != "DELETE ALL"):
            if confirmation == "DELETE ALL":
                with st.spinner("Deleting conversations..."):
                    success_count = 0
                    for conv in conversations:
                        if manager.delete_conversation(conv['id']):
                            success_count += 1

                    if success_count > 0:
                        # Clear current conversation if it was deleted
                        current_conv_id = st.session_state.get("current_conversation_id")
                        if current_conv_id:
                            # Check if current conversation was deleted
                            if not any(c['id'] == current_conv_id for c in conversations):
                                # Current conversation still exists, reload it
                                conversation = manager.get_conversation(current_conv_id, include_messages=True)
                                if conversation:
                                    st.session_state.conversation_messages = conversation.messages
                            else:
                                # Current conversation was deleted
                                st.session_state.current_conversation_id = None
                                st.session_state.conversation_messages = []

                        st.success(f"✅ Deleted {success_count} conversations!")
                        log("info", f"Deleted {success_count} conversations for user {user_id}")
                    else:
                        st.error("❌ Failed to delete conversations")

                    st.session_state.show_delete_all_dialog = False
                    st.rerun()

    with col_del2:
        if st.button("❌ Cancel"):
            st.session_state.show_delete_all_dialog = False
            st.rerun()


def inject_ui_initialize():
    """Initialize conversation export/import UI module."""
    log("debug", "Initializing conversation export/import UI module")

    # Initialize session state variables
    if "show_export_dialog" not in st.session_state:
        st.session_state.show_export_dialog = False
    if "show_import_dialog" not in st.session_state:
        st.session_state.show_import_dialog = False
    if "show_delete_all_dialog" not in st.session_state:
        st.session_state.show_delete_all_dialog = False

    return True
