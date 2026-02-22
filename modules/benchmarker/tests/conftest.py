"""Benchmarker test-local pytest bootstrap.

IMPORTANT: keep imports side-effect free at module import time so this conftest
cannot interfere with unrelated suites when benchmarker is present in testpaths.
"""

from __future__ import annotations

import logging
import os
import warnings

import pytest
from dotenv import load_dotenv


def _prepare_environment() -> None:
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
        message="Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.",
        category=UserWarning,
        module=r"streamlit\.runtime\.scriptrunner_utils\.script_run_context",
    )


def _initialize_modules():
    from shared.common import log
    from shared.module_handler import ModuleHandler

    handler = ModuleHandler()
    handler.initialize()

    active_modules = handler.get_active_modules()
    for module_name in active_modules:
        handler.load_module_ui(module_name)

    log("info", f"[benchmarker/tests] Active modules loaded: {active_modules}")
    return handler


def _initialize_ui_registry(handler) -> None:
    from shared.common import log
    from shared.ui_registry import UIRegistry

    ui_registry = UIRegistry()
    ui_registry.set_module_handler(handler)
    ui_registry.render_all("initialize")
    log("info", "[benchmarker/tests] UI registry initialize hooks executed")


def _reset_rag_for_integration() -> None:
    from modules.rag_manager import rag_manager
    from shared.cached import get_config, get_user_manager
    from shared.common import log

    cfg = get_config()
    classic_cfg = (cfg.get("modules.rag_manager", {}) or {}).get("engines", {}).get("classic", {})
    configured_threshold = classic_cfg.get("similarity_threshold", 0.3)

    classic_engine = rag_manager.get_engine("classic")
    if classic_engine is not None and hasattr(classic_engine, "similarity_threshold"):
        classic_engine.similarity_threshold = configured_threshold
        log("info", f"[benchmarker/tests] classic similarity_threshold set to {configured_threshold}")

    trainer = get_user_manager().get_user("master1")
    if trainer is not None:
        rag_manager.clear_all_documents(trainer["id"])
        log("info", "[benchmarker/tests] Cleared trainer RAG docs before integration run")


def _has_only_benchmarker_tests(session) -> bool:
    """Return True if ALL collected tests belong to the benchmarker suite."""
    return all(
        item.nodeid.startswith("modules/benchmarker/tests/")
        for item in session.items
    )


def _has_any_benchmarker_tests(session) -> bool:
    return any(
        item.nodeid.startswith("modules/benchmarker/tests/")
        for item in session.items
    )


@pytest.fixture(scope="session", autouse=True)
def _benchmarker_session_bootstrap(request):
    """
    Bootstrap for benchmarker tests.

    KEY DESIGN DECISION:
    When running alongside other test suites (e.g. BDD/Playwright tests that
    start a real Streamlit server against the shared tests/data/app.db), calling
    _initialize_modules() + _initialize_ui_registry() here causes module
    initialize hooks to run and mutate the shared database, corrupting the state
    that the Streamlit subprocess expects.

    Therefore we ONLY do the heavy module/UI initialization when the benchmarker
    is running in isolation. When mixed with other suites we do the minimum
    needed: environment prep + DB/user bootstrap.

    The integration_real_driver_setup fixture (used explicitly by
    test_runner_integration_real_driver.py) handles the per-test setup that
    the integration tests actually need.
    """
    if not _has_any_benchmarker_tests(request.session):
        return

    _prepare_environment()

    from shared.cached import get_config, get_db_manager, get_user_manager
    from shared.common import configure_logging_from_dict, init_database, init_user_manager, log

    cfg = get_config()

    if not cfg.get("llms.ollama_qwen.enabled", False):
        cfg.set("llms.ollama_qwen.enabled", True)
        log("info", "[benchmarker/tests] Enabled llms.ollama_qwen for benchmarker integration tests")

    configure_logging_from_dict(cfg.get("logging", {}))

    db = get_db_manager()
    if not db.is_initialized():
        db_cfg = cfg.get("database", {})
        db_url_or_path = db_cfg.get("url") or db_cfg.get("path")
        if db_url_or_path:
            init_database(use_memory=False, db_path=db_url_or_path)
        else:
            init_database(use_memory=False)
        log("info", "[benchmarker/tests] Database initialized in benchmarker session bootstrap")

    init_user_manager(create_default_users=True)
    get_user_manager()._create_default_users_fallback()
    log("info", "[benchmarker/tests] Default users ensured in benchmarker session bootstrap")

    # Only initialize modules/UI registry when running benchmarker tests alone.
    # In a mixed session, this corrupts shared DB state for other suites.
    if _has_only_benchmarker_tests(request.session):
        # Only initialize modules/UI registry when running benchmarker tests alone.
        # In a mixed session, this corrupts shared DB state (user options, RAG engine
        # registrations) that the Streamlit subprocess expects to own exclusively.
        has_non_benchmarker = any(
            not item.nodeid.startswith("modules/benchmarker/tests/")
            for item in request.session.items
        )
        if not has_non_benchmarker:
            handler = _initialize_modules()
            _initialize_ui_registry(handler)
        else:
            log("info", "[benchmarker/tests] Mixed session — skipping module init to protect shared DB state")
    else:
        log("info", "[benchmarker/tests] Mixed session detected — skipping module/UI "
                    "initialization to avoid corrupting shared DB state")


@pytest.fixture()
def integration_real_driver_setup():
    """
    Per-test setup for real-driver integration tests.

    Requested explicitly by test_runner_integration_real_driver.py.
    Handles module init here (safe: runs after all session fixtures, just
    before the specific test that needs it).
    """
    from shared.common import log, init_user_manager
    from shared.cached import get_db_manager, get_user_manager, get_config
    from shared.common import init_database

    cfg = get_config()
    db = get_db_manager()

    current_url = ""
    if getattr(db, "_engine", None) is not None:
        current_url = str(db._engine.url)

    if (not db.is_initialized()) or (":memory:" in current_url):
        db.dispose()
        db_cfg = cfg.get("database", {})
        db_url_or_path = db_cfg.get("url") or db_cfg.get("path")
        if db_url_or_path:
            init_database(use_memory=False, db_path=db_url_or_path)
        else:
            init_database(use_memory=False)
        log("info", "[benchmarker/tests] Reinitialized persistent test DB for integration run")

    init_user_manager(create_default_users=True)
    get_user_manager()._create_default_users_fallback()

    handler = _initialize_modules()

    # Force re-registration of rag_engine options. The reset_driver_and_llm_callbacks
    # fixture in rag_manager unit tests wipes driver._options in teardown, and the
    # guard flag prevents re-registration unless we reset it.
    import modules.rag_manager as _rag_module
    _rag_module._RAG_OPTIONS_REGISTERED = False
    _rag_module._INITIALIZED = False

    ui_registry = UIRegistry()
    ui_registry.set_module_handler(handler)
    ui_registry.render_all("initialize")
    log("info", "[real_driver] UI registry initialize hooks executed")
