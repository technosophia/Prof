"""
Regression tests for RAG manager driver registration.

These tests verify that:
- on_module_activated() registers driver options (not inject_ui_initialize)
- The module works headless (no Streamlit)
- Legacy and new hook protocols both work
"""

import pytest
import copy

import modules.rag_manager as rag_module
from shared.common import get_driver, get_llm_manager
from shared.driver import DriverOptionError
from shared.module_handler import ServiceLocator


@pytest.fixture()
def reset_driver_and_llm_callbacks():
    driver = get_driver()
    llm_manager = get_llm_manager()

    # Snapshot
    saved_rag_flags = {
        "_RAG_OPTIONS_REGISTERED": rag_module._RAG_OPTIONS_REGISTERED,
        "_INITIALIZED": rag_module._INITIALIZED,
        "_ENGINE_CONTEXT_CALLBACKS": copy.deepcopy(rag_module._ENGINE_CONTEXT_CALLBACKS),
    }
    saved_driver = {
        "_options": copy.deepcopy(driver._options),
        "_active_options": copy.deepcopy(driver._active_options),
        "_actions": copy.deepcopy(driver._actions),
    }
    saved_llm = {
        "context_callbacks": copy.deepcopy(llm_manager.context_callbacks),
    }

    # Reset for isolated tests
    rag_module._RAG_OPTIONS_REGISTERED = False
    rag_module._INITIALIZED = False
    rag_module._ENGINE_CONTEXT_CALLBACKS = {}
    driver._options = {}
    driver._active_options = {}
    driver._actions = {}
    llm_manager.context_callbacks = []

    yield driver, llm_manager

    # Restore
    for k, v in saved_rag_flags.items():
        setattr(rag_module, k, v)
    for k, v in saved_driver.items():
        setattr(driver, k, v)
    for k, v in saved_llm.items():
        setattr(llm_manager, k, v)


def _registered_rag_engine_names(driver):
    options = driver.list_options()
    return [opt["name"] for opt in options.get("rag_engine", [])]


def test_rag_engine_options_registered(reset_driver_and_llm_callbacks):
    """initialize() registers rag_engine options in the driver."""
    driver, _ = reset_driver_and_llm_callbacks

    assert rag_module.initialize() is True

    options = driver.list_options()
    assert "rag_engine" in options
    assert len(options["rag_engine"]) >= 1


def test_on_module_activated_registers_options(reset_driver_and_llm_callbacks):
    """on_module_activated() with a ServiceLocator also registers driver options."""
    driver, _ = reset_driver_and_llm_callbacks

    services = ServiceLocator()
    # Don't provide config/user_manager — factory will be skipped,
    # initialize() will still run and register options.
    rag_module.on_module_activated(services)

    options = driver.list_options()
    assert "rag_engine" in options


def test_switch_to_each_registered_engine(reset_driver_and_llm_callbacks):
    driver, _ = reset_driver_and_llm_callbacks

    rag_module.initialize()
    for name in _registered_rag_engine_names(driver):
        driver.switch_option("rag_engine", name)
        assert driver.get_active_option("rag_engine") == name


def test_unsupported_engine_raises_driver_error(reset_driver_and_llm_callbacks):
    driver, _ = reset_driver_and_llm_callbacks

    rag_module.initialize()
    with pytest.raises(DriverOptionError):
        driver.switch_option("rag_engine", "nonexistent")


def test_rag_registers_no_actions(reset_driver_and_llm_callbacks):
    driver, _ = reset_driver_and_llm_callbacks

    rag_module.initialize()
    assert driver.list_actions() == []


def test_activate_registers_context_callback(reset_driver_and_llm_callbacks):
    driver, llm_manager = reset_driver_and_llm_callbacks

    rag_module.initialize()
    names = _registered_rag_engine_names(driver)
    assert names

    driver.switch_option("rag_engine", names[0])
    assert len(llm_manager.context_callbacks) == 1


def test_deactivate_unregisters_context_callback(reset_driver_and_llm_callbacks):
    driver, llm_manager = reset_driver_and_llm_callbacks

    rag_module.initialize()
    names = _registered_rag_engine_names(driver)
    if len(names) < 2:
        pytest.skip("Need at least 2 registered RAG engines for deactivate switch test")

    driver.switch_option("rag_engine", names[0])
    callback_for_first = llm_manager.context_callbacks[0]

    driver.switch_option("rag_engine", names[1])

    assert callback_for_first not in llm_manager.context_callbacks


def test_on_module_deactivated_clears_callbacks(reset_driver_and_llm_callbacks):
    """on_module_deactivated() removes all registered LLM callbacks."""
    driver, llm_manager = reset_driver_and_llm_callbacks

    rag_module.initialize()
    names = _registered_rag_engine_names(driver)
    assert names

    driver.switch_option("rag_engine", names[0])
    assert len(llm_manager.context_callbacks) == 1

    rag_module.on_module_deactivated()
    assert len(llm_manager.context_callbacks) == 0


def test_rag_ui_initialize_only_sets_session_state(monkeypatch):
    """
    inject_ui_initialize in the new architecture ONLY sets st.session_state.
    It must NOT call initialize_rag_manager() — that is done by on_module_activated.
    """
    import modules.rag_manager.rag_manager_ui as rag_ui

    # Patch st.session_state
    fake_state = {}
    monkeypatch.setattr(rag_ui.st, "session_state", fake_state, raising=False)

    result = rag_ui.inject_ui_initialize()

    assert result is True
    # Session state keys should be initialized
    assert 'rag_debug_enabled' in fake_state
    assert 'rag_injection_enabled' in fake_state
    assert 'last_rag_context' in fake_state


def test_module_handler_calls_on_module_activated_not_inject_ui_initialize():
    """
    ModuleHandler.toggle_module should call on_module_activated, NOT inject_ui_initialize.
    inject_ui_initialize is ui_registry's responsibility.
    """
    from shared.module_handler import ModuleHandler, ServiceLocator
    from unittest.mock import MagicMock, patch

    handler = ModuleHandler()
    handler.initialize()

    activated_calls = []
    ui_init_calls = []

    original_hook = handler._call_module_hook

    def spy_hook(module_name, hook_name, **kwargs):
        if hook_name == "on_module_activated":
            activated_calls.append(module_name)
        if hook_name == "inject_ui_initialize":
            ui_init_calls.append(module_name)
        # Don't actually call through to avoid side effects

    handler._call_module_hook = spy_hook

    # Simulate toggling a module (deactivate then activate to force the hook)
    if "rag_manager" in handler.active_modules:
        handler.active_modules.remove("rag_manager")

    handler.toggle_module("rag_manager", True)

    assert "rag_manager" in activated_calls
    assert "rag_manager" not in ui_init_calls
