# modules/rag_bench/rag_bench_core.py
"""
Core functionality for RAG benchmarking.
Stores captured LLM responses and RAG context in database.
Includes support for comparing multiple RAG engines.
"""
import json
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

from core.logging import log

# Simple in-memory storage for captured data
# In a production module, you'd use the app's database
_captured_interactions = []
_max_stored = 1000  # Keep last 1000 interactions

# Storage for engine comparison results
_captured_comparison_contexts = []
_max_comparison_stored = 50  # Keep last 50 comparison runs


def capture_llm_response(monitor_data: Dict[str, Any]) -> None:
    """
    Monitor callback to capture LLM responses.
    This is called by llm_manager for every LLM call.
    """
    global _captured_interactions

    try:
        # Extract RAG context from messages
        rag_context = []
        messages = monitor_data.get("messages", [])

        for msg in messages:
            # Look for system messages with source containing "rag_context_callback"
            if (msg.get("role") == "system" and
                msg.get("source") and
                "rag_context_callback" in msg.get("source", "")):
                rag_context.append({
                    "content": msg.get("content", ""),
                    "source": msg.get("source", "rag_context"),
                    "role": "system",
                    "timestamp": datetime.now().isoformat()
                })

        # Extract relevant data
        interaction = {
            "timestamp": monitor_data.get("timestamp", datetime.now().isoformat()),
            "llm_id": monitor_data.get("llm_id"),
            "llm_type": monitor_data.get("llm_type"),
            "model": monitor_data.get("model"),
            "user_id": monitor_data.get("user_id"),
            "messages": messages,
            "response": monitor_data.get("response", ""),
            "input_tokens": monitor_data.get("input_tokens"),
            "output_tokens": monitor_data.get("output_tokens"),
            "total_tokens": monitor_data.get("total_tokens"),
            "success": monitor_data.get("success", True),
            "rag_context": rag_context  # Store extracted RAG context
        }

        # Try to determine which engine was used
        engine_used = None
        for msg in messages:
            if msg.get("role") == "system" and msg.get("source"):
                source = msg.get("source", "")
                if "rag_context_callback_" in source:
                    engine_used = source.replace("rag_context_callback_", "")
                    break

        if engine_used:
            interaction["engine_used"] = engine_used

        # Add to storage
        _captured_interactions.append(interaction)

        # Check if we're in test mode and store context for test UI
        import streamlit as st
        if hasattr(st, 'session_state') and st.session_state.get("rag_test_mode"):
            if rag_context:
                st.session_state.rag_test_captured_context = rag_context

        # Keep only last N interactions
        if len(_captured_interactions) > _max_stored:
            _captured_interactions = _captured_interactions[-_max_stored:]

    except Exception as e:
        log("error", f"rag_bench: failed to capture LLM response: {e}")


def capture_rag_context(user_id: str, messages: List[Dict]) -> Tuple[str, str, str]:
    """
    Context callback to capture RAG context.
    This is called by llm_manager when building context for an LLM call.

    Returns empty context to avoid modifying the actual LLM call.
    """
    try:
        # This is called before the LLM call, so we can't capture here
        # The actual RAG context will be in the messages during capture_llm_response
        pass

    except Exception as e:
        log("error", f"rag_bench: failed to capture RAG context: {e}")

    # Return empty context to avoid modifying the actual LLM call
    return "", "system", "bottom"


def capture_rag_context_for_comparison(
    engine_type: str,
    query: str,
    context_text: str,
    results: List[Dict],
    run_id: Optional[str] = None
) -> None:
    """
    Capture RAG context for engine comparison.
    This is called when comparing engines directly.

    Args:
        engine_type: The engine type
        query: The search query
        context_text: The context text
        results: List of result dictionaries
        run_id: Optional unique identifier for this comparison run
    """
    global _captured_comparison_contexts

    try:
        # Calculate aggregate stats
        max_score = 0
        avg_score = 0
        threshold = None

        if results:
            scores = [r.get('score', 0) for r in results if not r.get('no_results')]
            if scores:
                max_score = max(scores)
                avg_score = sum(scores) / len(scores)

            # Get threshold from first result if available
            for r in results:
                if r.get('threshold_used') is not None:
                    threshold = r.get('threshold_used')
                    break

        comparison_data = {
            "timestamp": datetime.now().isoformat(),
            "engine_type": engine_type,
            "query": query,
            "context_text": context_text,
            "results": results,
            "result_count": len([r for r in results if not r.get('no_results')]),
            "max_score": max_score,
            "avg_score": avg_score,
            "threshold": threshold,
            "run_id": run_id
        }

        log("debug", f"[RAG Compare] Capturing context for engine: {engine_type} with {len(results)} results, run_id={run_id}")

        _captured_comparison_contexts.append(comparison_data)

        # Keep only last N comparisons
        if len(_captured_comparison_contexts) > _max_comparison_stored:
            _captured_comparison_contexts = _captured_comparison_contexts[-_max_comparison_stored:]

        log("debug", f"[RAG Compare] Total comparison contexts now: {len(_captured_comparison_contexts)}")

    except Exception as e:
        log("error", f"rag_bench: failed to capture comparison context: {e}")


def get_captured_comparison_contexts(run_id: Optional[str] = None) -> List[Dict]:
    """Get all captured comparison contexts for the most recent query.

    Args:
        run_id: If provided, return contexts with this run_id.
                If None, return contexts with the most recent run_id.
    """

    if not _captured_comparison_contexts:
        return []

    if run_id is not None:
        # Return contexts with specific run_id
        result = [ctx for ctx in _captured_comparison_contexts if ctx.get("run_id") == run_id]
        result.sort(key=lambda x: x.get('engine_type', ''))
        log("debug", f"[RAG Compare] Retrieved {len(result)} contexts for run_id={run_id}")
        return result

    # Find the most recent run_id
    run_ids = {}
    for ctx in _captured_comparison_contexts:
        rid = ctx.get("run_id")
        if rid:
            # Use timestamp as tie-breaker if needed
            run_ids[rid] = ctx.get("timestamp")

    if not run_ids:
        # Fallback to old timestamp grouping (for backward compatibility)
        log("debug", "[RAG Compare] No run_id found, falling back to timestamp grouping")
        return _get_latest_by_timestamp()

    # Get the most recent run_id by timestamp
    latest_run_id = max(run_ids.items(), key=lambda x: x[1])[0]
    log("debug", f"[RAG Compare] Most recent run_id: {latest_run_id}")

    # Return all contexts with that run_id
    result = [ctx for ctx in _captured_comparison_contexts if ctx.get("run_id") == latest_run_id]
    result.sort(key=lambda x: x.get('engine_type', ''))
    log("debug", f"[RAG Compare] Retrieved {len(result)} contexts for latest run_id")
    return result


def _get_latest_by_timestamp() -> List[Dict]:
    """Fallback method: group by latest timestamp (old behavior)."""

    if not _captured_comparison_contexts:
        return []

    # Find the most recent timestamp
    latest_timestamp = None
    for ctx in _captured_comparison_contexts:
        ts = ctx.get("timestamp")
        if latest_timestamp is None or ts > latest_timestamp:
            latest_timestamp = ts

    # Return all contexts with that timestamp
    result = [ctx for ctx in _captured_comparison_contexts if ctx.get("timestamp") == latest_timestamp]
    result.sort(key=lambda x: x.get('engine_type', ''))
    log("debug", f"[RAG Compare] Retrieved {len(result)} contexts for timestamp {latest_timestamp}")
    return result


def clear_comparison_contexts() -> None:
    """Clear all captured comparison contexts."""
    global _captured_comparison_contexts
    _captured_comparison_contexts = []
    log("debug", "[RAG Compare] Cleared all comparison contexts")


def get_captured_interactions(limit: int = 100, offset: int = 0) -> List[Dict]:
    """Get captured interactions with pagination."""

    start = len(_captured_interactions) - offset - limit
    end = len(_captured_interactions) - offset

    if start < 0:
        start = 0
    if end < 0:
        end = 0

    return list(reversed(_captured_interactions[start:end]))


def get_interaction_by_index(index: int) -> Optional[Dict]:
    """Get a specific interaction by index (from newest)."""

    if 0 <= index < len(_captured_interactions):
        return _captured_interactions[-(index + 1)]
    return None


def clear_captured_interactions() -> int:
    """Clear all captured interactions. Returns count cleared."""
    global _captured_interactions
    count = len(_captured_interactions)
    _captured_interactions = []
    return count


def get_stats() -> Dict[str, Any]:
    """Get statistics about captured interactions."""

    total = len(_captured_interactions)
    with_context = sum(1 for i in _captured_interactions if i.get("rag_context"))

    # Group by LLM type
    by_llm = {}
    for i in _captured_interactions:
        llm_type = i.get("llm_type", "unknown")
        if llm_type not in by_llm:
            by_llm[llm_type] = 0
        by_llm[llm_type] += 1

    # Group by engine used
    by_engine = {}
    for i in _captured_interactions:
        engine = i.get("engine_used", "unknown")
        if engine not in by_engine:
            by_engine[engine] = 0
        by_engine[engine] += 1

    return {
        "total_interactions": total,
        "with_rag_context": with_context,
        "without_context": total - with_context,
        "by_llm_type": by_llm,
        "by_engine": by_engine,
        "storage_limit": _max_stored,
        "storage_used": total
    }
