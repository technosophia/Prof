# modules/rag_bench/rag_bench_core.py
"""
Core functionality for RAG benchmarking.
Stores captured LLM responses and RAG context in database.
"""
import json
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

from core.logging import log

# Simple in-memory storage for captured data
# In a production module, you'd use the app's database
_captured_interactions = []
_max_stored = 1000  # Keep last 1000 interactions


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
            # Look for system messages with source "rag_context_callback_classic"
            if (msg.get("role") == "system" and
                msg.get("source") == "rag_context_callback_classic"):
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


def get_captured_interactions(limit: int = 100, offset: int = 0) -> List[Dict]:
    """Get captured interactions with pagination."""
    global _captured_interactions

    start = len(_captured_interactions) - offset - limit
    end = len(_captured_interactions) - offset

    if start < 0:
        start = 0
    if end < 0:
        end = 0

    return list(reversed(_captured_interactions[start:end]))


def get_interaction_by_index(index: int) -> Optional[Dict]:
    """Get a specific interaction by index (from newest)."""
    global _captured_interactions

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
    global _captured_interactions

    total = len(_captured_interactions)
    with_context = sum(1 for i in _captured_interactions if i.get("rag_context"))

    # Group by LLM type
    by_llm = {}
    for i in _captured_interactions:
        llm_type = i.get("llm_type", "unknown")
        if llm_type not in by_llm:
            by_llm[llm_type] = 0
        by_llm[llm_type] += 1

    return {
        "total_interactions": total,
        "with_rag_context": with_context,
        "without_context": total - with_context,
        "by_llm_type": by_llm,
        "storage_limit": _max_stored,
        "storage_used": total
    }
