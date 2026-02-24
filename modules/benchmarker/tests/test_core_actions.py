"""Tests for benchmarker core actions."""

from unittest.mock import Mock

import pytest

from modules.benchmarker.core_actions import (
    action_create_conversation,
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



def test_switch_option_delegates_to_driver(monkeypatch):
    mock_driver = Mock()
    mock_driver.get_active_option.return_value = "memory"
    monkeypatch.setattr("modules.benchmarker.core_actions.get_driver", lambda: mock_driver)

    result = action_switch_option(DriverContext(), group="memory_backend", name="pedagogical_memory")

    mock_driver.switch_option.assert_called_once_with("memory_backend", "pedagogical_memory")
    assert result["previous"] == "memory"


def test_user_send_message_captures_injected_contexts(monkeypatch):
    class FakeMsg:
        def __init__(self, role, content):
            self.role = role
            self.content = content

        def to_dict(self):
            return {"role": self.role, "content": self.content}

    class FakeConversation:
        def __init__(self):
            self.messages = [FakeMsg("user", "history")]

    class FakeConversationManager:
        def __init__(self):
            self.added = []

        def get_conversation(self, conversation_id, include_messages=False):
            return FakeConversation()

        def add_message(self, conversation_id, message):
            self.added.append((conversation_id, message))

    class FakeLLMManager:
        def __init__(self):
            self._monitor_callbacks = []

        def register_monitor_callback(self, callback):
            self._monitor_callbacks.append(callback)

        def unregister_monitor_callback(self, callback):
            self._monitor_callbacks.remove(callback)

    fake_conv = FakeConversationManager()
    fake_llm = FakeLLMManager()

    monkeypatch.setattr("modules.benchmarker.core_actions.get_conversation_manager", lambda: fake_conv)
    monkeypatch.setattr("shared.common.get_llm_manager", lambda: fake_llm)

    async def fake_generate(message, conversation_history=None, user_id=None):
        for cb in list(fake_llm._monitor_callbacks):
            cb(
                {
                    "messages": [
                        {"role": "system", "content": "RAG contains voss_index", "source": "rag_mock"},
                        {"role": "user", "content": message},
                    ]
                }
            )
        return "ok"

    monkeypatch.setattr("modules.benchmarker.core_actions.llm_conversation_generate", fake_generate)

    result = action_user_send_message(
        DriverContext(student_id="bench_student", conversation_id="conv-1"),
        content="hello",
    )

    assert result["injected_contexts"]
    assert result["injected_contexts"][0]["source"] == "rag_mock"
    assert "voss_index" in result["injected_contexts"][0]["content"]


def test_user_send_message_no_contexts_returns_empty_list(monkeypatch):
    class FakeMsg:
        def __init__(self, role, content):
            self.role = role
            self.content = content

        def to_dict(self):
            return {"role": self.role, "content": self.content}

    class FakeConversation:
        def __init__(self):
            self.messages = [FakeMsg("user", "history")]

    class FakeConversationManager:
        def get_conversation(self, conversation_id, include_messages=False):
            return FakeConversation()

        def add_message(self, conversation_id, message):
            return None

    class FakeLLMManager:
        def __init__(self):
            self._monitor_callbacks = []

        def register_monitor_callback(self, callback):
            self._monitor_callbacks.append(callback)

        def unregister_monitor_callback(self, callback):
            self._monitor_callbacks.remove(callback)

    fake_llm = FakeLLMManager()
    monkeypatch.setattr("modules.benchmarker.core_actions.get_conversation_manager", lambda: FakeConversationManager())
    monkeypatch.setattr("shared.common.get_llm_manager", lambda: fake_llm)

    async def fake_generate(message, conversation_history=None, user_id=None):
        return "ok"

    monkeypatch.setattr("modules.benchmarker.core_actions.llm_conversation_generate", fake_generate)

    result = action_user_send_message(
        DriverContext(student_id="bench_student", conversation_id="conv-1"),
        content="hello",
    )

    assert result["injected_contexts"] == []


def test_monitor_callback_always_unregistered(monkeypatch):
    class FakeMsg:
        def __init__(self, role, content):
            self.role = role
            self.content = content

        def to_dict(self):
            return {"role": self.role, "content": self.content}

    class FakeConversation:
        def __init__(self):
            self.messages = [FakeMsg("user", "history")]

    class FakeConversationManager:
        def get_conversation(self, conversation_id, include_messages=False):
            return FakeConversation()

        def add_message(self, conversation_id, message):
            return None

    class FakeLLMManager:
        def __init__(self):
            self._monitor_callbacks = []

        def register_monitor_callback(self, callback):
            self._monitor_callbacks.append(callback)

        def unregister_monitor_callback(self, callback):
            self._monitor_callbacks.remove(callback)

    fake_llm = FakeLLMManager()
    monkeypatch.setattr("modules.benchmarker.core_actions.get_conversation_manager", lambda: FakeConversationManager())
    monkeypatch.setattr("shared.common.get_llm_manager", lambda: fake_llm)

    async def fake_generate(message, conversation_history=None, user_id=None):
        raise RuntimeError("boom")

    monkeypatch.setattr("modules.benchmarker.core_actions.llm_conversation_generate", fake_generate)

    with pytest.raises(RuntimeError):
        action_user_send_message(
            DriverContext(student_id="bench_student", conversation_id="conv-1"),
            content="hello",
        )

    assert fake_llm._monitor_callbacks == []
