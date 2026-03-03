"""Driver assertion handlers registered by the trainer module."""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from core.logging import log


def _get_step(steps_by_id: Dict[str, object], step_id: str) -> Optional[object]:
    return steps_by_id.get(step_id)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _as_text_list(value) -> List[str]:
    """Normalize assertion value into a cleaned list of strings."""
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    coerced = str(value).strip()
    return [coerced] if coerced else []


def _parse_threshold(value, default: float = 0.70) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _get_semantic_evaluator():
    """
    Retrieve the SemanticEvaluator from the ServiceLocator.

    Returns None (with a warning) if the service is not yet registered,
    so assertion handlers degrade gracefully rather than crashing.
    """
    try:
        from shared.common import get_module_handler
        services = get_module_handler().get_services()
        if services is None:
            log("warning", "SemanticEvaluator: ServiceLocator not yet initialised")
            return None
        evaluator = services.get("semantic_eval")
        if evaluator is None:
            log("warning", "SemanticEvaluator: 'semantic_eval' not registered in ServiceLocator")
        return evaluator
    except Exception as exc:
        log("error", f"SemanticEvaluator: could not retrieve service — {exc}")
        return None


# ---------------------------------------------------------------------------
# Shared semantic helpers (used by multiple assertion types)
# ---------------------------------------------------------------------------

def _run_semantic_containment(
    *,
    actual_text: str,
    contains_terms: List[str],
    threshold: float,
    subject: str,
    step_id: str,
) -> Dict:
    """
    Check that EVERY term in `contains_terms` is semantically contained
    somewhere inside `actual_text` (AND semantics, max-pooled per chunk).

    Delegates to SemanticEvaluator.contains_all_concepts().
    Falls back to substring matching if the service is unavailable.
    """
    if not contains_terms:
        return {"passed": False, "message": "Assertion param 'contains' is required"}

    text = actual_text or ""

    evaluator = _get_semantic_evaluator()
    if evaluator is None:
        # Graceful fallback to substring
        missing = [t for t in contains_terms if t.lower() not in text.lower()]
        if missing:
            return {
                "passed": False,
                "message": (
                    f"[fallback:substring] Missing term(s) {missing} in {subject} "
                    f"for step '{step_id}' (SemanticEvaluator unavailable)"
                ),
            }
        return {
            "passed": True,
            "message": (
                f"[fallback:substring] All terms {contains_terms} found in {subject} "
                f"for step '{step_id}'"
            ),
        }

    check = evaluator.contains_all_concepts(text, contains_terms, threshold=threshold)
    if check["passed"]:
        scores = {c: f"{r.best_score:.3f}" for c, r in check["results"].items()}
        return {
            "passed": True,
            "message": (
                f"All concepts {contains_terms} semantically present in {subject} "
                f"for step '{step_id}' — scores: {scores}"
            ),
        }
    else:
        failed_detail = {
            c: f"best={r.best_score:.3f}<{threshold}"
            for c, r in check["results"].items()
            if not r.passed
        }
        return {
            "passed": False,
            "message": (
                f"Concepts not found in {subject} for step '{step_id}': {failed_detail}"
            ),
        }


def _run_full_similarity(
    *,
    text_a: str,
    text_b: str,
    threshold: float,
    label: str,
) -> Dict:
    """
    Full-document cosine similarity between two texts.
    Delegates to SemanticEvaluator.similarity().
    """
    evaluator = _get_semantic_evaluator()
    if evaluator is None:
        return {
            "passed": False,
            "message": f"SemanticEvaluator unavailable — cannot compute similarity for {label}",
        }
    result = evaluator.similarity(text_a, text_b, threshold=threshold)
    status = "PASS" if result.passed else "FAIL"
    return {
        "passed": result.passed,
        "message": f"[{status}] similarity={result.score:.4f} (threshold={threshold}) for {label}",
    }


# ---------------------------------------------------------------------------
# Assertion handlers
# ---------------------------------------------------------------------------

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
    contains_terms = _as_text_list(params.get("contains", ""))
    not_contains_terms = _as_text_list(params.get("not_contains", ""))
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
    forbidden_terms = [_normalize_text(term) for term in not_contains_terms]
    forbidden_terms.extend(no_rag_markers)

    forbidden_match = None
    matched_term = ""
    for term in forbidden_terms:
        forbidden_match = next((c for c in candidates if term in _normalize_text(c.get("content", ""))), None)
        if forbidden_match:
            matched_term = term
            break

    if forbidden_match:
        preview = forbidden_match.get("content", "")
        log("info", f"[trainer] injected_context_contains forbidden term matched for step {step_id}: {matched_term}")
        if matched_term in no_rag_markers:
            return {
                "passed": False,
                "message": f"Context for step '{step_id}' contains '{matched_term}', so injected_context_contains cannot pass. Content preview: '{preview}...'",
            }
        return {
            "passed": False,
            "message": f"Context from source matching '{source_contains}' for step '{step_id}' contains forbidden text '{matched_term}'.",
        }

    if not_contains_terms and not contains_terms:
        return {
            "passed": True,
            "message": f"Context from source matching '{source_contains}' for step '{step_id}' does not contain forbidden terms {not_contains_terms}.",
        }

    if contains_terms:
        missing = []
        for term in contains_terms:
            has_term = any(term.lower() in c.get("content", "").lower() for c in candidates)
            if not has_term:
                missing.append(term)

        if missing:
            preview = candidates[0].get("content", "") if candidates else ""
            if len(missing) == 1 and len(contains_terms) == 1:
                return {
                    "passed": False,
                    "message": (
                        f"Context from source matching '{source_contains}' found for step '{step_id}' "
                        f"but does not contain '{contains_terms[0]}'. Content preview: '{preview}...'"
                    ),
                }
            return {
                "passed": False,
                "message": (
                    f"Context from source matching '{source_contains}' found for step '{step_id}' "
                    f"but missing required term(s) {missing}. Content preview: '{preview}...'"
                ),
            }

        return {
            "passed": True,
            "message": f"Found all required term(s) {contains_terms} in injected context for step '{step_id}'",
        }

    if source_contains:
        return {"passed": True, "message": f"Found context from source matching '{source_contains}' for step '{step_id}'"}
    return {"passed": True, "message": f"Injected contexts captured for step '{step_id}'"}


def assertion_response_contains_semantic(*, params: Dict, steps_by_id: Dict[str, object], events: List[Dict]) -> Dict:
    """
    Check that a step llm_response semantically contains all expected concepts.
    Uses chunked max-pooling via SemanticEvaluator.contains_all_concepts().
    """
    del events

    step_id = params.get("step_id")
    contains_terms = _as_text_list(params.get("contains", ""))
    threshold = _parse_threshold(params.get("threshold"), default=0.45)

    step = _get_step(steps_by_id, step_id)
    if not step:
        return {"passed": False, "message": f"Step '{step_id}' not found"}

    llm_response = (step.result or {}).get("llm_response", "")
    if not llm_response:
        return {"passed": False, "message": f"Step '{step_id}' has no llm_response"}

    return _run_semantic_containment(
        actual_text=llm_response,
        contains_terms=contains_terms,
        threshold=threshold,
        subject="response",
        step_id=step_id,
    )


def assertion_memory_contains_semantic(*, params: Dict, steps_by_id: Dict[str, object], events: List[Dict]) -> Dict:
    """
    Check that trigger_memory_analysis output semantically contains all expected concepts.
    Uses chunked max-pooling via SemanticEvaluator.contains_all_concepts().
    """
    del events

    step_id = params.get("step_id")
    contains_terms = _as_text_list(params.get("contains", ""))
    threshold = _parse_threshold(params.get("threshold"), default=0.45)

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

    return _run_semantic_containment(
        actual_text=memory_content,
        contains_terms=contains_terms,
        threshold=threshold,
        subject="memory",
        step_id=step_id,
    )


def assertion_injected_context_contains_semantics(*, params: Dict, steps_by_id: Dict[str, object], events: List[Dict]) -> Dict:
    """
    Check that injected context semantically contains all expected concepts.
    Uses chunked max-pooling via SemanticEvaluator.contains_all_concepts().
    """
    del events

    step_id = params.get("step_id")
    contains_terms = _as_text_list(params.get("contains", ""))
    threshold = _parse_threshold(params.get("threshold"), default=0.45)
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

    joined_content = "\n".join(str(c.get("content", "")) for c in candidates if c.get("content", ""))
    if not joined_content.strip():
        return {"passed": False, "message": f"Injected contexts for step '{step_id}' have no content to evaluate"}

    return _run_semantic_containment(
        actual_text=joined_content,
        contains_terms=contains_terms,
        threshold=threshold,
        subject=f"injected context (source='{source_contains}')",
        step_id=step_id,
    )


def assertion_response_similarity(*, params: Dict, steps_by_id: Dict[str, object], events: List[Dict]) -> Dict:
    """
    Full-document cosine similarity between llm_response and expected_response.

    Use this for overall response quality — not for checking if a specific
    concept is present (use response_contains_semantic for that).
    """
    del events

    step_id = params.get("step_id")
    threshold = _parse_threshold(params.get("threshold"), default=0.70)

    step = _get_step(steps_by_id, step_id)
    if not step:
        return {"passed": False, "message": f"Step '{step_id}' not found"}

    llm_response = str((step.result or {}).get("llm_response", "")).strip()
    expected = str(step.get("expected_response", "") if hasattr(step, "get") else "").strip()

    if not llm_response:
        return {"passed": False, "message": f"Step '{step_id}' has no llm_response"}
    if not expected:
        return {"passed": False, "message": f"Step '{step_id}' has no expected_response to compare against"}

    return _run_full_similarity(
        text_a=llm_response,
        text_b=expected,
        threshold=threshold,
        label=f"step '{step_id}'",
    )


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
        "Validate injected contexts captured during a message step (substring)",
    )
    register_assertion(
        "injected_context_contains_semantics",
        assertion_injected_context_contains_semantics,
        "Check injected context semantically contains expected concept (chunked max-pooling)",
    )
    register_assertion(
        "response_contains_semantic",
        assertion_response_contains_semantic,
        "Check LLM response semantically contains expected concept (chunked max-pooling)",
    )
    register_assertion(
        "memory_contains_semantic",
        assertion_memory_contains_semantic,
        "Check memory produced by trigger_memory_analysis semantically contains expected concept",
    )
    register_assertion(
        "response_similarity",
        assertion_response_similarity,
        "Full-document cosine similarity between llm_response and expected_response",
    )
