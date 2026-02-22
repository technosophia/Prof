"""Benchmarker test-local pytest bootstrap.

Ensures app-like initialization when running only `modules/benchmarker/tests/...`.
"""

from __future__ import annotations

import os
import logging
import warnings
from dotenv import load_dotenv

# Must happen before shared imports/config loading.
load_dotenv()
os.environ.setdefault("TEST_MODE", "true")

# Reduce Streamlit bare-mode logger noise during pytest runs.
_streamlit_ctx_logger = logging.getLogger("streamlit.runtime.scriptrunner_utils.script_run_context")
_streamlit_ctx_logger.setLevel(logging.ERROR)
_streamlit_ctx_logger.disabled = True

_streamlit_state_logger = logging.getLogger("streamlit.runtime.state.session_state_proxy")
_streamlit_state_logger.setLevel(logging.ERROR)
_streamlit_state_logger.disabled = True

# Silence known Streamlit bare-mode warning noise in pytest runs.
warnings.filterwarnings(
    "ignore",
    message="Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.",
    category=UserWarning,
    module=r"streamlit\.runtime\.scriptrunner_utils\.script_run_context",
)

from shared.cached import get_config, get_db_manager, get_user_manager
from shared.common import configure_logging_from_dict, init_database, init_user_manager, log
from shared.module_handler import ModuleHandler
from shared.ui_registry import UIRegistry


def _initialize_modules() -> ModuleHandler:
    handler = ModuleHandler()
    handler.initialize()

    # Mirror prof.py behavior: actively load each module UI package first.
    active_modules = handler.get_active_modules()
    for module_name in active_modules:
        handler.load_module_ui(module_name)

    log("info", f"[benchmarker/tests] Active modules loaded: {active_modules}")
    return handler


def _initialize_ui_registry(handler: ModuleHandler) -> None:
    # Mirror prof.py flow where UI registry triggers module initialize hooks.
    ui_registry = UIRegistry()
    ui_registry.set_module_handler(handler)
    ui_registry.render_all("initialize")
    log("info", "[benchmarker/tests] UI registry initialize hooks executed")


def pytest_configure(config):
    """Initialize app prerequisites for benchmarker tests."""
    cfg = get_config()

    # Keep test config behavior, but ensure ollama_qwen is available for ollama-marked integration tests.
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
        log("info", "[benchmarker/tests] Database initialized in pytest_configure")

    init_user_manager(create_default_users=True)
    get_user_manager()._create_default_users_fallback()
    log("info", "[benchmarker/tests] Default users ensured in pytest_configure")

    handler = _initialize_modules()
    _initialize_ui_registry(handler)
