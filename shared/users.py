"""
User management with database backend.
"""
import uuid
from typing import Dict, List, Optional, Any, Set
from datetime import datetime
from enum import Enum

from sqlalchemy import Column, String, Integer, Text, DateTime, Boolean, JSON, func, ForeignKey
from sqlalchemy.orm import Session, relationship, joinedload

from shared.database import Base, db_manager
from shared.common import _, log, get_config



class UserRole(Enum):
    """User roles enumeration."""
    ADMIN = "admin"
    MASTER = "master"
    NORMAL = "normal"


class UserTable(Base):
    """User model for database."""
    __tablename__ = 'users'

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    role = Column(String, default=UserRole.NORMAL.value)  # New: role field
    parent_id = Column(String, ForeignKey('users.id'), nullable=True)  # New: parent user
    profile = Column(JSON, default={})  # For preferences and other data
    user_metadata = Column(JSON, default={})

    # Relationships - FIXED: removed duplicate backref
    parent = relationship("UserTable", remote_side=[id], backref="child_users")
    # children property is available via backref: user.child_users


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
            # Initialize callback registry
            self._before_delete_callbacks = []
            self._profile_preferences_callbacks = []  # New: for extensible preferences

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
        """Create 7 default test users: 1 admin, 2 masters, 4 normal users."""
        # Double-check that database is initialized
        if not self.db.is_initialized():
            log("error", "Cannot create default users: database not initialized")
            return False

        with self.db.get_session() as session:
            try:
                # Check if we have any users
                user_count = session.query(UserTable).count()

                if user_count == 0:
                    # Create admin user
                    admin_user = UserTable(
                        id="admin",
                        name="System Administrator",
                        email="admin@example.com",
                        role=UserRole.ADMIN.value,
                        parent_id=None,
                        created_at=datetime.utcnow(),
                        is_active=True,
                        profile={"language": "en"},
                        user_metadata={"is_default": True, "created_by": "system"}
                    )
                    session.add(admin_user)

                    # Create master users
                    master1 = UserTable(
                        id="master1",
                        name="Master User 1",
                        email="master1@example.com",
                        role=UserRole.MASTER.value,
                        parent_id=None,
                        created_at=datetime.utcnow(),
                        is_active=True,
                        profile={"language": "en"},
                        user_metadata={"is_default": True, "created_by": "system"}
                    )
                    session.add(master1)

                    master2 = UserTable(
                        id="master2",
                        name="Master User 2",
                        email="master2@example.com",
                        role=UserRole.MASTER.value,
                        parent_id=None,
                        created_at=datetime.utcnow(),
                        is_active=True,
                        profile={"language": "fr"},
                        user_metadata={"is_default": True, "created_by": "system"}
                    )
                    session.add(master2)

                    # Create normal users for master1
                    normal1_m1 = UserTable(
                        id="normal1_m1",
                        name="Normal User 1 (Master 1)",
                        email="normal1_m1@example.com",
                        role=UserRole.NORMAL.value,
                        parent_id="master1",
                        created_at=datetime.utcnow(),
                        is_active=True,
                        profile={"language": "en"},
                        user_metadata={"is_default": True, "created_by": "system"}
                    )
                    session.add(normal1_m1)

                    normal2_m1 = UserTable(
                        id="normal2_m1",
                        name="Normal User 2 (Master 1)",
                        email="normal2_m1@example.com",
                        role=UserRole.NORMAL.value,
                        parent_id="master1",
                        created_at=datetime.utcnow(),
                        is_active=True,
                        profile={"language": "es"},
                        user_metadata={"is_default": True, "created_by": "system"}
                    )
                    session.add(normal2_m1)

                    # Create normal users for master2
                    normal1_m2 = UserTable(
                        id="normal1_m2",
                        name="Test User 1",
                        email="normal1_m2@example.com",
                        role=UserRole.NORMAL.value,
                        parent_id="master2",
                        created_at=datetime.utcnow(),
                        is_active=True,
                        profile={"language": "de"},
                        user_metadata={"is_default": True, "created_by": "system"}
                    )
                    session.add(normal1_m2)

                    normal2_m2 = UserTable(
                        id="normal2_m2",
                        name="Test User 2",
                        email="normal2_m2@example.com",
                        role=UserRole.NORMAL.value,
                        parent_id="master2",
                        created_at=datetime.utcnow(),
                        is_active=True,
                        profile={"language": "it"},
                        user_metadata={"is_default": True, "created_by": "system"}
                    )
                    session.add(normal2_m2)

                    log("info", f"Created 7 default users: 1 admin, 2 masters, 4 normal users")
                    return True
                else:
                    log("debug", "Default users already exist, skipping creation")
                    return False
            except Exception as e:
                log("error", f"Failed to create default users: {e}")
                return False

    def _user_to_dict(self, user: UserTable, include_children: bool = False) -> Dict[str, Any]:
        """Convert SQLAlchemy user object to dictionary."""
        result = {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "parent_id": user.parent_id,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "last_login": user.last_login.isoformat() if user.last_login else None,
            "is_active": user.is_active,
            "profile": user.profile or {},
            "metadata": user.user_metadata or {},
            "parent_name": user.parent.name if user.parent else None
        }

        if include_children and hasattr(user, 'child_users') and user.child_users:
            result["children"] = [self._user_to_dict(child) for child in user.child_users]

        return result

    def get_user(self, user_id: str, include_children: bool = False) -> Optional[Dict[str, Any]]:
        """Get a user by ID."""
        self._ensure_table_exists()

        with self.db.get_session() as session:
            query = session.query(UserTable).options(joinedload(UserTable.parent))
            if include_children:
                query = query.options(joinedload(UserTable.child_users))

            user = query.filter_by(id=user_id).first()
            if user:
                return self._user_to_dict(user, include_children)
            return None

    def get_user_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a user by name (case-insensitive)."""
        self._ensure_table_exists()

        with self.db.get_session() as session:
            user = session.query(UserTable).options(joinedload(UserTable.parent)).filter(
                func.lower(UserTable.name) == name.lower()
            ).first()
            if user:
                return self._user_to_dict(user)
            return None

    def get_all_users(self, current_user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all users, with filtering based on current user's role."""
        self._ensure_table_exists()

        with self.db.get_session() as session:
            query = session.query(UserTable).options(joinedload(UserTable.parent))

            # Apply role-based filtering
            if current_user_id:
                current_user = session.query(UserTable).filter_by(id=current_user_id).first()
                if current_user:
                    if current_user.role == UserRole.ADMIN.value:
                        # Admin sees all users
                        pass
                    elif current_user.role == UserRole.MASTER.value:
                        # Master sees themselves and their children
                        query = query.filter(
                            (UserTable.id == current_user_id) |
                            (UserTable.parent_id == current_user_id)
                        )
                    else:
                        # Normal users see only themselves
                        query = query.filter(UserTable.id == current_user_id)

            users = query.order_by(UserTable.created_at).all()
            return [self._user_to_dict(user) for user in users]

    def get_users_by_role(self, role: str) -> List[Dict[str, Any]]:
        """Get all users with a specific role."""
        self._ensure_table_exists()

        with self.db.get_session() as session:
            users = session.query(UserTable).options(joinedload(UserTable.parent)).filter(
                UserTable.role == role
            ).order_by(UserTable.created_at).all()
            return [self._user_to_dict(user) for user in users]

    def get_children(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all children of a user."""
        self._ensure_table_exists()

        with self.db.get_session() as session:
            user = session.query(UserTable).options(joinedload(UserTable.child_users)).filter_by(id=user_id).first()
            if user and hasattr(user, 'child_users') and user.child_users:
                return [self._user_to_dict(child) for child in user.child_users]
            return []

    def get_descendants(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all descendants of a user (children, grandchildren, etc.)."""
        self._ensure_table_exists()

        with self.db.get_session() as session:
            all_users = session.query(UserTable).options(joinedload(UserTable.parent)).all()

            # Build parent-child mapping
            parent_map = {}
            for user in all_users:
                if user.parent_id:
                    if user.parent_id not in parent_map:
                        parent_map[user.parent_id] = []
                    parent_map[user.parent_id].append(user)

            # Recursively collect descendants
            def collect_descendants(parent_id: str, result: List[Dict[str, Any]]):
                if parent_id in parent_map:
                    for child in parent_map[parent_id]:
                        result.append(self._user_to_dict(child))
                        collect_descendants(child.id, result)

            descendants = []
            collect_descendants(user_id, descendants)
            return descendants

    def create_user(self, name: str, role: str = UserRole.NORMAL.value,
                   email: Optional[str] = None, parent_id: Optional[str] = None,
                   profile: Optional[Dict] = None) -> str:
        """Create a new user with validation."""
        # Validate name
        if not name or not name.strip():
            raise ValueError("User name cannot be empty")

        # Validate role
        valid_roles = [role.value for role in UserRole]
        if role not in valid_roles:
            raise ValueError(f"Invalid role. Must be one of: {', '.join(valid_roles)}")

        # Validate parent for normal users
        if role == UserRole.NORMAL.value and not parent_id:
            raise ValueError("Normal users must have a parent (master)")

        # Validate parent exists and is a master
        if parent_id:
            self._ensure_table_exists()
            with self.db.get_session() as session:
                parent = session.query(UserTable).filter_by(id=parent_id).first()
                if not parent:
                    raise ValueError(f"Parent user with ID {parent_id} not found")
                if parent.role != UserRole.MASTER.value:
                    raise ValueError(f"Parent user must be a master, not {parent.role}")

        self._ensure_table_exists()

        user_id = str(uuid.uuid4())

        with self.db.get_session() as session:
            user = UserTable(
                id=user_id,
                name=name.strip(),
                email=email,
                role=role,
                parent_id=parent_id,
                created_at=datetime.utcnow(),
                is_active=True,
                profile=profile or {"language": "en"},
                user_metadata={"created_via": "ui"}
            )
            session.add(user)

        log("info", f"Created user: {name.strip()} (ID: {user_id}, Role: {role})")
        return user_id

    def update_user(self, user_id: str, current_user_id: Optional[str] = None, **kwargs) -> bool:
        """Update user information with permission checks."""
        self._ensure_table_exists()

        with self.db.get_session() as session:
            user = session.query(UserTable).filter_by(id=user_id).first()
            if not user:
                return False

            # Check permissions if current_user_id is provided
            if current_user_id:
                current_user = session.query(UserTable).filter_by(id=current_user_id).first()
                if not self.can_manage_user(current_user, user):
                    log("warning", f"User {current_user_id} cannot manage user {user_id}")
                    return False

            # Validate role changes
            if "role" in kwargs:
                new_role = kwargs["role"]
                valid_roles = [role.value for role in UserRole]
                if new_role not in valid_roles:
                    raise ValueError(f"Invalid role. Must be one of: {', '.join(valid_roles)}")

                # Normal users must have a parent
                if new_role == UserRole.NORMAL.value and not user.parent_id and "parent_id" not in kwargs:
                    raise ValueError("Normal users must have a parent")

                # If changing from normal to another role, keep parent for reference but can be None
                if user.role == UserRole.NORMAL.value and new_role != UserRole.NORMAL.value:
                    kwargs["parent_id"] = None

            # Validate parent changes
            if "parent_id" in kwargs:
                parent_id = kwargs["parent_id"]
                if parent_id:
                    parent = session.query(UserTable).filter_by(id=parent_id).first()
                    if not parent:
                        raise ValueError(f"Parent user with ID {parent_id} not found")
                    if parent.role != UserRole.MASTER.value:
                        raise ValueError(f"Parent user must be a master, not {parent.role}")
                    if user.role != UserRole.NORMAL.value:
                        raise ValueError("Only normal users can have a parent")

            # Update fields
            for key, value in kwargs.items():
                if key == "user_metadata":
                    pass
                elif key == "metadata":
                    key = "user_metadata"

                if hasattr(user, key):
                    setattr(user, key, value)
                elif key == "profile":
                    current_profile = user.profile or {}
                    current_profile.update(value)
                    user.profile = current_profile

            if "last_login" in kwargs:
                user.last_login = kwargs["last_login"]

            return True

    def can_manage_user(self, manager: UserTable, target_user: UserTable) -> bool:
        """Check if a user can manage another user."""
        # Users can always manage themselves
        if manager.id == target_user.id:
            return True

        # Admin can manage everyone
        if manager.role == UserRole.ADMIN.value:
            return True

        # Master can manage their children
        if manager.role == UserRole.MASTER.value:
            return target_user.parent_id == manager.id

        # Normal users can't manage anyone else
        return False

    def get_manageable_users(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all users that a user can manage."""
        user = self.get_user(user_id)
        if not user:
            return []

        if user["role"] == UserRole.ADMIN.value:
            return self.get_all_users()
        elif user["role"] == UserRole.MASTER.value:
            return self.get_children(user_id) + [user]  # Include themselves
        else:
            return [user]  # Only themselves

    def register_profile_preferences_callback(self, callback_func):
        """Register a callback for profile preferences.

        Args:
            callback_func: Function that returns a dict of preference fields
                         with structure: {"field_name": {"type": "text|select|checkbox",
                                                       "options": [...], "default": value}}
        """
        if callback_func not in self._profile_preferences_callbacks:
            self._profile_preferences_callbacks.append(callback_func)
            log("debug", f"Registered profile preferences callback: {callback_func.__name__}")

    def get_profile_preferences_schema(self) -> Dict[str, Any]:
        """Get the schema for profile preferences from all registered callbacks."""
        schema = {
            "language": {
                "type": "select",
                "options": ["en", "fr", "de", "es", "it", "zh", "ja", "ko"],
                "default": "en",
                "label": "Preferred Language"
            }
        }

        for callback in self._profile_preferences_callbacks:
            try:
                callback_schema = callback()
                schema.update(callback_schema)
            except Exception as e:
                log("error", f"Profile preferences callback failed: {e}")

        return schema

    def register_before_delete_callback(self, callback_func):
        """Register a callback to be executed before a user is deleted."""
        if callback_func not in self._before_delete_callbacks:
            self._before_delete_callbacks.append(callback_func)
            log("debug", f"Registered before_delete callback: {callback_func.__name__}")

    def unregister_before_delete_callback(self, callback_func):
        """Unregister a before_delete callback."""
        if callback_func in self._before_delete_callbacks:
            self._before_delete_callbacks.remove(callback_func)
            log("debug", f"Unregistered before_delete callback: {callback_func.__name__}")

    def delete_user(self, user_id: str, current_user_id: Optional[str] = None) -> bool:
        """Delete a user with permission checks."""
        self._ensure_table_exists()

        # Check permissions
        if current_user_id:
            with self.db.get_session() as session:
                current_user = session.query(UserTable).filter_by(id=current_user_id).first()
                target_user = session.query(UserTable).filter_by(id=user_id).first()
                if not current_user or not target_user:
                    return False
                if not self.can_manage_user(current_user, target_user):
                    log("warning", f"User {current_user_id} cannot delete user {user_id}")
                    return False

        # Execute before_delete callbacks
        all_successful = True
        for callback in self._before_delete_callbacks:
            try:
                success = callback(user_id)
                if not success:
                    all_successful = False
            except Exception as e:
                log("error", f"Callback raised exception: {e}")
                all_successful = False

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
            return True

    def update_last_login(self, user_id: str):
        """Update user's last login timestamp."""
        self.update_user(user_id, last_login=datetime.utcnow())

    def get_all_users_dict(self, current_user_id: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """Get all users as a dictionary with user_id as key."""
        users = self.get_all_users(current_user_id)
        return {user["id"]: user for user in users}

    def search_users(self, query: str, current_user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search users by name or email."""
        users = self.get_all_users(current_user_id)
        query_lower = query.lower()

        return [
            user for user in users
            if query_lower in user["name"].lower() or
               (user["email"] and query_lower in user["email"].lower())
        ]

    def get_active_users(self, current_user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all active users."""
        users = self.get_all_users(current_user_id)
        return [user for user in users if user.get("is_active", True)]

    def get_user_count(self, current_user_id: Optional[str] = None) -> int:
        """Get total number of users."""
        users = self.get_all_users(current_user_id)
        return len(users)


# Global user manager instance
user_manager = UserManager()


def init_user_manager(create_default_users: bool = True):
    """Initialize the user manager."""
    if create_default_users and user_manager.db.is_initialized():
        user_manager.init_default_users()
    return user_manager


def get_all_users() -> Dict[str, Dict[str, Any]]:
    """Backward compatibility alias."""
    return user_manager.get_all_users_dict()
