"""Scenario loading, replay and assertion evaluation for benchmarker."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
import re
import time
from typing import Dict, List, Optional

import yaml

from shared.common import get_current_llm_id, get_driver, get_section, get_user_manager, log
from shared.driver import DriverActionError, DriverContextError, DriverOptionError

from . import BenchmarkRun
from .session import SessionSerializer


@dataclass
class AssertionResult:
    """Result of a single scenario assertion."""

    id: str
    passed: bool
    message: str
    assertion_type: str


@dataclass
class StepResult:
    """Result of executing one scenario step."""

    step_id: str
    action: str
    actor: str
    success: bool
    result: Dict
    error: Optional[str] = None
    duration_seconds: float = 0.0
    params: Dict = field(default_factory=dict)


@dataclass
class RunResult:
    """Outcome of a full scenario run."""

    scenario_name: str
    session_path: str
    steps: List[StepResult]
    assertions: List[AssertionResult]
    assertions_passed: int
    assertions_total: int
    errors: List[str]
    summary: Dict
    success: bool


class ScenarioRunner:
    """Load, validate, replay scenarios and generate run artifacts."""

    ALLOWED_BY_ACTOR = {
        "student": {"user_send_message", "create_conversation"},
        "teacher": {"teacher_send_message", "trigger_memory_analysis", "add_student_note", "set_training_program"},
        "system": {"create_conversation", "set_training_program", "switch_option"},
    }

    def __init__(self):
        self.driver = get_driver()
        self.config = get_section("benchmarker")

    def run(self, scenario_path: str, option_overrides: Optional[Dict[str, str]] = None) -> RunResult:
        """Execute scenario file and return structured run result."""
        run_errors: List[str] = []
        steps_out: List[StepResult] = []
        assertions_out: List[AssertionResult] = []
        option_overrides = option_overrides or {}

        scenario = self._load_scenario(scenario_path)
        scenario_name = scenario.get("meta", {}).get("name", os.path.basename(scenario_path))

        validation_errors = self.validate_scenario(scenario)
        if validation_errors:
            return RunResult(
                scenario_name=scenario_name,
                session_path="",
                steps=[],
                assertions=[],
                assertions_passed=0,
                assertions_total=0,
                errors=validation_errors,
                summary={},
                success=False,
            )

        self.driver.start_session(scenario_name)
        started_at = time.time()

        setup = scenario.get("setup", {})
        created_users = self._ensure_test_users(setup)

        try:
            options = dict(scenario.get("options", {}))
            options.update(option_overrides)
            for group, option_name in options.items():
                self.driver.switch_option(group, option_name)

            llm_id = scenario.get("llm")
            if not llm_id:
                try:
                    llm_id = get_current_llm_id()
                except Exception:
                    llm_id = None

            self.driver.set_context(
                student_id=setup.get("student_id"),
                trainer_id=setup.get("trainer_id"),
                llm_id=llm_id,
            )

            for step in scenario.get("steps", []):
                resolved = self._resolve_step_params(step, setup)
                step_result = self._replay_step(resolved)
                steps_out.append(step_result)

            assertions_out = self._evaluate_assertions(scenario.get("assertions", []), steps_out)

        except Exception as exc:
            msg = f"Run-level failure: {exc}"
            run_errors.append(msg)
            log("error", msg, exc_info=True)

        summary = self.driver.get_session_summary()
        assertions_passed = len([a for a in assertions_out if a.passed])
        success = not run_errors and assertions_passed == len(assertions_out)

        run_result = RunResult(
            scenario_name=scenario_name,
            session_path="",
            steps=steps_out,
            assertions=assertions_out,
            assertions_passed=assertions_passed,
            assertions_total=len(assertions_out),
            errors=run_errors,
            summary=summary,
            success=success,
        )

        events = self.driver.get_session_events()
        serializer = SessionSerializer()
        session_path = serializer.write(
            run_result=run_result,
            events=events,
            output_dir=self.config.get("sessions_dir", "data/benchmarker/sessions"),
            options_snapshot=summary.get("active_options", {}),
            llm_id=llm_id,
            run_duration=time.time() - started_at,
        )
        run_result.session_path = session_path

        self._persist_run(run_result)

        if self.config.get("cleanup_after_run", False):
            self._cleanup_users(created_users)

        return run_result

    def validate_scenario(self, scenario: Dict) -> List[str]:
        """Return list of scenario validation errors."""
        errors: List[str] = []

        listed_options = self.driver.list_options()
        for group, option_name in scenario.get("options", {}).items():
            names = {opt["name"] for opt in listed_options.get(group, [])}
            if group not in listed_options:
                errors.append(f"Unknown option group: {group}")
            elif option_name not in names:
                errors.append(f"Unknown option '{option_name}' in group '{group}'")

        actions = {a["name"] for a in self.driver.list_actions()}
        ids = set()
        for idx, step in enumerate(scenario.get("steps", [])):
            sid = step.get("id")
            actor = step.get("actor")
            action = step.get("action")
            if not sid or not actor or not action:
                errors.append(f"Step #{idx + 1} missing required field(s): id/actor/action")
                continue
            if sid in ids:
                errors.append(f"Duplicate step id: {sid}")
            ids.add(sid)

            if action not in actions:
                errors.append(f"Unknown action in step {sid}: {action}")

            allowed = self.ALLOWED_BY_ACTOR.get(actor, set())
            if action not in allowed:
                errors.append(f"Actor '{actor}' cannot execute action '{action}' (step {sid})")

        return errors

    def _replay_step(self, step: Dict) -> StepResult:
        """Replay one step and continue on action/context errors."""
        step_id = step.get("id", "")
        action = step.get("action", "")
        actor = step.get("actor", "")
        params = step.get("params", {})

        if action not in self.ALLOWED_BY_ACTOR.get(actor, set()):
            msg = f"Actor '{actor}' is not allowed to run '{action}'"
            log("warning", msg)
            return StepResult(step_id=step_id, action=action, actor=actor, success=False, result={}, error=msg, params=params)

        started = time.time()
        try:
            if step.get("context"):
                self.driver.set_context(**step["context"])
            result = self.driver.do_action(action, **params)
            return StepResult(
                step_id=step_id,
                action=action,
                actor=actor,
                success=True,
                result=result,
                duration_seconds=time.time() - started,
                params=params,
            )
        except (DriverContextError, DriverActionError, DriverOptionError, ValueError) as exc:
            msg = str(exc)
            log("warning", f"Step {step_id} failed: {msg}", exc_info=True)
            return StepResult(
                step_id=step_id,
                action=action,
                actor=actor,
                success=False,
                result={},
                error=msg,
                duration_seconds=time.time() - started,
                params=params,
            )

    def _resolve_step_params(self, step: Dict, setup: Dict) -> Dict:
        """Resolve {{ setup.field }} placeholders in step params."""
        cloned = dict(step)
        params = dict(step.get("params", {}))
        resolved = {}
        for key, value in params.items():
            if isinstance(value, str):
                match = re.fullmatch(r"\{\{\s*setup\.(\w+)\s*\}\}", value)
                if match:
                    resolved[key] = setup.get(match.group(1), "")
                    continue
            resolved[key] = value
        cloned["params"] = resolved
        return cloned

    def _load_scenario(self, scenario_path: str) -> Dict:
        with open(scenario_path, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}

    def _evaluate_assertions(self, assertions: List[Dict], steps: List[StepResult]) -> List[AssertionResult]:
        events = self.driver.get_session_events()
        results: List[AssertionResult] = []

        for assertion in assertions:
            atype = assertion.get("type", "")
            aid = assertion.get("id", "")
            params = assertion.get("params", {})

            passed = False
            message = ""
            if atype == "action_succeeded":
                step_id = params.get("step_id")
                step = next((s for s in steps if s.step_id == step_id), None)
                passed = bool(step and step.success and not step.error)
                message = f"Step {step_id} completed without error" if passed else f"Step {step_id} failed or missing"
            elif atype == "llm_calls_made":
                llm_calls = [e for e in events if e.get("type") == "llm_call"]
                total = len(llm_calls)
                min_n = params.get("min", 0)
                max_n = params.get("max")
                passed = total >= min_n and (max_n is None or total <= max_n)
                message = f"{total} LLM calls recorded (min: {min_n}, max: {max_n})"
            elif atype == "plugin_event_occurred":
                plugin_id = params.get("plugin_id")
                event = params.get("event")
                passed = any(
                    e.get("type") == "plugin_event" and e.get("plugin_id") == plugin_id and e.get("event") == event
                    for e in events
                )
                message = f"Plugin event {plugin_id}:{event} {'found' if passed else 'not found'}"
            elif atype == "option_was_active":
                group = params.get("group")
                name = params.get("name")
                passed = any(
                    e.get("type") == "option_switch" and e.get("group") == group and e.get("option") == name
                    for e in events
                )
                message = f"Option {group}.{name} {'was' if passed else 'was not'} activated"
            elif atype == "context_field_set":
                field = params.get("field")
                value = params.get("value", None)
                matches = [
                    e
                    for e in events
                    if e.get("type") == "context_switch" and field in e.get("data", {})
                ]
                if value is None:
                    passed = any(m.get("data", {}).get(field) is not None for m in matches)
                else:
                    passed = any(m.get("data", {}).get(field) == value for m in matches)
                message = f"Context field {field} {'set' if passed else 'not set'}"
            else:
                message = f"Unsupported assertion type: {atype}"

            results.append(AssertionResult(id=aid, passed=passed, message=message, assertion_type=atype))

        return results

    def _ensure_test_users(self, setup: Dict) -> List[str]:
        created = []
        user_manager = get_user_manager()

        trainer_name = setup.get("trainer_id")
        student_name = setup.get("student_id")

        trainer = user_manager.get_user_by_name(trainer_name) if trainer_name else None
        if trainer is None and trainer_name:
            trainer_id, _ = user_manager.create_user(name=trainer_name, role="master")
            created.append(trainer_id)
            log("info", f"Created test user {trainer_name}")
            trainer = user_manager.get_user(trainer_id)

        student = user_manager.get_user_by_name(student_name) if student_name else None
        if student is None and student_name and trainer:
            student_id, _ = user_manager.create_user(name=student_name, role="normal", parent_id=trainer["id"])
            created.append(student_id)
            log("info", f"Created test user {student_name}")

        return created

    def _cleanup_users(self, user_ids: List[str]) -> None:
        if not user_ids:
            return
        user_manager = get_user_manager()
        for user_id in reversed(user_ids):
            user = user_manager.get_user(user_id)
            if user and user_manager.delete_user(user_id):
                log("info", f"Deleted test user {user.get('name', user_id)}")

    def _persist_run(self, run_result: RunResult) -> None:
        try:
            from shared.common import get_db_manager

            with get_db_manager().get_session() as session:
                session.add(
                    BenchmarkRun(
                        scenario_name=run_result.scenario_name,
                        run_at=datetime.now(timezone.utc),
                        duration_seconds=run_result.summary.get("duration_seconds", 0.0),
                        options=run_result.summary.get("active_options", {}),
                        success=1 if run_result.success else 0,
                        assertions_passed=run_result.assertions_passed,
                        assertions_total=run_result.assertions_total,
                        errors=run_result.errors,
                        session_file=run_result.session_path,
                        summary=run_result.summary,
                    )
                )
        except Exception as exc:
            log("error", f"Failed to persist benchmark run: {exc}", exc_info=True)
