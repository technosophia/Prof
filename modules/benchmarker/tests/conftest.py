"""Benchmarker test helpers.

Design goal: keep setup explicit and isolated so benchmarker integration tests
cannot leak global app state into the rest of the pytest session.
"""

from __future__ import annotations

import copy
import logging
import os
from unittest.mock import MagicMock
import warnings

import pytest
from dotenv import load_dotenv


BENCHMARKER_NODE_PREFIX = "modules/benchmarker/tests/"


def pytest_collection_modifyitems(items):
    """Tag benchmarker tests for selective runs/debugging."""
    for item in items:
        if item.nodeid.startswith(BENCHMARKER_NODE_PREFIX):
            item.add_marker("benchmarker")


def _prepare_environment() -> None:
    """Prepare environment without importing app modules at import-time."""
    load_dotenv()
    os.environ.setdefault("TEST_MODE", "true")

    streamlit_ctx_logger = logging.getLogger("streamlit.runtime.scriptrunner_utils.script_run_context")
    streamlit_ctx_logger.setLevel(logging.ERROR)
    streamlit_ctx_logger.disabled = True

    streamlit_state_logger = logging.getLogger("streamlit.runtime.state.session_state_proxy")
    streamlit_state_logger.setLevel(logging.ERROR)
    streamlit_state_logger.disabled = True

    warnings.filterwarnings(
        "ignore",
        message=(
            "Thread 'MainThread': missing ScriptRunContext! "
            "This warning can be ignored when running in bare mode."
        ),
        category=UserWarning,
        module=r"streamlit\.runtime\.scriptrunner_utils\.script_run_context",
    )


@pytest.fixture(scope="session")
def benchmarker_test_env():
    """Minimal environment fixture for benchmarker tests."""
    _prepare_environment()


@pytest.fixture()
def integration_real_driver_setup(benchmarker_test_env):
    """Run real-driver benchmarker tests in an isolated app state.

    This fixture deliberately snapshots and restores mutable global singletons
    (driver registrations/context and module init flags) so it cannot interfere
    with non-benchmarker suites collected in the same pytest session.
    """
    import modules.benchmarker as benchmarker_module
    import modules.rag_manager as rag_module
    from shared.cached import get_config, get_db_manager, get_user_manager
    from shared.common import get_driver, init_database, init_user_manager, log
    from shared.module_handler import ModuleHandler
    from shared.ui_registry import UIRegistry

    driver = get_driver()
    driver_options_before = copy.deepcopy(driver._options)
    driver_actions_before = copy.deepcopy(driver._actions)
    driver_active_before = copy.deepcopy(driver._active_options)
    driver_context_before = copy.deepcopy(driver._context)
    driver_events_before = copy.deepcopy(driver._session_events)
    driver_meta_before = copy.deepcopy(driver._session_meta)

    benchmarker_flags_before = {
        "_INITIALIZED": benchmarker_module._INITIALIZED,
        "_ACTIONS_REGISTERED": benchmarker_module._ACTIONS_REGISTERED,
        "_LLM_OPTIONS_REGISTERED": benchmarker_module._LLM_OPTIONS_REGISTERED,
    }
    rag_flags_before = {
        "_INITIALIZED": rag_module._INITIALIZED,
        "_RAG_OPTIONS_REGISTERED": rag_module._RAG_OPTIONS_REGISTERED,
    }

    cfg = get_config()
    ollama_qwen_enabled_before = cfg.get("llms.ollama_qwen.enabled", False)
    cfg.set("llms.ollama_qwen.enabled", True)

    db = get_db_manager()
    if not db.is_initialized():
        db_cfg = cfg.get("database", {})
        db_url_or_path = db_cfg.get("url") or db_cfg.get("path")
        if db_url_or_path:
            init_database(use_memory=False, db_path=db_url_or_path)
        else:
            init_database(use_memory=False)

    # Avoid re-initializing the user manager in mixed suites where another
    # module test may temporarily mock database internals. We only backfill
    # default users if the manager is real and master1 is missing.
    user_manager = get_user_manager()
    user_manager_db = getattr(user_manager, "db", None)
    if not isinstance(user_manager, MagicMock) and not isinstance(user_manager_db, MagicMock):
        if user_manager.get_user("master1") is None:
            init_user_manager(create_default_users=True)
            user_manager._create_default_users_fallback()

    # Re-run module initialize hooks for this integration test only.
    benchmarker_module._INITIALIZED = False
    benchmarker_module._ACTIONS_REGISTERED = False
    benchmarker_module._LLM_OPTIONS_REGISTERED = False
    rag_module._INITIALIZED = False
    rag_module._RAG_OPTIONS_REGISTERED = False

    handler = ModuleHandler()
    handler.initialize()
    for module_name in handler.get_active_modules():
        handler.load_module_ui(module_name)

    ui_registry = UIRegistry()
    ui_registry.set_module_handler(handler)
    ui_registry.render_all("initialize")
    log("info", "[benchmarker/tests] isolated integration setup complete")

    try:
        yield
    finally:
        # Restore mutable global state so benchmarker integration test cannot leak.
        driver._options = driver_options_before
        driver._actions = driver_actions_before
        driver._active_options = driver_active_before
        driver._context = driver_context_before
        driver._session_events = driver_events_before
        driver._session_meta = driver_meta_before

        cfg.set("llms.ollama_qwen.enabled", ollama_qwen_enabled_before)

        benchmarker_module._INITIALIZED = benchmarker_flags_before["_INITIALIZED"]
        benchmarker_module._ACTIONS_REGISTERED = benchmarker_flags_before["_ACTIONS_REGISTERED"]
        benchmarker_module._LLM_OPTIONS_REGISTERED = benchmarker_flags_before["_LLM_OPTIONS_REGISTERED"]
        rag_module._INITIALIZED = rag_flags_before["_INITIALIZED"]
        rag_module._RAG_OPTIONS_REGISTERED = rag_flags_before["_RAG_OPTIONS_REGISTERED"]
