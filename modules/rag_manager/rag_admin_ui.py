"""
Enhanced RAG Admin UI with Engine Management
"""

import streamlit as st
import os
import json
from datetime import datetime
from pathlib import Path
import tempfile
import uuid

from st_shared.cached import get_config
from modules.rag_manager.rag_limits_ui import render_limit_management_panel, render_limit_controls_in_search

def _get_rag_manager():
    """Lazy accessor — never called at module import time."""
    from modules.rag_manager.rag_factory import get_rag_manager
    return get_rag_manager()


from core.logging import log, set_log_module_level
from st_shared.cached import _

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
    st.header("🔄 Cache & Model Management")

    # Check if cache management is available
    if not hasattr(_get_rag_manager(), 'get_cache_info'):
        st.warning("Cache management is not available in this version.")
        st.info("Ensure you have the latest RAG manager with caching support.")
        return

    # Get cache information
    cache_info = _get_rag_manager().get_cache_info()

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
                if _get_rag_manager().clear_model_cache():
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
                _get_rag_manager().refresh_config()
                st.success("Configuration reloaded!")
                st.rerun()

    # ===== NEW: Model Change & Re-indexing Section =====
    st.divider()
    st.subheader("🔄 Model Change & Re-indexing")

    st.warning("""
    **Important:** When changing embedding models, you must re-index all documents.
    Different embedding models produce vectors of different dimensions, which are incompatible.
    """)

    # Get current model info from engines
    current_models = {}
    engines = _get_rag_manager().get_available_engines()

    for engine_info in engines:
        if engine_info['available']:
            engine = _get_rag_manager().get_engine(engine_info['type'])
            if hasattr(engine, 'model_name'):
                current_models[engine_info['type']] = engine.model_name

    if current_models:
        st.write("**Current Embedding Models:**")
        for engine_type, model_name in current_models.items():
            st.caption(f"- {engine_type}: `{model_name}`")

    # Re-indexing options
    st.markdown("### Re-indexing Options")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Step 1: Clear Existing Indices**")
        st.caption("Clear all indices before re-indexing with new model")

        if st.button("🗑️ Clear All Indices", type="secondary", use_container_width=True,
                    help="Clear all indices from all engines. Required before re-indexing with new model."):

            with st.spinner("Clearing all engine indices..."):
                # Double confirmation
                if st.session_state.get("confirm_clear_all_indices", False):
                    clear_stats = _get_rag_manager().clear_all_engine_indices()

                    if clear_stats:
                        st.success(f"Cleared indices for {len(clear_stats['engines_cleared'])} engines")
                        st.info(f"Updated metadata for {clear_stats['documents_updated']} documents")

                        if clear_stats['engines_failed']:
                            st.error(f"Failed to clear: {', '.join(clear_stats['engines_failed'])}")

                        # Reset confirmation
                        st.session_state["confirm_clear_all_indices"] = False
                        st.rerun()
                    else:
                        st.error("Failed to clear indices")
                else:
                    st.session_state["confirm_clear_all_indices"] = True
                    st.warning("⚠️ Are you absolutely sure? This will remove all indexed data from all engines. You will need to re-index all documents.")

    with col2:
        st.markdown("**Step 2: Re-index All Documents**")
        st.caption("Re-index all documents with current model")

        # Engine selection for re-indexing
        available_engines = [e['type'] for e in engines if e['available']]
        selected_engines = st.multiselect(
            "Select engines to re-index",
            options=available_engines,
            default=available_engines,
            key="reindex_engine_select",
            help="Choose which engines to re-index"
        )

        if st.button("🔄 Re-index All Documents", type="primary", use_container_width=True,
                    help="Re-index all documents across selected engines"):

            if not selected_engines:
                st.error("Please select at least one engine")
            else:
                with st.spinner(f"Re-indexing all documents with {len(selected_engines)} engine(s)... This may take a while."):

                    # Get document count for progress indication
                    docs = _get_rag_manager().get_user_documents(st.session_state.current_user['id'])
                    total_docs = len(docs)

                    if total_docs == 0:
                        st.info("No documents to re-index")
                    else:
                        # Create progress bar
                        progress_bar = st.progress(0, text=f"Re-indexing 0/{total_docs} documents...")

                        # Run re-indexing
                        reindex_stats = _get_rag_manager().reindex_all_documents(selected_engines)

                        progress_bar.empty()

                        # Show results
                        if reindex_stats['successful'] > 0:
                            st.success(f"✅ Successfully re-indexed: {reindex_stats['successful']} documents")

                        if reindex_stats['failed'] > 0:
                            st.error(f"❌ Failed: {reindex_stats['failed']} documents")

                            # Show errors in expander
                            with st.expander("View Errors"):
                                for error in reindex_stats['errors'][:10]:  # Show first 10
                                    st.caption(f"- {error}")
                                if len(reindex_stats['errors']) > 10:
                                    st.caption(f"... and {len(reindex_stats['errors']) - 10} more errors")

                        if reindex_stats['skipped'] > 0:
                            st.warning(f"⚠️ Skipped: {reindex_stats['skipped']} documents")

                        # Show per-engine stats
                        st.markdown("**Per-Engine Results:**")
                        for engine_type, stats in reindex_stats['engines_processed'].items():
                            st.caption(
                                f"- {engine_type}: {stats['successful']} successful, "
                                f"{stats['failed']} failed, {stats['skipped']} skipped"
                            )

    # Complete workflow button
    st.divider()
    st.markdown("### 🚀 Complete Workflow")

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("🔄 Clear & Re-index (All-in-One)", type="secondary", use_container_width=True):

            if st.session_state.get("confirm_complete_reindex", False):
                with st.spinner("Step 1: Clearing all indices..."):
                    _get_rag_manager().clear_all_engine_indices()

                with st.spinner("Step 2: Re-indexing all documents..."):
                    reindex_stats = _get_rag_manager().reindex_all_documents(available_engines)

                st.success(f"✅ Complete! Re-indexed {reindex_stats['successful']} documents")

                if reindex_stats['failed'] > 0:
                    st.error(f"❌ Failed: {reindex_stats['failed']} documents")

                st.session_state["confirm_complete_reindex"] = False
                st.rerun()
            else:
                st.session_state["confirm_complete_reindex"] = True
                st.warning("⚠️ This will clear ALL indices and re-index ALL documents. This action cannot be undone. Are you sure?")

    # Model change instructions
    with st.expander("ℹ️ How to Change Embedding Models", expanded=False):
        st.markdown("""
        **Steps to change embedding models:**

        1. **Update configuration**: Change `model_name` and `vector_dimension` in your config file
        2. **Clear cache**: Click "Clear Cache" above to remove old model weights
        3. **Clear indices**: Click "Clear All Indices" to remove incompatible vector data
        4. **Re-index**: Click "Re-index All Documents" to rebuild indices with new model

        **Why this is necessary:**
        - Different embedding models produce vectors of different dimensions
        - FAISS indexes are hard-coded to a specific dimension
        - Mixing dimensions causes errors and corrupts indexes
        """)

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
            key="doc_uploader",
            help=f"Maximum file size: {rag_config.get('max_file_size_mb', 10)}MB"
        )

    with col2:
        # Public upload option (only for admin/masters)
        is_public = False
        if user_role in ['admin', 'master']:
            is_public = st.checkbox(
                "Make public",
                key="make_public_checkbox",
                help="Public documents are visible to all users"
            )

        if uploaded_files and st.button("📤 Upload", type="primary", key="upload_button"):
            success_count = 0
            error_count = 0

            for uploaded_file in uploaded_files:
                try:
                    # Save uploaded file to temp location
                    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as tmp_file:
                        tmp_file.write(uploaded_file.getvalue())
                        tmp_path = tmp_file.name

                    # Upload to RAG manager
                    result = _get_rag_manager().upload_document(
                        tmp_path,
                        uploaded_file.name,
                        user_id,
                        is_public
                    )

                    # Clean up temp file
                    os.unlink(tmp_path)

                    if result:
                        success_count += 1
                        log("debug", f"Successfully uploaded: {uploaded_file.name}")
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

    documents = _get_rag_manager().get_user_documents(user_id)

    if not documents:
        st.info("No documents uploaded yet.")
    else:
        # Create a table of documents
        for i, doc in enumerate(documents):
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
                    if st.button("🔍", key=f"index_btn_{doc['filename']}_{i}", help="Index this document"):
                        st.session_state[f"indexing_{doc['filename']}"] = True

                with btn_col2:
                    # Delete button
                    delete_key = f"delete_btn_{doc['filename']}_{i}"
                    if st.button("🗑️", key=delete_key, help="Delete this document"):
                        if st.session_state.get(f"confirm_{delete_key}", False):
                            if _get_rag_manager().delete_document(doc['filename'], user_id):
                                st.success("Document deleted")
                                st.rerun()
                        else:
                            st.session_state[f"confirm_{delete_key}"] = True
                            st.warning(f"Delete {doc['original_filename']}?")

                # Indexing dialog
                if st.session_state.get(f"indexing_{doc['filename']}", False):
                    with st.expander(f"Index {doc['original_filename']}", expanded=True):
                        engines = _get_rag_manager().get_available_engines()
                        engine_options = [e['type'] for e in engines if e['available']]

                        selected_engine = st.selectbox(
                            "Select engine",
                            engine_options,
                            key=f"engine_select_{doc['filename']}_{i}",
                            index=0
                        )

                        col_a, col_b = st.columns(2)
                        with col_a:
                            if st.button("✅ Index", type="primary", key=f"confirm_index_{doc['filename']}_{i}"):
                                if _get_rag_manager().index_document(doc['filename'], selected_engine, user_id):
                                    st.success(f"Document indexed with {selected_engine} engine")
                                    st.session_state[f"indexing_{doc['filename']}"] = False
                                    st.rerun()
                        with col_b:
                            if st.button("❌ Cancel", key=f"cancel_index_{doc['filename']}_{i}"):
                                st.session_state[f"indexing_{doc['filename']}"] = False
                                st.rerun()


def _show_engines_tab():
    """Show RAG engines management tab — with inline config editor per engine."""
    st.header("RAG Engines")

    engines = _get_rag_manager().get_available_engines()
    if not engines:
        st.warning("No RAG engines available")
        return

    st.subheader("Available Engines")

    for i, engine in enumerate(engines):
        status_icon = "✅" if engine["available"] else "❌"
        default_badge = " ⭐ default" if engine["default"] else ""
        label = f"{status_icon} **{engine['type'].upper()}**{default_badge} — {engine['description']}"

        with st.expander(label, expanded=engine["default"]):

            col1, col2 = st.columns([2, 1])
            with col1:
                st.caption(f"Status: {'Available' if engine['available'] else 'Unavailable'}")
                # Show current live stats (chunks, docs)
                eng_obj = _get_rag_manager().get_engine(engine["type"])
                if eng_obj:
                    stats = eng_obj.get_stats()
                    info_parts = []
                    for k in ("total_chunks", "total_documents_indexed", "users_with_index",
                              "model_name", "dimension"):
                        if k in stats:
                            info_parts.append(f"{k.replace('_', ' ')}: **{stats[k]}**")
                    if info_parts:
                        st.caption("  ·  ".join(info_parts))

            with col2:
                if not engine["default"] and engine["available"]:
                    if st.button("Set as default", key=f"set_default_{engine['type']}_{i}"):
                        st.info(f"Setting default engine requires a config file change "
                                f"(set `default_engine` to `{engine['type']}`).")

            if engine["available"]:
                st.divider()
                st.markdown("**⚙️ Live Config Override**")
                _show_engine_config_editor(engine["type"])

    # Default engine info
    default_engine = _get_rag_manager().get_default_engine()
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

    # Add result limits management panel
    st.divider()
    render_limit_management_panel(_get_rag_manager())


def _show_search_test_tab():
    """Show search testing tab with diagnostics and integrity tooling."""
    st.header("Search Test")

    current_user = st.session_state.get('current_user')
    if not current_user:
        st.warning("Please log in to test search")
        return

    user_id = current_user['id']
    user_role = current_user.get('role')
    engines = _get_rag_manager().get_available_engines()
    available_engine_types = [e['type'] for e in engines if e['available']]

    # Result limit controls - with unique keys
    limit_controls = render_limit_controls_in_search(
        _get_rag_manager(),
        user_id,
        key_prefix="search_test"
    )

    # Generate a unique query ID for this search session if not exists
    if "search_test_query_id" not in st.session_state:
        st.session_state.search_test_query_id = str(uuid.uuid4())

    # Search input
    query = st.text_input(
        "Enter search query",
        placeholder="Search in your documents...",
        key="search_test_query_input"
    )

    col1, col2 = st.columns([2, 1])

    with col1:
        # Engine selection - WITH UNIQUE KEY
        engine_options_list = ["All"] + available_engine_types
        selected_engine = st.selectbox(
            "Engine",
            options=engine_options_list,  # ← Fixed: use 'options' not 'engine_options'
            index=0,
            key="search_test_engine_select"
        )

    with col2:
        # Show active override info if any
        if limit_controls["is_override"]:
            st.info(f"🔍 Override: {limit_controls['limit']} results")
        else:
            st.caption(f"Default: {limit_controls['limit']} results")

    threshold = st.slider(
        "Similarity Threshold (vector engines only)",
        min_value=0.0,
        max_value=1.0,
        value=0.5,
        step=0.05,
        key="search_test_threshold",
        help="Temporarily applied to classic/faiss_hierarchical for this search only."
    )
    st.caption("Threshold change is temporary and only applied for the current search execution.")

    integrity_failures = []

    def run_integrity_check():
        check_rows = []
        failed_docs = []

        user_docs = _get_rag_manager().get_user_documents(user_id)
        for doc in user_docs:
            filename = doc['filename']
            owner_id = doc['uploaded_by']
            metadata_doc = _get_rag_manager().documents.get(filename, {})
            file_path = metadata_doc.get('file_path', '')
            file_exists = bool(file_path) and os.path.exists(file_path)

            if not file_exists:
                check_rows.append({
                    'filename': filename,
                    'engine': '-',
                    'status': '❌ File missing on disk'
                })
                failed_docs.append(doc)
                continue

            indexed_in = doc.get('indexed_in', [])
            if not indexed_in:
                check_rows.append({
                    'filename': filename,
                    'engine': '-',
                    'status': '⚠️ Not indexed in any engine'
                })
                continue

            for eng_type in indexed_in:
                eng = _get_rag_manager().get_engine(eng_type)
                if not eng:
                    check_rows.append({
                        'filename': filename,
                        'engine': eng_type,
                        'status': '⚠️ Engine unavailable'
                    })
                    failed_docs.append(doc)
                    continue

                indexed_docs = eng.get_indexed_documents(owner_id)
                found = any(item.get('filename') == filename for item in indexed_docs)

                if found:
                    status = '✅ OK'
                else:
                    status = '⚠️ Indexed in metadata but not found in engine'
                    failed_docs.append(doc)

                check_rows.append({
                    'filename': filename,
                    'engine': eng_type,
                    'status': status
                })

        return check_rows, failed_docs

    if st.button("🩺 Run Index Integrity Check", key="integrity_check_btn"):
        rows, integrity_failures = run_integrity_check()
        if rows:
            st.dataframe(rows, use_container_width=True)
        if integrity_failures:
            st.warning(f"Integrity issues found for {len({d['filename'] for d in integrity_failures})} document(s).")
            if st.button("Re-index all documents", key="reindex_failed_btn"):
                with st.spinner("Re-indexing affected documents..."):
                    repaired = 0
                    for doc in {d['filename']: d for d in integrity_failures}.values():
                        filename = doc['filename']
                        owner_id = doc['uploaded_by']
                        indexed_in = doc.get('indexed_in', [])
                        if not indexed_in:
                            indexed_in = available_engine_types
                        for eng_type in indexed_in:
                            if _get_rag_manager().index_document(filename, eng_type, user_id):
                                repaired += 1
                    st.success(f"Re-index complete. Successful indexing operations: {repaired}")
                    rows_after, failures_after = run_integrity_check()
                    st.dataframe(rows_after, use_container_width=True)
                    if failures_after:
                        st.error("Some integrity issues remain after re-indexing.")
                    else:
                        st.success("All integrity checks passed after re-indexing.")
        else:
            st.success("Integrity check passed.")

    if query and st.button("🔍 Search", type="primary", key="search_test_btn"):
        vector_engine_types = ['classic', 'faiss_hierarchical']
        original_thresholds = _get_rag_manager().set_similarity_thresholds({
            engine_type: threshold for engine_type in vector_engine_types
        })

        try:
            with st.spinner("Searching..."):
                # Use the limit from controls
                if selected_engine == "All":
                    results = _get_rag_manager().search(
                        user_id,
                        query,
                        search_all=True,
                        limit=limit_controls["limit"],
                        query_id=limit_controls["query_id"]
                    )
                else:
                    results = _get_rag_manager().search(
                        user_id,
                        query,
                        selected_engine,
                        limit=limit_controls["limit"],
                        query_id=limit_controls["query_id"]
                    )

                # Show override indicator if active
                if limit_controls["is_override"]:
                    st.info(f"🔍 Using temporary override: {limit_controls['limit']} results")

                if selected_engine == "All":
                    for engine_type in available_engine_types:
                        engine_results = results.get(engine_type, [])
                        with st.expander(f"{engine_type.upper()} Engine ({len(engine_results)} results)", expanded=False):
                            if engine_results:
                                for i, result in enumerate(engine_results):
                                    st.write(f"**Document:** {result['filename']}")
                                    st.write(f"**Score:** {result['score']:.4f}")
                                    st.info(result['content'][:500] + "..." if len(result['content']) > 500 else result['content'])
                                    if i < len(engine_results) - 1:
                                        st.divider()
                            else:
                                st.info(f"No results found from {engine_type.upper()} engine")
                else:
                    engine_results = results.get(selected_engine, [])
                    if engine_results:
                        st.subheader(f"Results from {selected_engine.upper()} ({len(engine_results)} found)")
                        for i, result in enumerate(engine_results):
                            st.write(f"**Document:** {result['filename']}")
                            st.write(f"**Score:** {result['score']:.4f}")
                            st.info(result['content'][:500] + "..." if len(result['content']) > 500 else result['content'])
                            if i < len(engine_results) - 1:
                                st.divider()
                    else:
                        st.info(f"No results found from {selected_engine.upper()} engine")

                with st.expander("🔍 Raw Debug Results (no threshold filtering)", expanded=False):
                    debug_original_thresholds = _get_rag_manager().set_similarity_thresholds({
                        engine_type: 0.0 for engine_type in vector_engine_types
                    })

                    try:
                        raw_rows = []
                        for eng_type in available_engine_types:
                            if selected_engine != 'All' and eng_type != selected_engine:
                                continue

                            eng = _get_rag_manager().get_engine(eng_type)
                            if not eng:
                                continue

                            owner_ids = sorted({d['uploaded_by'] for d in _get_rag_manager().get_user_documents(user_id)})
                            if eng_type == 'simple':
                                query_terms = [w for w in query.lower().split() if w]
                                for owner in owner_ids:
                                    user_index = getattr(eng, 'indices', {}).get(owner, {})
                                    for fn, data in user_index.items():
                                        full_content = data.get('content', '')
                                        lower_content = full_content.lower()
                                        raw_score = sum(lower_content.count(w) for w in query_terms)
                                        preview = eng._extract_context(full_content, query.lower()) if full_content else ''
                                        raw_rows.append({
                                            'engine': eng_type,
                                            'filename': fn,
                                            'raw_score': raw_score,
                                            'content preview': preview[:200]
                                        })
                            else:
                                for owner in owner_ids:
                                    raw_results = eng.search(owner, query, limit=100)
                                    for r in raw_results:
                                        raw_rows.append({
                                            'engine': eng_type,
                                            'filename': r.get('filename'),
                                            'raw_score': r.get('score', 0),
                                            'content preview': (r.get('content', '') or '')[:200]
                                        })

                        if raw_rows:
                            st.dataframe(raw_rows, use_container_width=True)
                        else:
                            st.info('No raw results returned even with threshold=0.0')
                    finally:
                        _get_rag_manager().restore_similarity_thresholds(debug_original_thresholds)

                with st.expander("🔧 Debug Info", expanded=False):
                    st.json(results)
        finally:
            _get_rag_manager().restore_similarity_thresholds(original_thresholds)


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
        total_docs = _get_rag_manager().get_document_count()
        st.metric("Total Documents", total_docs)

    with col2:
        user_docs = _get_rag_manager().get_document_count(user_id)
        st.metric("Your Documents", user_docs)

    with col3:
        total_size = _get_rag_manager().get_total_size_mb()
        st.metric("Total Size", f"{total_size} MB")

    # Engine stats
    st.subheader("Engine Statistics")

    engines = _get_rag_manager().get_available_engines()
    for i, engine in enumerate(engines):
        if engine['available']:
            stats = _get_rag_manager().get_engine_stats(engine['type'], user_id)
            if stats:
                with st.expander(f"{engine['type'].upper()} Engine Stats"):
                    for key, value in stats.items():
                        st.write(f"**{key.replace('_', ' ').title()}:** {value}")

    # Advanced options
    with st.expander("⚙️ Advanced Options", expanded=False):
        if user_role in ['admin', 'master']:
            col1, col2 = st.columns(2)

            with col1:
                if st.button("🗑️ Clear All Your Documents", type="secondary", key="clear_all_docs_btn"):
                    if st.session_state.get("confirm_clear_all", False):
                        if _get_rag_manager().clear_all_documents(user_id):
                            st.success("All your documents cleared")
                            st.rerun()
                    else:
                        st.session_state["confirm_clear_all"] = True
                        st.warning("Are you sure? This will delete ALL documents you have access to.")

            with col2:
                if st.button("🔄 Refresh", type="secondary", key="stats_refresh_btn"):
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
        engine = _get_rag_manager().get_engine(engine_type)
        if not engine:
            return False, "Engine not found"

        # Clear from engine
        if not engine.clear_user_index(user_id):
            return False, "Failed to clear engine index"

        # Update metadata
        updated_count = 0
        for filename, doc_info in _get_rag_manager().documents.items():
            # Check if this document belongs to the user
            if 'uploaded_by' in doc_info and doc_info['uploaded_by'] == user_id:
                # Check if it's indexed in this engine
                if 'indexed_in' in doc_info and engine_type in doc_info['indexed_in']:
                    # Remove this engine from indexed_in
                    del doc_info['indexed_in'][engine_type]
                    updated_count += 1

        # Save the updated metadata
        _get_rag_manager()._save_metadata()

        return True, f"Cleared index for {updated_count} documents"

    # Get available engines
    engines = _get_rag_manager().get_available_engines()
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
        format_func=lambda x: f"{x.upper()} - {engine_options[x]['description']}",
        key="index_tab_engine_select"  # ← UNIQUE KEY
    )

    # Get documents for current user
    documents = _get_rag_manager().get_user_documents(user_id)

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
        for i, doc in enumerate(unindexed_documents):
            col1, col2, col3 = st.columns([1, 3, 2])
            with col1:
                # Checkbox for selection
                if st.checkbox(
                    "Select",
                    key=f"select_doc_{doc['filename']}_{i}_{selected_engine_type}",
                    label_visibility="collapsed"
                ):
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
            if selected_docs and st.button(f"📥 Index Selected ({len(selected_docs)})", type="primary", key="index_selected_btn"):
                success_count = 0
                failed_count = 0

                with st.spinner(f"Indexing {len(selected_docs)} document(s)..."):
                    for doc in selected_docs:
                        if _get_rag_manager().index_document(doc['filename'], selected_engine_type, user_id):
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
            if unindexed_documents and st.button("📦 Index All Unindexed", type="secondary", key="index_all_btn"):
                success_count = 0
                failed_count = 0

                with st.spinner(f"Indexing {len(unindexed_documents)} document(s)..."):
                    for doc in unindexed_documents:
                        if _get_rag_manager().index_document(doc['filename'], selected_engine_type, user_id):
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
            if st.button("🔄 Re-index All", type="secondary", key="reindex_all_btn"):
                success_count = 0
                failed_count = 0

                with st.spinner(f"Re-indexing {len(documents)} document(s)..."):
                    for doc in documents:
                        if _get_rag_manager().index_document(doc['filename'], selected_engine_type, user_id):
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
        if st.button("🔄 Re-index All Documents Anyway", type="secondary", key="reindex_anyway_btn"):
            success_count = 0
            failed_count = 0

            with st.spinner(f"Re-indexing {len(documents)} document(s)..."):
                for doc in documents:
                    if _get_rag_manager().index_document(doc['filename'], selected_engine_type, user_id):
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
            for i, doc in enumerate(indexed_documents):
                col1, col2, col3 = st.columns([3, 2, 1])
                with col1:
                    st.write(f"**{doc['original_filename']}**")
                with col2:
                    # Get indexing date if available
                    doc_info = _get_rag_manager().documents.get(doc['filename'], {})
                    indexed_info = doc_info.get('indexed_in', {})
                    if selected_engine_type in indexed_info:
                        index_date = datetime.fromisoformat(indexed_info[selected_engine_type]).strftime("%Y-%m-%d %H:%M")
                        st.caption(f"Indexed: {index_date}")
                with col3:
                    # Re-index button for individual document
                    if st.button("↻", key=f"reindex_single_{doc['filename']}_{i}_{selected_engine_type}", help="Re-index this document"):
                        with st.spinner(f"Re-indexing {doc['original_filename']}..."):
                            if _get_rag_manager().index_document(doc['filename'], selected_engine_type, user_id):
                                st.success(f"Re-indexed {doc['original_filename']}")
                                st.rerun()

    # Engine management section
    st.divider()
    st.subheader("4. Engine Management")

    selected_engine = _get_rag_manager().get_engine(selected_engine_type)
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
            if st.button("🗑️ Clear Index for This Engine", type="secondary", key="clear_index_btn"):
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
    if st.button("🔄 Refresh Indexing Status", key="refresh_index_status_btn"):
        st.rerun()


def inject_ui_admin_tab():
    """Register the enhanced RAG Manager admin tab."""
    return ("RAG Manager", show_rag_admin_content)


def inject_ui_main_content():
    """Render RAG manager content in main area (if applicable)."""
    # This module only provides admin interface
    return None


# Test function
def test_rag_manager():
    """Test the RAG manager functionality."""
    try:
        # Test engine discovery
        engines = _get_rag_manager().get_available_engines()
        log("debug", f"Test: Found {len(engines)} RAG engines")

        # Test default engine
        default_engine = _get_rag_manager().get_default_engine()
        if default_engine:
            log("debug", f"Test: Default engine is {default_engine.engine_type}")

        return True
    except Exception as e:
        log("error", f"RAG Manager test failed: {str(e)}", stacktrace=True)
        return False


def _show_engine_config_editor(engine_type: str) -> None:
    """
    Render an inline config editor for one engine.
    Works for any engine that implements get_config() / update_config().
    For engines that don't (simple, classic, hierarchical), falls back to
    a raw JSON editor so they still get *some* override capability.
    """
    engine = _get_rag_manager().get_engine(engine_type)
    if not engine:
        st.warning(f"Engine '{engine_type}' not found.")
        return

    session_key = f"engine_cfg_draft_{engine_type}"

    # ---- Build the editable config dict ----
    if hasattr(engine, "get_config") and engine.get_config():
        # Structured editor path (hybrid and any future engine that implements it)
        current_cfg = engine.get_config()
        use_structured = True
    else:
        # Raw JSON fallback for legacy engines
        # Reconstruct a best-effort config from known attributes
        current_cfg = {}
        for attr in ("similarity_threshold", "chunk_size", "chunk_overlap",
                     "index_path", "model_name"):
            if hasattr(engine, attr):
                val = getattr(engine, attr)
                current_cfg[attr] = str(val) if isinstance(val, type(engine.index_path
                                           if hasattr(engine, "index_path") else "")) else val
        use_structured = False

    # Initialise session draft on first render
    if session_key not in st.session_state:
        st.session_state[session_key] = dict(current_cfg)

    draft: dict = st.session_state[session_key]

    if use_structured:
        # ---- Structured widget editor ----
        st.caption("Changes to retrieval params (threshold, hyde, bm25…) apply immediately. "
                   "Chunking changes apply on next re-index.")

        col1, col2 = st.columns(2)

        with col1:
            # --- Retrieval params ---
            st.markdown("**Retrieval**")

            if "similarity_threshold" in draft:
                draft["similarity_threshold"] = st.slider(
                    "Similarity threshold",
                    0.0, 1.0, float(draft["similarity_threshold"]), 0.01,
                    key=f"{session_key}_threshold")

            if "hyde" in draft:
                draft["hyde"] = st.checkbox(
                    "HyDE (embed hypothetical answer)", bool(draft["hyde"]),
                    key=f"{session_key}_hyde")

            if "hyde_prompt_key" in draft:
                draft["hyde_prompt_key"] = st.text_input(
                    "HyDE prompt key (dotted path in prompts yaml)",
                    str(draft.get("hyde_prompt_key") or ""),
                    key=f"{session_key}_hyde_key",
                    help="e.g. rag_manager.hyde_prompt — set to empty to use built-in fallback")

            if "bm25_hybrid" in draft:
                draft["bm25_hybrid"] = st.checkbox(
                    "BM25 hybrid", bool(draft["bm25_hybrid"]),
                    key=f"{session_key}_bm25")

            if "bm25_alpha" in draft:
                draft["bm25_alpha"] = st.slider(
                    "BM25 alpha (0=pure BM25, 1=pure cosine)",
                    0.0, 1.0, float(draft["bm25_alpha"]), 0.05,
                    key=f"{session_key}_alpha",
                    disabled=not draft.get("bm25_hybrid", True) or bool(draft.get("bm25_rerank_only", True)))

            if "bm25_rerank_only" in draft:
                draft["bm25_rerank_only"] = st.checkbox(
                    "BM25 as tiebreaker only (recommended)",
                    bool(draft["bm25_rerank_only"]),
                    key=f"{session_key}_bm25_rerank",
                    disabled=not draft.get("bm25_hybrid", True),
                    help=(
                        "When ON: BM25 only reorders chunks with similar cosine scores. "
                        "Prevents high-frequency topic words from drowning out rare "
                        "but critical phrases (negations, specific facts). "
                        "Turn OFF to use full alpha blend instead."
                    ))

            if "use_summaries" in draft:
                draft["use_summaries"] = st.checkbox(
                    "Use doc summaries as extra chunks", bool(draft["use_summaries"]),
                    key=f"{session_key}_summaries")

        with col2:
            # --- Chunking params ---
            st.markdown("**Chunking** *(next re-index)*")

            if "chunk_strategy" in draft:
                strategies = ["sentence_window", "fixed", "sentence", "dynamic"]
                idx = strategies.index(draft["chunk_strategy"]) \
                      if draft["chunk_strategy"] in strategies else 0
                draft["chunk_strategy"] = st.selectbox(
                    "Chunk strategy", strategies, index=idx,
                    key=f"{session_key}_strategy")

            if "sentence_window_size" in draft:
                draft["sentence_window_size"] = st.number_input(
                    "Sentence window ±N",
                    1, 10, int(draft["sentence_window_size"]),
                    key=f"{session_key}_window",
                    disabled=(draft.get("chunk_strategy") != "sentence_window"))

            if "chunk_size" in draft:
                draft["chunk_size"] = st.number_input(
                    "Chunk size (chars)",
                    50, 4000, int(draft["chunk_size"]),
                    key=f"{session_key}_chunk_size",
                    disabled=(draft.get("chunk_strategy") not in ("fixed", "dynamic")))

            if "chunk_overlap" in draft:
                draft["chunk_overlap"] = st.number_input(
                    "Chunk overlap (chars)",
                    0, 500, int(draft["chunk_overlap"]),
                    key=f"{session_key}_overlap",
                    disabled=(draft.get("chunk_strategy") != "fixed"))

            if "dynamic_chunk_sizes" in draft:
                raw = ", ".join(str(x) for x in draft["dynamic_chunk_sizes"])
                edited = st.text_input(
                    "Dynamic chunk sizes (comma-separated)",
                    raw,
                    key=f"{session_key}_dyn_sizes",
                    disabled=(draft.get("chunk_strategy") != "dynamic"))
                try:
                    draft["dynamic_chunk_sizes"] = [
                        int(x.strip()) for x in edited.split(",") if x.strip()]
                except ValueError:
                    st.caption("⚠️ Invalid sizes — keeping previous value")

            if "contextual_chunking" in draft:
                draft["contextual_chunking"] = st.checkbox(
                    "Contextual chunking (LLM call per chunk — slow)",
                    bool(draft["contextual_chunking"]),
                    key=f"{session_key}_contextual")

    else:
        # ---- Raw JSON fallback ----
        st.caption("This engine doesn't expose a structured config. Edit raw JSON below.")
        import json as _json
        raw_json = st.text_area(
            "Config JSON",
            _json.dumps(draft, indent=2, default=str),
            height=200,
            key=f"{session_key}_raw_json")
        try:
            draft = _json.loads(raw_json)
            st.session_state[session_key] = draft
        except _json.JSONDecodeError as e:
            st.error(f"Invalid JSON: {e}")
            return

    # ---- Apply / Reset buttons ----
    col_a, col_b, _ = st.columns([1, 1, 3])
    with col_a:
        if st.button("✅ Apply", type="primary", key=f"{session_key}_apply"):
            try:
                if hasattr(engine, "update_config"):
                    engine.update_config(draft)
                    st.success(f"Config applied to {engine_type}.")
                else:
                    # Legacy engines: apply known scalar attrs directly
                    for k, v in draft.items():
                        if hasattr(engine, k):
                            try:
                                setattr(engine, k, type(getattr(engine, k))(v))
                            except Exception:
                                setattr(engine, k, v)
                    st.success(f"Config applied to {engine_type} (legacy mode).")
                # Sync draft with what's now live
                if hasattr(engine, "get_config") and engine.get_config():
                    st.session_state[session_key] = engine.get_config()
            except Exception as e:
                st.error(f"Failed to apply config: {e}")

    with col_b:
        if st.button("↩ Reset", key=f"{session_key}_reset"):
            if hasattr(engine, "get_config") and engine.get_config():
                st.session_state[session_key] = engine.get_config()
            else:
                st.session_state.pop(session_key, None)
            st.rerun()
