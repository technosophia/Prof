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

# ============ SESSION FIXTURES ============

@pytest.fixture(scope=SCOPE, autouse=True)
def setup_test_environment():
    """Setup test environment before any tests run."""
    # Set environment variables
    os.environ["TEST_MODE"] = "true"
    os.environ["CONFIG_FILE"] = "tests/test_config.json"  # Relatif depuis la racine
    os.environ["PLAYWRIGHT_ASYNCIO"] = "0"

    original_cwd = os.getcwd()

    print(f"\n=== DATABASE CLEANUP (FUNCTION) ===")
    # Import database modules
    from shared.database import db_manager, init_database

    if db_manager.is_initialized():
        print("Cleaning database before test...")
        success = db_manager.empty_all_tables()
        if success:
            print("✓ Database cleaned before test")
        else:
            print("⚠ Could not clean database (might be empty)")
    else:
        print("Database not initialized")

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

    yield

    # Restaurer le répertoire original
    if original_cwd != os.getcwd():
        os.chdir(original_cwd)
        print(f"Restored CWD to: {original_cwd}")

    if "TEST_MODE" in os.environ:
        del os.environ["TEST_MODE"]
    if "CONFIG_FILE" in os.environ:
        del os.environ["CONFIG_FILE"]
    if "PLAYWRIGHT_ASYNCIO" in os.environ:
        del os.environ["PLAYWRIGHT_ASYNCIO"]

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
        launch_options["slow_mo"] = 1000  # Ralentir pour voir ce qui se passe
    else:
        launch_options["slow_mo"] = 1000
        print(f"🚀 Launching browser in HEADLESS mode")

    browser = playwright.chromium.launch(**launch_options)

    yield browser

    browser.close()

@pytest.fixture(scope=SCOPE)
def streamlit_server():
    """Start Streamlit server for testing - runs once per session."""
    # Kill any existing Streamlit process
    subprocess.run(["pkill", "-f", "streamlit"], capture_output=True, shell=True)
    time.sleep(2)

    # Create test environment
    env = os.environ.copy()
    env["TEST_MODE"] = "true"
    env["CONFIG_FILE"] = "tests/test_config.json"  # Chemin relatif depuis la racine

    # Afficher les variables d'environnement pour debug
    print(f"\n=== STREAMLIT SERVER CONFIG ===")
    print(f"Project root: {PROJECT_ROOT}")
    print(f"App.py at root: {os.path.join(PROJECT_ROOT, 'app.py')}")
    print(f"Exists: {os.path.exists(os.path.join(PROJECT_ROOT, 'app.py'))}")

    # Créer le répertoire de logs
    log_dir = os.path.join(PROJECT_ROOT, "tests", "logs")
    os.makedirs(log_dir, exist_ok=True)

    stdout_path = os.path.join(log_dir, "streamlit_stdout.log")
    stderr_path = os.path.join(log_dir, "streamlit_stderr.log")

    stdout_file = open(stdout_path, "w")
    stderr_file = open(stderr_path, "w")

    # Start Streamlit server DEPUIS LA RACINE DU PROJET
    cmd = [
        "streamlit", "run", "app.py",
        "--server.port", str(TEST_PORT),
        "--server.runOnSave", "false",
        "--browser.serverAddress", "localhost",
        "--logger.level", "debug",
        "--server.fileWatcherType", "none",
        "--server.headless", "true"
    ]

    print(f"Launching: {' '.join(cmd)}")
    print(f"From directory: {PROJECT_ROOT} (app.py exists: {os.path.exists(os.path.join(PROJECT_ROOT, 'app.py'))})")
    print(f"Logs going to: {log_dir}")

    process = subprocess.Popen(
        cmd,
        stdout=stdout_file,
        stderr=stderr_file,
        env=env,
        cwd=PROJECT_ROOT,  # CRITIQUE: laucnh from the root
        preexec_fn=os.setsid
    )

    # Register cleanup function
    def cleanup():
        print("\n=== Cleaning up Streamlit server ===")
        stdout_file.close()
        stderr_file.close()

        if process.poll() is None:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                process.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass

        # Nettoyer les processus restants
        subprocess.run(["pkill", "-f", "streamlit"], capture_output=True, shell=True)
        time.sleep(1)

    atexit.register(cleanup)

    # Wait for server to start
    max_retries = 60
    for i in range(max_retries):
        try:
            response = requests.get(f"http://localhost:{TEST_PORT}/_stcore/health", timeout=2)
            if response.status_code == 200:
                print("✓ Streamlit server started successfully")
                time.sleep(5)  # Attendre que tout soit initialisé
                break
        except Exception as e:
            if i % 10 == 0:
                print(f"Waiting for Streamlit server... ({i+1}/{max_retries})")

            if i == max_retries - 1:
                print("Failed to start Streamlit server")
                # Afficher les logs d'erreur
                try:
                    stderr_file.flush()
                    with open(stderr_path, "r") as f:
                        lines = f.readlines()
                        print(f"Last 20 lines of stderr:\n{''.join(lines[-20:])}")
                except:
                    pass
                cleanup()
                raise RuntimeError(f"Failed to start Streamlit server after {max_retries} seconds")
            time.sleep(1)

    print("Streamlit server started...")
    time.sleep(5)
    yield process

    # Cleanup
    cleanup()
    atexit.unregister(cleanup)

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

# ============ MOCK FIXTURES ============

@pytest.fixture
def mock_db_manager():
    """Mock database manager for testing."""
    with patch('shared.database.db_manager') as mock_db:
        # Setup mock database with test users
        mock_users = [
            {
                "id": "test1",
                "name": "Test User 1",
                "email": "test1@example.com",
                "is_active": True,
                "profile": {"role": "user", "rights": ["read", "write"]},
                "metadata": {"is_default": True}
            },
            {
                "id": "test2",
                "name": "Test User 2",
                "email": "test2@example.com",
                "is_active": True,
                "profile": {"role": "admin", "rights": ["read", "write", "delete"]},
                "metadata": {"is_default": True}
            }
        ]

        mock_db.get_user.side_effect = lambda user_id: next(
            (user for user in mock_users if user["id"] == user_id), None
        )
        mock_db.get_all_users.return_value = mock_users
        mock_db.create_user.return_value = "new_user_id"
        mock_db.update_user.return_value = True
        mock_db.delete_user.return_value = True
        mock_db.update_last_login.return_value = None

        yield mock_db

@pytest.fixture
def mock_user_manager(mock_db_manager):
    """Mock user manager for testing."""
    with patch('shared.users.user_manager') as mock_user_mgr:
        mock_user_mgr.db = mock_db_manager

        mock_user_mgr.get_user.side_effect = mock_db_manager.get_user
        mock_user_mgr.get_all_users.return_value = {
            user["id"]: user for user in mock_db_manager.get_all_users()
        }
        mock_user_mgr.create_user.return_value = "new_user_id"
        mock_user_mgr.delete_user.return_value = True
        mock_user_mgr.update_user.return_value = True
        mock_user_mgr.update_last_login.return_value = None

        yield mock_user_mgr

# file name: conftest.py (updated patch_database fixture)

# file name: conftest.py (FIXED patch_database fixture)

@pytest.fixture(autouse=True)
def patch_database():
    """Patch database to properly initialize for tests."""
    import os
    from unittest.mock import patch

    # Ensure TEST_MODE is set
    os.environ["TEST_MODE"] = "true"

    # Track if we've initialized
    initialized = False

    def mock_init_database(use_memory=False, db_path=None):
        nonlocal initialized

        # Import here to avoid circular imports
        from shared.database import init_database as real_init_database
        from shared.database import Base
        from shared.users import UserTable
        from shared.conversation import ConversationTable, MessageTable

        # Always use in-memory for tests
        db = real_init_database(use_memory=True, db_path=None)

        # Create tables if not already done
        if not initialized:
            Base.metadata.create_all(db._engine)
            db._tables_created = True
            initialized = True
            log("info", "Database tables created for tests")

        return db

    # Patch app.init_database to use our mock
    with patch('app.init_database', side_effect=mock_init_database):
        # Also need to patch the database in conversation_ui module
        with patch('conversation_ui.conversation_manager._ensure_tables_exist', return_value=True):
            yield

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
