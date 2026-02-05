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
from unittest.mock import patch, MagicMock
from playwright.sync_api import sync_playwright

def pytest_sessionfinish(session, exitstatus):
    """Clean up after all tests are done."""
    print("\n" + "="*50)
    print("PYTEST SESSION FINISHED - FINAL CLEANUP")
    print("="*50)

    # Kill any remaining Streamlit processes
    subprocess.run("pkill -9 -f 'streamlit run app.py'", shell=True,
                   capture_output=True, timeout=5)

os.environ["TEST_MODE"] = "true"
os.environ["PLAYWRIGHT_ASYNCIO"] = "0"
from shared.common import get_config
from shared.database import db_manager, init_database
from shared.users import user_manager
import tempfile
from modules.rag_manager import rag_manager


SCOPE = "module"
TEST_PORT = 8505

warnings.filterwarnings("ignore", category=UserWarning, module="streamlit.runtime.scriptrunner_utils")
warnings.filterwarnings("ignore", category=UserWarning, module="streamlit.runtime.state.session_state_proxy")

CONFTEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CONFTEST_DIR)  # Remonter d'un niveau depuis tests/
sys.path.insert(0, PROJECT_ROOT)
os.environ["PYTHONPATH"] = PROJECT_ROOT
print(f"Python path: {sys.path}")


print(f"Conftest directory: {CONFTEST_DIR}")
print(f"Project root: {PROJECT_ROOT}")
print(f"App.py exists at root: {os.path.exists(os.path.join(PROJECT_ROOT, 'app.py'))}")

def cleanup_directory(directory):
    import shutil
    if os.path.exists(directory):
        print(f"Cleaning up directory: {directory}")
        for item in os.listdir(directory):
            item_path = os.path.join(directory, item)
            try:
                if os.path.isfile(item_path) or os.path.islink(item_path):
                    os.unlink(item_path)
                    print(f"  ✓ Deleted file: {item}")
                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                    print(f"  ✓ Deleted directory: {item}")
            except Exception as e:
                print(f"  ⚠ Failed to delete {item_path}: {e}")

def setup_database():

    print(f"\n=== DATABASE CLEANUP (FUNCTION) ===")
    # Get database path from config
    db_config_path = get_config().get("database", {}).get("path", ".")
    db_full_path = os.path.abspath(db_config_path)
    db_path = os.path.join(db_config_path, "app.db")

    print(f"Database path: {db_path}")
    print(f"Database exists: {os.path.exists(db_path)}")

    # CRITICAL: Dispose of any existing database connections
    if db_manager.is_initialized():
        print("Disposing of existing database connections...")
        db_manager.dispose()
        print("✓ Database connections disposed")

    # Initialize database
    print(f"Initializing database at {db_path}...")
    try:
        init_database(use_memory=False, db_path=db_path)
        print("✓ Database initialized")
    except Exception as e:
        print(f"⚠ Error initializing database: {e}")
        # Try one more time
        db_manager.dispose()
        init_database(use_memory=False, db_path=db_path)

    # Clean database
    if db_manager.is_initialized():
        print("Cleaning database...")
        success = db_manager.empty_all_tables()
        if success:
            print("✓ Database cleaned")
        else:
            print("⚠ Could not clean database")
    else:
        print("❌ Database not initialized after init_database() call!")

    # Create default users
    print("Creating default users...")
    try:
        user_manager.create_default_users()
        print("✓ Default users created")
    except Exception as e:
        print(f"⚠ Error creating default users: {e}")

    return db_full_path

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
            if db_manager.is_initialized():
                filename = rag_manager.upload_document(
                    source_path=temp_path,
                    original_filename="kevin_info.txt",
                    user_id=admin_id,
                    is_public=False
                )

                default_engine = rag_manager.get_default_engine().engine_type
                rag_manager.index_document(filename, default_engine, admin_id)

                print(f"[SETUP] RAG Test Data Initialized with {default_engine}: {filename}")
                return temp_path
            else:
                print(f"Database not initialized, attempt {attempt + 1}/{max_attempts}")
        except Exception as e:
            print(f"Error setting up RAG data (attempt {attempt + 1}): {e}")
            time.sleep(0.5)

    print("❌ Failed to setup RAG test data after multiple attempts")
    return temp_path  # Return temp path anyway for cleanup


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Setup test environment before any tests run."""
    print(f"\n=== TEST ENVIRONMENT SETUP ===")
    print(f"Project root: {PROJECT_ROOT}")

    # Store original CWD
    original_cwd = os.getcwd()

    # Change to project root if needed
    if original_cwd != PROJECT_ROOT:
        os.chdir(PROJECT_ROOT)
        print(f"Changed CWD to: {PROJECT_ROOT}")

    try:
        # Setup database FIRST
        print("\n=== DATABASE INITIALIZATION ===")
        db_full_path = setup_database()

        # Setup RAG data AFTER database is ready
        print("\n=== RAG DATA INITIALIZATION ===")
        temp_path = setup_rag_test_data()

        yield {
            "db_path": db_full_path,
            "temp_path": temp_path
        }

    finally:
        # CLEANUP AFTER TEST COMPLETES
        print("\n=== TEST ENVIRONMENT CLEANUP ===")

        # Change back to original directory for cleanup
        if os.getcwd() != original_cwd:
            os.chdir(original_cwd)
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        cleanup_directory(db_full_path)
        # Clean up environment variables
        for var in ["TEST_MODE", "CONFIG_FILE", "PLAYWRIGHT_ASYNCIO"]:
            if var in os.environ:
                del os.environ[var]

        print("✓ Test environment cleanup complete")


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
        print(f"🔍 Launching browser in HEADED mode (headless={headless})")
        launch_options["slow_mo"] = 200  # Ralentir pour voir ce qui se passe
    else:
        launch_options["slow_mo"] = 200
        print(f"🚀 Launching browser in HEADLESS mode")

    browser = playwright.chromium.launch(**launch_options)

    yield browser

    browser.close()

@pytest.fixture(scope="session")
def streamlit_server(setup_test_environment):
    """Start Streamlit server for testing."""
    print("\n=== STARTING STREAMLIT SERVER ===")

    # 1. Kill any stray processes
    subprocess.run("pkill -9 -f 'streamlit run app.py'", shell=True, capture_output=True)

    env = os.environ.copy()
    log_dir = os.path.join(PROJECT_ROOT, "tests", "logs")
    os.makedirs(log_dir, exist_ok=True)

    stdout_file = open(os.path.join(log_dir, "streamlit_stdout.log"), "w")
    stderr_file = open(os.path.join(log_dir, "streamlit_stderr.log"), "w")

    cmd = [
        "streamlit", "run", "app.py",
        "--server.port", str(TEST_PORT),
        "--server.headless", "true",
        "--server.fileWatcherType", "none",
        "--server.enableCORS", "false",
        "--server.enableXsrfProtection", "false"
    ]

    print(f"Launching Streamlit with command: {' '.join(cmd)}")
    print(f"Working directory: {PROJECT_ROOT}")

    process = None
    try:
        process = subprocess.Popen(
            cmd,
            stdout=stdout_file,
            stderr=stderr_file,
            env=env,
            cwd=PROJECT_ROOT,
            preexec_fn=os.setsid
        )

        print(f"Streamlit process started with PID: {process.pid}")

        # Health check with retries
        start_time = time.time()
        success = False
        max_wait = 30
        while time.time() - start_time < max_wait:
            try:
                response = requests.get(f"http://localhost:{TEST_PORT}/_stcore/health", timeout=5)
                if response.status_code == 200:
                    success = True
                    print(f"✓ Streamlit server is ready after {int(time.time() - start_time)} seconds")
                    break
                time.sleep(1)
            except TimeoutError:
                pass
            except requests.RequestException as e:
                if time.time() - start_time > 10:
                    print(f"Waiting for Streamlit... ({int(time.time() - start_time)}s)")
                time.sleep(1)

        if not success:
            print("❌ Streamlit failed to start within timeout")
            if process:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                process.wait(timeout=5)
            raise RuntimeError("Streamlit failed to start")

        yield process

    finally:
        # CLEANUP: Kill the entire process group
        print("\n=== SHUTTING DOWN STREAMLIT SERVER ===")
        if process:
            try:
                print(f"Terminating process group for PID: {process.pid}")
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                process.wait(timeout=5)
                print("✓ Streamlit server terminated gracefully")
            except subprocess.TimeoutExpired:
                print("Process didn't terminate, forcing kill...")
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                process.wait(timeout=2)
                print("✓ Streamlit server killed")
            except ProcessLookupError:
                print("Process already terminated")
            except Exception as e:
                print(f"Error during shutdown: {e}")

        stdout_file.close()
        stderr_file.close()

        # Final cleanup of any remaining processes
        subprocess.run("pkill -9 -f 'streamlit run app.py'", shell=True, capture_output=True)

# ============ FUNCTION FIXTURES ============

@pytest.fixture
def context():
    """Test context to store state between steps."""
    return {}

@pytest.fixture
def enable_debug():
    """Fixture to enable debug mode (screenshots, logging)."""
    debug_enabled = os.getenv("PYTEST_DEBUG", "false").lower() in ("true", "1", "yes")
    print(f"Debug mode: {'ENABLED' if debug_enabled else 'DISABLED'}")
    return debug_enabled

@pytest.fixture
def debug_dir(enable_debug):
    """Create debug directory if debug mode is enabled."""
    if enable_debug:
        debug_path = os.path.join("tests", "debug")
        os.makedirs(debug_path, exist_ok=True)
        print(f"Debug directory: {os.path.abspath(debug_path)}")
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



# ============ HELPER FUNCTIONS ============

def take_screenshot(page, filename, debug_enabled, full_page=False):
    """Take screenshot only if debug mode is enabled."""
    if debug_enabled:
        debug_path = os.path.join("tests", "debug")
        filepath = os.path.join(debug_path, filename)
        page.screenshot(path=filepath, full_page=full_page)
        print(f"  Screenshot saved: {filename}")

def find_element_by_text(page, text, exact=False):
    """Find an element containing specific text."""
    if exact:
        return page.get_by_text(text, exact=True)
    else:
        return page.get_by_text(text)

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
