# modules/demo/tests/test_demo.py
"""
Tests for the demo module.

Uses the project's standard test harness (root conftest.py), which:
  - calls register_all_services() → all shared managers are live
  - initialises a real DB with default users
  - calls module_handler.activate_all() → on_module_activated() has fired

We use real services directly. No patching of shared.common needed.
Business logic functions accept their managers as arguments, so they are
called exactly as they would be in production.

Regression pattern:
  Every symbol imported from shared.common appears in TestSharedCommonAPIContract.
  A rename in shared breaks that test immediately — caught before runtime.
"""

import pytest
from shared.common import (
    get_user_manager,
    get_conversation_manager,
    get_llm_manager,
    get_prompt_manager,
    register_llm_context_callback,
    unregister_llm_context_callback,
    register_user_message_callback,
    unregister_user_message_callback,
    register_option,
    register_action,
    record_plugin_event,
    get_driver,
    get_user_settings_manager,
    UserRole,
)
from st_shared.cached import get_config
from modules.demo.demo_core import (
    get_demo_config_value,
    get_demo_translation,
    get_demo_prompt,
    list_users,
    get_user,
    list_user_conversations,
    get_conversation_messages,
    create_conversation,
    send_user_message,
    check_services,
    EXPECTED_SERVICES,
    demo_on_module_activated,
    demo_on_module_deactivated,
    _demo_context_provider,
)


# ─── Regression: shared.common API contract ───────────────────────────────────

class TestSharedCommonAPIContract:
    """Fail fast if shared.common renames or removes an API used by this module."""

    def test_user_manager_callable(self):
        assert callable(get_user_manager)

    def test_conversation_manager_callable(self):
        assert callable(get_conversation_manager)

    def test_llm_manager_callable(self):
        assert callable(get_llm_manager)

    def test_prompt_manager_callable(self):
        assert callable(get_prompt_manager)

    def test_user_settings_manager_callable(self):
        assert callable(get_user_settings_manager)

    def test_driver_callable(self):
        assert callable(get_driver)

    def test_user_role_importable(self):
        assert UserRole is not None

    def test_llm_callbacks_callable(self):
        assert callable(register_llm_context_callback)
        assert callable(unregister_llm_context_callback)

    def test_conversation_callbacks_callable(self):
        assert callable(register_user_message_callback)
        assert callable(unregister_user_message_callback)

    def test_driver_functions_callable(self):
        assert callable(register_option)
        assert callable(register_action)
        assert callable(record_plugin_event)


# ─── Infrastructure ────────────────────────────────────────────────────────────

class TestInfrastructure:

    def test_config_value_is_loaded(self):
        """
        modules.demo.greeting must be present in config.
        If this fails, check that config.json auto-loading works for this module
        (the core/config.py walk must reach modules/demo/config.json).
        """
        cfg = get_config()
        value = get_demo_config_value(cfg)
        assert value != "⚠ CONFIG NOT LOADED", (
            "Config key 'modules.demo.greeting' not found. "
            "Verify config.json is in modules/demo/ and the config loader walks that path."
        )
        assert isinstance(value, str) and len(value) > 0

    def test_translation_function_receives_correct_key(self):
        """Translation function is called with the correct dot-notation key."""
        received_keys = []
        def spy_translate(key, lang=None):
            received_keys.append(key)
            return f"t:{key}"
        get_demo_translation(spy_translate, "demo.check_translation")
        assert "demo.check_translation" in received_keys

    def test_translation_sentinel_detected(self):
        """Missing key returns the system sentinel '[key]', not an empty string."""
        def missing_translate(key, lang=None):
            return f"[{key}]"
        result = get_demo_translation(missing_translate, "demo.nonexistent")
        assert result == "[demo.nonexistent]"

    def test_prompt_is_loaded(self):
        """demo.system prompt must be present in prompt.en.yml."""
        pm = get_prompt_manager()
        result = get_demo_prompt(pm)
        assert result != "⚠ PROMPT NOT LOADED", (
            "Prompt 'demo.system' not found. "
            "Verify prompt.en.yml is in modules/demo/ and the prompt loader scans that path."
        )
        assert isinstance(result, str) and len(result) > 0


# ─── Users ────────────────────────────────────────────────────────────────────

class TestUsers:

    def test_list_returns_at_least_default_users(self):
        users = list_users(get_user_manager())
        assert isinstance(users, list)
        assert len(users) > 0

    def test_user_dicts_have_required_fields(self):
        users = list_users(get_user_manager())
        for u in users:
            assert "id" in u and isinstance(u["id"], str)
            assert "username" in u and isinstance(u["username"], str)
            assert "role" in u and isinstance(u["role"], str)

    def test_get_user_found(self):
        um = get_user_manager()
        users = list_users(um)
        assert users, "Need at least one user"
        result = get_user(um, users[0]["id"])
        assert result is not None
        assert result["id"] == users[0]["id"]

    def test_get_user_nonexistent_returns_none(self):
        result = get_user(get_user_manager(), "nonexistent_id_xyz_987")
        assert result is None


# ─── Conversations ────────────────────────────────────────────────────────────

class TestConversations:

    def _first_user_id(self):
        users = list_users(get_user_manager())
        assert users, "Need at least one user"
        return users[0]["id"]

    def test_create_conversation_returns_string_id(self):
        cm = get_conversation_manager()
        conv_id = create_conversation(cm, self._first_user_id(), "Test conv")
        assert isinstance(conv_id, str) and len(conv_id) > 0

    def test_created_conversation_appears_in_list(self):
        cm = get_conversation_manager()
        uid = self._first_user_id()
        create_conversation(cm, uid, "Listed conv")
        convs = list_user_conversations(cm, uid)
        assert isinstance(convs, list)
        assert any(c["title"] == "Listed conv" for c in convs)

    def test_conversation_dicts_have_required_fields(self):
        cm = get_conversation_manager()
        uid = self._first_user_id()
        create_conversation(cm, uid, "Fields test")
        convs = list_user_conversations(cm, uid)
        for c in convs:
            assert "id" in c and isinstance(c["id"], str)
            assert "title" in c
            assert "message_count" in c and isinstance(c["message_count"], int)

    def test_send_and_read_message(self):
        cm = get_conversation_manager()
        uid = self._first_user_id()
        conv_id = create_conversation(cm, uid, "Message conv")
        assert conv_id, "create_conversation must return a non-empty string"

        send_user_message(cm, conv_id, "Hello from demo test")
        messages = get_conversation_messages(cm, conv_id)

        assert len(messages) >= 1
        assert any(m["content"] == "Hello from demo test" for m in messages)
        for m in messages:
            assert "role" in m and "content" in m


# ─── LLM context provider ─────────────────────────────────────────────────────

class TestLLMContextProvider:

    def test_returns_three_string_tuple(self):
        result = _demo_context_provider("msg", [])
        assert isinstance(result, tuple) and len(result) == 3
        assert all(isinstance(s, str) for s in result)

    def test_register_unregister_does_not_raise(self):
        def dummy(msg, hist): return ("", "", "")
        register_llm_context_callback(dummy)
        unregister_llm_context_callback(dummy)


# ─── Services introspection ───────────────────────────────────────────────────

class TestServicesIntrospection:

    def test_all_expected_services_present(self):
        """
        All expected services must be available after register_all_services().
        If this fails, a service was not registered in st_shared/cached.py.
        """
        from shared.module_handler import module_handler
        services = module_handler.get_services()
        assert services is not None, (
            "ServiceLocator is None — register_all_services() must be called "
            "before tests (done in conftest.py pytest_sessionstart)."
        )
        status = check_services(services)
        missing = [name for name, ok in status.items() if not ok]
        assert not missing, f"Missing services in ServiceLocator: {missing}"

    def test_expected_services_covers_core_set(self):
        """EXPECTED_SERVICES must include the minimum core services."""
        core = {"config", "user_manager", "conversation_manager", "llm_manager", "prompt_manager"}
        assert core.issubset(set(EXPECTED_SERVICES))


# ─── Module lifecycle ──────────────────────────────────────────────────────────

class TestModuleLifecycle:

    def test_on_module_activated_does_not_raise(self):
        from shared.module_handler import module_handler
        services = module_handler.get_services()
        # May already be activated — must not raise even when called again
        try:
            demo_on_module_activated(services)
        except Exception as e:
            pytest.fail(f"demo_on_module_activated raised unexpectedly: {e}")

    def test_on_module_deactivated_does_not_raise(self):
        try:
            demo_on_module_deactivated()
        except Exception as e:
            pytest.fail(f"demo_on_module_deactivated raised unexpectedly: {e}")
