"""Tests for benchmarker core actions."""

from unittest.mock import Mock

import pytest

from modules.benchmarker.core_actions import (
    action_create_conversation,
    action_set_training_program,
    action_switch_option,
    action_user_send_message,
)
from shared.common import get_driver
from shared.driver import DriverContext, DriverContextError


def test_create_conversation_returns_id(monkeypatch):
    driver = get_driver()
    driver.clear_context()

    class FakeConv:
        def create_conversation(self, user_id, title, metadata=None):
            return "conv-1"

    monkeypatch.setattr("modules.benchmarker.core_actions.get_conversation_manager", lambda: FakeConv())

    result = action_create_conversation(DriverContext(student_id="bench_student"), title="T")
    assert result["conversation_id"] == "conv-1"
    assert driver.get_context().conversation_id == "conv-1"


def test_create_conversation_requires_student_id():
    driver = get_driver()
    driver.register_action("create_conversation_test", action_create_conversation, required_context=["student_id"])
    driver.clear_context()

    with pytest.raises(DriverContextError):
        driver.do_action("create_conversation_test", title="x")


def test_user_send_message_requires_conversation():
    driver = get_driver()
    driver.register_action(
        "user_send_message_test",
        action_user_send_message,
        required_context=["student_id", "conversation_id"],
    )
    driver.clear_context()
    driver.set_context(student_id="bench_student")

    with pytest.raises(DriverContextError):
        driver.do_action("user_send_message_test", content="hello")


def test_set_training_program_saves_prompt(monkeypatch):
    saved = {}

    def fake_save_prompt(key, value):
        saved["key"] = key
        saved["value"] = value
        return True

    monkeypatch.setattr("modules.benchmarker.core_actions.save_prompt", fake_save_prompt)
    result = action_set_training_program(DriverContext(trainer_id="bench_trainer"), content="program")

    assert result == {"saved": True}
    assert saved["key"] == "trainer.teacher.training_program"


def test_switch_option_delegates_to_driver(monkeypatch):
    mock_driver = Mock()
    mock_driver.get_active_option.return_value = "memory"
    monkeypatch.setattr("modules.benchmarker.core_actions.get_driver", lambda: mock_driver)

    result = action_switch_option(DriverContext(), group="memory_backend", name="pedagogical_memory")

    mock_driver.switch_option.assert_called_once_with("memory_backend", "pedagogical_memory")
    assert result["previous"] == "memory"
