"""Driver integration layer for trainer (options, actions, assertions)."""

from __future__ import annotations

from typing import Dict

from core.logging import log
from shared.common import get_driver, record_plugin_event, register_action, register_option, set_prompt, register_assertion
from shared.driver import DriverContext

from .driver_assertions import register_trainer_driver_assertions
from .manager import get_trainer_manager
from .plugin_base import get_plugin_manager


def _get_plugin(name: str):
    plugin_manager = get_plugin_manager()
    if hasattr(plugin_manager, "set_trainer_manager"):
        plugin_manager.set_trainer_manager(get_trainer_manager())
    return plugin_manager.get_plugin(name)


def _activate_memory_plugin(name: str, trainer_id: str) -> None:
    plugin = _get_plugin(name)
    if not plugin:
        log("warning", f"trainer: plugin '{name}' not found")
        return
    if trainer_id is None:
        log("warning", f"trainer: trainer_id not set in driver context — cannot activate plugin '{name}'")
        return
    plugin._mark_active()
    plugin.on_activate(trainer_id)


def _deactivate_memory_plugin(name: str, trainer_id: str) -> None:
    plugin = _get_plugin(name)
    if not plugin:
        log("warning", f"trainer: plugin '{name}' not found")
        return
    plugin._mark_inactive()
    if trainer_id is None:
        log("warning", f"trainer: trainer_id not set in driver context — cannot fully deactivate plugin '{name}'")
        return
    plugin.on_deactivate(trainer_id)


def _action_trigger_analysis(context: DriverContext, **params) -> Dict:
    active = get_driver().get_active_option("memory_backend")
    if not active:
        log("warning", "trainer: no memory_backend active for trigger_memory_analysis")
        return {"success": False, "reason": "no_active_backend"}

    plugin_names = [n.strip() for n in active.split("+")]
    results = {}
    overall_success = True

    for name in plugin_names:
        plugin = _get_plugin(name)
        if not plugin:
            log("warning", f"trainer: plugin '{name}' not found")
            results[name] = {"success": False, "reason": "not_found"}
            overall_success = False
            continue
        if not hasattr(plugin, "_action_trigger_analysis"):
            log("warning", f"trainer: plugin '{name}' does not support 'trigger_memory_analysis' — skipping")
            results[name] = {"success": False, "reason": "unsupported"}
            continue

        results[name] = plugin._action_trigger_analysis(context, **params)
        if not results[name].get("success"):
            overall_success = False

    return {"success": overall_success, "plugin": active, "details": results}


def _action_set_training_program(context: DriverContext, **params) -> Dict:
    del context
    content = params.get("content", "")
    if not content.strip():
        log("warning", "set_training_program: empty content")
        return {"saved": False, "reason": "empty_content"}
    set_prompt("trainer.teacher.training_program", content)
    return {"saved": True}


def _action_add_student_note(context: DriverContext, **params) -> Dict:
    content = params.get("content", "")
    if not content.strip():
        log("warning", "add_student_note: empty content")
        return {"saved": False, "reason": "empty_content"}

    active = get_driver().get_active_option("memory_backend") or ""
    pad_is_active = "student_pad" in active

    plugin = _get_plugin("student_pad")
    if not plugin:
        log("warning", "add_student_note: student_pad plugin not found")
        return {"saved": False, "reason": "plugin_not_found"}

    result = plugin.add_note(student_id=context.student_id, content=content, topic=params.get("topic", ""))
    if not pad_is_active:
        log("warning", "add_student_note: student_pad not active — note saved but will not be injected into context")
        result["warned"] = True

    record_plugin_event(
        "student_pad",
        "note_added",
        {"student_id": context.student_id, "content": content[:100], "topic": params.get("topic", "")},
    )
    return result


def register_trainer_driver_bindings() -> None:
    """Register trainer options/actions/assertions in shared driver."""
    for name, description in [
        ("memory", "LLM-summarised pedagogical memory (SQL backend)"),
        ("pedagogical_memory", "Atomic fact memory with semantic retrieval"),
        ("student_pad", "Student self-notes injected as memory context"),
    ]:
        if _get_plugin(name):
            register_option(
                group="memory_backend",
                name=name,
                activate_fn=lambda n=name: _activate_memory_plugin(n, get_driver().get_context().trainer_id),
                deactivate_fn=lambda n=name: _deactivate_memory_plugin(n, get_driver().get_context().trainer_id),
                description=description,
            )

    if _get_plugin("memory") and _get_plugin("student_pad"):

        def _activate_memory_pad():
            tid = get_driver().get_context().trainer_id
            _activate_memory_plugin("memory", tid)
            _activate_memory_plugin("student_pad", tid)

        def _deactivate_memory_pad():
            tid = get_driver().get_context().trainer_id
            _deactivate_memory_plugin("memory", tid)
            _deactivate_memory_plugin("student_pad", tid)

        register_option(
            group="memory_backend",
            name="memory+student_pad",
            activate_fn=_activate_memory_pad,
            deactivate_fn=_deactivate_memory_pad,
            description="Summarised memory combined with student self-notes",
        )

    if _get_plugin("pedagogical_memory") and _get_plugin("student_pad"):

        def _activate_ped_pad():
            tid = get_driver().get_context().trainer_id
            _activate_memory_plugin("pedagogical_memory", tid)
            _activate_memory_plugin("student_pad", tid)

        def _deactivate_ped_pad():
            tid = get_driver().get_context().trainer_id
            _deactivate_memory_plugin("pedagogical_memory", tid)
            _deactivate_memory_plugin("student_pad", tid)

        register_option(
            group="memory_backend",
            name="pedagogical_memory+student_pad",
            activate_fn=_activate_ped_pad,
            deactivate_fn=_deactivate_ped_pad,
            description="Atomic fact memory combined with student self-notes",
        )

    register_action(
        name="trigger_memory_analysis",
        handler_fn=_action_trigger_analysis,
        description="Run analysis on new conversations and update student memory",
        required_context=["student_id", "trainer_id"],
    )

    register_action(
        name="set_training_program",
        handler_fn=_action_set_training_program,
        description="Set the training program text for the current trainer",
        required_context=["trainer_id"],
    )

    register_action(
        name="add_student_note",
        handler_fn=_action_add_student_note,
        description="Add a personal note for the current student (student_pad)",
        required_context=["student_id"],
    )

    register_trainer_driver_assertions(register_assertion)
