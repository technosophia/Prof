"""
RAG Manager UI Module

UI components for RAG document management.
Uses the new UI injection mechanism with admin_tab injection point.
"""

import streamlit as st
import os
from datetime import datetime
from pathlib import Path
import tempfile
from shared.logging import log
from shared.translate import _
from shared.config import get_config

# Import the RAG manager - use absolute import path
try:
    # When loaded as a module
    from modules.rag_manager import rag_manager
except ImportError:
    # Fallback for direct execution or different import paths
    try:
        # Try relative import
        from .rag_manager import rag_manager
    except ImportError:
        # Last resort: try to import by manipulating sys.path
        import sys
        from pathlib import Path
        current_dir = Path(__file__).parent
        module_dir = current_dir.parent
        sys.path.insert(0, str(module_dir))
        from rag_manager import rag_manager

def show_rag_admin_content():
    """Display the RAG Manager admin content."""
    st.title("📚 RAG Document Manager")

    # Get configuration from shared config
    config = get_config()
    rag_config = config.get("rag_manager", {})

    # Get data directory from RAG manager
    data_dir = rag_manager.data_dir

    # Display stats
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Documents", rag_manager.get_document_count())
    with col2:
        st.metric("Total Size", f"{rag_manager.get_total_size_mb()} MB")
    with col3:
        st.metric("Data Directory", data_dir.name if data_dir else "Not set")

    # Upload Section
    st.header(_("upload_documents"))

    # Get allowed extensions from config
    allowed_extensions = rag_config.get("allowed_extensions", [".txt", ".pdf", ".md"])
    allowed_types = [ext.lstrip('.') for ext in allowed_extensions]

    uploaded_files = st.file_uploader(
        _("upload_documents"),
        type=allowed_types,
        accept_multiple_files=True,
        help=f"Maximum file size: {rag_config.get('max_file_size_mb', 10)}MB"
    )

    if uploaded_files and st.button(_("upload_button"), type="primary"):
        success_count = 0
        error_count = 0

        for uploaded_file in uploaded_files:
            try:
                # Save uploaded file to temp location
                with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as tmp_file:
                    tmp_file.write(uploaded_file.getvalue())
                    tmp_path = tmp_file.name

                # Upload to RAG manager
                result = rag_manager.upload_document(tmp_path, uploaded_file.name)

                # Clean up temp file
                os.unlink(tmp_path)

                if result:
                    success_count += 1
                    log("info", f"Successfully uploaded: {uploaded_file.name}")
                else:
                    error_count += 1
                    st.error(_("upload_error").format(error=f"Failed to upload {uploaded_file.name}"))

            except Exception as e:
                error_count += 1
                log("error", f"Error uploading {uploaded_file.name}: {str(e)}")
                st.error(_("upload_error").format(error=str(e)))

        if success_count > 0:
            st.success(_("upload_success"))
            st.rerun()

    # Document List Section
    st.header(_("document_list"))

    documents = rag_manager.get_document_list()

    if not documents:
        st.info(_("no_documents"))
    else:
        # Create a table of documents
        for doc in documents:
            col1, col2, col3, col4 = st.columns([3, 2, 2, 1])

            with col1:
                st.write(f"**{doc['original_filename']}**")
                st.caption(f"Stored as: {doc['filename']}")

            with col2:
                st.write(f"{doc['file_size_mb']} MB")

            with col3:
                upload_date = datetime.fromisoformat(doc['uploaded_at']).strftime("%Y-%m-%d %H:%M")
                st.write(upload_date)

            with col4:
                # Delete button with confirmation
                delete_key = f"delete_{doc['filename']}"
                if st.button("🗑️", key=delete_key, help=_("delete")):
                    if st.session_state.get(f"confirm_{delete_key}", False):
                        # Second click - actually delete
                        if rag_manager.delete_document(doc['filename']):
                            st.success(_("delete_success"))
                            st.rerun()
                    else:
                        # First click - show confirmation
                        st.session_state[f"confirm_{delete_key}"] = True
                        st.warning(_("delete_confirm").format(filename=doc['original_filename']))

    # Advanced Options (collapsible)
    with st.expander("⚙️ Advanced Options"):
        col1, col2 = st.columns(2)

        with col1:
            # Clear all button (with confirmation)
            if st.button("🗑️ Clear All Documents", type="secondary"):
                if st.session_state.get("confirm_clear_all", False):
                    if rag_manager.clear_all_documents():
                        st.success("All documents cleared")
                        st.rerun()
                else:
                    st.session_state["confirm_clear_all"] = True
                    st.warning("Are you sure you want to delete ALL documents? This action cannot be undone.")

        with col2:
            # Refresh button
            if st.button("🔄 Refresh List"):
                st.rerun()

        # Configuration info
        st.divider()
        st.subheader("Configuration")
        st.json(rag_config)

def inject_ui_admin_tab():
    """Register the RAG Manager admin tab using the new injection mechanism.
    Returns: (tab_name, render_function) tuple."""
    return ("RAG Manager", show_rag_admin_content)

def inject_ui_initialize():
    """Initialize RAG manager module."""
    # No need to register anything here - handled by UI registry

def inject_ui_main_content():
    """Render RAG manager content in main area (if applicable)."""
    # This module only provides admin interface
    return None

# Test function
def test_rag_manager():
    """Test the RAG manager functionality."""
    try:
        # Test document list
        documents = rag_manager.get_document_list()
        log("info", f"Test: Found {len(documents)} documents")

        # Test configuration
        config = get_config()
        rag_config = config.get("rag_manager", {})
        log("info", f"Test: Data directory: {rag_manager.data_dir}")

        return True
    except Exception as e:
        log("error", f"RAG Manager test failed: {str(e)}", exc_info=True)
        return False
