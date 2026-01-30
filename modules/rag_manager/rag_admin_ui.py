"""
Enhanced RAG Admin UI with Engine Management
"""

import streamlit as st
import os
from datetime import datetime
from pathlib import Path
import tempfile
from shared.logging import log
from shared.translate import _
from shared.config import get_config

from modules.rag_manager.rag_manager import rag_manager


def show_rag_admin_content():
    """Display the enhanced RAG Manager admin content."""
    st.title("📚 RAG Document Manager")

    # Tabs for different functionalities
    tab1, tab2, tab3, tab4 = st.tabs([
        "📄 Documents",
        "🔧 Engines",
        "🔍 Search Test",
        "📊 Stats"
    ])

    with tab1:
        _show_documents_tab()

    with tab2:
        _show_engines_tab()

    with tab3:
        _show_search_test_tab()

    with tab4:
        _show_stats_tab()


def _show_documents_tab():
    """Show documents management tab."""
    st.header("Document Management")

    # Get current user
    current_user = st.session_state.get('current_user')
    if not current_user:
        st.warning("Please log in to manage documents")
        return

    user_id = current_user['id']
    user_role = current_user['role']

    # Upload Section
    st.subheader("Upload Documents")

    # Get configuration
    config = get_config()
    rag_config = config.get("rag_manager", {})
    allowed_extensions = rag_config.get("allowed_extensions", [".txt", ".pdf", ".md"])
    allowed_types = [ext.lstrip('.') for ext in allowed_extensions]

    col1, col2 = st.columns(2)
    with col1:
        uploaded_files = st.file_uploader(
            "Choose files",
            type=allowed_types,
            accept_multiple_files=True,
            help=f"Maximum file size: {rag_config.get('max_file_size_mb', 10)}MB"
        )

    with col2:
        # Public upload option (only for admin/masters)
        is_public = False
        if user_role in ['admin', 'master']:
            is_public = st.checkbox("Make public",
                                  help="Public documents are visible to all users")

        if uploaded_files and st.button("📤 Upload", type="primary"):
            success_count = 0
            error_count = 0

            for uploaded_file in uploaded_files:
                try:
                    # Save uploaded file to temp location
                    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as tmp_file:
                        tmp_file.write(uploaded_file.getvalue())
                        tmp_path = tmp_file.name

                    # Upload to RAG manager
                    result = rag_manager.upload_document(
                        tmp_path,
                        uploaded_file.name,
                        user_id,
                        is_public
                    )

                    # Clean up temp file
                    os.unlink(tmp_path)

                    if result:
                        success_count += 1
                        log("info", f"Successfully uploaded: {uploaded_file.name}")
                    else:
                        error_count += 1
                        st.error(f"Failed to upload {uploaded_file.name}")

                except Exception as e:
                    error_count += 1
                    log("error", f"Error uploading {uploaded_file.name}: {str(e)}")
                    st.error(f"Error uploading {uploaded_file.name}: {str(e)}")

            if success_count > 0:
                st.success(f"Successfully uploaded {success_count} file(s)")
                st.rerun()

    # Document List Section
    st.subheader("Your Documents")

    documents = rag_manager.get_user_documents(user_id)

    if not documents:
        st.info("No documents uploaded yet.")
    else:
        # Create a table of documents
        for doc in documents:
            col1, col2, col3, col4, col5 = st.columns([3, 2, 2, 2, 2])

            with col1:
                st.write(f"**{doc['original_filename']}**")
                st.caption(f"ID: {doc['filename']}")
                if doc.get('is_public'):
                    st.caption("🌍 Public")

            with col2:
                st.write(f"{doc['file_size_mb']} MB")

            with col3:
                upload_date = datetime.fromisoformat(doc['uploaded_at']).strftime("%Y-%m-%d")
                st.write(upload_date)

            with col4:
                # Show indexing status
                indexed_in = doc.get('indexed_in', [])
                if indexed_in:
                    st.write(f"Indexed in: {', '.join(indexed_in)}")
                else:
                    st.write("Not indexed")

            with col5:
                # Action buttons
                btn_col1, btn_col2 = st.columns(2)

                with btn_col1:
                    # Index button
                    if st.button("🔍", key=f"index_{doc['filename']}", help="Index this document"):
                        st.session_state[f"indexing_{doc['filename']}"] = True

                with btn_col2:
                    # Delete button
                    delete_key = f"delete_{doc['filename']}"
                    if st.button("🗑️", key=delete_key, help="Delete this document"):
                        if st.session_state.get(f"confirm_{delete_key}", False):
                            if rag_manager.delete_document(doc['filename'], user_id):
                                st.success("Document deleted")
                                st.rerun()
                        else:
                            st.session_state[f"confirm_{delete_key}"] = True
                            st.warning(f"Delete {doc['original_filename']}?")

                # Indexing dialog
                if st.session_state.get(f"indexing_{doc['filename']}", False):
                    with st.expander(f"Index {doc['original_filename']}", expanded=True):
                        engines = rag_manager.get_available_engines()
                        engine_options = [e['type'] for e in engines if e['available']]

                        selected_engine = st.selectbox(
                            "Select engine",
                            engine_options,
                            key=f"engine_select_{doc['filename']}"
                        )

                        col_a, col_b = st.columns(2)
                        with col_a:
                            if st.button("✅ Index", type="primary"):
                                if rag_manager.index_document(doc['filename'], selected_engine, user_id):
                                    st.success(f"Document indexed with {selected_engine} engine")
                                    st.session_state[f"indexing_{doc['filename']}"] = False
                                    st.rerun()
                        with col_b:
                            if st.button("❌ Cancel"):
                                st.session_state[f"indexing_{doc['filename']}"] = False
                                st.rerun()


def _show_engines_tab():
    """Show RAG engines management tab."""
    st.header("RAG Engines")

    engines = rag_manager.get_available_engines()

    if not engines:
        st.warning("No RAG engines available")
        return

    # Engine selection
    st.subheader("Available Engines")

    for engine in engines:
        col1, col2, col3 = st.columns([2, 3, 1])

        with col1:
            st.write(f"**{engine['type'].upper()}**")
            if engine['default']:
                st.caption("⭐ Default")

        with col2:
            st.write(engine['description'])
            status = "✅ Available" if engine['available'] else "❌ Unavailable"
            st.caption(status)

        with col3:
            if not engine['default'] and engine['available']:
                if st.button("Set Default", key=f"set_default_{engine['type']}"):
                    # In a real implementation, you would update the config
                    st.info(f"Setting {engine['type']} as default would require config update")

    # Default engine info
    default_engine = rag_manager.get_default_engine()
    if default_engine:
        st.divider()
        st.subheader("Default Engine Info")
        st.write(f"**Type:** {default_engine.engine_type}")
        st.write(f"**Description:** {default_engine.description}")

        # Show stats
        stats = default_engine.get_stats()
        if stats:
            st.write("**Statistics:**")
            for key, value in stats.items():
                if key != 'engine_type':
                    st.write(f"- {key}: {value}")


def _show_search_test_tab():
    """Show search testing tab."""
    st.header("Search Test")

    current_user = st.session_state.get('current_user')
    if not current_user:
        st.warning("Please log in to test search")
        return

    user_id = current_user['id']

    col1, col2 = st.columns([3, 1])

    with col1:
        query = st.text_input("Enter search query", placeholder="Search in your documents...")

    with col2:
        engines = rag_manager.get_available_engines()
        engine_options = ["All"] + [e['type'] for e in engines if e['available']]
        selected_engine = st.selectbox("Engine", engine_options, index=0)

    if query and st.button("🔍 Search", type="primary"):
        with st.spinner("Searching..."):
            if selected_engine == "All":
                results = rag_manager.search(user_id, query)
            else:
                results = rag_manager.search(user_id, query, selected_engine)

            if not results:
                st.info("No results found")
            else:
                for engine_type, engine_results in results.items():
                    with st.expander(f"Results from {engine_type.upper()} ({len(engine_results)} found)", expanded=True):
                        for i, result in enumerate(engine_results[:5]):  # Limit to 5 results per engine
                            st.write(f"**Document:** {result['filename']}")
                            st.write(f"**Score:** {result['score']}")
                            st.write(f"**Content:**")
                            st.info(result['content'])
                            if i < len(engine_results) - 1:
                                st.divider()


def _show_stats_tab():
    """Show statistics tab."""
    st.header("Statistics")

    current_user = st.session_state.get('current_user')
    if not current_user:
        st.warning("Please log in to view statistics")
        return

    user_id = current_user['id']
    user_role = current_user['role']

    # Overall stats
    st.subheader("Overall Statistics")

    col1, col2, col3 = st.columns(3)

    with col1:
        total_docs = rag_manager.get_document_count()
        st.metric("Total Documents", total_docs)

    with col2:
        user_docs = rag_manager.get_document_count(user_id)
        st.metric("Your Documents", user_docs)

    with col3:
        total_size = rag_manager.get_total_size_mb()
        st.metric("Total Size", f"{total_size} MB")

    # Engine stats
    st.subheader("Engine Statistics")

    engines = rag_manager.get_available_engines()
    for engine in engines:
        if engine['available']:
            stats = rag_manager.get_engine_stats(engine['type'], user_id)
            if stats:
                with st.expander(f"{engine['type'].upper()} Engine Stats"):
                    for key, value in stats.items():
                        st.write(f"**{key.replace('_', ' ').title()}:** {value}")

    # Advanced options
    with st.expander("⚙️ Advanced Options", expanded=False):
        if user_role in ['admin', 'master']:
            col1, col2 = st.columns(2)

            with col1:
                if st.button("🗑️ Clear All Your Documents", type="secondary"):
                    if st.session_state.get("confirm_clear_all", False):
                        if rag_manager.clear_all_documents(user_id):
                            st.success("All your documents cleared")
                            st.rerun()
                    else:
                        st.session_state["confirm_clear_all"] = True
                        st.warning("Are you sure? This will delete ALL documents you have access to.")

            with col2:
                if st.button("🔄 Refresh", type="secondary"):
                    st.rerun()


def inject_ui_admin_tab():
    """Register the enhanced RAG Manager admin tab."""
    return ("RAG Manager", show_rag_admin_content)


def inject_ui_initialize():
    """Initialize RAG manager module."""
    # RAG manager is already initialized as a singleton
    return True


def inject_ui_main_content():
    """Render RAG manager content in main area (if applicable)."""
    # This module only provides admin interface
    return None


# Test function
def test_rag_manager():
    """Test the RAG manager functionality."""
    try:
        # Test engine discovery
        engines = rag_manager.get_available_engines()
        log("info", f"Test: Found {len(engines)} RAG engines")

        # Test default engine
        default_engine = rag_manager.get_default_engine()
        if default_engine:
            log("info", f"Test: Default engine is {default_engine.engine_type}")

        return True
    except Exception as e:
        log("error", f"RAG Manager test failed: {str(e)}", exc_info=True)
        return False
