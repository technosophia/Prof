# file name: conftest.py (version refactorisée)
"""
Pytest configuration and fixtures for all tests.
"""
import sys
import os
import json
import pytest
import time
import subprocess
import requests
import atexit
import signal
import warnings
import re
from unittest.mock import patch, MagicMock
from playwright.sync_api import sync_playwright

# CRITICAL: Load .env BEFORE any shared imports, because shared.common
# instantiates the LLMManager singleton (and GroqEngine) at import time.
# If GROQ_API_KEY isn't in os.environ yet when that happens, the engine
# marks itself unavailable permanently — even if the key arrives later.
from dotenv import load_dotenv
load_dotenv()

def _log(message, level="INFO"):
    """Log message with process ID and timestamp."""
    #pid = os.getpid()
    #timestamp = time.strftime("%H:%M:%S")
    #formatted_message = f"[{timestamp}][PID:{pid}][{level}] {message}"
    formatted_message = f"[{level}] {message}"
    print(formatted_message)
    return formatted_message


def extract_sqlite_file_path(db_url_or_path: str) -> str:
    """
    Extract the file path from a SQLite database URL or return the path if it's already a file path.

    Args:
        db_url_or_path: Either a SQLite URL (sqlite:///path/to/db.db) or a file path

    Returns:
        The extracted file path
    """
    if not db_url_or_path or not isinstance(db_url_or_path, str):
        return db_url_or_path

    # Match sqlite:///path format
    sqlite_pattern = r'^sqlite:///(.+)$'
    match = re.match(sqlite_pattern, db_url_or_path)

    if match:
        file_path = match.group(1)
        # Handle Windows paths with drive letters
        if file_path.startswith('/') and len(file_path) > 2 and file_path[2] == ':':
            # Remove leading slash for Windows paths like /C:/path
            file_path = file_path[1:]
        return file_path

    # Already a file path
    return db_url_or_path


def get_database_file_path():
    """
    Get the actual database file path from config, handling both URL and path formats.

    Returns:
        Tuple of (database_directory, database_file_path)
    """
    config = get_config()
    db_config = config.get("database", {})

    # Try to get URL first, then path
    db_url_or_path = db_config.get("url") or db_config.get("path", ".")

    # Extract file path if it's a URL
    db_file_path = extract_sqlite_file_path(db_url_or_path)

    # Handle cases where it's just a directory
    if os.path.isdir(db_file_path) or not db_file_path.endswith('.db'):
        db_dir = db_file_path
        db_full_path = os.path.join(db_dir, "app.db")
    else:
        db_dir = os.path.dirname(db_file_path)
        db_full_path = db_file_path

    return db_dir, db_full_path


def pytest_sessionfinish(session, exitstatus):
    """Clean up after all tests are done."""
    print('\n')
    _log("="*50)
    _log("PYTEST SESSION FINISHED - FINAL CLEANUP")
    _log("="*50)

    # Small delay to ensure all processes have released file handles
    time.sleep(1)

    # Kill any remaining Streamlit processes
    subprocess.run("pkill -9 -f 'streamlit run prof.py'", shell=True,
                   capture_output=True, timeout=5)

def pytest_sessionstart(session):
    """Initialize database at the VERY beginning of the test session."""
    _log("=== SESSION START - INITIALIZING DATABASE ===")

    # Get database file path from config
    db_dir, db_full_path = get_database_file_path()

    # CRITICAL: Dispose of any existing database connections
    if get_db_manager().is_initialized():
        _log("Disposing of existing database connections...")
        get_db_manager().dispose()

    # Initialize database with the appropriate format
    _log(f"Initializing database at {db_full_path}...")
    try:
        # Check if config uses URL format
        config = get_config()
        db_config = config.get("database", {})
        db_url_or_path = db_config.get("url") or db_config.get("path", ".")

        if db_url_or_path.startswith('sqlite:///'):
            # Use the URL directly
            init_database(use_memory=False, db_path=db_url_or_path)
        else:
            # Use the file path
            init_database(use_memory=False, db_path=db_full_path)

        _log("✓ Database initialized")
    except Exception as e:
        _log(f"⚠ Error initializing database: {e}", level="ERROR")
        # Try one more time
        get_db_manager().dispose()
        if db_url_or_path.startswith('sqlite:///'):
            init_database(use_memory=False, db_path=db_url_or_path)
        else:
            init_database(use_memory=False, db_path=db_full_path)

    # Clean database
    if get_db_manager().is_initialized():
        _log("Cleaning database...")
        success = get_db_manager().empty_all_tables()
        if success:
            _log("✓ Database cleaned")
        else:
            _log("⚠ Could not clean database", level="WARNING")

    # Create default users
    _log("Creating default users...")
    try:
        get_user_manager()._create_default_users_fallback()
        _log("✓ Default users created")
    except Exception as e:
        _log(f"⚠ Error creating default users: {e}", level="ERROR")

    return db_dir

def pytest_bdd_before_step(request, feature, scenario, step, step_func):
    """Log step before execution."""
    _log(f"\n[STEP START] Feature: {feature.name} - Scenario: {scenario.name}")
    _log(f"           Step:@{step.type} {step.name}")

SCOPE = "module"
TEST_PORT = 8505

warnings.filterwarnings("ignore", category=UserWarning, module="streamlit.runtime.scriptrunner_utils")
warnings.filterwarnings("ignore", category=UserWarning, module="streamlit.runtime.state.session_state_proxy")

CONFTEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CONFTEST_DIR)  # Remonter d'un niveau depuis tests/
sys.path.insert(0, PROJECT_ROOT)
os.environ["PYTHONPATH"] = PROJECT_ROOT

os.environ["TEST_MODE"] = "true"
os.environ["PLAYWRIGHT_ASYNCIO"] = "0"
from shared.common import get_config
from shared.common import get_db_manager, init_database
from shared.common import get_user_manager
import tempfile
from modules.rag_manager import rag_manager


_log(f"Python path: {sys.path}")
_log(f"Conftest directory: {CONFTEST_DIR}")
_log(f"Project root: {PROJECT_ROOT}")
_log(f"prof.py exists at root: {os.path.exists(os.path.join(PROJECT_ROOT, 'prof.py'))}")

def cleanup_directory(directory):
    import shutil
    if os.path.exists(directory):
        _log(f"Cleaning up directory: {directory}")
        for item in os.listdir(directory):
            item_path = os.path.join(directory, item)
            try:
                if os.path.isfile(item_path) or os.path.islink(item_path):
                    os.unlink(item_path)
                    _log(f"  ✓ Deleted file: {item}")
                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                    _log(f"  ✓ Deleted directory: {item}")
            except Exception as e:
                _log(f"  ⚠ Failed to delete {item_path}: {e}", level="WARNING")

def setup_database():
    _log(f"\n=== DATABASE CLEANUP (FUNCTION) ===")

    # Get database file path from config
    db_dir, db_full_path = get_database_file_path()

    _log(f"Database path: {db_full_path}")
    _log(f"Database exists: {os.path.exists(db_full_path)}")

    # CRITICAL: Dispose of any existing database connections
    if get_db_manager().is_initialized():
        _log("Disposing of existing database connections...")
        get_db_manager().dispose()
        _log("✓ Database connections disposed")

    # Initialize database with the appropriate format
    _log(f"Initializing database at {db_full_path}...")
    try:
        config = get_config()
        db_config = config.get("database", {})
        db_url_or_path = db_config.get("url") or db_config.get("path", ".")

        if db_url_or_path.startswith('sqlite:///'):
            init_database(use_memory=False, db_path=db_url_or_path)
        else:
            init_database(use_memory=False, db_path=db_full_path)

        _log("✓ Database initialized")
    except Exception as e:
        _log(f"⚠ Error initializing database: {e}", level="ERROR")
        # Try one more time
        get_db_manager().dispose()
        if db_url_or_path.startswith('sqlite:///'):
            init_database(use_memory=False, db_path=db_url_or_path)
        else:
            init_database(use_memory=False, db_path=db_full_path)

    # Clean database
    if get_db_manager().is_initialized():
        _log("Cleaning database...")
        success = get_db_manager().empty_all_tables()
        if success:
            _log("✓ Database cleaned")
        else:
            _log("⚠ Could not clean database", level="WARNING")
    else:
        _log("❌ Database not initialized after init_database() call!", level="ERROR")

    # Create default users
    _log("Creating default users...")
    try:
        get_user_manager()._create_default_users_fallback()
        _log("✓ Default users created")
    except Exception as e:
        _log(f"⚠ Error creating default users: {e}", level="ERROR")

    return db_dir

def setup_rag_test_data():

    # Wait a bit for database to be fully ready
    test_content = """The address of Kevin is 1 place du Louvre, Paris.
    Kevin works as a software engineer at TechCorp.
    His phone number is +33 1 23 45 67 89."""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(test_content)
        temp_path = f.name

    admin_id = "admin"

    # Wait for database to be ready
    max_attempts = 5
    for attempt in range(max_attempts):
        try:
            if get_db_manager().is_initialized():
                filename = rag_manager.upload_document(
                    source_path=temp_path,
                    original_filename="kevin_info.txt",
                    user_id=admin_id,
                    is_public=False
                )

                default_engine = rag_manager.get_default_engine().engine_type
                rag_manager.index_document(filename, default_engine, admin_id)

                _log(f"[SETUP] RAG Test Data Initialized with {default_engine}: {filename}")
                return temp_path
            else:
                _log(f"Database not initialized, attempt {attempt + 1}/{max_attempts}")
        except Exception as e:
            _log(f"Error setting up RAG data (attempt {attempt + 1}): {e}", level="ERROR")
            time.sleep(0.5)

    _log("❌ Failed to setup RAG test data after multiple attempts", level="ERROR")
    return temp_path  # Return temp path anyway for cleanup


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Setup test environment after database is initialized."""
    _log(f"\n=== TEST ENVIRONMENT SETUP ===")
    _log(f"Project root: {PROJECT_ROOT}")

    # Store original CWD
    original_cwd = os.getcwd()
    temp_path = ""

    # Get database directory from config
    db_dir, _ = get_database_file_path()

    # Change to project root if needed
    if original_cwd != PROJECT_ROOT:
        os.chdir(PROJECT_ROOT)
        _log(f"Changed CWD to: {PROJECT_ROOT}")

    try:
        # Setup RAG data (database already initialized in pytest_sessionstart)
        _log("\n=== RAG DATA INITIALIZATION ===")
        temp_path = setup_rag_test_data()

        yield {
            "db_path": db_dir,  # Return the directory for backward compatibility
            "temp_path": temp_path
        }

    finally:
        # CLEANUP AFTER TEST COMPLETES
        _log("\n=== TEST ENVIRONMENT CLEANUP ===")

        # Change back to original directory for cleanup
        if os.getcwd() != original_cwd:
            os.chdir(original_cwd)
        if os.path.exists(temp_path):
            os.unlink(temp_path)

        # Clean up environment variables
        for var in ["TEST_MODE","PLAYWRIGHT_ASYNCIO"]:
            if var in os.environ:
                del os.environ[var]

        _log("✓ Test environment cleanup complete")


@pytest.fixture(scope=SCOPE)
def playwright():
    """Playwright session fixture."""
    # Désactiver asyncio pour Playwright sync
    original_asyncio_mode = os.environ.get("PYTEST_ASYNCIO_MODE")
    if original_asyncio_mode:
        del os.environ["PYTEST_ASYNCIO_MODE"]

    with sync_playwright() as p:
        yield p

    if original_asyncio_mode:
        os.environ["PYTEST_ASYNCIO_MODE"] = original_asyncio_mode

@pytest.fixture(scope=SCOPE)
def browser(playwright, request):
    """Browser session fixture avec support pour --headed."""
    # Vérifier si --headed est spécifié
    headless = not request.config.getoption("--headed")

    # Configurer les options de lancement
    launch_options = {
        "headless": headless,
        "args": [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-web-security",
            "--disable-features=IsolateOrigins,site-per-process"
        ]
    }

    if not headless:
        _log(f"🔍 Launching browser in HEADED mode (headless={headless})")
        launch_options["slow_mo"] = 200  # Ralentir pour voir ce qui se passe
    else:
        launch_options["slow_mo"] = 200
        _log(f"🚀 Launching browser in HEADLESS mode")

    browser = playwright.chromium.launch(**launch_options)

    yield browser

    browser.close()

@pytest.fixture(scope="session")
def streamlit_server(setup_test_environment):
    """Start Streamlit server for testing."""
    _log("\n=== STARTING STREAMLIT SERVER ===")

    # 1. Kill any stray processes
    subprocess.run("pkill -9 -f 'streamlit run prof.py'", shell=True, capture_output=True)

    # CRITICAL FIX: Ensure database is fully initialized before starting Streamlit
    _, db_full_path = get_database_file_path()

    max_wait = 10
    start_time = time.time()
    while time.time() - start_time < max_wait:
        if os.path.exists(db_full_path) and os.path.getsize(db_full_path) > 0:
            _log(f"✓ Database file exists and has content: {db_full_path}")
            break
        _log(f"Waiting for database file to be created... ({int(time.time() - start_time)}s)")
        time.sleep(0.5)
    else:
        _log(f"⚠ Database file not found after {max_wait}s, continuing anyway...")

    env = os.environ.copy()
    log_dir = os.path.join(PROJECT_ROOT, "tests", "logs")
    os.makedirs(log_dir, exist_ok=True)

    stdout_file = open(os.path.join(log_dir, "streamlit_stdout.log"), "w")
    stderr_file = open(os.path.join(log_dir, "streamlit_stderr.log"), "w")

    cmd = [
        "streamlit", "run", "prof.py",
        "--server.port", str(TEST_PORT),
        "--server.headless", "true",
        "--server.fileWatcherType", "none",
        "--server.enableCORS", "false",
        "--server.enableXsrfProtection", "false"
    ]

    _log(f"Launching Streamlit with command: {' '.join(cmd)}")
    _log(f"Working directory: {PROJECT_ROOT}")

    process = None
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            #stdout=stdout_file, # Can cause interference BUG
            #stderr=stderr_file, # Can cause interference BUG
            env=env,
            cwd=PROJECT_ROOT,
            preexec_fn=os.setsid
        )

        _log(f"Streamlit process started with PID: {process.pid}")

        # Health check with retries
        start_time = time.time()
        success = False
        max_wait = 30
        while time.time() - start_time < max_wait:
            try:
                response = requests.get(f"http://localhost:{TEST_PORT}/_stcore/health", timeout=5)
                if response.status_code == 200:
                    success = True
                    _log(f"✓ Streamlit server is ready after {int(time.time() - start_time)} seconds")
                    break
                time.sleep(1)
            except TimeoutError:
                pass
            except requests.RequestException as e:
                if time.time() - start_time > 10:
                    _log(f"Waiting for Streamlit... ({int(time.time() - start_time)}s)")
                time.sleep(1)

        if not success:
            _log("❌ Streamlit failed to start within timeout", level="ERROR")
            if process:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                process.wait(timeout=5)
            raise RuntimeError("Streamlit failed to start")

        yield process

    finally:
        # CLEANUP: Kill the entire process group
        _log("\n=== SHUTTING DOWN STREAMLIT SERVER ===")
        if process:
            try:
                _log(f"Terminating process group for PID: {process.pid}")
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                process.wait(timeout=5)
                _log("✓ Streamlit server terminated gracefully")
            except subprocess.TimeoutExpired:
                _log("Process didn't terminate, forcing kill...", level="WARNING")
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                process.wait(timeout=2)
                _log("✓ Streamlit server killed")
            except ProcessLookupError:
                _log("Process already terminated")
            except Exception as e:
                _log(f"Error during shutdown: {e}", level="ERROR")

        stdout_file.close()
        stderr_file.close()

        # Final cleanup of any remaining processes
        subprocess.run("pkill -9 -f 'streamlit run prof.py'", shell=True, capture_output=True)

# ============ FUNCTION FIXTURES ============

@pytest.fixture
def context():
    """Test context to store state between steps."""
    return {}

@pytest.fixture
def enable_debug():
    """Fixture to enable debug mode (screenshots, logging)."""
    debug_enabled = os.getenv("PYTEST_DEBUG", "false").lower() in ("true", "1", "yes")
    #print(f"Debug mode: {'ENABLED' if debug_enabled else 'DISABLED'}") # Can cause interference BUG
    return debug_enabled

@pytest.fixture
def debug_dir(enable_debug):
    """Create debug directory if debug mode is enabled."""
    if enable_debug:
        debug_path = os.path.join("tests", "debug")
        os.makedirs(debug_path, exist_ok=True)
        #print(f"Debug directory: {os.path.abspath(debug_path)}") # Can cause interference BUG
    return enable_debug

@pytest.fixture
def browser_context(browser):
    """Create browser context once per test."""
    context = browser.new_context()
    yield context
    context.close()

@pytest.fixture
def page(browser_context):
    """Create a new page for each test."""
    page = browser_context.new_page()

    # IMPORTANT: Augmenter les timeouts pour le mode headed
    page.set_default_timeout(60000)  # 60 secondes au lieu de 30
    page.set_default_navigation_timeout(60000)

    # Forcer une taille de fenêtre spécifique
    page.set_viewport_size({"width": 1280, "height": 900})

    yield page
    page.close()



# ============ MARKS ============

def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line(
        "markers",
        "bdd: BDD tests using pytest-bdd"
    )
    config.addinivalue_line(
        "markers",
        "integration: Integration tests with UI"
    )
    config.addinivalue_line(
        "markers",
        "unit: Unit tests without UI"
    )
    config.addinivalue_line(
        "markers",
        "streamlit_testing: Tests using streamlit.testing.v1 (no browser)"
    )
    config.addinivalue_line(
        "markers",
        "playwright: Tests using Playwright (browser automation)"
    )
    config.addinivalue_line(
        "markers",
        "rag: Tests using RAG (browser automation)"
    )
