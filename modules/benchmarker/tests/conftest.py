"""Benchmarker test-local pytest bootstrap.

Ensures app-like initialization when running only `modules/benchmarker/tests/...`.
"""

from __future__ import annotations

import os
from dotenv import load_dotenv

# Must happen before shared imports/config loading.
load_dotenv()
os.environ.setdefault("TEST_MODE", "true")

from shared.cached import get_config, get_db_manager, get_user_manager
from shared.common import configure_logging_from_dict, init_database, init_user_manager, log
from shared.module_handler import ModuleHandler


def _initialize_modules() -> None:
    handler = ModuleHandler()
    handler.initialize()
    active_modules = handler.get_active_modules()
    log("info", f"[benchmarker/tests] Active modules loaded: {active_modules}")


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

    _initialize_modules()
