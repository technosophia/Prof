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

warnings.filterwarnings("ignore", category=UserWarning, module="streamlit.runtime.scriptrunner_utils")
warnings.filterwarnings("ignore", category=UserWarning, module="streamlit.runtime.state.session_state_proxy")

# Add the project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ============ CONFIGURATION ============
TEST_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "test_config.json"
)

print(f"Looking for test config at: {TEST_CONFIG_PATH}")

if not os.path.exists(TEST_CONFIG_PATH):
    project_root = os.path.dirname(TEST_CONFIG_PATH)
    alt_path = os.path.join(project_root, "tests", "test_config.json")
    print(f"Test config not found at primary location, trying: {alt_path}")
    if os.path.exists(alt_path):
        TEST_CONFIG_PATH = alt_path
    else:
        raise FileNotFoundError(f"Could not find test_config.json. Tried: {TEST_CONFIG_PATH} and {alt_path}")

print(f"Loading test config from: {TEST_CONFIG_PATH}")

with open(TEST_CONFIG_PATH, 'r') as f:
    TEST_CONFIG = json.load(f)

print(f"Test config loaded. Available LLMs: {list(TEST_CONFIG.get('llms', {}).keys())}")

# ============ SESSION FIXTURES ============

@pytest.fixture(scope="function", autouse=True)
def setup_test_environment():
    """Setup test environment before any tests run."""
    os.environ["TEST_MODE"] = "true"
    os.environ["CONFIG_FILE"] = TEST_CONFIG_PATH
    os.environ["PLAYWRIGHT_ASYNCIO"] = "0"  # Important pour éviter le conflit

    print(f"\n=== TEST ENVIRONMENT SETUP ===")
    print(f"TEST_MODE: {os.getenv('TEST_MODE')}")
    print(f"CONFIG_FILE: {os.getenv('CONFIG_FILE')}")
    print(f"Mock LLM in config: {'mock' in TEST_CONFIG.get('llms', {})}")
    print("=" * 30 + "\n")

    yield

    if "TEST_MODE" in os.environ:
        del os.environ["TEST_MODE"]
    if "CONFIG_FILE" in os.environ:
        del os.environ["CONFIG_FILE"]
    if "PLAYWRIGHT_ASYNCIO" in os.environ:
        del os.environ["PLAYWRIGHT_ASYNCIO"]

@pytest.fixture(scope="function")
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

# conftest.py - Modifier la fixture browser

@pytest.fixture(scope="function")
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
        launch_options["slow_mo"] = 100  # Ralentir pour voir ce qui se passe
    else:
        print(f"🚀 Launching browser in HEADLESS mode")

    browser = playwright.chromium.launch(**launch_options)

    yield browser

    browser.close()

# conftest.py - Ajouter cette fixture

@pytest.fixture(scope="function")
def browser_context(browser, request):
    """Create browser context with video recording for headed mode."""
    # Créer le contexte avec plus d'options de débogage en mode headed
    context_options = {
        "viewport": {"width": 1280, "height": 720},
        "ignore_https_errors": True,
    }

    # Activer l'enregistrement vidéo uniquement en mode headed ou sur demande
    if request.config.getoption("--headed") or os.getenv("PYTEST_RECORD_VIDEO"):
        # Créer un répertoire pour les vidéos
        video_dir = os.path.join("tests", "videos")
        os.makedirs(video_dir, exist_ok=True)

        # Nom du test pour le fichier vidéo
        test_name = request.node.name.replace("[", "_").replace("]", "_")
        video_path = os.path.join(video_dir, f"{test_name}.webm")

        context_options["record_video_dir"] = "tests/videos"
        context_options["record_video_size"] = {"width": 1280, "height": 720}

    context = browser.new_context(**context_options)

    yield context

    # Fermer le contexte
    context.close()

@pytest.fixture(scope="function")
def streamlit_server():
    """Start Streamlit server for testing - runs once per session."""
    # Kill any existing Streamlit process
    subprocess.run(["pkill", "-f", "streamlit"], capture_output=True, shell=True)
    time.sleep(1)

    # Create test environment
    env = os.environ.copy()
    env["TEST_MODE"] = "true"
    env["CONFIG_FILE"] = "test_config.json"
    env["PYTHONPATH"] = os.path.dirname(os.path.abspath(__file__))

    # Start Streamlit server
    cmd = [
        "streamlit", "run", "app.py",
        "--server.port", "8502",
        "--server.runOnSave", "false",
        "--browser.serverAddress", "localhost",
        "--logger.level", "info",
        "--server.fileWatcherType", "none"
    ]

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        preexec_fn=os.setsid
    )

    # Register cleanup function
    def cleanup():
        if process.poll() is None:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                process.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    atexit.register(cleanup)

    # Wait for server to start
    max_retries = 30
    for i in range(max_retries):
        try:
            response = requests.get("http://localhost:8502/_stcore/health", timeout=2)
            if response.status_code == 200:
                print("✓ Streamlit server started successfully")
                break
        except:
            if i == max_retries - 1:
                cleanup()
                raise RuntimeError("Failed to start Streamlit server after 30 seconds")
            time.sleep(1)

    time.sleep(2)
    yield process

    # Cleanup after tests
    cleanup()
    atexit.unregister(cleanup)
    subprocess.run(["pkill", "-f", "streamlit"], capture_output=True, shell=True)
    time.sleep(1)

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
    # Set longer timeout for slow Streamlit
    page.set_default_timeout(30000)
    yield page
    page.close()

# ============ MOCK FIXTURES ============

@pytest.fixture(autouse=True)
def patch_config():
    """Patch the get_config function for all tests."""
    os.environ["TEST_MODE"] = "true"

    with patch('shared.config.get_config', return_value=TEST_CONFIG):
        with patch('shared.config.init_config', return_value=TEST_CONFIG):
            yield

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

@pytest.fixture(autouse=True)
def patch_database():
    """Patch database to use test config."""
    with patch('app.init_database') as mock_init_db:
        mock_init_db.return_value = None
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
