"""Driver assertion handlers registered by the trainer module."""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from core.logging import log


def _get_step(steps_by_id: Dict[str, object], step_id: str) -> Optional[object]:
    return steps_by_id.get(step_id)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def assertion_action_succeeded(*, params: Dict, steps_by_id: Dict[str, object], events: List[Dict]) -> Dict:
    del events
    step_id = params.get("step_id")
    step = _get_step(steps_by_id, step_id)
    passed = bool(step and step.success and not step.error)
    message = f"Step {step_id} completed without error" if passed else f"Step {step_id} failed or missing"
    return {"passed": passed, "message": message}


def assertion_llm_calls_made(*, params: Dict, steps_by_id: Dict[str, object], events: List[Dict]) -> Dict:
    del steps_by_id
    llm_calls = [e for e in events if e.get("type") == "llm_call"]
    total = len(llm_calls)
    min_n = params.get("min", 0)
    max_n = params.get("max")
    passed = total >= min_n and (max_n is None or total <= max_n)
    return {"passed": passed, "message": f"{total} LLM calls recorded (min: {min_n}, max: {max_n})"}


def assertion_plugin_event_occurred(*, params: Dict, steps_by_id: Dict[str, object], events: List[Dict]) -> Dict:
    del steps_by_id
    plugin_id = params.get("plugin_id")
    event = params.get("event")
    passed = any(
        e.get("type") == "plugin_event" and e.get("plugin_id") == plugin_id and e.get("event") == event
        for e in events
    )
    return {"passed": passed, "message": f"Plugin event {plugin_id}:{event} {'found' if passed else 'not found'}"}


def assertion_option_was_active(*, params: Dict, steps_by_id: Dict[str, object], events: List[Dict]) -> Dict:
    del steps_by_id
    group = params.get("group")
    name = params.get("name")
    passed = any(e.get("type") == "option_switch" and e.get("group") == group and e.get("option") == name for e in events)
    return {"passed": passed, "message": f"Option {group}.{name} {'was' if passed else 'was not'} activated"}


def assertion_context_field_set(*, params: Dict, steps_by_id: Dict[str, object], events: List[Dict]) -> Dict:
    del steps_by_id
    field = params.get("field")
    value = params.get("value", None)
    matches = [e for e in events if e.get("type") == "context_switch" and field in e.get("data", {})]
    if value is None:
        passed = any(m.get("data", {}).get(field) is not None for m in matches)
    else:
        passed = any(m.get("data", {}).get(field) == value for m in matches)
    return {"passed": passed, "message": f"Context field {field} {'set' if passed else 'not set'}"}


def assertion_injected_context_contains(*, params: Dict, steps_by_id: Dict[str, object], events: List[Dict]) -> Dict:
    del events
    step_id = params.get("step_id")
    contains = params.get("contains", "")
    not_contains = params.get("not_contains", "")
    source_contains = params.get("source_contains", "")

    step = _get_step(steps_by_id, step_id)
    if not step:
        return {"passed": False, "message": f"Step '{step_id}' not found in run results"}

    injected = step.result.get("injected_contexts", [])
    if not injected:
        return {
            "passed": False,
            "message": f"No injected contexts captured for step '{step_id}'. Check that the monitor callback was registered correctly.",
        }

    candidates = injected
    if source_contains:
        alias_map = {"student_pad": ["student_pad", "student_note", "student_notes", "get_student_notes_context"]}
        match_terms = alias_map.get(source_contains.lower(), [source_contains.lower()])
        candidates = [c for c in injected if any(term in c.get("source", "").lower() for term in match_terms)]
        if not candidates:
            sources = [c.get("source", "") for c in injected]
            return {
                "passed": False,
                "message": f"No context with source containing '{source_contains}' found for step '{step_id}'. Sources present: {sources}",
            }

    no_rag_markers = ["no rag results found", "no rag result found", "no results found", "no result found"]
    forbidden_terms = []
    if not_contains:
        forbidden_terms.append(_normalize_text(not_contains))
    forbidden_terms.extend(no_rag_markers)

    forbidden_match = None
    matched_term = ""
    for term in forbidden_terms:
        forbidden_match = next((c for c in candidates if term in _normalize_text(c.get("content", ""))), None)
        if forbidden_match:
            matched_term = term
            break

    if forbidden_match:
        preview = forbidden_match.get("content", "")[:140]
        log("info", f"[trainer] injected_context_contains forbidden term matched for step {step_id}: {matched_term}")
        if matched_term in no_rag_markers:
            return {
                "passed": False,
                "message": f"Context for step '{step_id}' contains '{matched_term}', so injected_context_contains cannot pass. Content preview: '{preview}...'",
            }
        return {
            "passed": False,
            "message": f"Context from source matching '{source_contains}' for step '{step_id}' contains forbidden text '{not_contains}'.",
        }

    if not_contains:
        return {
            "passed": True,
            "message": f"Context from source matching '{source_contains}' for step '{step_id}' does not contain '{not_contains}'.",
        }

    if contains:
        matching = [c for c in candidates if contains.lower() in c.get("content", "").lower()]
        if not matching:
            preview = candidates[0].get("content", "")[:100] if candidates else ""
            return {
                "passed": False,
                "message": f"Context from source matching '{source_contains}' found for step '{step_id}' but does not contain '{contains}'. Content preview: '{preview}...'",
            }
        return {
            "passed": True,
            "message": f"Found '{contains}' in context from '{matching[0].get('source', '')}' for step '{step_id}'",
        }

    if source_contains:
        return {"passed": True, "message": f"Found context from source matching '{source_contains}' for step '{step_id}'"}
    return {"passed": True, "message": f"Injected contexts captured for step '{step_id}'"}




def assertion_response_contains_semantic(*, params: Dict, steps_by_id: Dict[str, object], events: List[Dict]) -> Dict:
    """Check that a step llm_response semantically contains expected content."""
    del events

    from shared.common import get_embedding
    import numpy as np

    step_id = params.get("step_id")
    contains = params.get("contains", "")
    threshold = float(params.get("threshold", 0.70))
    mode = str(params.get("mode", "embedding"))

    step = _get_step(steps_by_id, step_id)
    if not step:
        return {"passed": False, "message": f"Step '{step_id}' not found"}

    llm_response = (step.result or {}).get("llm_response", "")
    if not llm_response:
        return {"passed": False, "message": f"Step '{step_id}' has no llm_response"}
    if not contains:
        return {"passed": False, "message": "Assertion param 'contains' is required"}

    if mode == "substring":
        passed = contains.lower() in llm_response.lower()
        return {
            "passed": passed,
            "message": f"Substring '{contains}' {'found' if passed else 'not found'} in response for step '{step_id}'",
        }

    try:
        vec_response = np.asarray(get_embedding(llm_response), dtype=np.float32)
        vec_contains = np.asarray(get_embedding(contains), dtype=np.float32)
        norm_response = float(np.linalg.norm(vec_response))
        norm_contains = float(np.linalg.norm(vec_contains))
        if norm_response == 0 or norm_contains == 0:
            return {"passed": False, "message": "Could not compute embeddings (zero vector)"}
        similarity = float(np.dot(vec_response, vec_contains) / (norm_response * norm_contains))
        passed = similarity >= threshold
        return {
            "passed": passed,
            "message": (
                f"Semantic similarity of response to '{contains}' = {similarity:.3f} "
                f"({'≥' if passed else '<'} threshold {threshold}) for step '{step_id}'"
            ),
        }
    except Exception as exc:
        return {"passed": False, "message": f"Embedding check failed: {exc}"}


def assertion_memory_contains_semantic(*, params: Dict, steps_by_id: Dict[str, object], events: List[Dict]) -> Dict:
    """Check that trigger_memory_analysis output semantically contains expected content."""
    del events

    from shared.common import get_embedding
    import numpy as np

    step_id = params.get("step_id")
    contains = params.get("contains", "")
    threshold = float(params.get("threshold", 0.70))
    mode = str(params.get("mode", "embedding"))

    step = _get_step(steps_by_id, step_id)
    if not step:
        return {"passed": False, "message": f"Step '{step_id}' not found"}
    if step.action != "trigger_memory_analysis":
        return {
            "passed": False,
            "message": f"Step '{step_id}' is not a trigger_memory_analysis step (got '{step.action}')",
        }

    memory_content = (step.result or {}).get("memory_content", "")
    if not memory_content:
        return {
            "passed": False,
            "message": (
                f"Step '{step_id}' has no memory_content in result. "
                "Ensure memory plugins include memory_content in trigger analysis output."
            ),
        }
    if not contains:
        return {"passed": False, "message": "Assertion param 'contains' is required"}

    if mode == "substring":
        passed = contains.lower() in memory_content.lower()
        return {
            "passed": passed,
            "message": f"Substring '{contains}' {'found' if passed else 'not found'} in memory for step '{step_id}'",
        }

    try:
        vec_memory = np.asarray(get_embedding(memory_content), dtype=np.float32)
        vec_contains = np.asarray(get_embedding(contains), dtype=np.float32)
        norm_memory = float(np.linalg.norm(vec_memory))
        norm_contains = float(np.linalg.norm(vec_contains))
        if norm_memory == 0 or norm_contains == 0:
            return {"passed": False, "message": "Could not compute embeddings (zero vector)"}
        similarity = float(np.dot(vec_memory, vec_contains) / (norm_memory * norm_contains))
        passed = similarity >= threshold
        return {
            "passed": passed,
            "message": (
                f"Semantic similarity of memory to '{contains}' = {similarity:.3f} "
                f"({'≥' if passed else '<'} threshold {threshold}) for step '{step_id}'"
            ),
        }
    except Exception as exc:
        return {"passed": False, "message": f"Embedding check failed: {exc}"}

def register_trainer_driver_assertions(register_assertion) -> None:
    """Register trainer-provided assertion handlers into the shared driver."""
    register_assertion("action_succeeded", assertion_action_succeeded, "Step succeeded without error")
    register_assertion("llm_calls_made", assertion_llm_calls_made, "Validate number of llm_call events")
    register_assertion("plugin_event_occurred", assertion_plugin_event_occurred, "Validate plugin event emission")
    register_assertion("option_was_active", assertion_option_was_active, "Validate option switch happened")
    register_assertion("context_field_set", assertion_context_field_set, "Validate context field switch")
    register_assertion(
        "injected_context_contains",
        assertion_injected_context_contains,
        "Validate injected contexts captured during a message step",
    )
    register_assertion(
        "response_contains_semantic",
        assertion_response_contains_semantic,
        "Check LLM response semantically contains expected concept (embedding cosine similarity)",
    )
    register_assertion(
        "memory_contains_semantic",
        assertion_memory_contains_semantic,
        "Check memory produced by trigger_memory_analysis semantically contains expected concept",
    )
