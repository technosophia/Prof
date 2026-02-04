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
    from shared.database import db_manager, init_database
    from shared.users import user_manager
    from shared.common import get_config
    import tempfile
    from modules.rag_manager import rag_manager
    # Set environment variables
    os.environ["TEST_MODE"] = "true"
    os.environ["CONFIG_FILE"] = "tests/test_config.json"
    os.environ["PLAYWRIGHT_ASYNCIO"] = "0"

    original_cwd = os.getcwd()

    print(f"\n=== DATABASE CLEANUP (FUNCTION) ===")
    # 1. Initialize the database
    db_config_path = get_config().get("database", {}).get("path", ".")
    db_full_path = os.path.abspath(db_config_path)
    db_path = db_config_path + "/app.db"
    print(f"Initializing database...{db_path}")
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

    # 3. Setup RAG test data (WITH TEST_MODE still set)
    test_content = """The address of Kevin is 1 place du Louvre, Paris.
Kevin works as a software engineer at TechCorp.
His phone number is +33 1 23 45 67 89."""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(test_content)
        temp_path = f.name

    try:
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

        # Restaurer le répertoire original
        if original_cwd != os.getcwd():
            os.chdir(original_cwd)
            print(f"Restored CWD to: {original_cwd}")

        yield filename
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

        import shutil
        for item in os.listdir(db_full_path):
            item_path = os.path.join(db_full_path, item)
            try:
                if os.path.isfile(item_path) or os.path.islink(item_path):
                    os.unlink(item_path)
                    print(f"  Deleted file: {item}")
                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                    print(f"  Deleted directory: {item}")
            except Exception as e:
                print(f"  Failed to delete {item_path}: {e}")

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
        launch_options["slow_mo"] = 200  # Ralentir pour voir ce qui se passe
    else:
        launch_options["slow_mo"] = 200
        print(f"🚀 Launching browser in HEADLESS mode")

    browser = playwright.chromium.launch(**launch_options)

    yield browser

    browser.close()

@pytest.fixture(scope=SCOPE)
def streamlit_server(setup_test_environment):
    """Start Streamlit server for testing - runs once per session."""
    # Kill any existing Streamlit process
    subprocess.run(["pkill", "-f", "streamlit"], capture_output=True, shell=True)
    time.sleep(2)

    # Create test environment
    env = os.environ.copy()
    env["TEST_MODE"] = "true"

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
    time.sleep(2)
    yield process
    # process.terminate()
    # try:
    #     process.wait(timeout=5) # Wait up to 5 seconds for it to release file handles
    # except subprocess.TimeoutExpired:
    #     print("[WARNING] Streamlit didn't stop, killing it...")
    #     process.kill()
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
