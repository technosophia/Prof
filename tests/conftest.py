"""
Pytest configuration and fixtures.
"""
import sys
import os
import json
import pytest
from unittest.mock import patch, MagicMock

# Add the project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load test config
TEST_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "test_config.json"
)

with open(TEST_CONFIG_PATH, 'r') as f:
    TEST_CONFIG = json.load(f)


@pytest.fixture(autouse=True)
def patch_config():
    """Patch the get_config function for all tests."""
    with patch('shared.config.get_config', return_value=TEST_CONFIG):
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
