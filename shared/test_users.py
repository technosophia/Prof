"""
Tests for the user management module.
"""
import pytest
import sys
import os
from unittest.mock import MagicMock, patch
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared.users import UserManager


class TestUserManager:
    """Test the UserManager class."""

    def setup_method(self):
        """Setup for each test."""
        self.user_manager = UserManager()
        self.user_manager.db = MagicMock()

    def test_singleton(self):
        """Test that UserManager is a singleton."""
        user_manager1 = UserManager()
        user_manager2 = UserManager()
        assert user_manager1 is user_manager2

    def test_get_user(self):
        """Test getting a user."""
        mock_user = {
            "id": "test1",
            "name": "Test User",
            "email": "test@example.com"
        }
        self.user_manager.db.get_user.return_value = mock_user

        user = self.user_manager.get_user("test1")
        assert user == mock_user
        self.user_manager.db.get_user.assert_called_once_with("test1")

    def test_get_all_users(self):
        """Test getting all users."""
        mock_users = [
            {"id": "test1", "name": "User 1"},
            {"id": "test2", "name": "User 2"}
        ]
        self.user_manager.db.get_all_users.return_value = mock_users

        users = self.user_manager.get_all_users()
        assert len(users) == 2
        assert users["test1"]["name"] == "User 1"
        assert users["test2"]["name"] == "User 2"

    def test_create_user_success(self):
        """Test successful user creation."""
        self.user_manager.db.create_user.return_value = "new_user_id"

        user_id = self.user_manager.create_user(
            name="New User",
            email="new@example.com",
            profile={"role": "admin"}
        )

        assert user_id == "new_user_id"
        self.user_manager.db.create_user.assert_called_once_with(
            "New User", "new@example.com", {"role": "admin"}
        )

    def test_create_user_empty_name(self):
        """Test user creation with empty name."""
        with pytest.raises(ValueError, match="User name cannot be empty"):
            self.user_manager.create_user("")

    def test_create_user_whitespace_name(self):
        """Test user creation with whitespace only name."""
        with pytest.raises(ValueError, match="User name cannot be empty"):
            self.user_manager.create_user("   ")

    def test_delete_user_success(self):
        """Test successful user deletion."""
        self.user_manager.db.delete_user.return_value = True

        success = self.user_manager.delete_user("some_user_id")
        assert success == True
        self.user_manager.db.delete_user.assert_called_once_with("some_user_id")

    def test_delete_user_default(self):
        """Test deleting default users should fail."""
        success = self.user_manager.delete_user("test1")
        assert success == False
        self.user_manager.db.delete_user.assert_not_called()

        success = self.user_manager.delete_user("test2")
        assert success == False
        self.user_manager.db.delete_user.assert_not_called()

    def test_update_user(self):
        """Test updating a user."""
        self.user_manager.db.update_user.return_value = True

        success = self.user_manager.update_user(
            "test1",
            name="Updated Name",
            email="updated@example.com"
        )

        assert success == True
        self.user_manager.db.update_user.assert_called_once_with(
            "test1", name="Updated Name", email="updated@example.com"
        )

    def test_update_last_login(self):
        """Test updating last login."""
        self.user_manager.update_last_login("test1")
        self.user_manager.db.update_last_login.assert_called_once_with("test1")

    def test_search_users(self):
        """Test searching users."""
        mock_users = [
            {"id": "1", "name": "John Doe", "email": "john@example.com"},
            {"id": "2", "name": "Jane Smith", "email": "jane@example.com"},
            {"id": "3", "name": "Bob Johnson", "email": "bob@test.com"}
        ]
        self.user_manager.db.get_all_users.return_value = mock_users

        # Search by name (case insensitive)
        results = self.user_manager.search_users("john")
        assert len(results) == 2  # John Doe and Bob Johnson

        # Search by email
        results = self.user_manager.search_users("example.com")
        assert len(results) == 2  # John and Jane

        # Search with no results
        results = self.user_manager.search_users("nonexistent")
        assert len(results) == 0

    def test_get_active_users(self):
        """Test getting active users."""
        mock_users = [
            {"id": "1", "name": "Active User", "is_active": True},
            {"id": "2", "name": "Inactive User", "is_active": False},
            {"id": "3", "name": "Another Active", "is_active": True},
            {"id": "4", "name": "No Status"}  # Should default to active
        ]
        self.user_manager.db.get_all_users.return_value = mock_users

        active_users = self.user_manager.get_active_users()
        assert len(active_users) == 3  # Two active + one without status

    def test_get_user_count(self):
        """Test getting user count."""
        mock_users = [
            {"id": "1", "name": "User 1"},
            {"id": "2", "name": "User 2"},
            {"id": "3", "name": "User 3"}
        ]
        self.user_manager.db.get_all_users.return_value = mock_users

        count = self.user_manager.get_user_count()
        assert count == 3


def test_init_user_manager():
    """Test the init_user_manager function."""
    from shared.users import user_manager, init_user_manager

    # init_user_manager should return the singleton
    result = init_user_manager()
    assert result is user_manager
