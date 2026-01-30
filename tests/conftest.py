# file name: conftest.py
"""
Pytest configuration and fixtures.
"""
import sys
import os
import json
import pytest
from unittest.mock import patch, MagicMock
from playwright.sync_api import sync_playwright

import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="streamlit.runtime.scriptrunner_utils")
warnings.filterwarnings("ignore", category=UserWarning, module="streamlit.runtime.state.session_state_proxy")

# Add the project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# FIXED: Find test_config.json relative to this file
TEST_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "test_config.json"
)

print(f"Looking for test config at: {TEST_CONFIG_PATH}")

# Check if the file exists
if not os.path.exists(TEST_CONFIG_PATH):
    # Try looking from the project root
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

@pytest.fixture(scope="function", autouse=True)
def setup_test_environment():
    """Setup test environment before any tests run."""
    # Set TEST_MODE environment variable
    os.environ["TEST_MODE"] = "true"

    # Also set CONFIG_FILE to ensure test config is used
    os.environ["CONFIG_FILE"] = TEST_CONFIG_PATH

    print(f"\n=== TEST ENVIRONMENT SETUP ===")
    print(f"TEST_MODE: {os.getenv('TEST_MODE')}")
    print(f"CONFIG_FILE: {os.getenv('CONFIG_FILE')}")
    print(f"Mock LLM in config: {'mock' in TEST_CONFIG.get('llms', {})}")
    print("=" * 30 + "\n")

    yield

    # Cleanup
    if "TEST_MODE" in os.environ:
        del os.environ["TEST_MODE"]
    if "CONFIG_FILE" in os.environ:
        del os.environ["CONFIG_FILE"]

@pytest.fixture(scope="function")
def playwright():
    """Playwright session fixture."""
    with sync_playwright() as p:
        yield p

@pytest.fixture(scope="function")
def browser(playwright):
    """Browser session fixture."""
    browser = playwright.chromium.launch()
    yield browser
    browser.close()

@pytest.fixture
def page(browser):
    """Page fixture for each test."""
    context = browser.new_context()
    page = context.new_page()
    yield page
    context.close()

@pytest.fixture(autouse=True)
def patch_config():
    """Patch the get_config function for all tests."""
    # Ensure TEST_MODE is set
    os.environ["TEST_MODE"] = "true"

    # Patch the config module
    with patch('shared.config.get_config', return_value=TEST_CONFIG):
        # Also patch init_config to return test config
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

        # Setup user manager methods
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
        # Make it use in-memory database
        mock_init_db.return_value = None
        yield


# Ajouter ces fixtures si elles n'existent pas déjà

@pytest.fixture(scope="function")
def test_context():
    """Test context to store state between steps."""
    return {}

# Optionnel: Fixture spécifique pour les tests Test
@pytest.fixture
def test_module_enabled():
    """Ensure Test module is enabled for testing."""
    # You might need to patch or enable the Test module here
    return True

import pytest
import os
from _pytest.nodes import Item
from _pytest.reports import TestReport

@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item: Item, call: pytest.CallInfo) -> None:
    """
    Hook pour prendre un screenshot automatique en cas d'échec d'un test.
    Le screenshot est sauvegardé dans tests/debug/errors/error_<test_name>.png
    """
    # Exécute tous les autres hooks pour obtenir le report final
    outcome = yield
    rep: TestReport = outcome.get_result()

    # On ne s'intéresse qu'aux échecs pendant la phase "call" (exécution du test)
    # (on ignore les erreurs de setup/teardown pour éviter les doublons)
    if rep.when == "call" and rep.failed:
        # Vérifie que la fixture 'page' existe bien dans le test
        if "page" in item.fixturenames:
            page = item.funcargs["page"]

            # Crée le répertoire de destination s'il n'existe pas
            error_dir = os.path.join("tests", "debug", "errors")
            os.makedirs(error_dir, exist_ok=True)

            # Nom du screenshot : error_<nom_du_test>.png
            # item.name est le nom du test (ex: test_create_conversation_and_send_a_message)
            # On nettoie les caractères problématiques pour le nom de fichier
            safe_test_name = "".join(c if c.isalnum() else "_" for c in item.name)
            filename = f"error_{safe_test_name}.png"
            filepath = os.path.join(error_dir, filename)

            try:
                page.screenshot(path=filepath, full_page=True)
                print(f"\nScreenshot d'erreur sauvegardé : {filepath}")

                # Optionnel : attacher le screenshot au report (utile pour pytest-html ou Allure)
                if hasattr(rep, "longrepr"):
                    rep.longrepr = f"{rep.longrepr}\n[Screenshot] {filepath}"
            except Exception as e:
                print(f"\nImpossible de prendre le screenshot : {e}")
