from uuid import uuid4

import pytest

from modules.benchmarker import initialize
from modules.benchmarker.core_actions import (
    action_create_conversation,
    action_set_training_program,
)
from modules.benchmarker.runner import ScenarioRunner
from shared.driver import DriverContextError
from shared.common import get_driver, get_user_manager


@pytest.fixture
def benchmark_context_ids():
    user_manager = get_user_manager()
    trainer_name = f"trainer_{uuid4().hex[:8]}"
    student_name = f"student_{uuid4().hex[:8]}"

    trainer_id, _ = user_manager.create_user(name=trainer_name, role="master")
    student_id, _ = user_manager.create_user(name=student_name, role="normal", parent_id=trainer_id)
    return trainer_id, student_id


@pytest.fixture
def initialized_driver(benchmark_context_ids):
    initialize()
    driver = get_driver()
    driver.start_session("test_benchmarker")
    driver.clear_context()
    trainer_id, student_id = benchmark_context_ids
    driver.set_context(trainer_id=trainer_id, student_id=student_id)
    return driver


def test_create_conversation_sets_context(benchmark_context_ids):
    _, student_id = benchmark_context_ids
    context = get_driver().get_context()
    context.student_id = student_id

    result = action_create_conversation(context, title="Test benchmark")

    assert result["created"] is True
    assert result["conversation_id"]
    assert context.conversation_id == result["conversation_id"]


def test_user_send_message_requires_conversation(initialized_driver):
    with pytest.raises(DriverContextError):
        initialized_driver.do_action("user_send_message", content="Hello")


def test_actor_validation_warns_on_wrong_actor(initialized_driver, monkeypatch):
    logs = []

    def fake_log(level, message, *args, **kwargs):
        logs.append((level, message))

    monkeypatch.setattr("modules.benchmarker.runner.log", fake_log)

    runner = ScenarioRunner(driver=initialized_driver)
    scenario = {
        "name": "invalid_actor_action",
        "steps": [
            {
                "id": "s1",
                "actor": "student",
                "action": "trigger_memory_analysis",
                "params": {},
            }
        ],
    }

    validation_errors = runner.validate_scenario(scenario)
    run_result = runner.run(scenario)

    assert validation_errors
    assert run_result["steps"][0]["status"] == "error"
    assert "cannot execute action" in run_result["steps"][0]["error"]
    assert any(level == "warning" for level, _ in logs)


def test_set_training_program(initialized_driver, monkeypatch):
    captured = {}

    def fake_save_prompt(key, value, language=None):
        captured["key"] = key
        captured["value"] = value
        captured["language"] = language
        return True

    monkeypatch.setattr("modules.benchmarker.core_actions.save_prompt", fake_save_prompt)

    result = action_set_training_program(
        initialized_driver.get_context(),
        content="Recursion requires a base case.",
    )

    assert result == {"saved": True}
    assert captured["key"] == "trainer.teacher.training_program"
    assert captured["value"] == "Recursion requires a base case."
