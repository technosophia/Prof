"""Benchmarker test-local pytest bootstrap.

Ensures database and default users are available even when running only
`modules/benchmarker/tests/...` directly (without collecting top-level tests/).
"""

from __future__ import annotations

from shared.cached import get_config, get_db_manager, get_user_manager
from shared.common import init_database, log


def pytest_configure(config):
    """Initialize DB and default users for benchmarker test runs if needed."""
    db = get_db_manager()
    if not db.is_initialized():
        db_cfg = get_config().get("database", {})
        db_url_or_path = db_cfg.get("url") or db_cfg.get("path")
        if db_url_or_path:
            init_database(use_memory=False, db_path=db_url_or_path)
        else:
            init_database(use_memory=False)
        log("info", "[benchmarker/tests] Database initialized in pytest_configure")

    # Ensure baseline fixture users are present (master1, normal2_m1, ...)
    get_user_manager()._create_default_users_fallback()
    log("info", "[benchmarker/tests] Default users ensured in pytest_configure")
