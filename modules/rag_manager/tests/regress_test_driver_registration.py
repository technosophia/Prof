"""
TODO : makge regression in modules/benchmarker/tests/test_runner_integration_real_driver.py::test_full_run_real_driver_scenarios[full_nexoria]
"""

import pytest

import modules.rag_manager as rag_module
from shared.common import get_driver, get_llm_manager
from st_shared.driver import DriverOptionError


import copy

@pytest.fixture()
def reset_driver_and_llm_callbacks():
    driver = get_driver()
    llm_manager = get_llm_manager()

    # ── Snapshot ──────────────────────────────────────────────────────────
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

    # ── Reset for isolated tests  ──────────────────────────────────────────
    rag_module._RAG_OPTIONS_REGISTERED = False
    rag_module._INITIALIZED = False
    rag_module._ENGINE_CONTEXT_CALLBACKS = {}
    driver._options = {}
    driver._active_options = {}
    driver._actions = {}
    llm_manager.context_callbacks = []

    yield driver, llm_manager

    # ── Restore ───────────────────────────────────────────────────────────
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
    driver, _ = reset_driver_and_llm_callbacks

    assert rag_module.initialize() is True

    options = driver.list_options()
    assert "rag_engine" in options
    assert len(options["rag_engine"]) >= 1


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


def test_rag_ui_initialize_calls_rag_module_initialize(monkeypatch):
    import modules.rag_manager.rag_manager_ui as rag_ui

    called = {"count": 0}

    def fake_initialize():
        called["count"] += 1
        return True

    monkeypatch.setattr(rag_ui, "initialize_rag_manager", fake_initialize)
    monkeypatch.setitem(rag_ui.st.session_state, "rag_injection_enabled", False)

    assert rag_ui.inject_ui_initialize() is True
    assert called["count"] == 1
