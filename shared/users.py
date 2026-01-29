"""
User management with database backend.
"""
import uuid
from typing import Dict, List, Optional, Any
from datetime import datetime

from sqlalchemy import Column, String, Integer, Text, DateTime, Boolean, JSON, func
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
            # NOTE: We don't call _ensure_table_exists() here anymore
            # It will be called when needed
            # Initialize callback registry
            self._before_delete_callbacks = []

    def _ensure_table_exists(self):
        """Ensure the users table exists."""
        if not self.db.is_initialized():
            log("warning", "Database not initialized, cannot ensure users table exists")
            return False

        try:
            UserTable.__table__.create(bind=self.db._engine, checkfirst=True)
            log("debug", "Users table ensured to exist")
            return True
        except Exception as e:
            log("error", f"Failed to ensure users table exists: {e}")
            return False

    def init_default_users(self):
        """Initialize default users. Call this after database is initialized."""
        # First ensure the table exists
        if not self._ensure_table_exists():
            log("error", "Cannot create default users: users table does not exist")
            return False

        # Then create default users if needed
        return self.create_default_users()

    def create_default_users(self):
        """Create default test users if needed."""
        # Double-check that database is initialized
        if not self.db.is_initialized():
            log("error", "Cannot create default users: database not initialized")
            return False

        with self.db.get_session() as session:
            try:
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
                    return True
                else:
                    log("debug", "Default users already exist, skipping creation")
                    return False
            except Exception as e:
                log("error", f"Failed to create default users: {e}")
                return False

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
        # Ensure table exists before querying
        self._ensure_table_exists()

        with self.db.get_session() as session:
            user = session.query(UserTable).filter_by(id=user_id).first()
            if user:
                return self._user_to_dict(user)
            return None

    def get_user_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a user by name (case-insensitive)."""
        # Ensure table exists before querying
        self._ensure_table_exists()

        with self.db.get_session() as session:
            user = session.query(UserTable).filter(
                func.lower(UserTable.name) == name.lower()
            ).first()
            if user:
                return self._user_to_dict(user)
            return None

    def get_all_users(self) -> List[Dict[str, Any]]:
        """Get all users."""
        # Ensure table exists before querying
        self._ensure_table_exists()

        with self.db.get_session() as session:
            users = session.query(UserTable).order_by(UserTable.created_at).all()
            return [self._user_to_dict(user) for user in users]

    def create_user(self, name: str, email: Optional[str] = None,
                   profile: Optional[Dict] = None) -> str:
        """Create a new user."""
        # Validate name
        if not name or not name.strip():
            raise ValueError("User name cannot be empty")

        # Ensure table exists before creating
        self._ensure_table_exists()

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
        # Ensure table exists before updating
        self._ensure_table_exists()

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

    def register_before_delete_callback(self, callback_func):
        """Register a callback to be executed before a user is deleted.

        Args:
            callback_func: Function that takes user_id as argument and returns bool
                         (True if cleanup successful, False otherwise)
        """
        if callback_func not in self._before_delete_callbacks:
            self._before_delete_callbacks.append(callback_func)
            log("debug", f"Registered before_delete callback: {callback_func.__name__}")

    def unregister_before_delete_callback(self, callback_func):
        """Unregister a before_delete callback."""
        if callback_func in self._before_delete_callbacks:
            self._before_delete_callbacks.remove(callback_func)
            log("debug", f"Unregistered before_delete callback: {callback_func.__name__}")

    def delete_user(self, user_id: str) -> bool:
        """Delete a user."""
        # Ensure table exists before deleting
        self._ensure_table_exists()

        # Execute all registered before_delete callbacks
        log("info", f"Executing before_delete callbacks for user {user_id}")
        all_successful = True

        for callback in self._before_delete_callbacks:
            try:
                success = callback(user_id)
                if not success:
                    log("warning", f"Callback {callback.__name__} failed for user {user_id}")
                    all_successful = False
                else:
                    log("debug", f"Callback {callback.__name__} succeeded for user {user_id}")
            except Exception as e:
                log("error", f"Callback {callback.__name__} raised exception: {e}")
                all_successful = False

        # If any callback failed, don't delete the user
        if not all_successful:
            log("error", f"Aborting user deletion for {user_id} due to callback failures")
            return False

        with self.db.get_session() as session:
            user = session.query(UserTable).filter_by(id=user_id).first()
            if not user:
                log("warning", f"User {user_id} not found for deletion")
                return False

            user_name = user.name
            session.delete(user)
            log("info", f"Deleted user: {user_name} (ID: {user_id})")
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


def init_user_manager(create_default_users: bool = True):
    """Initialize the user manager.

    Args:
        create_default_users: If True, create default test users if none exist.
    """
    # Don't create default users during tests or if database not initialized
    if create_default_users and user_manager.db.is_initialized():
        user_manager.init_default_users()
    return user_manager


# For backward compatibility - alias the method that app.py uses
def get_all_users() -> Dict[str, Dict[str, Any]]:
    """Backward compatibility alias for UserManager.get_all_users_dict()"""
    return user_manager.get_all_users_dict()
