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

os.environ["TEST_MODE"] = "true"
from shared.common import get_config


SCOPE = "function"
TEST_PORT = 8505

warnings.filterwarnings("ignore", category=UserWarning, module="streamlit.runtime.scriptrunner_utils")
warnings.filterwarnings("ignore", category=UserWarning, module="streamlit.runtime.state.session_state_proxy")

# ============ TROUVER LA VRAIE RACINE DU PROJET ============
# Le fichier conftest.py est dans tests/, donc on remonte d'un niveau
CONFTEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CONFTEST_DIR)  # Remonter d'un niveau depuis tests/

print(f"Conftest directory: {CONFTEST_DIR}")
print(f"Project root: {PROJECT_ROOT}")
print(f"App.py exists at root: {os.path.exists(os.path.join(PROJECT_ROOT, 'app.py'))}")

# Ajouter la racine du projet au chemin Python
sys.path.insert(0, PROJECT_ROOT)

# FORCER le PYTHONPATH pour Streamlit
os.environ["PYTHONPATH"] = PROJECT_ROOT

print(f"Python path: {sys.path}")

# ============ CONFIGURATION ============
# Chercher test_config.json à plusieurs endroits
possible_config_paths = [
    os.path.join(CONFTEST_DIR, "test_config.json"),  # Dans tests/
    os.path.join(PROJECT_ROOT, "tests", "test_config.json"),  # Dans tests/ depuis racine
    os.path.join(PROJECT_ROOT, "test_config.json"),  # À la racine
]

TEST_CONFIG_PATH = None
for path in possible_config_paths:
    if os.path.exists(path):
        TEST_CONFIG_PATH = path
        print(f"Found test config at: {path}")
        break

if not TEST_CONFIG_PATH:
    raise FileNotFoundError(f"Could not find test_config.json. Tried: {possible_config_paths}")

print(f"Loading test config from: {TEST_CONFIG_PATH}")

with open(TEST_CONFIG_PATH, 'r') as f:
    TEST_CONFIG = json.load(f)

print(f"Test config loaded. Available LLMs: {list(TEST_CONFIG.get('llms', {}).keys())}")


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
    from shared.database import db_manager, init_database
    from shared.users import user_manager

    print(f"\n=== DATABASE CLEANUP (FUNCTION) ===")
    # 1. Initialize the database
    db_config_path = get_config().get("database", {}).get("path", ".")
    db_full_path = os.path.abspath(db_config_path)
    db_path = db_config_path + "/app.db"
    print(f"Initializing database...{db_path}")
    # CRITICAL: Dispose of any existing database connections from previous test
    # After dispose(), is_initialized() will return False, so init_database() will work
    if db_manager.is_initialized():
        print("Disposing of existing database connections from previous test...")
        db_manager.dispose()
        # Extra delay to ensure SQLite releases the file lock
        time.sleep(0.5)
        print("✓ Database connections disposed")
    init_database(use_memory=False, db_path=db_path)

    if db_manager.is_initialized():
        print("Cleaning database before test...")
        success = db_manager.empty_all_tables()
        if success:
            print("✓ Database cleaned before test")
        else:
            print("⚠ Could not clean database (might be empty)")
    else:
        print("Database not initialized")

    # 2. Create default users (WITH TEST_MODE still set)
    user_manager.create_default_users()
    print("✓ Default users created before test")
    return db_full_path

def setup_rag_test_data():
    import tempfile
    from modules.rag_manager import rag_manager

    test_content = """The address of Kevin is 1 place du Louvre, Paris.
    Kevin works as a software engineer at TechCorp.
    His phone number is +33 1 23 45 67 89."""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(test_content)
        temp_path = f.name

    admin_id = "admin"
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

@pytest.fixture(scope=SCOPE, autouse=True)
def setup_test_environment():
    """Setup test environment before any tests run."""
    os.environ["TEST_MODE"] = "true"
    # Set environment variables
    os.environ["CONFIG_FILE"] = "tests/test_config.json"
    os.environ["PLAYWRIGHT_ASYNCIO"] = "0"
    original_cwd = os.getcwd()
    time.sleep(1)

    db_full_path = setup_database()

    print(f"\n=== TEST ENVIRONMENT SETUP ===")
    print(f"Original CWD: {original_cwd}")
    print(f"Project root: {PROJECT_ROOT}")

    # Changer de répertoire seulement si nécessaire
    if original_cwd != PROJECT_ROOT:
        os.chdir(PROJECT_ROOT)
        print(f"Changed CWD to: {os.getcwd()}")
    else:
        print(f"Already in project root")

    print(f"App.py exists: {os.path.exists('app.py')}")
    print(f"Config file: {os.path.join(PROJECT_ROOT, os.environ['CONFIG_FILE'])}")
    print(f"Config exists: {os.path.exists(os.path.join(PROJECT_ROOT, os.environ['CONFIG_FILE']))}")
    print("=" * 30 + "\n")

    temp_path = setup_rag_test_data()

    # Restaurer le répertoire original
    if original_cwd != os.getcwd():
        os.chdir(original_cwd)
        print(f"Restored CWD to: {original_cwd}")
    try:
        yield
    finally:
        # CLEANUP AFTER TEST COMPLETES
        print("\n=== TEST ENVIRONMENT CLEANUP ===")

        from shared.database import db_manager, init_database
        if db_manager.is_initialized():
            db_manager.dispose()
            time.sleep(0.5)
        # Clean up temp file
        if os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
                print(f"✓ Deleted temp file: {temp_path}")
            except Exception as e:
                print(f"⚠ Could not delete temp file: {e}")

        cleanup_directory(db_full_path)

        # Clean up environment variables
        for var in ["TEST_MODE", "CONFIG_FILE", "PLAYWRIGHT_ASYNCIO"]:
            if var in os.environ:
                del os.environ[var]

        time.sleep(0.5)
        print("✓ Test environment cleanup complete")


@pytest.fixture(scope=SCOPE)
def playwright(setup_test_environment):
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

# Change at the top of the file
import pty # For better process control if needed, but os.setsid is key

@pytest.fixture(scope=SCOPE)
def streamlit_server(setup_test_environment):
    """Start Streamlit server for testing."""
    # 1. Kill any stray processes using a more robust selector
    subprocess.run("pkill -9 -f 'streamlit run app.py'", shell=True, capture_output=True)
    time.sleep(1)

    env = os.environ.copy()
    env["TEST_MODE"] = "true"
    env["PYTHONPATH"] = PROJECT_ROOT

    log_dir = os.path.join(PROJECT_ROOT, "tests", "logs")
    os.makedirs(log_dir, exist_ok=True)

    stdout_file = open(os.path.join(log_dir, "streamlit_stdout.log"), "w")
    stderr_file = open(os.path.join(log_dir, "streamlit_stderr.log"), "w")

    cmd = [
        "streamlit", "run", "app.py",
        "--server.port", str(TEST_PORT),
        "--server.headless", "true",
        "--server.fileWatcherType", "none"
    ]

    # Use start_new_session=True to create a process group
    process = subprocess.Popen(
        cmd,
        stdout=stdout_file,
        stderr=stderr_file,
        env=env,
        cwd=PROJECT_ROOT,
        preexec_fn=os.setsid  # Creates a process group
    )

    # Health check
    start_time = time.time()
    success = False
    while time.time() - start_time < 30:
        try:
            if requests.get(f"http://localhost:{TEST_PORT}/_stcore/health").status_code == 200:
                success = True
                break
        except:
            time.sleep(0.5)

    if not success:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        raise RuntimeError("Streamlit failed to start")

    yield process

    # CLEANUP: Kill the entire process group
    print("\n=== Shutting down Streamlit Process Group ===")
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        process.wait(timeout=5)
    except:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)

    stdout_file.close()
    stderr_file.close()

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

# ============ HOOKS ============

@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """
    Hook pour prendre un screenshot automatique en cas d'échec d'un test.
    """
    outcome = yield
    rep = outcome.get_result()

    if rep.when == "call" and rep.failed:
        if "page" in item.fixturenames:
            page = item.funcargs["page"]

            error_dir = os.path.join("tests", "debug", "errors")
            os.makedirs(error_dir, exist_ok=True)

            safe_test_name = "".join(c if c.isalnum() else "_" for c in item.name)
            filename = f"error_{safe_test_name}.png"
            filepath = os.path.join(error_dir, filename)

            try:
                page.screenshot(path=filepath, full_page=True)
                print(f"\nScreenshot d'erreur sauvegardé : {filepath}")
            except Exception as e:
                print(f"\nImpossible de prendre le screenshot : {e}")

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
