"""Tests for benchmarker scenario runner."""

from pathlib import Path

import pytest

from modules.benchmarker.runner import ScenarioRunner


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
