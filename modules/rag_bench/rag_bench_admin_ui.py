# modules/rag_bench/rag_bench_admin_ui.py
"""
RAG Benchmark UI - Admin tab for viewing LLM responses with RAG context.
Includes test interface to manually query and compare RAG engines.
"""

import streamlit as st
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List

from modules.rag_bench.rag_bench_core import (
    get_captured_interactions,
    clear_captured_interactions,
    get_stats,
    capture_rag_context_for_comparison,
    get_captured_comparison_contexts,
    clear_comparison_contexts
)
from shared.common import llm_conversation_generate, get_current_llm_info
from core.logging import log, capture_log_start, capture_log_end
from modules.rag_bench.rag_bench_run_tab import get_benchmark_run_tab

def inject_ui_admin_tab():
    def render():
        st.header("🔬 RAG Benchmark")
        st.caption("Test and compare RAG engines side by side")

        bench_tab_name, bench_render = get_benchmark_run_tab()

        tab1, tab2, tab3, tab4 = st.tabs([
            "🧪 Test LLM with RAG",
            "🔍 Compare RAG Engines",
            "📊 Captured Interactions",
            bench_tab_name,           # 🏁 Benchmark
        ])

        with tab1:
            render_test_interface()
        with tab2:
            render_rag_comparison_interface()
        with tab3:
            render_captured_interactions()
        with tab4:
            bench_render()

    return ("RAG Benchmark", render)


def render_test_interface():
    """Render the test query interface (original functionality)."""
    st.subheader("Test RAG Query with LLM")
    st.caption("Ask a question and see what RAG context is retrieved by the selected engine")

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

    # Get available RAG engines
    rag_manager = _get_rag_manager()
    available_engines = rag_manager.get_available_engines()
    engine_options = [e['type'] for e in available_engines if e['available']]

    if not engine_options:
        st.warning("No RAG engines available")
        return

    # Test query form
    with st.form(key="rag_test_form"):
        question = st.text_area(
            "Your question:",
            height=100,
            placeholder="e.g., What is the capital of France?",
            help="Ask a question to see what RAG context is retrieved and the LLM's response"
        )

        col1, col2, col3 = st.columns([2, 2, 4])
        with col1:
            selected_engine = st.selectbox(
                "RAG Engine",
                options=engine_options,
                index=0,
                help="Select which RAG engine to use for context retrieval"
            )

        with col2:
            submitted = st.form_submit_button("🚀 Ask", width='stretch')

        with col3:
            show_context_only = st.checkbox(
                "Show context only (skip LLM call)",
                help="If checked, only show the retrieved RAG context without calling the LLM"
            )

    # Handle form submission
    if submitted and question:
        with st.spinner(f"Processing with {selected_engine} engine..."):
            # Clear previous test results
            if "rag_test_response" in st.session_state:
                del st.session_state.rag_test_response
            if "rag_test_context" in st.session_state:
                del st.session_state.rag_test_context
            if "rag_test_engine" in st.session_state:
                del st.session_state.rag_test_engine

            # Run the test
            asyncio.run(run_rag_test(question, user_id, selected_engine, show_context_only))

    # Display results if available
    if "rag_test_response" in st.session_state or "rag_test_context" in st.session_state:
        st.divider()

        # Show which engine was used
        if "rag_test_engine" in st.session_state:
            st.info(f"**Engine used:** {st.session_state.rag_test_engine}")

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
        if st.button("🧹 Clear Results", width='stretch'):
            keys_to_clear = ["rag_test_response", "rag_test_context", "rag_test_tokens",
                           "rag_test_show_context_only", "rag_test_engine"]
            for key in keys_to_clear:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()


def render_rag_comparison_interface():
    """New interface to compare contexts from all RAG engines."""
    st.subheader("Compare RAG Engines Side by Side")
    st.caption("See what context each RAG engine would retrieve for your query")

    # Check if user is logged in
    if 'current_user' not in st.session_state or not st.session_state.current_user:
        st.warning("You must be logged in to compare RAG engines")
        return

    current_user = st.session_state.current_user
    user_id = current_user.get('id', 'unknown')

    # Get available RAG engines
    rag_manager = _get_rag_manager()
    available_engines = rag_manager.get_available_engines()

    # Filter only available engines
    engine_options = [{
        'type': e['type'],
        'description': e.get('description', ''),
        'default': e.get('default', False)
    } for e in available_engines if e['available']]

    if not engine_options:
        st.warning("No RAG engines available")
        return

    cola, colb = st.columns([1, 1])
    # Debug toggle
    with cola:
        debug_mode = st.checkbox("Enable debug logging", value=False, key="rag_bench_debug_mode")
        if debug_mode:
            st.info("Debug mode enabled - logs will be captured and displayed")

    # Show engine status
    with colb:
        for engine in engine_options:
            default_marker = "⭐ " if engine['default'] else ""
            st.write(f"{default_marker}**{engine['type']}**: {engine['description']}")

    # Query input
    query = st.text_area(
        "Enter your query:",
        height=100,
        placeholder="What would you like to search for?",
        key="rag_comparison_query_input"
    )

    col1, col2 = st.columns([1, 3])
    with col1:
        limit = st.number_input(
            "Results per engine",
            min_value=1,
            max_value=10,
            value=3,
            key="rag_comparison_limit_input"
        )

    with col2:
        st.write("")  # Spacing
        st.write("")
        compare_button = st.button("🔍 Compare All Engines", type="primary", use_container_width=True)

    # Handle comparison
    if compare_button and query:
        # Generate a unique run_id for this comparison
        run_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
        st.session_state["_rag_comparison_run_id"] = run_id

        # Store query info
        st.session_state["_rag_comparison_query"] = query
        st.session_state["_rag_comparison_limit"] = limit
        st.session_state["_rag_comparison_timestamp"] = datetime.now().isoformat()

        # Clear previous results
        clear_comparison_contexts()

        # Start log capture if debug mode is enabled
        if debug_mode:
            capture_log_start("DEBUG", max_messages=1000)
            st.session_state["_rag_comparison_debug_mode"] = True
            log("debug", "[RAG Compare] ========== STARTING RAG ENGINE COMPARISON ==========")
            log("debug", f"[RAG Compare] Run ID: {run_id}")
            log("debug", f"[RAG Compare] User ID: {user_id}")
            log("debug", f"[RAG Compare] Query: {query}")
            log("debug", f"[RAG Compare] Limit per engine: {limit}")

        # Run comparison for all engines
        with st.spinner(f"Retrieving context from {len(engine_options)} engines..."):
            for engine_info in engine_options:
                engine_type = engine_info['type']
                try:
                    log("debug", f"[RAG Compare] Testing engine: {engine_type} with query: {query}")

                    # Get search results directly
                    search_results = rag_manager.search(
                        user_id=user_id,
                        query=query,
                        engine_type=engine_type,
                        limit=limit
                    )

                    engine_results = search_results.get(engine_type, []) if search_results else []
                    log("debug", f"[RAG Compare] Engine {engine_type} returned {len(engine_results)} search results")

                    # Get context text for display
                    context_text = ""
                    if engine_results:
                        context_parts = [
                            f"From document '{r['filename']}':\n{r['content']}\n"
                            for r in engine_results
                        ]
                        context_text = "Relevant context from documents:\n" + "\n".join(context_parts)

                    # Store for display with run_id
                    capture_rag_context_for_comparison(
                        engine_type=engine_type,
                        query=query,
                        context_text=context_text,
                        results=engine_results,
                        run_id=run_id
                    )
                except Exception as e:
                    log("error", f"[RAG Compare] Error with {engine_type}: {str(e)}", stacktrace=True)
                    st.error(f"Error with {engine_type}: {str(e)}")

            st.rerun()

    # Display comparison results if they exist
    if "_rag_comparison_query" in st.session_state:
        st.divider()

        # Query info
        st.info(f"**Query:** {st.session_state['_rag_comparison_query']}")
        if "_rag_comparison_timestamp" in st.session_state:
            st.caption(f"Retrieved at: {st.session_state['_rag_comparison_timestamp']}")

        # Get all captured contexts for this run_id
        run_id = st.session_state.get("_rag_comparison_run_id")
        comparison_contexts = get_captured_comparison_contexts(run_id=run_id)

        if not comparison_contexts:
            st.warning("No comparison results yet. Click 'Compare All Engines' to retrieve contexts.")
            return

        # Show summary of which engines returned results
        engines_with_results = [ctx for ctx in comparison_contexts if ctx.get('results')]
        engines_without_results = [ctx for ctx in comparison_contexts if not ctx.get('results')]

        col1, col2 = st.columns(2)
        with col1:
            st.success(f"✅ Engines with results: {len(engines_with_results)}")
        with col2:
            if engines_without_results:
                st.warning(f"❌ Engines with no results: {len(engines_without_results)}")

        # Sort comparison contexts to match engine_options order for consistent display
        engine_order = [e['type'] for e in engine_options]
        comparison_contexts.sort(key=lambda x: engine_order.index(x['engine_type'])
                                 if x['engine_type'] in engine_order else 999)

        # Create tabs for each engine
        engine_tabs = st.tabs([f"⚙️ {ctx['engine_type'].upper()}" for ctx in comparison_contexts])

        for tab, ctx in zip(engine_tabs, comparison_contexts):
            with tab:
                engine_type = ctx['engine_type']

                # Show if this is the default engine
                is_default = any(e['default'] and e['type'] == engine_type for e in engine_options)
                if is_default:
                    st.caption("⭐ Default Engine")

                # Display context
                st.markdown("### 📚 Retrieved Context")

                if ctx.get('results'):
                    # Calculate threshold statistics
                    results_with_threshold = [r for r in ctx['results'] if r.get('threshold_used') is not None]

                    if results_with_threshold:
                        # Get the first result's threshold info (all should be same for the engine)
                        sample_result = results_with_threshold[0]
                        threshold = sample_result.get('threshold_used')
                        max_score = max([r.get('max_score_reached', 0) for r in ctx['results'] if r.get('max_score_reached')])

                        # Display threshold info with visual indicator
                        col1, col2 = st.columns(2)
                        with col1:
                            if threshold is not None:
                                st.metric("Similarity Threshold", f"{threshold:.3f}")
                        with col2:
                            if max_score > 0:
                                st.metric("Max Score Achieved", f"{max_score:.3f}")

                        # Show if threshold might be too high
                        if threshold is not None and max_score > 0:
                            if max_score < threshold:
                                st.warning(f"⚠️ Max score ({max_score:.3f}) is below threshold ({threshold:.3f}) - no results would be returned in normal operation")
                            elif max_score - threshold < 0.1:
                                st.info(f"📊 Max score is close to threshold (difference: {max_score - threshold:.3f})")
                            else:
                                st.success(f"✅ Good margin above threshold (difference: {max_score - threshold:.3f})")

                    st.success(f"Found {len([r for r in ctx['results'] if not r.get('no_results')])} results")

                    for i, result in enumerate(ctx['results']):
                        if result.get('no_results'):
                            with st.expander(f"📊 No Results - Diagnostic Info", expanded=True):
                                st.warning("No documents matched the query")
                                if result.get('max_score_reached', 0) > 0:
                                    st.info(f"Highest score achieved: {result['max_score_reached']:.3f}")
                                    if result.get('threshold_used') is not None:
                                        if result['max_score_reached'] < result['threshold_used']:
                                            st.error(f"❌ All scores below threshold ({result['threshold_used']:.3f})")
                                        else:
                                            st.success(f"✅ Scores above threshold but filtered elsewhere")
                                else:
                                    st.info("No matches found at all")
                            continue

                        # Get threshold info
                        threshold_used = result.get('threshold_used', 'N/A')
                        max_score_reached = result.get('max_score_reached', 0)

                        # Create score display
                        score_display = f"score: {result.get('score', 0):.4f}"
                        if isinstance(threshold_used, float):
                            score_display += f" | threshold: {threshold_used:.2f}"
                        if max_score_reached > 0:
                            score_display += f" | max: {max_score_reached:.3f}"

                        with st.expander(
                            f"📄 {result.get('filename', f'Result {i+1}')} ({score_display})",
                            expanded=i==0
                        ):
                            st.markdown(result.get('content', 'No content'))

                            # Show metadata
                            metadata = {k: v for k, v in result.items()
                                      if k not in ['content', 'filename', 'score', 'threshold_used', 'max_score_reached', 'no_results', 'metadata']}
                            if result.get('metadata'):
                                metadata.update(result['metadata'])
                            if metadata:
                                st.caption("Metadata:")
                                st.json(metadata)
                else:
                    st.error("❌ No results retrieved by this engine")

                    # Get threshold from engine if possible
                    rag_manager = _get_rag_manager()
                    engine = rag_manager.get_engine(engine_type)
                    if engine and hasattr(engine, 'similarity_threshold'):
                        st.info(f"Current similarity threshold: {engine.similarity_threshold}")

        # Summary statistics
        st.divider()
        st.subheader("📊 Comparison Summary")

        summary_data = []
        for ctx in comparison_contexts:
            result_count = len(ctx.get('results', []))
            avg_score = 0
            if result_count > 0:
                avg_score = sum(r.get('score', 0) for r in ctx['results']) / result_count

            summary_data.append({
                "Engine": ctx['engine_type'],
                "Results": result_count,
                "Avg Score": f"{avg_score:.4f}" if result_count > 0 else "N/A",
                "Has Context": "✅" if ctx.get('context_text') else "❌"
            })

        if summary_data:
            st.dataframe(summary_data, use_container_width=True)

        # Show debug logs if they were captured
        if st.session_state.get("_rag_comparison_debug_mode", False):
            st.divider()
            st.subheader("🔧 Debug Logs")

            logs = capture_log_end()

            if logs:
                with st.expander(f"View {len(logs)} captured log messages", expanded=True):
                    # Flatten the logs if they're nested lists
                    flat_logs = []
                    for log_item in logs[-500:]:  # Take last 500 items
                        if isinstance(log_item, list):
                            flat_logs.extend(log_item)
                        else:
                            flat_logs.append(str(log_item))

                    # Format logs as markdown with line breaks
                    log_text = "\n".join(flat_logs)
                    st.markdown(f"```\n{log_text}\n```")
            else:
                st.info("No logs captured")

            # Clear debug mode flag
            del st.session_state["_rag_comparison_debug_mode"]

        # Clear button
        if st.button("🧹 Clear Comparison Results", use_container_width=True):
            clear_comparison_contexts()
            # Clear the stored session state variables
            keys_to_clear = ["_rag_comparison_query", "_rag_comparison_timestamp",
                           "_rag_comparison_limit", "_rag_comparison_run_id"]
            for key in keys_to_clear:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()


async def run_rag_test(question: str, user_id: str, engine_type: str, show_context_only: bool = False):
    """Run a test RAG query and capture context using specified engine."""
    try:
        # Get RAG manager
        rag_manager = _get_rag_manager()

        # Clear previous context capture
        if "rag_test_captured_context" in st.session_state:
            del st.session_state.rag_test_captured_context

        # Set a flag to indicate we're in test mode
        st.session_state.rag_test_mode = True
        st.session_state.rag_test_show_context_only = show_context_only
        st.session_state.rag_test_engine = engine_type

        # Temporarily set the default engine to the selected one
        original_default = rag_manager.default_engine
        rag_manager.default_engine = engine_type

        try:
            if not show_context_only:
                # Make the LLM call - this will trigger context callbacks
                response = await llm_conversation_generate(
                    message=question,
                    user_id=user_id
                )

                # Store the response
                st.session_state.rag_test_response = response

                # Look for the context in the most recent interaction
                if "rag_test_captured_context" in st.session_state:
                    st.session_state.rag_test_context = st.session_state.rag_test_captured_context
            else:
                # Context-only mode: get context directly
                context = rag_manager.get_rag_context(
                    user_id=user_id,
                    query=question,
                    engine_type=engine_type
                )

                # Also get detailed search results
                search_results = rag_manager.search(
                    user_id=user_id,
                    query=question,
                    engine_type=engine_type,
                    limit=3
                )

                engine_results = search_results.get(engine_type, []) if search_results else []

                st.session_state.rag_test_response = None
                st.session_state.rag_test_context = engine_results
                st.session_state.rag_test_show_context_only = True

        finally:
            # Restore original default engine
            rag_manager.default_engine = original_default

    except Exception as e:
        st.error(f"Error during test: {str(e)}")
    finally:
        # Clear test mode flag
        if "rag_test_mode" in st.session_state:
            del st.session_state.rag_test_mode


def render_captured_interactions():
    """Render the captured interactions view (unchanged)."""
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
        if st.button("🔄 Refresh", width='stretch'):
            st.rerun()

    with col2:
        if st.button("🗑️ Clear All", width='stretch', type="secondary"):
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
    """Render a single interaction as an expandable card (unchanged)."""
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


def _get_rag_manager():
    """Helper to get RAG manager instance."""
    from modules.rag_manager.rag_factory import get_rag_manager
    return get_rag_manager()
