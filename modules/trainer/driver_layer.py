"""Driver integration layer for trainer (options, actions, assertions)."""

from __future__ import annotations

from typing import Dict

from core.logging import log
from shared.driver import DriverContext, DriverOptionError, DriverContextError

from .driver_assertions import register_trainer_driver_assertions


def _get_plugin(plugin_manager, trainer_manager, name: str):
    if hasattr(plugin_manager, "set_trainer_manager"):
        plugin_manager.set_trainer_manager(trainer_manager)
    return plugin_manager.get_plugin(name)


def register_trainer_driver_bindings(
    driver, plugin_manager, trainer_manager, record_plugin_event_fn
) -> None:
    """Register trainer options/actions/assertions in shared driver."""

    def _activate_memory_plugin(name: str, trainer_id: str) -> None:
        """Activate a memory plugin and synchronize with database."""
        log(
            "debug",
            f"[MEMORY_ACTIVATION] Attempting to activate plugin '{name}' for trainer '{trainer_id}'",
        )

        if trainer_id is None:
            error_msg = f"trainer: trainer_id not set in driver context — cannot activate plugin '{name}'"
            log("error", error_msg)
            raise DriverContextError(error_msg)

        plugin = _get_plugin(plugin_manager, trainer_manager, name)
        if not plugin:
            error_msg = f"trainer: plugin '{name}' not found"
            log("error", error_msg)
            raise DriverOptionError(error_msg)

        # Check plugin supports activation
        if not hasattr(plugin, "on_activate"):
            error_msg = f"trainer: plugin '{name}' missing required on_activate method"
            log("error", error_msg)
            raise DriverOptionError(error_msg)

        # 1. Verify trainer_manager is available
        if trainer_manager is None:
            error_msg = (
                f"trainer: trainer_manager not available for plugin '{name}' activation"
            )
            log("error", error_msg)
            raise RuntimeError(error_msg)

        # 2. Sync with database
        db_success = trainer_manager.set_plugin_active(trainer_id, plugin.id, True)
        if not db_success:
            error_msg = f"trainer: failed to set plugin '{name}' active in database for trainer '{trainer_id}'"
            log("error", error_msg)
            raise RuntimeError(error_msg)
        log(
            "debug", f"[MEMORY_ACTIVATION] Plugin '{name}' synced to database as active"
        )

        # 3. Verify database state immediately
        db_active = trainer_manager.is_plugin_active(trainer_id, plugin.id)
        if not db_active:
            error_msg = (
                f"trainer: plugin '{name}' marked active but database check failed"
            )
            log("error", error_msg)
            raise RuntimeError(error_msg)
        log("debug", f"[MEMORY_ACTIVATION] Database verification passed for '{name}'")

        # 4. Call plugin's on_activate
        try:
            plugin.on_activate(trainer_id)
            log(
                "debug",
                f"[MEMORY_ACTIVATION] Plugin '{name}'.on_activate() completed successfully",
            )
        except Exception as e:
            error_msg = f"trainer: plugin '{name}'.on_activate() failed: {e}"
            log("error", error_msg, stacktrace=True)
            raise DriverOptionError(error_msg) from e

        log(
            "info",
            f"[MEMORY_ACTIVATION] SUCCESS: Plugin '{name}' fully activated for trainer '{trainer_id}'",
        )

    def _deactivate_memory_plugin(name: str, trainer_id: str) -> None:
        """Deactivate a memory plugin and synchronize with database."""
        log(
            "debug",
            f"[MEMORY_DEACTIVATION] Attempting to deactivate plugin '{name}' for trainer '{trainer_id}'",
        )

        if trainer_id is None:
            error_msg = f"trainer: trainer_id not set in driver context — cannot deactivate plugin '{name}'"
            log("error", error_msg)
            raise DriverContextError(error_msg)

        plugin = _get_plugin(plugin_manager, trainer_manager, name)
        if not plugin:
            error_msg = f"trainer: plugin '{name}' not found"
            log("error", error_msg)
            raise DriverOptionError(error_msg)

        # 1. Call plugin's on_deactivate first
        try:
            plugin.on_deactivate(trainer_id)
            log(
                "debug",
                f"[MEMORY_DEACTIVATION] Plugin '{name}'.on_deactivate() completed",
            )
        except Exception as e:
            log(
                "warning",
                f"trainer: plugin '{name}'.on_deactivate() failed: {e}",
                stacktrace=True,
            )

        # 2. Sync with database
        db_success = trainer_manager.set_plugin_active(trainer_id, plugin.id, False)
        if not db_success:
            error_msg = f"trainer: failed to set plugin '{name}' inactive in database for trainer '{trainer_id}'"
            log("error", error_msg)
            raise RuntimeError(error_msg)
        log(
            "debug",
            f"[MEMORY_DEACTIVATION] Plugin '{name}' synced to database as inactive",
        )

        # 3. Verify database state
        db_active = trainer_manager.is_plugin_active(trainer_id, plugin.id)
        if db_active:
            error_msg = f"trainer: plugin '{name}' still shows active in database after deactivation"
            log("error", error_msg)
            raise RuntimeError(error_msg)
        log("debug", f"[MEMORY_DEACTIVATION] Database verification passed for '{name}'")

        log(
            "info",
            f"[MEMORY_DEACTIVATION] SUCCESS: Plugin '{name}' fully deactivated for trainer '{trainer_id}'",
        )

    def _get_context_and_verify(
        plugin, trainer_id: str, student_id: str, step_id: str
    ) -> Dict[str, str]:
        """Helper to get context with verification."""
        log(
            "debug",
            f"[CONTEXT_VERIFICATION] Getting context for plugin '{plugin.id}', trainer '{trainer_id}', student '{student_id}', step '{step_id}'",
        )

        # Verify plugin is active in memory
        if not plugin.is_active():
            error_msg = f"Plugin '{plugin.id}' is not marked active in memory for step '{step_id}'"
            log("error", error_msg)
            raise RuntimeError(error_msg)

        # Verify plugin is active in database
        if trainer_manager and not trainer_manager.is_plugin_active(
            trainer_id, plugin.id
        ):
            error_msg = f"Plugin '{plugin.id}' is not active in database for trainer '{trainer_id}' (step '{step_id}')"
            log("error", error_msg)
            raise RuntimeError(error_msg)

        # Get context
        context = plugin.get_context(student_id)
        log(
            "debug",
            f"[CONTEXT_VERIFICATION] Plugin '{plugin.id}' returned context: {bool(context)}",
        )

        if context:
            log("debug", f"[CONTEXT_VERIFICATION] Context keys: {list(context.keys())}")
        else:
            log(
                "warning",
                f"[CONTEXT_VERIFICATION] Plugin '{plugin.id}' returned empty context for step '{step_id}'",
            )

        return context

    def _action_trigger_analysis(context: DriverContext, **params) -> Dict:
        active = driver.get_active_option("memory_backend")
        if not active:
            log(
                "warning",
                "trainer: no memory_backend active for trigger_memory_analysis",
            )
            return {"success": False, "reason": "no_active_backend"}

        plugin_names = [n.strip() for n in active.split("+")]
        results = {}
        overall_success = True

        for name in plugin_names:
            plugin = _get_plugin(plugin_manager, trainer_manager, name)
            if not plugin:
                log("warning", f"trainer: plugin '{name}' not found")
                results[name] = {"success": False, "reason": "not_found"}
                overall_success = False
                continue
            if not hasattr(plugin, "_action_trigger_analysis"):
                log(
                    "warning",
                    f"trainer: plugin '{name}' does not support 'trigger_memory_analysis' — skipping",
                )
                results[name] = {"success": False, "reason": "unsupported"}
                continue

            results[name] = plugin._action_trigger_analysis(context, **params)
            if not results[name].get("success"):
                overall_success = False

        return {"success": overall_success, "plugin": active, "details": results}

    def _action_add_student_note(context: DriverContext, **params) -> Dict:
        content = params.get("content", "")
        if not content.strip():
            log("warning", "add_student_note: empty content")
            return {"saved": False, "reason": "empty_content"}

        active = driver.get_active_option("memory_backend") or ""
        pad_is_active = "student_pad" in active

        plugin = _get_plugin(plugin_manager, trainer_manager, "student_pad")
        if not plugin:
            log("warning", "add_student_note: student_pad plugin not found")
            return {"saved": False, "reason": "plugin_not_found"}

        result = plugin.add_note(
            student_id=context.student_id,
            content=content,
            topic=params.get("topic", ""),
        )
        if not pad_is_active:
            log(
                "warning",
                "add_student_note: student_pad not active — note saved but will not be injected into context",
            )
            result["warned"] = True

        record_plugin_event_fn(
            "student_pad",
            "note_added",
            {
                "student_id": context.student_id,
                "content": content[:100],
                "topic": params.get("topic", ""),
            },
        )
        return result

    for name, description in [
        ("memory", "LLM-summarised pedagogical memory (SQL backend)"),
        ("pedagogical_memory", "Atomic fact memory with semantic retrieval"),
        ("student_pad", "Student self-notes injected as memory context"),
    ]:
        if _get_plugin(plugin_manager, trainer_manager, name):
            driver.register_option(
                group="memory_backend",
                name=name,
                activate_fn=lambda n=name: _activate_memory_plugin(
                    n, driver.get_context().trainer_id
                ),
                deactivate_fn=lambda n=name: _deactivate_memory_plugin(
                    n, driver.get_context().trainer_id
                ),
                description=description,
            )

    if _get_plugin(plugin_manager, trainer_manager, "memory") and _get_plugin(
        plugin_manager, trainer_manager, "student_pad"
    ):
        driver.register_option(
            group="memory_backend",
            name="memory+student_pad",
            activate_fn=lambda: (
                _activate_memory_plugin("memory", driver.get_context().trainer_id),
                _activate_memory_plugin("student_pad", driver.get_context().trainer_id),
            ),
            deactivate_fn=lambda: (
                _deactivate_memory_plugin("memory", driver.get_context().trainer_id),
                _deactivate_memory_plugin(
                    "student_pad", driver.get_context().trainer_id
                ),
            ),
            description="Summarised memory combined with student self-notes",
        )

    if _get_plugin(
        plugin_manager, trainer_manager, "pedagogical_memory"
    ) and _get_plugin(plugin_manager, trainer_manager, "student_pad"):
        driver.register_option(
            group="memory_backend",
            name="pedagogical_memory+student_pad",
            activate_fn=lambda: (
                _activate_memory_plugin(
                    "pedagogical_memory", driver.get_context().trainer_id
                ),
                _activate_memory_plugin("student_pad", driver.get_context().trainer_id),
            ),
            deactivate_fn=lambda: (
                _deactivate_memory_plugin(
                    "pedagogical_memory", driver.get_context().trainer_id
                ),
                _deactivate_memory_plugin(
                    "student_pad", driver.get_context().trainer_id
                ),
            ),
            description="Atomic fact memory combined with student self-notes",
        )

    driver.register_action(
        name="trigger_memory_analysis",
        handler_fn=_action_trigger_analysis,
        description="Run analysis on new conversations and update student memory",
        required_context=["student_id", "trainer_id"],
    )
    driver.register_action(
        name="add_student_note",
        handler_fn=_action_add_student_note,
        description="Add a personal note for the current student (student_pad)",
        required_context=["student_id"],
    )

    register_trainer_driver_assertions(driver.register_assertion)
