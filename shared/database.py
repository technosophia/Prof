"""
Unified database management with SQLAlchemy.
Supports both in-memory (for testing) and persistent storage.
"""
import os
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

from sqlalchemy import create_engine, Column, String, Integer, Text, DateTime, Boolean, JSON
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from contextlib import contextmanager

from shared.config import get_config
from shared.logging import log

Base = declarative_base()

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


class DatabaseManager:
    """Manages database connections and operations."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
            cls._instance._engine = None
            cls._instance._session_factory = None
            cls._instance._in_memory = False
            cls._instance._initialized_flag = False  # Track if initialize() was called
        return cls._instance

    def __init__(self):
        # Don't reinitialize if already done
        pass

    def is_initialized(self):
        """Check if database is initialized."""
        return self._engine is not None

    def initialize(self, use_memory: bool = False, db_path: Optional[str] = None, create_default_users: bool = True):
        """Initialize the database connection."""
        if self._engine is not None:
            return

        if use_memory:
            # In-memory database for testing
            self._engine = create_engine('sqlite:///:memory:', echo=False)
            self._in_memory = True
            log("info", "Initialized in-memory database for testing")
        else:
            # Persistent database
            if db_path is None:
                # Use config or default path
                db_dir = get_config().get("database.path", "data")
                db_path = os.path.join(db_dir, "app.db")

            # Ensure directory exists
            db_dir = os.path.dirname(db_path)
            if db_dir:  # Not empty string
                try:
                    Path(db_dir).mkdir(parents=True, exist_ok=True)
                    log("debug", f"Ensured directory exists: {db_dir}")
                except Exception as e:
                    log("error", f"Failed to create directory {db_dir}: {e}")
                    raise

            db_url = f'sqlite:///{db_path}'
            try:
                self._engine = create_engine(db_url, echo=False)
                self._in_memory = False
                log("info", f"Initialized database at {db_path}")
            except Exception as e:
                log("error", f"Failed to create database at {db_path}: {e}")
                raise

        # Create all registered tables
        try:
            Base.metadata.create_all(self._engine)
            self._session_factory = sessionmaker(bind=self._engine)
            self._initialized_flag = True
            log("info", "Database tables created successfully")
        except Exception as e:
            log("error", f"Failed to create database tables: {e}")
            # Clean up on failure
            self._engine = None
            self._session_factory = None
            raise

        # Create default users if requested
        if create_default_users:
            try:
                self.create_default_users()
            except Exception as e:
                log("error", f"Failed to create default users: {e}")
                # Don't raise - we can continue without default users

    @contextmanager
    def get_session(self) -> Session:
        """Get a database session with context manager."""
        if self._engine is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")

        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            log("error", f"Database error: {e}", exc_info=True)
            raise
        finally:
            session.close()

    def register_table(self, table_name: str, table_class):
        """Register a new table definition."""
        # Store table class
        if not hasattr(self, '_registered_tables'):
            self._registered_tables = {}

        self._registered_tables[table_name] = table_class

        # Create table if engine exists
        if self._engine:
            table_class.__table__.create(bind=self._engine, checkfirst=True)
            log("debug", f"Registered table: {table_name}")

    def create_default_users(self):
        """Create default test users if needed."""
        with self.get_session() as session:
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

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get a user by ID."""
        with self.get_session() as session:
            user = session.query(UserTable).filter_by(id=user_id).first()
            if user:
                return self._user_to_dict(user)
            return None

    def get_all_users(self) -> List[Dict[str, Any]]:
        """Get all users."""
        with self.get_session() as session:
            users = session.query(UserTable).order_by(UserTable.created_at).all()
            return [self._user_to_dict(user) for user in users]

    def create_user(self, name: str, email: Optional[str] = None,
                   profile: Optional[Dict] = None) -> str:
        """Create a new user."""
        import uuid

        user_id = str(uuid.uuid4())

        with self.get_session() as session:
            user = UserTable(
                id=user_id,
                name=name,
                email=email,
                created_at=datetime.utcnow(),
                is_active=True,
                profile=profile or {"role": "user", "rights": ["read"]},
                user_metadata={"created_via": "ui"}
            )
            session.add(user)

        log("info", f"Created user: {name} (ID: {user_id})")
        return user_id

    def update_user(self, user_id: str, **kwargs) -> bool:
        """Update user information."""
        with self.get_session() as session:
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
                user.last_login = datetime.utcnow()

            session.commit()
            return True

    def delete_user(self, user_id: str) -> bool:
        """Delete a user."""
        with self.get_session() as session:
            user = session.query(UserTable).filter_by(id=user_id).first()
            if not user:
                return False

            session.delete(user)
            log("info", f"Deleted user: {user.name} (ID: {user_id})")
            return True

    def update_last_login(self, user_id: str):
        """Update user's last login timestamp."""
        self.update_user(user_id, last_login=datetime.utcnow())

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


# Global database manager instance
db_manager = DatabaseManager()


def init_database(use_memory: bool = False, db_path: Optional[str] = None, create_default_users: bool = True):
    """Initialize the database."""
    db_manager.initialize(use_memory=use_memory, db_path=db_path, create_default_users=create_default_users)
    return db_manager


def get_db():
    """Get the database manager instance."""
    return db_manager
