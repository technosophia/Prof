# conftest.py
"""
Pytest configuration and fixtures for all tests.

Module initialisation (two phases)
-----------------------------------
Phase 1 — Functional (headless):
    module_handler.initialize() calls on_module_activated() on every active
    NEW-STYLE module. Driver options and LLM callbacks are registered here,
    no Streamlit context required.

Phase 2 — Legacy inject_ui_initialize() (headless-tolerant):
    OLD-STYLE modules that have not yet been migrated to on_module_activated()
    still register their driver options/actions inside inject_ui_initialize().
    We call this for each module, swallowing Streamlit errors (st.session_state
    writes fail headless, but the functional registrations happen first and are
    NOT rolled back on exception).

    This phase must remain until every module has been migrated.
    See MIGRATE.md for the migration checklist.

Structure:
  - Logging
  - Path / DB helpers
  - Session hooks  (pytest_sessionstart / pytest_sessionfinish)
  - Session-scoped fixtures
  - Function-scoped fixtures
  - Markers
"""

import atexit  # noqa: F401 – kept for future use
import copy
import logging
import os
import re
import signal
import subprocess
import sys
import time
import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch  # noqa: F401

import pytest
import requests
from playwright.sync_api import sync_playwright

# ---------------------------------------------------------------------------
# 0.  Silence noisy third-party warnings ONCE
# ---------------------------------------------------------------------------
from core.database import init_database

_SILENCED_WARNINGS = [
    ("ignore", UserWarning,        "streamlit.runtime.scriptrunner_utils"),
    ("ignore", UserWarning,        "streamlit.runtime.state.session_state_proxy"),
    ("ignore", UserWarning,        r"torch\.cuda"),
    ("ignore", DeprecationWarning, None),
]
for action, category, module in _SILENCED_WARNINGS:
    kw = {"category": category}
    if module:
        kw["module"] = module
    warnings.filterwarnings(action, **kw)

warnings.filterwarnings(
    "ignore",
    message="Thread 'MainThread': missing ScriptRunContext!",
    category=UserWarning,
)

for logger_name in (
    "streamlit",
    "streamlit.runtime",
    "streamlit.runtime.scriptrunner_utils",
    "streamlit.runtime.scriptrunner_utils.script_run_context",
    "streamlit.runtime.state",
    "streamlit.runtime.state.session_state_proxy",
):
    _logger = logging.getLogger(logger_name)
    _logger.handlers.clear()
    _logger.propagate = False
    _logger.disabled = True
    _logger.setLevel(logging.CRITICAL)


# ---------------------------------------------------------------------------
# 1.  Load .env BEFORE any shared imports
# ---------------------------------------------------------------------------
from dotenv import load_dotenv
load_dotenv()


# ---------------------------------------------------------------------------
# 2.  Path setup
# ---------------------------------------------------------------------------
_CONFTEST_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = (
    _CONFTEST_DIR
    if (_CONFTEST_DIR / "prof.py").exists()
    else _CONFTEST_DIR.parent
)
sys.path.insert(0, str(PROJECT_ROOT))
os.environ["PYTHONPATH"] = str(PROJECT_ROOT)
os.environ["TEST_MODE"] = "true"
os.environ["PLAYWRIGHT_ASYNCIO"] = "0"

TEST_PORT = 8505
_BROWSER_SCOPE = "module"


# ---------------------------------------------------------------------------
# 3.  Shared imports (after path + .env are ready)
# ---------------------------------------------------------------------------
from st_shared.cached import get_config, get_db_manager, get_user_manager
from st_shared.cached import get_db_manager, get_user_manager, get_conversation_manager
from st_shared.cached import get_prompt_manager, get_llm_manager

from shared.common import init_user_manager
from shared.module_handler import ModuleHandler, module_handler
from shared.ui_registry import UIRegistry
from modules.rag_manager import rag_manager
from core.logging import log, set_log_module_level, configure_logging_from_dict

configure_logging_from_dict(get_config().get("logging", {}))

log("debug", f"Python path  : {sys.path}")
log("debug", f"Conftest dir : {_CONFTEST_DIR}")
log("debug", f"Project root : {PROJECT_ROOT}")
log("debug", f"prof.py found: {(PROJECT_ROOT / 'prof.py').exists()}")


# ---------------------------------------------------------------------------
# 5.  Database helpers
# ---------------------------------------------------------------------------
def _extract_sqlite_path(db_url_or_path: str) -> str:
    if not db_url_or_path or not isinstance(db_url_or_path, str):
        return db_url_or_path
    match = re.match(r"^sqlite:///(.+)$", db_url_or_path)
    if not match:
        return db_url_or_path
    file_path = match.group(1)
    if file_path.startswith("/") and len(file_path) > 2 and file_path[2] == ":":
        file_path = file_path[1:]
    return file_path


def _get_db_paths() -> tuple[str, str]:
    config = get_config()
    db_config = config.get("database", {})
    raw = db_config.get("url") or db_config.get("path", ".")
    file_path = _extract_sqlite_path(raw)
    if os.path.isdir(file_path) or not file_path.endswith(".db"):
        return file_path, os.path.join(file_path, "app.db")
    return os.path.dirname(file_path), file_path


def _db_url() -> str:
    config = get_config()
    db_config = config.get("database", {})
    return db_config.get("url") or db_config.get("path", ".")


def _init_db_with_retry(raw_url: str, db_full_path: str, *, attempts: int = 2) -> None:
    for attempt in range(1, attempts + 1):
        try:
            if raw_url.startswith("sqlite:///"):
                init_database(use_memory=False, db_path=raw_url)
            else:
                init_database(use_memory=False, db_path=db_full_path)
            return
        except Exception as exc:
            log("debug", f"DB init attempt {attempt}/{attempts} failed: {exc}", level="ERROR")
            get_db_manager().dispose()
            if attempt == attempts:
                raise


def _reset_db() -> str:
    db_dir, db_full_path = _get_db_paths()
    raw = _db_url()

    log("debug", f"DB path : {db_full_path}  (exists={os.path.exists(db_full_path)})")

    if get_db_manager().is_initialized():
        log("debug", "Disposing existing DB connections…")
        get_db_manager().dispose()

    log("debug", "Initialising database…")
    _init_db_with_retry(raw, db_full_path)
    log("debug", "✓ Database initialised")

    if get_db_manager().is_initialized():
        if get_db_manager().empty_all_tables():
            log("debug", "✓ Database wiped")
        else:
            log("debug", "⚠ Could not wipe database", level="WARNING")
    else:
        log("debug", "❌ Database not initialised after init call!", level="ERROR")

    try:
        get_user_manager()._create_default_users_fallback()
        log("debug", "✓ Default users created")
    except Exception as exc:
        log("debug", f"⚠ Could not create default users: {exc}", level="ERROR")

    return db_dir


# ---------------------------------------------------------------------------
# 6.  Module initialisation helper
# ---------------------------------------------------------------------------
def _init_modules() -> None:
    """Initialise all active modules in two phases.

    Phase 1 — new-style functional hooks (headless, no Streamlit):
        module_handler.initialize() calls on_module_activated() for every
        active module that implements it.  Driver options + LLM callbacks
        are registered here.

    Phase 2 — legacy inject_ui_initialize() (headless-tolerant):
        Old-style modules that have NOT yet been migrated to on_module_activated()
        still register their driver options/actions inside inject_ui_initialize().
        We load each *_ui.py and call inject_ui_initialize(), catching any
        Streamlit exception (st.session_state writes fail headless, but the
        functional registrations happen before any st.* call and are NOT
        rolled back on exception).

        This phase is safe to run for new-style modules too: their
        inject_ui_initialize() only sets session_state defaults, so the
        exception is caught and ignored harmlessly.

        Remove this phase once every module has been migrated.
        See MIGRATE.md migration checklist.
    """
    # Phase 1 — new-style on_module_activated()
    if not module_handler._initialized:
        module_handler.initialize()
        # IMPORTANT: After initialization, we need to activate all modules
        # to trigger on_module_activated() hooks
        module_handler.activate_all()
        log("debug", "Module handler initialized and activated")
    else:
        log("debug", "module_handler already initialized, skipping Phase 1")

    log("debug", f"Active modules: {module_handler.get_active_modules()}")

    # Phase 2 — legacy inject_ui_initialize() for old-style modules
    for module_name in module_handler.get_active_modules():
        module_info = module_handler.get_module_info(module_name)
        if not module_info or not module_info.get("has_ui"):
            continue
        ui_mod = module_handler.load_module_ui(module_name)
        if ui_mod is None:
            continue
        fn = getattr(ui_mod, "inject_ui_initialize", None)
        if not callable(fn):
            continue
        try:
            fn()
            log("debug", f"  inject_ui_initialize OK: {module_name}")
        except Exception:
            # Streamlit context errors are expected and harmless here.
            # Functional side-effects (register_option/register_action calls
            # that happen before any st.* line) are already applied.
            log("debug", f"  inject_ui_initialize partial (headless): {module_name}")

    log("debug", "✓ Modules initialised")


# ---------------------------------------------------------------------------
# 7.  RAG test-data helper
# ---------------------------------------------------------------------------
def _setup_rag_test_data() -> None:
    """Upload and index shared RAG fixtures once per test session."""
    docs = [
        (PROJECT_ROOT / "tests" / "kevin.txt", "admin"),
        (PROJECT_ROOT / "modules" / "benchmarker" / "tests" / "nexoria.md", "master1"),
    ]

    for attempt in range(1, 6):
        try:
            if not get_db_manager().is_initialized():
                log("debug", f"DB not ready, RAG setup attempt {attempt}/5")
                time.sleep(0.5)
                continue

            for user_id in ("admin", "master1"):
                rag_manager.clear_all_documents(user_id)

            for doc_path, user_id in docs:
                filename = rag_manager.upload_document(
                    source_path=str(doc_path),
                    original_filename=doc_path.name,
                    user_id=user_id,
                    is_public=False,
                )
                for strategy in ("classic", "simple"):
                    rag_manager.index_document(filename, strategy, user_id)
                log("debug", f"[SETUP] Indexed {filename} for {user_id}")
            return

        except Exception as exc:
            log("debug", f"RAG setup attempt {attempt}/5 failed: {exc}", level="ERROR")
            time.sleep(0.5)

    raise RuntimeError("Failed to set up RAG test data after 5 attempts")


# ---------------------------------------------------------------------------
# 8.  Filesystem cleanup helper
# ---------------------------------------------------------------------------
def _cleanup_directory(directory: str) -> None:
    import shutil
    if not os.path.exists(directory):
        return
    log("debug", f"Cleaning directory: {directory}")
    for name in os.listdir(directory):
        item = os.path.join(directory, name)
        try:
            if os.path.isfile(item) or os.path.islink(item):
                os.unlink(item)
            elif os.path.isdir(item):
                shutil.rmtree(item)
            log("debug", f"  ✓ Removed: {name}")
        except Exception as exc:
            log("debug", f"  ⚠ Could not remove {item}: {exc}", level="WARNING")


# ---------------------------------------------------------------------------
# 9.  Session hooks
# ---------------------------------------------------------------------------
def pytest_sessionstart(session) -> None:  # noqa: ARG001
    log("debug", "=== SESSION START ===")

    # Step 1: DB must exist before users or modules.
    _reset_db()

    # Step 2: Users before modules (some modules query users at activation).
    log("debug", "Creating default users…")
    try:
        init_user_manager(create_default_users=True)
    except Exception as exc:
        log("debug", f"⚠ init_user_manager failed: {exc}", level="ERROR")

    # IMPORTANT: Set up services for modules BEFORE initialization
    from shared.module_handler import ServiceLocator

    services = ServiceLocator()
    services.register("config", get_config())
    services.register("user_manager", get_user_manager())
    services.register("db_manager", get_db_manager())
    services.register("conversation_manager", get_conversation_manager())
    services.register("prompt_manager", get_prompt_manager())
    services.register("llm_manager", get_llm_manager())
    # Add other services as needed
    module_handler.set_services(services)

    # Step 3: Module initialisation (Phase 1: on_module_activated; Phase 2: legacy).
    log("debug", "Initialising modules…")
    _init_modules()

    # Step 4: RAG test corpus.
    log("debug", "Preparing shared RAG corpus…")
    _setup_rag_test_data()

    log("debug", "✓ Session setup complete")


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001
    log("debug", "\n=== SESSION FINISH – CLEANUP ===")
    time.sleep(1)

    subprocess.run(
        "pkill -9 -f 'streamlit run prof.py'",
        shell=True, capture_output=True, timeout=5,
    )

    db_dir, db_full_path = _get_db_paths()
    if get_db_manager().is_initialized():
        get_db_manager().dispose()

    if os.path.exists(db_full_path):
        os.unlink(db_full_path)
        log("debug", f"✓ Deleted DB file: {db_full_path}")

    _cleanup_directory(db_dir)

    rag_data_dir = getattr(rag_manager, "data_dir", None)
    if rag_data_dir:
        _cleanup_directory(str(rag_data_dir))


# ---------------------------------------------------------------------------
# 10.  BDD step logging
# ---------------------------------------------------------------------------
def pytest_bdd_before_step(request, feature, scenario, step, step_func):  # noqa: ARG001
    log("debug", f"\n[STEP] {feature.name} › {scenario.name}")
    log("debug", f"       @{step.type} {step.name}")


# ---------------------------------------------------------------------------
# 11.  Marker collection
# ---------------------------------------------------------------------------
def pytest_collection_modifyitems(items) -> None:
    for item in items:
        if item.nodeid.startswith("modules/benchmarker/tests/"):
            item.add_marker("benchmarker")


# ---------------------------------------------------------------------------
# 12.  Session-scoped fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Ensure CWD is set correctly and clean up env vars afterwards."""
    log("debug", "=== TEST ENVIRONMENT SETUP ===")
    original_cwd = os.getcwd()
    db_dir, _ = _get_db_paths()

    if original_cwd != str(PROJECT_ROOT):
        os.chdir(PROJECT_ROOT)
        log("debug", f"CWD → {PROJECT_ROOT}")

    yield {"db_path": db_dir}

    log("debug", "=== TEST ENVIRONMENT CLEANUP ===")
    if os.getcwd() != original_cwd:
        os.chdir(original_cwd)
    for var in ("TEST_MODE", "PLAYWRIGHT_ASYNCIO"):
        os.environ.pop(var, None)
    log("debug", "✓ Env cleanup done")


@pytest.fixture(scope="session")
def streamlit_server(setup_test_environment):
    """Start a Streamlit server for end-to-end tests."""
    log("debug", "=== STARTING STREAMLIT SERVER ===")
    subprocess.run("pkill -9 -f 'streamlit run prof.py'", shell=True, capture_output=True)

    _, db_full_path = _get_db_paths()
    _poll_until(
        lambda: os.path.exists(db_full_path) and os.path.getsize(db_full_path) > 0,
        timeout=10, interval=0.5,
        label="DB file ready",
    )

    log_dir = PROJECT_ROOT / "tests" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "streamlit", "run", "prof.py",
        "--server.port", str(TEST_PORT),
        "--server.headless", "true",
        "--server.fileWatcherType", "none",
        "--server.enableCORS", "false",
        "--server.enableXsrfProtection", "false",
    ]
    log("debug", f"Command : {' '.join(cmd)}")

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=os.environ.copy(),
        cwd=PROJECT_ROOT,
        preexec_fn=os.setsid,
    )
    log("debug", f"Streamlit PID: {process.pid}")

    health_url = f"http://localhost:{TEST_PORT}/_stcore/health"
    if not _poll_until(
        lambda: _http_ok(health_url),
        timeout=30, interval=1,
        label="Streamlit health",
    ):
        _kill_process_group(process)
        raise RuntimeError("Streamlit failed to become healthy within 30 s")

    yield process

    log("debug", "=== SHUTTING DOWN STREAMLIT ===")
    _kill_process_group(process, graceful=True)
    subprocess.run("pkill -9 -f 'streamlit run prof.py'", shell=True, capture_output=True)


@pytest.fixture(scope=_BROWSER_SCOPE)
def playwright():
    """Synchronous Playwright instance."""
    original = os.environ.pop("PYTEST_ASYNCIO_MODE", None)
    with sync_playwright() as pw:
        yield pw
    if original is not None:
        os.environ["PYTEST_ASYNCIO_MODE"] = original


@pytest.fixture(scope=_BROWSER_SCOPE)
def browser(playwright, request):
    """Chromium browser, headed when ``--headed`` is passed."""
    headless = not request.config.getoption("--headed")
    log("debug", f"Browser: {'HEADLESS' if headless else 'HEADED'}")
    b = playwright.chromium.launch(
        headless=headless,
        slow_mo=200,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-web-security",
            "--disable-features=IsolateOrigins,site-per-process",
        ],
    )
    yield b
    b.close()


# ---------------------------------------------------------------------------
# 13.  Function-scoped fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def context():
    """Blank dict for sharing state between BDD steps."""
    return {}


@pytest.fixture
def enable_debug():
    """True when ``PYTEST_DEBUG=true`` is set in the environment."""
    return os.getenv("PYTEST_DEBUG", "false").lower() in ("true", "1", "yes")


@pytest.fixture
def debug_dir(enable_debug):
    """Create and return the debug screenshot directory (or False)."""
    if enable_debug:
        path = Path("tests") / "debug"
        path.mkdir(parents=True, exist_ok=True)
        return path
    return False


@pytest.fixture
def browser_context(browser):
    ctx = browser.new_context()
    yield ctx
    ctx.close()


@pytest.fixture
def page(browser_context):
    p = browser_context.new_page()
    p.set_default_timeout(60_000)
    p.set_default_navigation_timeout(60_000)
    p.set_viewport_size({"width": 1280, "height": 900})
    yield p
    p.close()


# ---------------------------------------------------------------------------
# 14.  Markers
# ---------------------------------------------------------------------------
def pytest_configure(config) -> None:
    markers = [
        ("bdd",               "BDD tests using pytest-bdd"),
        ("integration",       "Integration tests with UI"),
        ("unit",              "Unit tests without UI"),
        ("streamlit_testing", "Tests using streamlit.testing.v1 (no browser)"),
        ("playwright",        "Tests using Playwright (browser automation)"),
        ("rag",               "Tests using RAG"),
    ]
    for name, description in markers:
        config.addinivalue_line("markers", f"{name}: {description}")


# ---------------------------------------------------------------------------
# 15.  Internal utilities
# ---------------------------------------------------------------------------
def _http_ok(url: str) -> bool:
    try:
        return requests.get(url, timeout=5).status_code == 200
    except requests.RequestException:
        return False


def _poll_until(
    condition,
    *,
    timeout: float,
    interval: float = 1.0,
    label: str = "condition",
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            log("debug", f"✓ {label}")
            return True
        time.sleep(interval)
    log("debug", f"⚠ Timed out waiting for: {label}", level="WARNING")
    return False


def _kill_process_group(process, *, graceful: bool = False) -> None:
    try:
        pgid = os.getpgid(process.pid)
        if graceful:
            os.killpg(pgid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
                log("debug", "✓ Process terminated gracefully")
                return
            except subprocess.TimeoutExpired:
                log("debug", "Graceful shutdown timed out, killing…", level="WARNING")
        os.killpg(pgid, signal.SIGKILL)
        process.wait(timeout=2)
        log("debug", "✓ Process killed")
    except ProcessLookupError:
        log("debug", "Process already gone")
    except Exception as exc:
        log("debug", f"Error killing process: {exc}", level="ERROR")
