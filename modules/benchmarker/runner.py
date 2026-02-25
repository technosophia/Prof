"""Scenario loading, replay and assertion evaluation for benchmarker."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
import re
import time
from typing import Dict, List, Optional

import yaml

from shared.common import get_current_llm_id, get_driver, get_user_manager, set_current_llm
from shared.driver import DriverActionError, DriverContextError, DriverOptionError

from modules.benchmarker import initialize as initialize_benchmarker
from modules.benchmarker.benchmarker import BenchmarkRun
from modules.benchmarker.session import SessionSerializer


from core.logging import log, set_log_module_level
from st_shared.cached import get_section, get_db_manager
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
        "student": {"user_send_message", "create_conversation", "add_student_note"},
        "teacher": {"teacher_send_message", "trigger_memory_analysis", "set_training_program"},
        "system": {"create_conversation", "set_training_program", "switch_option"},
    }

    def __init__(self):
        # Ensure benchmarker actions and table are available before any validation/run.
        initialize_benchmarker()
        self.driver = get_driver()
        self.config = get_section("benchmarker")

    def run(
        self,
        scenario_path: str,
        option_overrides: Optional[Dict[str, str]] = None,
        setup_overrides: Optional[Dict[str, str]] = None,
        llm_override: Optional[str] = None,
    ) -> RunResult:
        """Execute scenario file and return structured run result."""
        run_errors: List[str] = []
        steps_out: List[StepResult] = []
        assertions_out: List[AssertionResult] = []
        option_overrides = option_overrides or {}
        setup_overrides = setup_overrides or {}

        scenario = self._load_scenario(scenario_path)
        scenario_name = scenario.get("meta", {}).get("name", os.path.basename(scenario_path))
        log("info", f"Benchmarker run start: scenario={scenario_name} path={scenario_path}")

        validation_errors = self.validate_scenario(scenario)
        if validation_errors:
            for err in validation_errors:
                log("warning", f"Scenario validation error: {err}")
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

        setup = dict(scenario.get("setup", {}))
        setup.update({k: v for k, v in setup_overrides.items() if v})
        created_users = self._ensure_test_users(setup)

        scenario_options = dict(scenario.get("options") or {})
        llm_id = (llm_override or "").strip() or scenario.get("llm") or scenario_options.get("llm")

        try:
            if not llm_id:
                try:
                    llm_id = get_current_llm_id()
                except Exception:
                    llm_id = None

            if llm_id:
                switched = set_current_llm(llm_id)
                log("info", f"LLM override request '{llm_id}' applied={switched}")

            self.driver.set_context(
                student_id=setup.get("student_id"),
                trainer_id=setup.get("trainer_id"),
                llm_id=llm_id,
            )
            log(
                "info",
                f"Initial context set: student={setup.get('student_id')} trainer={setup.get('trainer_id')} llm={llm_id}",
            )

            options = dict(scenario_options)
            options.update(option_overrides)
            for group, option_name in options.items():
                log("info", f"Switching option {group} -> {option_name}")
                self.driver.switch_option(group, option_name)

            # Keep driver context aligned with active llm option so actions that
            # rely on context.llm_id (e.g. user_send_message) don't revert to an
            # earlier default.
            active_llm_id = options.get("llm") or llm_id
            if active_llm_id and active_llm_id != llm_id:
                llm_id = active_llm_id
            if llm_id:
                self.driver.set_context(llm_id=llm_id)

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
        success = not run_errors and not [e for e in steps_out if not e.success] and assertions_passed == len(assertions_out)

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
            rubric_name=scenario.get("rubric"),
        )
        run_result.session_path = session_path

        self._persist_run(run_result)

        if self.config.get("cleanup_after_run", False):
            self._cleanup_users(created_users)

        log(
            "info",
            f"Benchmarker run complete: steps={len(run_result.steps)} assertions={run_result.assertions_passed}/{run_result.assertions_total} success={run_result.success}",
        )
        return run_result

    def validate_scenario(self, scenario: Dict) -> List[str]:
        """Return list of scenario validation errors."""
        errors: List[str] = []

        listed_options = self.driver.list_options()
        for group, option_name in scenario.get("options", {}).items():
            # Runner must support cold start with no options registered.
            if not listed_options:
                log("info", f"No driver options registered; skipping option validation for {group}.{option_name}")
                continue
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
        log("info", f"Running step {step_id}: [{actor}] {action} params={params}")
        try:
            if step.get("context"):
                self.driver.set_context(**step["context"])
                log("info", f"Applied step-specific context for {step_id}: {step['context']}")
            result = self.driver.do_action(action, **params)
            duration = time.time() - started
            log("info", f"Step {step_id} completed in {duration:.3f}s")
            return StepResult(
                step_id=step_id,
                action=action,
                actor=actor,
                success=True,
                result=result,
                duration_seconds=duration,
                params=params,
            )
        except (DriverContextError, DriverActionError, DriverOptionError, ValueError) as exc:
            msg = str(exc)
            duration = time.time() - started
            log("warning", f"Step {step_id} failed in {duration:.3f}s: {msg}", exc_info=True)
            return StepResult(
                step_id=step_id,
                action=action,
                actor=actor,
                success=False,
                result={},
                error=msg,
                duration_seconds=duration,
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

        def _get_step_result(step_id: str) -> Optional[StepResult]:
            return next((s for s in steps if s.step_id == step_id), None)

        for assertion in assertions:
            atype = assertion.get("type", "")
            aid = assertion.get("id", "")
            params = assertion.get("params", {})

            passed = False
            message = ""
            if atype == "action_succeeded":
                step_id = params.get("step_id")
                step = _get_step_result(step_id)
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
            elif atype == "injected_context_contains":
                step_id = params.get("step_id")
                contains = params.get("contains", "")
                not_contains = params.get("not_contains", "")
                source_contains = params.get("source_contains", "")

                step = _get_step_result(step_id)
                if not step:
                    message = f"Step '{step_id}' not found in run results"
                else:
                    injected = step.result.get("injected_contexts", [])
                    if not injected:
                        message = (
                            f"No injected contexts captured for step '{step_id}'. "
                            "Check that the monitor callback was registered correctly."
                        )
                    else:
                        candidates = injected
                        if source_contains:
                            alias_map = {
                                "student_pad": ["student_pad", "student_note", "student_notes", "get_student_notes_context"],
                            }
                            match_terms = alias_map.get(source_contains.lower(), [source_contains.lower()])
                            candidates = [
                                c
                                for c in injected
                                if any(term in c.get("source", "").lower() for term in match_terms)
                            ]
                            if not candidates:
                                sources = [c.get("source", "") for c in injected]
                                message = (
                                    f"No context with source containing '{source_contains}' found for step '{step_id}'. "
                                    f"Sources present: {sources}"
                                )

                        if not message:
                            def _normalize_text(text: str) -> str:
                                return re.sub(r"\s+", " ", (text or "").strip().lower())

                            no_rag_markers = [
                                "no rag results found",
                                "no rag result found",
                                "no results found",
                                "no result found"
                            ]

                            forbidden_terms = []
                            if not_contains:
                                forbidden_terms.append(_normalize_text(not_contains))
                            forbidden_terms.extend(no_rag_markers)

                            if candidates:
                                debug_previews = [
                                    {
                                        "source": c.get("source", ""),
                                        "content_preview": (c.get("content", "") or "")[:120],
                                    }
                                    for c in candidates
                                ]
                                log("debug", f"[benchmarker] injected_context_contains candidates for step {step_id}: {debug_previews}")

                            forbidden_match = None
                            matched_term = ""
                            for term in forbidden_terms:
                                forbidden_match = next(
                                    (c for c in candidates if term in _normalize_text(c.get("content", ""))),
                                    None,
                                )
                                if forbidden_match:
                                    matched_term = term
                                    break

                            if forbidden_match:
                                preview = forbidden_match.get("content", "")[:140]
                                log("info", f"[benchmarker] injected_context_contains forbidden term matched for step {step_id}: {matched_term}")
                                if matched_term in no_rag_markers:
                                    message = (
                                        f"Context for step '{step_id}' contains '{matched_term}', "
                                        "so injected_context_contains cannot pass. "
                                        f"Content preview: '{preview}...'"
                                    )
                                else:
                                    message = (
                                        f"Context from source matching '{source_contains}' for step '{step_id}' "
                                        f"contains forbidden text '{not_contains}'."
                                    )
                            elif not_contains:
                                passed = True
                                message = (
                                    f"Context from source matching '{source_contains}' for step '{step_id}' "
                                    f"does not contain '{not_contains}'."
                                )
                            elif contains:
                                matching = [
                                    c for c in candidates if contains.lower() in c.get("content", "").lower()
                                ]
                                if not matching:
                                    preview = candidates[0].get("content", "")[:100] if candidates else ""
                                    message = (
                                        f"Context from source matching '{source_contains}' found for step '{step_id}' "
                                        f"but does not contain '{contains}'. Content preview: '{preview}...'"
                                    )
                                else:
                                    passed = True
                                    message = (
                                        f"Found '{contains}' in context from "
                                        f"'{matching[0].get('source', '')}' for step '{step_id}'"
                                    )
                            else:
                                passed = True
                                if source_contains:
                                    message = (
                                        f"Found context from source matching '{source_contains}' "
                                        f"for step '{step_id}'"
                                    )
                                else:
                                    message = f"Injected contexts captured for step '{step_id}'"
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
