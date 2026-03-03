# modules/rag_bench/rag_bench_ui.py
"""
RAG Benchmark UI - Admin tab for viewing LLM responses with RAG context.
Includes test interface to manually query and see RAG context.
"""

import streamlit as st
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List

from modules.rag_bench.rag_bench_core import (
    get_captured_interactions,
    clear_captured_interactions,
    get_stats
)
from shared.common import llm_conversation_generate, get_current_llm_info


def inject_ui_admin_tab():
    """
    Render the RAG Benchmark admin tab.
    Returns (tab_name, render_function) for the admin interface.
    """

    def render():
        st.header("🔬 RAG Benchmark")
        st.caption("Test RAG context and view captured interactions")

        # Create tabs for different views
        tab1, tab2 = st.tabs(["🧪 Test RAG Query", "📊 Captured Interactions"])

        with tab1:
            render_test_interface()

        with tab2:
            render_captured_interactions()

    return ("RAG Benchmark", render)


def render_test_interface():
    """Render the test query interface."""
    st.subheader("Test RAG Query")
    st.caption("Ask a question and see what RAG context is retrieved")

    # Check if user is logged in
    if 'current_user' not in st.session_state or not st.session_state.current_user:
        st.warning("You must be logged in to test RAG queries")
        return

    current_user = st.session_state.current_user
    user_id = current_user.get('id', 'unknown')

    # Show current LLM info
    current_llm = get_current_llm_info()
    if current_llm:
        st.info(f"**Current LLM:** {current_llm.get('name', 'Unknown')} ({current_llm.get('model', 'Unknown')})")

    # Test query form
    with st.form(key="rag_test_form"):
        question = st.text_area(
            "Your question:",
            height=100,
            placeholder="e.g., What is the capital of France?",
            help="Ask a question to see what RAG context is retrieved and the LLM's response"
        )

        col1, col2 = st.columns([1, 4])
        with col1:
            submitted = st.form_submit_button("🚀 Ask", use_container_width=True)
        with col2:
            show_context_only = st.checkbox(
                "Show context only (skip LLM call)",
                help="If checked, only show the retrieved RAG context without calling the LLM"
            )

    # Handle form submission
    if submitted and question:
        with st.spinner("Processing..."):
            # Clear previous test results
            if "rag_test_response" in st.session_state:
                del st.session_state.rag_test_response
            if "rag_test_context" in st.session_state:
                del st.session_state.rag_test_context

            # Run the test
            asyncio.run(run_rag_test(question, user_id, show_context_only))

    # Display results if available
    if "rag_test_response" in st.session_state or "rag_test_context" in st.session_state:
        st.divider()
        st.subheader("Results")

        col_left, col_right = st.columns(2)

        with col_left:
            st.markdown("### 🤖 LLM Response")
            if "rag_test_response" in st.session_state:
                response = st.session_state.rag_test_response
                st.markdown(response)

                # Show token usage if available
                if "rag_test_tokens" in st.session_state:
                    tokens = st.session_state.rag_test_tokens
                    st.caption(f"Tokens: {tokens.get('total', 'N/A')} (input: {tokens.get('input', 'N/A')}, output: {tokens.get('output', 'N/A')})")
            else:
                if st.session_state.get("rag_test_show_context_only"):
                    st.info("LLM call skipped (context only mode)")
                else:
                    st.info("No response captured")

        with col_right:
            st.markdown("### 📚 RAG Context")
            if "rag_test_context" in st.session_state:
                context = st.session_state.rag_test_context
                if context:
                    for i, chunk in enumerate(context):
                        source = chunk.get("source", f"chunk_{i+1}")
                        content = chunk.get("content", "")

                        with st.expander(f"📄 {source}", expanded=i == 0):
                            st.markdown(content)

                            # Show metadata
                            metadata = {k: v for k, v in chunk.items()
                                      if k not in ["content", "source", "role", "timestamp"]}
                            if metadata:
                                st.caption("Metadata:")
                                st.json(metadata)
                else:
                    st.info("No RAG context retrieved for this query")
            else:
                st.info("No context captured")

        # Clear test button
        if st.button("🧹 Clear Results", use_container_width=True):
            keys_to_clear = ["rag_test_response", "rag_test_context", "rag_test_tokens", "rag_test_show_context_only"]
            for key in keys_to_clear:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()


async def run_rag_test(question: str, user_id: str, show_context_only: bool = False):
    """Run a test RAG query and capture context."""
    try:
        # Clear previous context capture
        if "rag_test_captured_context" in st.session_state:
            del st.session_state.rag_test_captured_context

        # Set a flag to indicate we're in test mode
        st.session_state.rag_test_mode = True
        st.session_state.rag_test_show_context_only = show_context_only

        if not show_context_only:
            # Make the LLM call - this will trigger context callbacks
            response = await llm_conversation_generate(
                message=question,
                user_id=user_id
            )

            # Store the response
            st.session_state.rag_test_response = response

            # Look for the context in the most recent interaction
            # The context should have been captured by capture_rag_context
            if "rag_test_captured_context" in st.session_state:
                st.session_state.rag_test_context = st.session_state.rag_test_captured_context
        else:
            st.session_state.rag_test_response = None
            st.session_state.rag_test_show_context_only = True

            # In context-only mode, we need to trigger context retrieval without LLM call
            # This depends on how your RAG module works - you might need to call a specific function
            st.info("Context-only mode: Please implement RAG context retrieval")

    except Exception as e:
        st.error(f"Error during test: {str(e)}")
    finally:
        # Clear test mode flag
        if "rag_test_mode" in st.session_state:
            del st.session_state.rag_test_mode


def render_captured_interactions():
    """Render the captured interactions view."""
    stats = get_stats()

    # Stats row
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Interactions", stats["total_interactions"])

    with col2:
        st.metric("With RAG Context", stats["with_rag_context"])

    with col3:
        if stats["total_interactions"] > 0:
            pct = (stats["with_rag_context"] / stats["total_interactions"] * 100)
            st.metric("Context Coverage", f"{pct:.1f}%")
        else:
            st.metric("Context Coverage", "0%")

    with col4:
        st.metric("Storage Used", f"{stats['storage_used']}/{stats['storage_limit']}")

    # Controls
    col1, col2, col3 = st.columns([1, 1, 4])

    with col1:
        if st.button("🔄 Refresh", use_container_width=True):
            st.rerun()

    with col2:
        if st.button("🗑️ Clear All", use_container_width=True, type="secondary"):
            count = clear_captured_interactions()
            st.success(f"Cleared {count} interactions")
            st.rerun()

    st.divider()

    # Interaction selector
    if stats["total_interactions"] > 0:
        # Pagination controls
        col1, col2, col3 = st.columns([2, 1, 2])

        with col1:
            page_size = st.selectbox(
                "Items per page",
                options=[10, 25, 50, 100],
                index=1,
                key="rag_bench_page_size"
            )

        with col2:
            total_pages = (stats["total_interactions"] + page_size - 1) // page_size
            page = st.number_input(
                "Page",
                min_value=1,
                max_value=total_pages,
                value=1,
                key="rag_bench_page"
            )

        with col3:
            st.write("")
            st.write("")
            st.write(f"Showing {min(page_size, stats['total_interactions'])} of {stats['total_interactions']}")

        # Get interactions for current page
        offset = (page - 1) * page_size
        interactions = get_captured_interactions(limit=page_size, offset=offset)

        # Display interactions
        for i, interaction in enumerate(interactions):
            _render_interaction_card(interaction, i + offset)

    else:
        st.info("No interactions captured yet. Use the test tab to generate some RAG queries.")


def _render_interaction_card(interaction: Dict[str, Any], index: int):
    """Render a single interaction as an expandable card."""

    timestamp = interaction.get("timestamp", "Unknown")
    try:
        # Format timestamp nicely
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
    except:
        time_str = timestamp

    llm_type = interaction.get("llm_type", "unknown")
    model = interaction.get("model", "unknown")
    has_context = bool(interaction.get("rag_context"))

    # Create expander with summary info
    context_indicator = "📚" if has_context else "❌"
    success_indicator = "✅" if interaction.get("success", True) else "❌"

    expander_label = f"{success_indicator} [{index+1}] {time_str} - {llm_type}/{model} {context_indicator}"

    with st.expander(expander_label, expanded=False):
        # Metadata row
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.caption(f"**User ID:** {interaction.get('user_id', 'N/A')}")

        with col2:
            st.caption(f"**LLM ID:** {interaction.get('llm_id', 'N/A')}")

        with col3:
            if interaction.get("total_tokens"):
                st.caption(f"**Tokens:** {interaction['total_tokens']:,}")

        with col4:
            st.caption(f"**Context:** {'Yes' if has_context else 'No'}")

        st.divider()

        # Side-by-side view
        col_left, col_right = st.columns(2)

        with col_left:
            st.markdown("### 🤖 LLM Response")

            # Show the user's question if available
            messages = interaction.get("messages", [])
            user_question = None
            rag_context_messages = []

            for msg in messages:
                if msg.get("role") == "user":
                    user_question = msg.get("content")
                elif msg.get("role") == "system" and msg.get("source") == "rag_context_callback_classic":
                    rag_context_messages.append(msg)

            if user_question:
                with st.container(border=True):
                    st.caption("**User question:**")
                    st.markdown(user_question)

            # Show the response
            response = interaction.get("response", "")
            if response:
                with st.container(border=True):
                    st.caption("**Assistant response:**")
                    st.markdown(response)
            else:
                st.warning("No response captured")

        with col_right:
            st.markdown("### 📚 RAG Context")

            # Extract RAG context from messages if not already in rag_context field
            rag_context = interaction.get("rag_context")

            # If no dedicated rag_context field, look for system messages with rag_context_callback source
            if not rag_context:
                messages = interaction.get("messages", [])
                rag_context = []
                for msg in messages:
                    if msg.get("role") == "system" and msg.get("source") == "rag_context_callback_classic":
                        rag_context.append({
                            "content": msg.get("content", ""),
                            "source": msg.get("source", "rag_context"),
                            "role": "system"
                        })

            if rag_context:
                for j, chunk in enumerate(rag_context):
                    source = chunk.get("source", f"chunk_{j+1}")
                    content = chunk.get("content", "")

                    with st.expander(f"📄 {source}", expanded=j == 0):
                        st.markdown(content)

                        # Show any metadata
                        metadata = {k: v for k, v in chunk.items()
                                  if k not in ["content", "source", "role", "timestamp"]}
                        if metadata:
                            st.caption("Metadata:")
                            st.json(metadata)
            else:
                # Try to display raw messages for debugging
                messages = interaction.get("messages", [])
                system_msgs = [m for m in messages if m.get("role") == "system"]
                if system_msgs:
                    with st.expander("🔧 Raw System Messages", expanded=True):
                        for j, msg in enumerate(system_msgs):
                            st.json(msg)
                else:
                    st.info("No RAG context captured for this interaction")

        st.divider()

        # Raw data expander for debugging
        with st.expander("🔧 Raw Data", expanded=False):
            # Create a copy without the full response for cleaner display
            display_data = interaction.copy()
            if len(display_data.get("response", "")) > 500:
                display_data["response"] = display_data["response"][:500] + "... [truncated]"
            st.json(display_data)
