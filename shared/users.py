"""
User management with database backend.
"""
import uuid
from typing import Dict, List, Optional, Any
from datetime import datetime

from sqlalchemy import Column, String, Integer, Text, DateTime, Boolean, JSON
from sqlalchemy.orm import Session

from shared.database import Base, db_manager
from shared.logging import log


class UserTable(Base):
    """User model for database."""
    __tablename__ = 'users'

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    profile = Column(JSON, default={})  # For future rights/permissions
    user_metadata = Column(JSON, default={})  # Renamed from 'metadata' to avoid conflict


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

            # Ensure the users table exists when UserManager is initialized
            self._ensure_table_exists()

    def _ensure_table_exists(self):
        """Ensure the users table exists."""
        if self.db.is_initialized():
            try:
                UserTable.__table__.create(bind=self.db._engine, checkfirst=True)
                log("debug", "Users table ensured to exist")
            except Exception as e:
                log("error", f"Failed to ensure users table exists: {e}")

    def create_default_users(self):
        """Create default test users if needed."""
        with self.db.get_session() as session:
            # Check if we have any users
            user_count = session.query(UserTable).count()

            if user_count == 0:
                # Create test users
                test_users = [
                    {
                        "id": "test1",
                        "name": "Test User 1",
                        "email": "test1@example.com",
                        "profile": {"role": "user", "rights": ["read", "write"]}
                    },
                    {
                        "id": "test2",
                        "name": "Test User 2",
                        "email": "test2@example.com",
                        "profile": {"role": "admin", "rights": ["read", "write", "delete"]}
                    }
                ]

                for user_data in test_users:
                    user = UserTable(
                        id=user_data["id"],
                        name=user_data["name"],
                        email=user_data["email"],
                        created_at=datetime.utcnow(),
                        is_active=True,
                        profile=user_data.get("profile", {}),
                        user_metadata={"is_default": True}
                    )
                    session.add(user)

                log("info", f"Created {len(test_users)} default test users")

    def _user_to_dict(self, user: UserTable) -> Dict[str, Any]:
        """Convert SQLAlchemy user object to dictionary."""
        return {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "last_login": user.last_login.isoformat() if user.last_login else None,
            "is_active": user.is_active,
            "profile": user.profile or {},
            "metadata": user.user_metadata or {}  # Map back to 'metadata' in dict
        }

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get a user by ID."""
        with self.db.get_session() as session:
            user = session.query(UserTable).filter_by(id=user_id).first()
            if user:
                return self._user_to_dict(user)
            return None

    def get_all_users(self) -> List[Dict[str, Any]]:
        """Get all users."""
        with self.db.get_session() as session:
            users = session.query(UserTable).order_by(UserTable.created_at).all()
            return [self._user_to_dict(user) for user in users]

    def create_user(self, name: str, email: Optional[str] = None,
                   profile: Optional[Dict] = None) -> str:
        """Create a new user."""
        # Validate name
        if not name or not name.strip():
            raise ValueError("User name cannot be empty")

        user_id = str(uuid.uuid4())

        with self.db.get_session() as session:
            user = UserTable(
                id=user_id,
                name=name.strip(),
                email=email,
                created_at=datetime.utcnow(),
                is_active=True,
                profile=profile or {"role": "user", "rights": ["read"]},
                user_metadata={"created_via": "ui"}
            )
            session.add(user)

        log("info", f"Created user: {name.strip()} (ID: {user_id})")
        return user_id

    def update_user(self, user_id: str, **kwargs) -> bool:
        """Update user information."""
        with self.db.get_session() as session:
            user = session.query(UserTable).filter_by(id=user_id).first()
            if not user:
                return False

            for key, value in kwargs.items():
                if key == "user_metadata":
                    # Already the correct name
                    pass
                elif key == "metadata":  # Backward compatibility
                    key = "user_metadata"

                if hasattr(user, key):
                    setattr(user, key, value)
                elif key == "profile":
                    # Merge profiles
                    current_profile = user.profile or {}
                    current_profile.update(value)
                    user.profile = current_profile

            # Update last login if specified
            if "last_login" in kwargs:
                # Use the value passed in kwargs, not datetime.utcnow()
                user.last_login = kwargs["last_login"]

            # NO explicit commit here - the context manager handles it
            return True

    def delete_user(self, user_id: str) -> bool:
        """Delete a user."""
        with self.db.get_session() as session:
            user = session.query(UserTable).filter_by(id=user_id).first()
            if not user:
                return False

            session.delete(user)
            log("info", f"Deleted user: {user.name} (ID: {user_id})")
            # NO explicit commit here - the context manager handles it
            return True

    def update_last_login(self, user_id: str):
        """Update user's last login timestamp."""
        self.update_user(user_id, last_login=datetime.utcnow())

    def get_all_users_dict(self) -> Dict[str, Dict[str, Any]]:
        """Get all users as a dictionary with user_id as key."""
        users = self.get_all_users()
        return {user["id"]: user for user in users}

    def search_users(self, query: str) -> List[Dict[str, Any]]:
        """Search users by name or email."""
        users = self.get_all_users()
        query_lower = query.lower()

        return [
            user for user in users
            if query_lower in user["name"].lower() or
               (user["email"] and query_lower in user["email"].lower())
        ]

    def get_active_users(self) -> List[Dict[str, Any]]:
        """Get all active users."""
        users = self.get_all_users()
        return [user for user in users if user.get("is_active", True)]

    def get_user_count(self) -> int:
        """Get total number of users."""
        users = self.get_all_users()
        return len(users)


# Global user manager instance
user_manager = UserManager()


def init_user_manager():
    """Initialize the user manager."""
    return user_manager


# For backward compatibility - alias the method that app.py uses
def get_all_users() -> Dict[str, Dict[str, Any]]:
    """Backward compatibility alias for UserManager.get_all_users_dict()"""
    return user_manager.get_all_users_dict()
