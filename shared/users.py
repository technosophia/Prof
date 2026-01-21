"""
User management with database backend.
"""
from typing import Dict, List, Optional, Any

from shared.database import db_manager
from shared.logging import log


class UserManager:
    """Manages user operations."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # Initialize only once
        if not hasattr(self, '_initialized'):
            self.db = db_manager  # Use the global database manager
            self._initialized = True

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get a user by ID."""
        return self.db.get_user(user_id)

    def get_all_users(self) -> Dict[str, Dict[str, Any]]:
        """Get all users as a dictionary with user_id as key."""
        users = self.db.get_all_users()
        return {user["id"]: user for user in users}

    def create_user(self, name: str, email: Optional[str] = None,
                   profile: Optional[Dict] = None) -> str:
        """Create a new user."""
        # Validate name
        if not name or not name.strip():
            raise ValueError("User name cannot be empty")

        # Create user in database
        user_id = self.db.create_user(name.strip(), email, profile)

        log("info", f"User created: {name} ({user_id})")
        return user_id

    def delete_user(self, user_id: str) -> bool:
        """Delete a user."""
        if user_id in ["test1", "test2"]:
            log("warning", f"Cannot delete default test user: {user_id}")
            return False

        success = self.db.delete_user(user_id)
        if success:
            log("info", f"User deleted: {user_id}")
        return success

    def update_user(self, user_id: str, **kwargs) -> bool:
        """Update user information."""
        return self.db.update_user(user_id, **kwargs)

    def update_last_login(self, user_id: str):
        """Update user's last login timestamp."""
        self.db.update_last_login(user_id)

    def search_users(self, query: str) -> List[Dict[str, Any]]:
        """Search users by name or email."""
        users = self.db.get_all_users()
        query_lower = query.lower()

        return [
            user for user in users
            if query_lower in user["name"].lower() or
               (user["email"] and query_lower in user["email"].lower())
        ]

    def get_active_users(self) -> List[Dict[str, Any]]:
        """Get all active users."""
        users = self.db.get_all_users()
        return [user for user in users if user.get("is_active", True)]

    def get_user_count(self) -> int:
        """Get total number of users."""
        users = self.db.get_all_users()
        return len(users)


# Global user manager instance
user_manager = UserManager()


def init_user_manager():
    """Initialize the user manager."""
    return user_manager
