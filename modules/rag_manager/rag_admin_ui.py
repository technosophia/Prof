"""
Enhanced RAG Admin UI with Engine Management
"""

import streamlit as st
import os
from datetime import datetime
from pathlib import Path
import tempfile
from shared.logging import log
from shared.common import _
from shared.config import get_config
import json

from modules.rag_manager.rag_manager import rag_manager


def show_rag_admin_content():
    """Display the enhanced RAG Manager admin content."""
    st.title("📚 RAG Document Manager")

    # Tabs for different functionalities - ADDED CACHE TAB
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📄 Documents",
        "🔧 Engines",
        "🔍 Search Test",
        "📊 Stats",
        "🔗 Index",
        "🔄 Cache"  # NEW TAB
    ])

    with tab1:
        _show_documents_tab()

    with tab2:
        _show_engines_tab()

    with tab3:
        _show_search_test_tab()

    with tab4:
        _show_stats_tab()

    with tab5:
        _show_index_tab()

    with tab6:  # NEW CACHE TAB
        _show_cache_tab()


def _show_cache_tab():
    """Show cache management tab."""
    st.header("🔄 Cache Management")

    # Check if cache management is available
    if not hasattr(rag_manager, 'get_cache_info'):
        st.warning("Cache management is not available in this version.")
        st.info("Ensure you have the latest RAG manager with caching support.")
        return

    # Get cache information
    cache_info = rag_manager.get_cache_info()

    # Cache status display
    col1, col2, col3 = st.columns(3)

    with col1:
        if cache_info.get('caching_available', False):
            st.metric("Caching", "✅ Available", delta=None)
        else:
            st.metric("Caching", "❌ Unavailable", delta="Not enabled")

    with col2:
        if cache_info.get('cache_initialized', False):
            st.metric("Status", "✅ Initialized", delta=None)
        else:
            st.metric("Status", "❌ Not Initialized", delta="Check config")

    with col3:
        cached_count = len(cache_info.get('cached_models', []))
        st.metric("Cached Models", cached_count)

    # Cache control buttons
    st.subheader("Cache Operations")

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("🔄 Clear Cache", type="primary", use_container_width=True,
                   help="Clear all cached model weights. Models will reload on next use."):
            with st.spinner("Clearing cache..."):
                if rag_manager.clear_model_cache():
                    st.success("Cache cleared successfully!")
                    st.rerun()
                else:
                    st.error("Failed to clear cache")

    with col2:
        if st.button("📊 Refresh Cache Info", use_container_width=True):
            st.rerun()

    with col3:
        if st.button("⚙️ Reload Config", use_container_width=True,
                   help="Reload RAG configuration from config file"):
            with st.spinner("Reloading config..."):
                rag_manager.refresh_config()
                st.success("Configuration reloaded!")
                st.rerun()

    # Cache details
    st.subheader("Cache Details")

    if cache_info.get('cached_models'):
        st.write("**Currently Cached Models:**")

        # Display each cached model
        for model_name in cache_info.get('cached_models', []):
            with st.expander(f"📦 {model_name}", expanded=False):
                # Try to get additional info
                st.write(f"**Model:** `{model_name}`")

                # Show cache statistics if available
                cache_stats = cache_info.get('cache_stats', {})
                if model_name in cache_stats:
                    model_stats = cache_stats[model_name]
                    st.write("**Cache Statistics:**")
                    for key, value in model_stats.items():
                        if key != 'model_name':
                            st.write(f"- {key.replace('_', ' ').title()}: {value}")

        # Total cache info
        st.divider()
        st.info(f"Total models cached: {len(cache_info.get('cached_models', []))}")
    else:
        st.info("No models are currently cached.")

    # Performance information
    st.subheader("Performance Information")

    with st.expander("ℹ️ About Caching", expanded=False):
        st.markdown("""
        **Model caching improves performance by:**

        1. **Faster loading**: Models load once and are reused
        2. **Reduced memory**: Single instance shared across sessions
        3. **Better UX**: No waiting for model downloads

        **Cache behavior:**
        - Models are cached for 1 hour (TTL)
        - Maximum 3 models cached at once
        - Cache is cleared when configuration changes
        - Cache can be manually cleared when needed
        """)

    # Advanced cache management
    st.subheader("Advanced Cache Management")

    with st.expander("🔧 Advanced Options", expanded=False):
        col1, col2 = st.columns(2)

        with col1:
            # Pre-load specific model
            popular_models = [
                "sentence-transformers/all-MiniLM-L6-v2",
                "sentence-transformers/all-mpnet-base-v2",
                "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
            ]

            model_to_preload = st.selectbox(
                "Pre-load model",
                options=popular_models,
                index=0,
                help="Select a model to pre-load into cache"
            )

            if st.button("Pre-load Model", use_container_width=True):
                # Note: This requires implementation in rag_caching.py
                st.info(f"Model pre-loading would be implemented in rag_caching.py")
                # Example: rag_manager.preload_model(model_to_preload)

        with col2:
            # Cache size adjustment
            cache_size = st.slider(
                "Max cache entries",
                min_value=1,
                max_value=10,
                value=3,
                help="Maximum number of models to keep in cache"
            )

            if st.button("Update Cache Size", use_container_width=True):
                st.info(f"Cache size set to {cache_size} entries")
                # Note: This would require updating @st.cache_resource decorator

        # Cache debugging
        st.divider()
        st.write("**Debug Information:**")
        st.code(json.dumps(cache_info, indent=2), language="json")

    # Cache statistics over time (placeholder for future implementation)
    st.subheader("Cache Performance")

    # Placeholder for cache hit/miss statistics
    st.info("""
    **Future enhancements:**
    - Cache hit/miss statistics
    - Memory usage tracking
    - Performance comparison graphs
    - Automatic cache optimization
    """)


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

            # Always show all available engines, even if empty
            if selected_engine == "All":
                all_engines = [e['type'] for e in engines if e['available']]
                for engine_type in all_engines:
                    engine_results = results.get(engine_type, [])
                    with st.expander(f"{engine_type.upper()} Engine ({len(engine_results)} results)", expanded=False):
                        if engine_results:
                            for i, result in enumerate(engine_results):
                                st.write(f"**Document:** {result['filename']}")
                                st.write(f"**Score:** {result['score']:.4f}")
                                st.write(f"**Content:**")
                                st.info(result['content'][:500] + "..." if len(result['content']) > 500 else result['content'])
                                if i < len(engine_results) - 1:
                                    st.divider()
                        else:
                            st.info(f"No results found from {engine_type.upper()} engine")
            else:
                # Single engine search
                engine_results = results.get(selected_engine, [])
                if engine_results:
                    st.subheader(f"Results from {selected_engine.upper()} ({len(engine_results)} found)")
                    for i, result in enumerate(engine_results):
                        st.write(f"**Document:** {result['filename']}")
                        st.write(f"**Score:** {result['score']:.4f}")
                        st.write(f"**Content:**")
                        st.info(result['content'][:500] + "..." if len(result['content']) > 500 else result['content'])
                        if i < len(engine_results) - 1:
                            st.divider()
                else:
                    st.info(f"No results found from {selected_engine.upper()} engine")

            # Show raw results for debugging
            with st.expander("🔧 Debug Info", expanded=False):
                st.json(results)


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


def _show_index_tab():
    """NEW: Show document indexing tab."""
    st.header("📚 Document Indexing")

    # Get current user
    current_user = st.session_state.get('current_user')
    if not current_user:
        st.warning("Please log in to manage indexing")
        return

    user_id = current_user['id']

    # Helper function to clear engine index and metadata
    def clear_engine_index_for_user(engine_type, user_id):
        """Clear engine index for a user and update metadata."""
        engine = rag_manager.get_engine(engine_type)
        if not engine:
            return False, "Engine not found"

        # Clear from engine
        if not engine.clear_user_index(user_id):
            return False, "Failed to clear engine index"

        # Update metadata
        updated_count = 0
        for filename, doc_info in rag_manager.documents.items():
            # Check if this document belongs to the user
            if 'uploaded_by' in doc_info and doc_info['uploaded_by'] == user_id:
                # Check if it's indexed in this engine
                if 'indexed_in' in doc_info and engine_type in doc_info['indexed_in']:
                    # Remove this engine from indexed_in
                    del doc_info['indexed_in'][engine_type]
                    updated_count += 1

        # Save the updated metadata
        rag_manager._save_metadata()

        return True, f"Cleared index for {updated_count} documents"

    # Get available engines
    engines = rag_manager.get_available_engines()
    available_engines = [e for e in engines if e['available']]

    if not available_engines:
        st.warning("No RAG engines available for indexing")
        return

    # Engine selection
    st.subheader("1. Select RAG Engine")

    engine_options = {e['type']: e for e in available_engines}
    selected_engine_type = st.selectbox(
        "Choose an engine to index documents:",
        options=list(engine_options.keys()),
        format_func=lambda x: f"{x.upper()} - {engine_options[x]['description']}"
    )

    # Get documents for current user
    documents = rag_manager.get_user_documents(user_id)

    if not documents:
        st.info("No documents available for indexing. Upload documents first.")
        return

    # Filter documents not yet indexed in selected engine
    unindexed_documents = []
    indexed_documents = []

    for doc in documents:
        if selected_engine_type in doc.get('indexed_in', []):
            indexed_documents.append(doc)
        else:
            unindexed_documents.append(doc)

    st.subheader("2. Indexing Status")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Documents", len(documents))
    with col2:
        st.metric("Indexed", len(indexed_documents))
    with col3:
        st.metric("Not Indexed", len(unindexed_documents))

    # Indexing options
    st.subheader("3. Indexing Options")

    if unindexed_documents:
        # Individual document indexing
        st.markdown("**Index Individual Documents**")

        # Create a table of unindexed documents with checkboxes
        st.markdown("Select documents to index:")

        selected_docs = []
        for doc in unindexed_documents:
            col1, col2, col3 = st.columns([1, 3, 2])
            with col1:
                # Checkbox for selection
                if st.checkbox("Select", key=f"select_{doc['filename']}_{selected_engine_type}"):
                    selected_docs.append(doc)
            with col2:
                st.write(f"**{doc['original_filename']}**")
            with col3:
                upload_date = datetime.fromisoformat(doc['uploaded_at']).strftime("%Y-%m-%d")
                st.write(f"Uploaded: {upload_date}")

        # Bulk indexing options
        st.divider()
        st.markdown("**Bulk Operations**")

        col_a, col_b, col_c = st.columns(3)

        with col_a:
            # Index selected documents
            if selected_docs and st.button(f"📥 Index Selected ({len(selected_docs)})", type="primary"):
                success_count = 0
                failed_count = 0

                with st.spinner(f"Indexing {len(selected_docs)} document(s)..."):
                    for doc in selected_docs:
                        if rag_manager.index_document(doc['filename'], selected_engine_type, user_id):
                            success_count += 1
                        else:
                            failed_count += 1

                if success_count > 0:
                    st.success(f"Successfully indexed {success_count} document(s)")
                if failed_count > 0:
                    st.error(f"Failed to index {failed_count} document(s)")
                st.rerun()

        with col_b:
            # Index all unindexed documents
            if unindexed_documents and st.button("📦 Index All Unindexed", type="secondary"):
                success_count = 0
                failed_count = 0

                with st.spinner(f"Indexing {len(unindexed_documents)} document(s)..."):
                    for doc in unindexed_documents:
                        if rag_manager.index_document(doc['filename'], selected_engine_type, user_id):
                            success_count += 1
                        else:
                            failed_count += 1

                if success_count > 0:
                    st.success(f"Successfully indexed {success_count} document(s)")
                if failed_count > 0:
                    st.error(f"Failed to index {failed_count} document(s)")
                st.rerun()

        with col_c:
            # Re-index all documents (even already indexed)
            if st.button("🔄 Re-index All", type="secondary"):
                success_count = 0
                failed_count = 0

                with st.spinner(f"Re-indexing {len(documents)} document(s)..."):
                    for doc in documents:
                        if rag_manager.index_document(doc['filename'], selected_engine_type, user_id):
                            success_count += 1
                        else:
                            failed_count += 1

                if success_count > 0:
                    st.success(f"Successfully re-indexed {success_count} document(s)")
                if failed_count > 0:
                    st.error(f"Failed to re-index {failed_count} document(s)")
                st.rerun()

    else:
        st.info(f"All your documents are already indexed in the {selected_engine_type} engine.")

        # Option to re-index anyway
        if st.button("🔄 Re-index All Documents Anyway", type="secondary"):
            success_count = 0
            failed_count = 0

            with st.spinner(f"Re-indexing {len(documents)} document(s)..."):
                for doc in documents:
                    if rag_manager.index_document(doc['filename'], selected_engine_type, user_id):
                        success_count += 1
                    else:
                        failed_count += 1

            if success_count > 0:
                st.success(f"Successfully re-indexed {success_count} document(s)")
            if failed_count > 0:
                st.error(f"Failed to re-index {failed_count} document(s)")
            st.rerun()

    # Already indexed documents section
    if indexed_documents:
        st.divider()
        st.subheader(f"Already Indexed in {selected_engine_type.upper()}")

        with st.expander(f"View {len(indexed_documents)} indexed documents", expanded=False):
            for doc in indexed_documents:
                col1, col2, col3 = st.columns([3, 2, 1])
                with col1:
                    st.write(f"**{doc['original_filename']}**")
                with col2:
                    # Get indexing date if available
                    doc_info = rag_manager.documents.get(doc['filename'], {})
                    indexed_info = doc_info.get('indexed_in', {})
                    if selected_engine_type in indexed_info:
                        index_date = datetime.fromisoformat(indexed_info[selected_engine_type]).strftime("%Y-%m-%d %H:%M")
                        st.caption(f"Indexed: {index_date}")
                with col3:
                    # Re-index button for individual document
                    if st.button("↻", key=f"reindex_{doc['filename']}_{selected_engine_type}", help="Re-index this document"):
                        with st.spinner(f"Re-indexing {doc['original_filename']}..."):
                            if rag_manager.index_document(doc['filename'], selected_engine_type, user_id):
                                st.success(f"Re-indexed {doc['original_filename']}")
                                st.rerun()

    # Engine management section
    st.divider()
    st.subheader("4. Engine Management")

    selected_engine = rag_manager.get_engine(selected_engine_type)
    if selected_engine:
        col1, col2 = st.columns(2)

        with col1:
            # Get engine stats
            engine_stats = selected_engine.get_stats(user_id)
            st.markdown("**Engine Statistics**")
            if engine_stats:
                for key, value in engine_stats.items():
                    if key != 'engine_type':
                        st.write(f"- {key.replace('_', ' ').title()}: {value}")
            else:
                st.write("No statistics available")

        with col2:
            # Clear index option
            st.markdown("**Index Management**")
            if st.button("🗑️ Clear Index for This Engine", type="secondary"):
                if st.session_state.get(f"confirm_clear_{selected_engine_type}", False):
                    success, message = clear_engine_index_for_user(selected_engine_type, user_id)
                    if success:
                        st.success(message)
                        st.rerun()
                    else:
                        st.error(message)
                else:
                    st.session_state[f"confirm_clear_{selected_engine_type}"] = True
                    st.warning(f"Are you sure you want to clear the {selected_engine_type} index? This will remove all your documents from this engine's index.")

    # Refresh button
    if st.button("🔄 Refresh Indexing Status"):
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
