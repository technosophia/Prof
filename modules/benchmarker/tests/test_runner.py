"""Tests for benchmarker scenario runner."""

from pathlib import Path

import pytest

from modules.benchmarker.runner import ScenarioRunner, StepResult
from modules.trainer.driver_assertions import (
    assertion_action_succeeded,
    assertion_context_field_set,
    assertion_injected_context_contains,
    assertion_llm_calls_made,
    assertion_option_was_active,
    assertion_plugin_event_occurred,
)


class FakeDriver:
    def __init__(self):
        self.options = {"memory_backend": [{"name": "memory", "active": False}]}
        self.actions = [
            {"name": "create_conversation"},
            {"name": "set_training_program"},
            {"name": "user_send_message"},
            {"name": "switch_option"},
        ]
        self.events = []
        self._assertion_handlers = {
            "action_succeeded": assertion_action_succeeded,
            "llm_calls_made": assertion_llm_calls_made,
            "plugin_event_occurred": assertion_plugin_event_occurred,
            "option_was_active": assertion_option_was_active,
            "context_field_set": assertion_context_field_set,
            "injected_context_contains": assertion_injected_context_contains,
        }

    def list_options(self):
        return self.options

    def list_actions(self):
        return self.actions

    def start_session(self, name=""):
        self.events = []

    def switch_option(self, group, name):
        self.events.append({"type": "option_switch", "group": group, "option": name})

    def set_context(self, **kwargs):
        self.events.append({"type": "context_switch", "data": kwargs})

    def do_action(self, name, **params):
        if params.get("explode"):
            raise ValueError("boom")
        self.events.append({"type": "action", "name": name, "params": params})
        if name == "user_send_message":
            self.events.append({"type": "llm_call", "llm_id": "groq", "prompt_tokens": 1, "completion_tokens": 1})
        return {"ok": True}

    def get_session_events(self):
        return self.events

    def get_session_summary(self):
        return {
            "total_llm_calls": len([e for e in self.events if e.get("type") == "llm_call"]),
            "total_tokens": 4,
            "active_options": {"memory_backend": "memory"},
            "duration_seconds": 0.5,
        }



    def list_assertions(self):
        return [{"name": name} for name in self._assertion_handlers.keys()]

    def evaluate_assertion(self, name, **payload):
        return self._assertion_handlers[name](**payload)

def _scenario_path():
    return str(Path("modules/benchmarker/scenarios/example_basic.yaml"))


def test_validate_scenario_passes_for_valid(monkeypatch):
    runner = ScenarioRunner()
    runner.driver = FakeDriver()
    scenario = runner._load_scenario(_scenario_path())

    assert runner.validate_scenario(scenario) == []


def test_validate_scenario_fails_for_unknown_option(monkeypatch):
    runner = ScenarioRunner()
    runner.driver = FakeDriver()
    scenario = runner._load_scenario(_scenario_path())
    scenario["options"] = {"missing": "x"}

    errors = runner.validate_scenario(scenario)
    assert any("Unknown option group" in e for e in errors)


def test_validate_scenario_fails_for_unknown_action(monkeypatch):
    runner = ScenarioRunner()
    runner.driver = FakeDriver()
    scenario = runner._load_scenario(_scenario_path())
    scenario["steps"][0]["action"] = "nope"

    errors = runner.validate_scenario(scenario)
    assert any("Unknown action" in e for e in errors)


def test_actor_violation_records_warning_not_exception(monkeypatch):
    runner = ScenarioRunner()
    runner.driver = FakeDriver()
    step = {"id": "s1", "actor": "student", "action": "trigger_memory_analysis", "params": {}}

    result = runner._replay_step(step)
    assert not result.success
    assert result.error


def test_full_run_example_basic(monkeypatch, tmp_path):
    runner = ScenarioRunner()
    runner.driver = FakeDriver()
    runner.config["sessions_dir"] = str(tmp_path)

    monkeypatch.setattr(runner, "_ensure_test_users", lambda setup: [])
    monkeypatch.setattr(runner, "_persist_run", lambda run_result: None)

    result = runner.run(_scenario_path())
    assert result.success
    assert result.assertions_passed == result.assertions_total
    assert Path(result.session_path).exists()




def test_run_sets_context_before_options(monkeypatch, tmp_path):
    runner = ScenarioRunner()
    runner.driver = FakeDriver()
    runner.config["sessions_dir"] = str(tmp_path)

    monkeypatch.setattr(runner, "_ensure_test_users", lambda setup: [])
    monkeypatch.setattr(runner, "_persist_run", lambda run_result: None)

    scenario = runner._load_scenario(_scenario_path())
    scenario["options"] = {"memory_backend": "memory"}
    scenario_path = tmp_path / "scenario_with_options.yaml"
    scenario_path.write_text(__import__("yaml").safe_dump(scenario), encoding="utf-8")

    result = runner.run(str(scenario_path))
    assert result.success

    event_types = [e.get("type") for e in runner.driver.get_session_events()]
    assert "context_switch" in event_types
    assert "option_switch" in event_types
    assert event_types.index("context_switch") < event_types.index("option_switch")

def test_step_error_does_not_abort_run(monkeypatch, tmp_path):
    runner = ScenarioRunner()
    runner.driver = FakeDriver()
    runner.config["sessions_dir"] = str(tmp_path)
    monkeypatch.setattr(runner, "_ensure_test_users", lambda setup: [])
    monkeypatch.setattr(runner, "_persist_run", lambda run_result: None)

    scenario = runner._load_scenario(_scenario_path())
    scenario["steps"][2]["params"]["explode"] = True
    tmp_file = tmp_path / "scenario.yaml"
    tmp_file.write_text(__import__("yaml").safe_dump(scenario), encoding="utf-8")

    result = runner.run(str(tmp_file))
    assert len(result.steps) == len(scenario["steps"])
    assert any(not step.success for step in result.steps)
    assert any(step.step_id == "s3" for step in result.steps)


def test_full_run_example_basic_uses_default_llm_when_missing(monkeypatch, tmp_path):
    runner = ScenarioRunner()
    runner.driver = FakeDriver()
    runner.config["sessions_dir"] = str(tmp_path)

    monkeypatch.setattr(runner, "_ensure_test_users", lambda setup: [])
    monkeypatch.setattr(runner, "_persist_run", lambda run_result: None)
    monkeypatch.setattr("modules.benchmarker.runner.get_current_llm_id", lambda: "mock-default")

    switched = {}
    monkeypatch.setattr("modules.benchmarker.runner.set_current_llm", lambda llm_id: switched.setdefault("llm", llm_id) or True)

    scenario = runner._load_scenario(_scenario_path())
    scenario.pop("llm", None)
    tmp_file = tmp_path / "scenario_no_llm.yaml"
    tmp_file.write_text(__import__("yaml").safe_dump(scenario), encoding="utf-8")

    result = runner.run(str(tmp_file))
    assert result.success
    assert switched["llm"] == "mock-default"
    context_events = [e for e in runner.driver.get_session_events() if e.get("type") == "context_switch"]
    assert any(e.get("data", {}).get("llm_id") == "mock-default" for e in context_events)


def test_injected_context_contains_passes(monkeypatch):
    runner = ScenarioRunner()
    runner.driver = FakeDriver()
    steps = [
        StepResult(
            step_id="s1",
            action="user_send_message",
            actor="student",
            success=True,
            result={
                "injected_contexts": [
                    {"source": "rag_mock", "content": "Document contains voss_index guidance", "role": "system"}
                ]
            },
        )
    ]

    out = runner._evaluate_assertions(
        [
            {
                "id": "a1",
                "type": "injected_context_contains",
                "params": {"step_id": "s1", "contains": "voss_index", "source_contains": "rag"},
            }
        ],
        steps,
    )

    assert out[0].passed is True


def test_injected_context_contains_fails_wrong_content():
    runner = ScenarioRunner()
    runner.driver = FakeDriver()
    steps = [
        StepResult(
            step_id="s1",
            action="user_send_message",
            actor="student",
            success=True,
            result={"injected_contexts": [{"source": "rag_mock", "content": "other text", "role": "system"}]},
        )
    ]

    out = runner._evaluate_assertions(
        [{"id": "a1", "type": "injected_context_contains", "params": {"step_id": "s1", "contains": "voss_index"}}],
        steps,
    )

    assert out[0].passed is False
    assert "does not contain 'voss_index'" in out[0].message


def test_injected_context_contains_fails_wrong_source():
    runner = ScenarioRunner()
    runner.driver = FakeDriver()
    steps = [
        StepResult(
            step_id="s1",
            action="user_send_message",
            actor="student",
            success=True,
            result={"injected_contexts": [{"source": "memory_mock", "content": "voss_index", "role": "system"}]},
        )
    ]

    out = runner._evaluate_assertions(
        [
            {
                "id": "a1",
                "type": "injected_context_contains",
                "params": {"step_id": "s1", "source_contains": "rag"},
            }
        ],
        steps,
    )

    assert out[0].passed is False
    assert "Sources present" in out[0].message


def test_injected_context_contains_no_contexts_captured():
    runner = ScenarioRunner()
    runner.driver = FakeDriver()
    steps = [
        StepResult(
            step_id="s1",
            action="user_send_message",
            actor="student",
            success=True,
            result={"injected_contexts": []},
        )
    ]

    out = runner._evaluate_assertions(
        [{"id": "a1", "type": "injected_context_contains", "params": {"step_id": "s1"}}],
        steps,
    )

    assert out[0].passed is False
    assert "No injected contexts captured" in out[0].message



def test_injected_context_contains_fails_on_rag_no_results_marker_even_if_contains_matches():
    runner = ScenarioRunner()
    runner.driver = FakeDriver()
    steps = [
        StepResult(
            step_id="s1",
            action="user_send_message",
            actor="student",
            success=True,
            result={
                "injected_contexts": [
                    {
                        "source": "rag_mock",
                        "content": "[WARNING] No RAG results found for query: Tuesday Sync",
                        "role": "system",
                    }
                ]
            },
        )
    ]

    out = runner._evaluate_assertions(
        [
            {
                "id": "a1",
                "type": "injected_context_contains",
                "params": {"step_id": "s1", "contains": "Tuesday Sync", "source_contains": "rag"},
            }
        ],
        steps,
    )

    assert out[0].passed is False
    assert "no rag results found" in out[0].message.lower()


def test_injected_context_contains_fails_on_rag_no_result_singular_marker():
    runner = ScenarioRunner()
    runner.driver = FakeDriver()
    steps = [
        StepResult(
            step_id="s1",
            action="user_send_message",
            actor="student",
            success=True,
            result={
                "injected_contexts": [
                    {
                        "source": "rag_context_callback_faiss_hierarchical",
                        "content": "[WARNING] No RAG result found for query: Also, who runs the Tuesday Sync?",
                        "role": "system",
                    }
                ]
            },
        )
    ]

    out = runner._evaluate_assertions(
        [
            {
                "id": "a1",
                "type": "injected_context_contains",
                "params": {"step_id": "s1", "contains": "Tuesday Sync", "source_contains": "rag"},
            }
        ],
        steps,
    )

    assert out[0].passed is False
    assert "no rag result found" in out[0].message.lower()


def test_injected_context_not_contains_passes_when_forbidden_text_absent():
    runner = ScenarioRunner()
    runner.driver = FakeDriver()
    steps = [
        StepResult(
            step_id="s1",
            action="user_send_message",
            actor="student",
            success=True,
            result={"injected_contexts": [{"source": "rag_mock", "content": "useful rag context", "role": "system"}]},
        )
    ]

    out = runner._evaluate_assertions(
        [
            {
                "id": "a1",
                "type": "injected_context_contains",
                "params": {"step_id": "s1", "source_contains": "rag", "not_contains": "forbidden"},
            }
        ],
        steps,
    )

    assert out[0].passed is True


def test_injected_context_not_contains_fails_when_forbidden_text_present():
    runner = ScenarioRunner()
    runner.driver = FakeDriver()
    steps = [
        StepResult(
            step_id="s1",
            action="user_send_message",
            actor="student",
            success=True,
            result={"injected_contexts": [{"source": "rag_mock", "content": "has forbidden token", "role": "system"}]},
        )
    ]

    out = runner._evaluate_assertions(
        [
            {
                "id": "a1",
                "type": "injected_context_contains",
                "params": {"step_id": "s1", "source_contains": "rag", "not_contains": "forbidden"},
            }
        ],
        steps,
    )

    assert out[0].passed is False
    assert "forbidden text 'forbidden'" in out[0].message

def test_injected_context_source_only():
    runner = ScenarioRunner()
    runner.driver = FakeDriver()
    steps = [
        StepResult(
            step_id="s1",
            action="user_send_message",
            actor="student",
            success=True,
            result={"injected_contexts": [{"source": "rag_mock", "content": "abc", "role": "system"}]},
        )
    ]

    out = runner._evaluate_assertions(
        [
            {
                "id": "a1",
                "type": "injected_context_contains",
                "params": {"step_id": "s1", "source_contains": "rag"},
            }
        ],
        steps,
    )

    assert out[0].passed is True


def test_validate_scenario_reports_unknown_option_group():
    runner = ScenarioRunner()
    runner.driver = FakeDriver()
    scenario = {
        "meta": {"name": "x"},
        "options": {"nonexistent_group": "foo"},
        "steps": [{"id": "s1", "actor": "student", "action": "user_send_message", "params": {}}],
    }

    errors = runner.validate_scenario(scenario)
    assert any("Unknown option group: nonexistent_group" in e for e in errors)


def test_validate_scenario_reports_unknown_action():
    runner = ScenarioRunner()
    runner.driver = FakeDriver()
    scenario = {
        "meta": {"name": "x"},
        "options": {},
        "steps": [{"id": "s1", "actor": "student", "action": "unknown_action", "params": {}}],
    }

    errors = runner.validate_scenario(scenario)
    assert any("Unknown action in step s1: unknown_action" in e for e in errors)


def test_validate_scenario_passes_with_all_registered():
    runner = ScenarioRunner()
    runner.driver = FakeDriver()
    scenario = {
        "meta": {"name": "x"},
        "options": {"memory_backend": "memory"},
        "steps": [
            {"id": "s1", "actor": "system", "action": "create_conversation", "params": {}},
            {"id": "s2", "actor": "student", "action": "user_send_message", "params": {}},
        ],
    }

    assert runner.validate_scenario(scenario) == []


def test_injected_context_source_alias_student_pad_matches_student_notes_callback():
    runner = ScenarioRunner()
    runner.driver = FakeDriver()
    steps = [
        StepResult(
            step_id="s1",
            action="user_send_message",
            actor="student",
            success=True,
            result={"injected_contexts": [{"source": "get_student_notes_context", "content": "some note", "role": "system"}]},
        )
    ]

    out = runner._evaluate_assertions(
        [
            {
                "id": "a1",
                "type": "injected_context_contains",
                "params": {"step_id": "s1", "source_contains": "student_pad"},
            }
        ],
        steps,
    )

    assert out[0].passed is True
