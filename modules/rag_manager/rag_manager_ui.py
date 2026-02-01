# [file name]: rag_manager_ui.py (updated - add debug switch and RAG context injection)
"""
RAG Manager UI Module - Updated with debug switch and RAG context injection
"""

import streamlit as st
import os
import json
from datetime import datetime
from pathlib import Path
import tempfile
from shared.logging import log
from shared.common import _
from shared.config import get_config
from shared.llm import register_llm_callback, unregister_llm_callback
from typing import List, Dict, Optional

# Import the RAG manager
try:
    from modules.rag_manager import rag_manager
except ImportError:
    # Fallback for direct execution
    from .rag_manager import rag_manager


def rag_context_callback(user_id: str, messages: List[Dict]) -> str:
    """
    RAG context callback function that retrieves relevant documents
    based on the last user message and returns formatted context.

    Args:
        user_id: The user's ID for document access control
        messages: List of chat messages from the conversation

    Returns:
        Formatted context string to augment the LLM prompt
    """
    # Get the last user message
    user_messages = [msg for msg in messages if msg.get("role") == "user"]
    if not user_messages:
        log("warning", "No user messages found for RAG context")
        return ""

    last_user_message = user_messages[-1].get("content", "")
    if not last_user_message:
        log("warning", "Empty user message for RAG context")
        return ""

    #log("info", f"RAG debug Last User Message:{last_user_message}")

    # Initialize session state for RAG context
    if "last_rag_context" not in st.session_state:
        st.session_state.last_rag_context = ""

    # Reset previous context
    st.session_state.last_rag_context = ""
    st.session_state.last_rag_query = last_user_message
    st.session_state.last_rag_timestamp = datetime.now().timestamp()

    try:
        # Search for relevant documents using RAG manager
        search_results = rag_manager.search(user_id, last_user_message)
        #log("info", f"RAG debug Search Results:{search_results}")

        # Check if we have any results
        # search_results is a dict with engine names as keys
        if not search_results or all(len(results) == 0 for results in search_results.values()):
            log("warning", "No RAG results found for query")
            st.session_state.last_rag_context = "No relevant documents found in knowledge base."
            return ""

        # Build context from search results
        context_parts = []
        context_parts.append("CONTEXT FROM KNOWLEDGE BASE:")
        context_parts.append("=" * 50)

        # Process results from each engine
        engine_counter = 0
        for engine_name, results in search_results.items():
            if results:  # Only process engines with results
                engine_counter += 1
                context_parts.append(f"\n--- Engine: {engine_name.upper()} ---")

                # Add each document from this engine
                for i, result in enumerate(results):
                    filename = result.get('filename', 'Unknown')
                    content = result.get('content', '')
                    score = result.get('score', 0)

                    context_parts.append(f"\nDocument {i+1}: {filename}")
                    context_parts.append(f"Relevance Score: {score:.3f}")
                    context_parts.append(f"Content: {content}")

        # Add instructions for the LLM
        context_parts.append("\n" + "=" * 50)
        context_parts.append("INSTRUCTIONS:")
        context_parts.append("- Use the above context to inform your response")
        context_parts.append("- If the context is relevant, incorporate it naturally into your answer")
        context_parts.append("- If the context doesn't contain relevant information, respond based on your own knowledge")
        context_parts.append("- Do not mention that you are using a knowledge base or external context")
        context_parts.append("- Cite specific information from the context when applicable")
        context_parts.append("")

        # Join all parts into final context
        context_text = "\n".join(context_parts)

        # Log and store the context
        log("debug", f"RAG debug Context length:{len(context_text)} chars")
        log("debug", f"RAG debug Context preview:{context_text[:100]}...")

        # Store in session state for UI display
        st.session_state.last_rag_context = context_text

        return context_text

    except Exception as e:
        log("error", f"RAG search failed: {str(e)}", exc_info=True)
        error_msg = f"Error retrieving context: {str(e)}"
        st.session_state.last_rag_context = error_msg
        return ""


def show_rag_admin_content():
    """Display the RAG Manager admin content with indexing."""
    st.title("📚 RAG Document Manager")

    # Get configuration
    config = get_config()
    rag_config = config.get("rag_manager", {})

    # Display stats
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Documents", rag_manager.get_document_count())
    with col2:
        st.metric("Total Size", f"{rag_manager.get_total_size_mb()} MB")
    with col3:
        current_user = st.session_state.get("current_user")
        user_id = current_user.get("id") if current_user else None
        st.metric("Your Documents", rag_manager.get_document_count(user_id))
    with col4:
        engines = rag_manager.get_available_engines()
        st.metric("Engines", len([e for e in engines if e["available"]]))

    # Engine Management Section
    st.header("🛠️ RAG Engine Management")

    engines = rag_manager.get_available_engines()
    current_engine = rag_manager.current_engine

    engine_cols = st.columns(len(engines) if len(engines) <= 4 else 4)
    for idx, engine in enumerate(engines):
        col_idx = idx % len(engine_cols)
        with engine_cols[col_idx]:
            is_current = engine["type"] == current_engine
            status = "🟢" if engine["available"] else "🔴"

            st.markdown(f"**{engine['type'].upper()}** {status}")
            st.caption(engine["description"])

            if engine["available"] and not is_current:
                if st.button(f"Set as Default", key=f"set_engine_{engine['type']}",
                           help=f"Use {engine['type']} as default RAG engine"):
                    if rag_manager.set_current_engine(engine["type"]):
                        st.success(f"Default engine set to {engine['type']}")
                        st.rerun()

            if is_current:
                st.success("✓ Current default")

    # Indexing Section
    st.header("📄 Document Indexing")

    # Get documents for current user
    current_user = st.session_state.get("current_user")
    user_id = current_user.get("id") if current_user else None
    documents = rag_manager.get_document_list(user_id)

    if documents:
        # Create a table for indexing
        st.subheader("Index Documents in Engines")

        # Let user select which engine to index to
        available_engines = [e["type"] for e in engines if e["available"]]
        selected_engine = st.selectbox(
            "Select RAG Engine to index to:",
            available_engines,
            index=available_engines.index(current_engine) if current_engine in available_engines else 0
        )

        # Display documents with indexing status
        indexed_count = 0
        for doc in documents:
            col1, col2, col3, col4 = st.columns([3, 2, 2, 2])

            with col1:
                st.write(f"**{doc['original_filename']}**")
                st.caption(f"Visibility: {doc.get('visibility', 'private')}")

            with col2:
                # Show indexing status
                if selected_engine in doc.get('indexed_in', []):
                    st.success("✅ Indexed")
                    indexed_count += 1
                else:
                    st.warning("❌ Not indexed")

            with col3:
                # Index button
                if selected_engine not in doc.get('indexed_in', []):
                    if st.button("Index", key=f"index_{doc['filename']}_{selected_engine}"):
                        with st.spinner(f"Indexing {doc['original_filename']}..."):
                            if rag_manager.index_document(doc['filename'], selected_engine):
                                st.success(f"Indexed in {selected_engine}")
                                st.rerun()
                            else:
                                st.error(f"Failed to index")

            with col4:
                # Re-index button (even if already indexed)
                if st.button("Re-index", key=f"reindex_{doc['filename']}_{selected_engine}"):
                    with st.spinner(f"Re-indexing {doc['original_filename']}..."):
                        if rag_manager.index_document(doc['filename'], selected_engine):
                            st.success(f"Re-indexed in {selected_engine}")
                            st.rerun()
                        else:
                            st.error(f"Failed to re-index")

        # Bulk indexing
        st.divider()
        st.subheader("Bulk Operations")

        col1, col2 = st.columns(2)

        with col1:
            if st.button(f"📦 Index All in {selected_engine}", type="secondary"):
                with st.spinner(f"Indexing all documents in {selected_engine}..."):
                    result = rag_manager.index_all_documents(selected_engine)

                    if result["success"]:
                        st.success(f"Indexed {result['indexed']}/{result['total']} documents")
                        if result["failed"] > 0:
                            st.warning(f"{result['failed']} documents failed to index")
                    else:
                        st.error(f"Bulk indexing failed: {result.get('error', 'Unknown error')}")

                    st.rerun()

        with col2:
            if st.button(f"🗑️ Clear {selected_engine} Index", type="secondary"):
                engine_obj = rag_manager.get_engine(selected_engine)
                if engine_obj and st.checkbox(f"Confirm clear ALL documents from {selected_engine} index"):
                    if engine_obj.clear_index():
                        st.success(f"Cleared {selected_engine} index")
                        st.rerun()
                    else:
                        st.error(f"Failed to clear index")

    else:
        st.info("No documents available for indexing.")

    # Upload Section (from original)
    st.header(_("upload_documents"))

    # Get allowed extensions
    allowed_extensions = rag_config.get("allowed_extensions", [".txt", ".pdf", ".md"])
    allowed_types = [ext.lstrip('.') for ext in allowed_extensions]

    # Visibility options based on user role
    current_user = st.session_state.get("current_user", {})
    user_role = current_user.get("role", "normal")

    visibility_options = ["private"]
    if user_role == "admin":
        visibility_options.append("public")

    col1, col2 = st.columns(2)
    with col1:
        uploaded_files = st.file_uploader(
            _("upload_documents"),
            type=allowed_types,
            accept_multiple_files=True,
            help=f"Maximum file size: {rag_config.get('max_file_size_mb', 10)}MB"
        )

    with col2:
        visibility = st.selectbox(
            "Document Visibility",
            visibility_options,
            help="Private: only you and admin can see. Public: all users can see (admin only)."
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
                owner_id = current_user.get("id") if current_user else None
                result = rag_manager.upload_document(tmp_path, uploaded_file.name, owner_id, visibility)

                # Clean up temp file
                os.unlink(tmp_path)

                if result:
                    success_count += 1
                    log("info", f"Successfully uploaded: {uploaded_file.name}")

                    # Auto-index in default engine
                    if rag_config.get("auto_index", True):
                        rag_manager.index_document(result, rag_manager.current_engine)
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

    # Document List Section (updated with permissions)
    st.header(_("document_list"))

    documents = rag_manager.get_document_list(user_id)

    if not documents:
        st.info(_("no_documents"))
    else:
        # Create a table of documents
        for doc in documents:
            col1, col2, col3, col4, col5 = st.columns([3, 2, 2, 2, 1])

            with col1:
                st.write(f"**{doc['original_filename']}**")
                st.caption(f"Visibility: {doc.get('visibility', 'private')}")

            with col2:
                st.write(f"{doc['file_size_mb']} MB")

            with col3:
                upload_date = datetime.fromisoformat(doc['uploaded_at']).strftime("%Y-%m-%d")
                st.write(upload_date)

            with col4:
                # Show indexing status for current engine
                if current_engine in doc.get('indexed_in', []):
                    st.success("✓ Indexed")
                else:
                    st.warning("Not indexed")

            with col5:
                # Delete button with confirmation
                delete_key = f"delete_{doc['filename']}"
                if st.button("🗑️", key=delete_key, help=_("delete")):
                    if st.session_state.get(f"confirm_{delete_key}", False):
                        # Second click - actually delete
                        if rag_manager.delete_document(doc['filename'], user_id):
                            st.success(_("delete_success"))
                            st.rerun()
                    else:
                        # First click - show confirmation
                        st.session_state[f"confirm_{delete_key}"] = True
                        st.warning(_("delete_confirm").format(filename=doc['original_filename']))

    # Advanced Options
    with st.expander("⚙️ Advanced Options"):
        col1, col2 = st.columns(2)

        with col1:
            # Clear all button (admin only)
            if current_user.get("role") == "admin":
                if st.button("🗑️ Clear All Documents", type="secondary"):
                    if st.session_state.get("confirm_clear_all", False):
                        if rag_manager.clear_all_documents(user_id):
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


def inject_ui_sidebar():
    """Inject RAG settings into the sidebar."""

    # Get current user
    current_user = st.session_state.get('current_user')
    if not current_user:
        return

    # Only show for users with permission
    if current_user['role'] not in ['admin', 'master']:
        return

    # Add RAG settings section to sidebar
    with st.sidebar.expander("⚙️ RAG Settings", expanded=False):
        # Get available engines
        engines = rag_manager.get_available_engines()
        available_engines = [e for e in engines if e['available']]

        if not available_engines:
            st.warning("No engines available")
            return

        # Get current default engine
        config = get_config()
        current_default = config.get("rag_manager.default_engine", "simple")

        # Create engine selector
        engine_options = [e['type'] for e in available_engines]
        current_index = engine_options.index(current_default) if current_default in engine_options else 0

        selected_engine = st.selectbox(
            "Default RAG Engine",
            options=engine_options,
            index=current_index,
            help="Select the default engine for searches and indexing"
        )

        # RAG Debug switch
        st.divider()
        st.subheader("Debug")

        rag_debug_enabled = st.toggle(
            "Show RAG Context",
            value=st.session_state.get('rag_debug_enabled', False),
            help="When enabled, shows the RAG context used for LLM queries in an expander"
        )

        if rag_debug_enabled != st.session_state.get('rag_debug_enabled', True):
            st.session_state.rag_debug_enabled = rag_debug_enabled
            st.rerun()

        st.caption("Displays retrieved document context in chat")

        # Enable/Disable RAG context injection
        rag_injection_enabled = st.toggle(
            "Enable RAG Context Injection",
            value=st.session_state.get('rag_injection_enabled', True),
            help="When enabled, RAG context will be automatically injected into LLM queries"
        )

        if rag_injection_enabled != st.session_state.get('rag_injection_enabled'):
            st.session_state.rag_injection_enabled = rag_injection_enabled
            # Register or unregister the callback based on toggle state
            if rag_injection_enabled:
                register_llm_callback(rag_context_callback)
                st.sidebar.success("RAG context injection enabled")
            else:
                unregister_llm_callback(rag_context_callback)
                st.sidebar.info("RAG context injection disabled")
            st.rerun()

        # Update button
        if st.button("Apply Changes", type="secondary", use_container_width=True):
            if selected_engine != current_default:
                # Try to update the RAG module config file
                rag_config_path = Path(__file__).parent / "config.json"

                try:
                    # Load current RAG config
                    if rag_config_path.exists():
                        with open(rag_config_path, 'r', encoding='utf-8') as f:
                            rag_config = json.load(f)
                    else:
                        rag_config = {"rag_manager": {}}

                    # Update default engine
                    if "rag_manager" not in rag_config:
                        rag_config["rag_manager"] = {}

                    rag_config["rag_manager"]["default_engine"] = selected_engine

                    # Save back to file
                    with open(rag_config_path, 'w', encoding='utf-8') as f:
                        json.dump(rag_config, f, indent=2, ensure_ascii=False)

                    # Update in-memory config
                    config.set("rag_manager.default_engine", selected_engine)
                    rag_manager.default_engine = selected_engine

                    st.sidebar.success(f"Default engine set to: {selected_engine}")
                    st.sidebar.info("Changes will take effect immediately")
                    log("info", f"Default RAG engine changed to {selected_engine}")
                    st.rerun()

                except Exception as e:
                    st.sidebar.error(f"Failed to update config: {str(e)}")
                    log("error", f"Failed to update RAG config: {str(e)}")
            else:
                st.sidebar.info("No changes made")

        # Quick info
        st.caption(f"Current: {current_default}")

        # Engine status summary
        st.divider()
        st.caption("Engine Status:")
        for engine in available_engines:
            status_icon = "✅" if engine['available'] else "❌"
            default_icon = "⭐" if engine['type'] == current_default else ""
            st.caption(f"{status_icon} {default_icon} {engine['type']}")


def inject_ui_admin_tab():
    """Register the RAG Manager admin tab."""
    return ("RAG Manager", show_rag_admin_content)


def inject_ui_initialize():
    """Initialize RAG manager module."""
    # Initialize session state for debug mode
    if 'rag_debug_enabled' not in st.session_state:
        st.session_state.rag_debug_enabled = False

    # Initialize session state for injection toggle
    if 'rag_injection_enabled' not in st.session_state:
        st.session_state.rag_injection_enabled = True

    # Initialize session state for storing RAG context
    if 'last_rag_context' not in st.session_state:
        st.session_state.last_rag_context = ""
    if 'last_rag_query' not in st.session_state:
        st.session_state.last_rag_query = ""
    if 'last_rag_timestamp' not in st.session_state:
        st.session_state.last_rag_timestamp = 0

    # Register the RAG context callback if injection is enabled
    if st.session_state.rag_injection_enabled:
        register_llm_callback(rag_context_callback)

    return True


def inject_ui_main_content():
    """Render RAG manager content in main area."""
    return None


def inject_ui_inside_conversation():
    """Render RAG debug context after conversation."""
    # Only show if debug is enabled and we have context to show
    if (st.session_state.get('rag_debug_enabled', False) and
        'last_rag_context' in st.session_state and
        st.session_state.last_rag_context):

        with st.expander("🔍 RAG Debug Context", expanded=False):
            st.write("**Last RAG context injected into LLM:**")

            # Display context with syntax highlighting for better readability
            context_text = st.session_state.last_rag_context

            # Format the context text
            formatted_context = context_text.replace("---", "\n---")

            st.text_area(
                "Context",
                formatted_context,
                height=200,
                key="rag_debug_context_display",
                label_visibility="collapsed"
            )

            # Add some metadata if available
            col1, col2 = st.columns(2)
            with col1:
                if 'last_rag_query' in st.session_state and st.session_state.last_rag_query:
                    st.caption(f"**Query:** {st.session_state.last_rag_query}")

            with col2:
                if 'last_rag_timestamp' in st.session_state and st.session_state.last_rag_timestamp:
                    timestamp = datetime.fromtimestamp(st.session_state.last_rag_timestamp)
                    st.caption(f"**Retrieved:** {timestamp.strftime('%Y-%m-%d %H:%M:%S')}")

            # Clear button
            if st.button("Clear RAG Context History", type="secondary"):
                st.session_state.last_rag_context = ""
                st.session_state.last_rag_query = ""
                st.session_state.last_rag_timestamp = 0
                st.rerun()

    return None


# Test function
def test_rag_manager():
    """Test the RAG manager functionality."""
    try:
        # Test engine discovery
        engines = rag_manager.get_available_engines()
        log("info", f"Test: Found {len(engines)} RAG engines")

        # Test document list
        documents = rag_manager.get_document_list()
        log("info", f"Test: Found {len(documents)} documents")

        # Test search functionality
        if documents:
            test_query = "test search"
            search_results = rag_manager.search(query=test_query, top_k=2)
            log("info", f"Test: Search returned {search_results.get('count', 0)} results for query '{test_query}'")

        return True
    except Exception as e:
        log("error", f"RAG Manager test failed: {str(e)}", exc_info=True)
        return False
