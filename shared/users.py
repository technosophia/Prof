"""
User management with database backend.
[api]
How to get the current user : user = st.session_state.current_user
How to check if a user can access admin tab : can_access_admin_tab(user)
How to check user role : user.get("role") in [UserRole.ADMIN.value, UserRole.MASTER.value]

# User Management System (`shared/users.py`)
Built-in user authentication and role-based access control with database persistence. Supports hierarchical user relationships (ADMIN, MASTER, NORMAL).

**Exported components:**
- `UserRole`: Enum for user permissions
- `get_user_manager()`: Access user management singleton
- `init_user_manager()`: Initialize with default users
- `get_all_users()`: Get all users as dictionary
- Automatic cleanup callbacks for user deletion
-
## User objets
User object structure returned by UserManager.get_user() and similar methods:

{
    "id": str,                          # Unique user identifier (UUID or predefined)
    "name": str,                        # Full name, must not be empty
    "email": Optional[str],             # Email address, can be null
    "role": str,                       # One of: "admin", "master", "normal"
    "parent_id": Optional[str],        # ID of parent user (required for normal users, must be master)
    "created_at": Optional[str],       # ISO 8601 datetime string, null if not set
    "last_login": Optional[str],       # ISO 8601 datetime string, null if never logged in
    "is_active": bool,                # Whether user account is active (default: True)
    "profile": Dict[str, Any],        # User preferences (includes language: str with 2-letter code)
    "metadata": Dict[str, Any],       # System metadata (creation source, defaults, etc.)
    "parent_name": Optional[str],     # Display name of parent user, null if no parent
    "children": Optional[List[Dict]]  # Only when include_children=True: recursive list of child users
}

Role hierarchy:
- ADMIN: System administrators, can manage all users
- MASTER: Can manage themselves and their direct children (normal users)
- NORMAL: Regular users, must have a master as parent, can only see themselves

This structure is JSON-serializable and used consistently across get_user(),
get_all_users(), search_users(), and similar methods.


# User Settings System (`shared/settings.py`)
Manages user-specific configuration and preferences with database persistence.

**Exported functions:**
- `get_user_settings_manager()`: Access user settings manager

"""

import uuid
import hashlib
import secrets
import json
import os
import csv
import io
import re
from typing import Dict, List, Optional, Any, Set, Tuple
from datetime import datetime, timedelta
from datetime import datetime as dt_datetime
from enum import Enum

from sqlalchemy import (
    Column,
    String,
    Integer,
    Text,
    DateTime,
    Boolean,
    JSON,
    func,
    ForeignKey,
    inspect,
    text,
)
from sqlalchemy.orm import Session, relationship, joinedload

from core.logging import log, set_log_module_level
from core.database import get_db_manager, Base
from core.config import get_config
from core.callback import register_callback, unregister_callback, clear_callbacks
from shared.mailer_lite import notify_account_approved


class UserRole(Enum):
    """User roles enumeration."""

    ADMIN = "admin"
    MASTER = "master"
    NORMAL = "normal"


class UserAction(Enum):
    """User action types for logging."""

    LOGIN = "login"
    LOGOUT = "logout"
    CREATE_USER = "create_user"
    UPDATE_USER = "update_user"
    DELETE_USER = "delete_user"
    GENERATE_RESET_CODE = "generate_reset_code"
    RESET_PASSWORD = "reset_password"
    CHANGE_PASSWORD = "change_password"
    SWITCH_USER = "switch_user"
    EXPORT_USERS = "export_users"
    IMPORT_USERS = "import_users"
    VIEW_LOGS = "view_logs"
    LOGIN_FAILED = "login_failed"
    RESET_CODE_USED = "reset_code_used"


class UserTable(Base):
    """User model for database."""

    __tablename__ = "users"

    id = Column(String(36), primary_key=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    password_hash = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    role = Column(String(20), default=UserRole.NORMAL.value)
    registration_status = Column(String(20), nullable=True, default="approved")
    parent_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    profile = Column(JSON, default={})
    user_metadata = Column(JSON, default={})
    reset_code = Column(String(64), nullable=True)
    reset_code_expires = Column(DateTime, nullable=True)

    # Relationships - define them explicitly
    parent = relationship("UserTable", remote_side=[id], back_populates="children")
    children = relationship("UserTable", back_populates="parent")


class PreregisteredEmail(Base):
    """Pre-registered emails accepted for auto-approved registration."""

    __tablename__ = "preregistered_emails"

    email = Column(String(255), primary_key=True)
    added_at = Column(DateTime, default=datetime.utcnow)
    added_by = Column(String(36), nullable=True)
    deadline_months = Column(Integer, nullable=False, default=6)
    expiry_message = Column(Text, nullable=True)


class UserActionLog(Base):
    """Log of user actions for auditing."""

    __tablename__ = "user_action_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True)  # Add length
    username = Column(String(255), nullable=True)  # Add length
    action = Column(String(50), nullable=False)  # Add length
    target_user_id = Column(String(36), nullable=True)  # Add length
    target_username = Column(String(255), nullable=True)  # Add length
    details = Column(JSON, default={})
    timestamp = Column(DateTime, default=datetime.utcnow)
    success = Column(Boolean, default=True)
    error_message = Column(String(500), nullable=True)  # Add length


class UserManager:
    """Manages user operations."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # Initialize only once
        if not hasattr(self, "_initialized"):
            self.db = get_db_manager()  # Use the global database manager
            self._initialized = True
            # Initialize callback registry
            self._before_delete_callbacks = []
            self._profile_preferences_callbacks = []
            self._ensure_action_log_table()

    def _ensure_table_exists(self):
        """Ensure the users table exists."""
        if not self.db.is_initialized():
            log("warning", "Database not initialized, cannot ensure users table exists")
            return False

        try:
            UserTable.__table__.create(bind=self.db._engine, checkfirst=True)

            inspector = inspect(self.db._engine)
            user_columns = {column["name"] for column in inspector.get_columns("users")}
            if "registration_status" not in user_columns:
                with self.db._engine.begin() as conn:
                    conn.execute(
                        text(
                            "ALTER TABLE users ADD COLUMN registration_status VARCHAR(20) DEFAULT 'approved'"
                        )
                    )
                log("info", "Added missing users.registration_status column")

            log("debug", "Users table ensured to exist")
            return True
        except Exception as e:
            log("error", f"Failed to ensure users table exists: {e}")
            return False

    def _ensure_action_log_table(self):
        """Ensure the user action log table exists."""
        if not self.db.is_initialized():
            return False

        try:
            UserActionLog.__table__.create(bind=self.db._engine, checkfirst=True)
            return True
        except Exception as e:
            log("error", f"Failed to ensure action log table exists: {e}")
            return False

    def _ensure_preregistered_emails_table(self):
        """Ensure the preregistered_emails table exists."""
        if not self.db.is_initialized():
            return False

        try:
            PreregisteredEmail.__table__.create(bind=self.db._engine, checkfirst=True)
            inspector = inspect(self.db._engine)
            columns = {
                column["name"] for column in inspector.get_columns("preregistered_emails")
            }

            if "deadline_months" not in columns:
                with self.db._engine.begin() as conn:
                    conn.execute(
                        text(
                            "ALTER TABLE preregistered_emails "
                            "ADD COLUMN deadline_months INTEGER DEFAULT 6"
                        )
                    )
                log("info", "Added missing preregistered_emails.deadline_months column")

            if "expiry_message" not in columns:
                with self.db._engine.begin() as conn:
                    conn.execute(
                        text(
                            "ALTER TABLE preregistered_emails "
                            "ADD COLUMN expiry_message TEXT"
                        )
                    )
                log("info", "Added missing preregistered_emails.expiry_message column")
            return True
        except Exception as e:
            log("error", f"Failed to ensure preregistered emails table exists: {e}")
            return False

    @staticmethod
    def compute_deadline_at(deadline_months: int) -> str:
        """Compute deadline datetime as ISO string."""
        safe_months = max(1, int(deadline_months))
        deadline = datetime.utcnow() + timedelta(days=safe_months * 30)
        return deadline.isoformat()

    @staticmethod
    def _deadline_message_prefix(message: Optional[str]) -> str:
        custom_message = (message or "").strip()
        if custom_message:
            return custom_message
        return "Your access period has ended. Please contact your teacher."

    def _check_deadline_expiry(self, session: Session, user: UserTable) -> Optional[str]:
        """Deactivate user if preregistered deadline has passed.

        Returns the message to display when access is expired, otherwise None.
        """
        metadata = user.user_metadata or {}
        if not metadata.get("preregistered_deadline_at"):
            is_retroactive_candidate = (
                user.role == UserRole.NORMAL.value
                and (user.registration_status or "approved") == "approved"
                and bool(user.parent_id)
            )
            if is_retroactive_candidate:
                created_at = user.created_at or datetime.utcnow()
                metadata = {
                    **metadata,
                    "preregistered": metadata.get("preregistered", True),
                    "preregistered_deadline_months": metadata.get(
                        "preregistered_deadline_months", 6
                    ),
                    "preregistered_deadline_at": (
                        created_at + timedelta(days=6 * 30)
                    ).isoformat(),
                }
                user.user_metadata = metadata
                session.commit()

        deadline_iso = metadata.get("preregistered_deadline_at")
        if not deadline_iso:
            return None

        try:
            deadline_at = dt_datetime.fromisoformat(deadline_iso)
        except ValueError:
            log(
                "warning",
                f"Invalid preregistered_deadline_at for user {user.id}: {deadline_iso}",
            )
            return None

        if dt_datetime.utcnow() < deadline_at:
            return None

        if user.is_active:
            user.is_active = False
            session.commit()

        return self._deadline_message_prefix(metadata.get("preregistered_expiry_message"))

    def enforce_deadline_for_user(self, user_id: str) -> Optional[str]:
        """Enforce deadline policy and return expiry message if expired."""
        self._ensure_table_exists()
        with self.db.get_session() as session:
            user = session.query(UserTable).filter_by(id=user_id).first()
            if not user:
                return None
            return self._check_deadline_expiry(session, user)

    def _hash_password(self, password: str) -> str:
        """Hash a password using SHA-256 with salt."""
        salt = secrets.token_hex(16)
        hash_obj = hashlib.sha256((salt + password).encode())
        return f"{salt}${hash_obj.hexdigest()}"

    def _verify_password(self, password: str, password_hash: str) -> bool:
        """Verify a password against its hash."""
        if not password_hash or "$" not in password_hash:
            return False
        salt, hash_value = password_hash.split("$", 1)
        check_hash = hashlib.sha256((salt + password).encode()).hexdigest()
        return secrets.compare_digest(check_hash, hash_value)

    def _generate_reset_code(self) -> str:
        """Generate a secure random reset code."""
        return secrets.token_urlsafe(32)  # 32 characters, URL-safe

    def log_user_action(
        self,
        user_id: Optional[str],
        action: str,
        target_user_id: Optional[str] = None,
        target_username: Optional[str] = None,
        details: Optional[Dict] = None,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> bool:
        """Log a user action for auditing."""
        try:
            self._ensure_action_log_table()

            username = None
            if user_id:
                user = self.get_user(user_id)
                if user:
                    username = user.get("name")

            target_username_resolved = target_username
            if target_user_id and not target_username_resolved:
                target = self.get_user(target_user_id)
                if target:
                    target_username_resolved = target.get("name")

            log_entry = UserActionLog(
                id=str(uuid.uuid4()),
                user_id=user_id,
                username=username,
                action=action,
                target_user_id=target_user_id,
                target_username=target_username_resolved,
                details=details or {},
                timestamp=datetime.utcnow(),
                success=success,
                error_message=error_message,
            )

            with self.db.get_session() as session:
                session.add(log_entry)
                session.commit()

            return True
        except Exception as e:
            log("error", f"Failed to log user action: {e}")
            return False

    def get_user_action_logs(
        self,
        user_id: Optional[str] = None,
        target_user_id: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        current_user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get user action logs with filtering and permission checks."""
        self._ensure_action_log_table()

        with self.db.get_session() as session:
            query = session.query(UserActionLog)

            # Apply permission filtering if current_user_id provided
            if current_user_id:
                current_user = self.get_user(current_user_id)
                if not current_user:
                    return []

                if current_user["role"] == UserRole.ADMIN.value:
                    # Admin sees all logs
                    pass
                elif current_user["role"] == UserRole.MASTER.value:
                    # Master sees logs for themselves and their children
                    children = self.get_children(current_user_id)
                    child_ids = [c["id"] for c in children]
                    # Users whose logs can be seen: current_user + children
                    visible_user_ids = [current_user_id] + child_ids

                    query = query.filter(
                        (UserActionLog.user_id.in_(visible_user_ids))
                        | (UserActionLog.target_user_id.in_(visible_user_ids))
                    )
                else:
                    # Normal users see only their own logs
                    query = query.filter(UserActionLog.user_id == current_user_id)

            # Apply filters
            if user_id:
                query = query.filter(UserActionLog.user_id == user_id)
            if target_user_id:
                query = query.filter(UserActionLog.target_user_id == target_user_id)
            if action:
                query = query.filter(UserActionLog.action == action)

            # Order by most recent first
            query = query.order_by(UserActionLog.timestamp.desc())

            # Apply pagination
            query = query.limit(limit).offset(offset)

            logs = []
            for log_entry in query.all():
                logs.append(
                    {
                        "id": log_entry.id,
                        "user_id": log_entry.user_id,
                        "username": log_entry.username,
                        "action": log_entry.action,
                        "target_user_id": log_entry.target_user_id,
                        "target_username": log_entry.target_username,
                        "details": log_entry.details or {},
                        "timestamp": log_entry.timestamp.isoformat()
                        if log_entry.timestamp
                        else None,
                        "success": log_entry.success,
                        "error_message": log_entry.error_message,
                    }
                )

            return logs

    def init_default_users(self, config=None):
        if not self._ensure_table_exists():
            log("error", "Cannot create default users: users table does not exist")
            return False
        return self.create_default_users(config)

    def export_users(
        self,
        include_children: bool = False,
        user_ids: Optional[List[str]] = None,
        requesting_user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Export users to JSON-serializable dictionary.

        Args:
            include_children: Whether to include full child hierarchies
            user_ids: Optional list of specific user IDs to export (None = all manageable by requesting_user)
            requesting_user_id: ID of user requesting export (for permission checks and logging)

        Returns:
            Dictionary with users and metadata
        """
        self._ensure_table_exists()

        # Check permissions if requesting_user_id provided
        if requesting_user_id:
            requesting_user = self.get_user(requesting_user_id)
            if not requesting_user:
                raise ValueError("Requesting user not found")

            if requesting_user["role"] not in [
                UserRole.ADMIN.value,
                UserRole.MASTER.value,
            ]:
                raise PermissionError("Only admin and master users can export users")

        with self.db.get_session() as session:
            # Determine which users to export
            if user_ids:
                # Filter to only users the requester can see
                if requesting_user_id:
                    manageable = self.get_manageable_users(requesting_user_id)
                    manageable_ids = [u["id"] for u in manageable]
                    user_ids = [uid for uid in user_ids if uid in manageable_ids]

                users = (
                    session.query(UserTable).filter(UserTable.id.in_(user_ids)).all()
                )
            else:
                if requesting_user_id:
                    # Get all manageable users
                    manageable = self.get_manageable_users(requesting_user_id)
                    manageable_ids = [u["id"] for u in manageable]
                    users = (
                        session.query(UserTable)
                        .filter(UserTable.id.in_(manageable_ids))
                        .all()
                    )
                else:
                    users = session.query(UserTable).all()

            export_data = {
                "exported_at": datetime.utcnow().isoformat(),
                "version": "1.0",
                "user_count": len(users),
                "users": [],
            }

            for user in users:
                user_dict = self._user_to_dict(user, include_children=include_children)
                # Remove sensitive fields
                user_dict.pop("password_hash", None)
                user_dict.pop("reset_code", None)
                user_dict.pop("reset_code_expires", None)
                export_data["users"].append(user_dict)

            # Log the export
            if requesting_user_id:
                self.log_user_action(
                    user_id=requesting_user_id,
                    action=UserAction.EXPORT_USERS.value,
                    details={
                        "user_count": len(users),
                        "include_children": include_children,
                    },
                    success=True,
                )

            return export_data

    def import_users(
        self,
        import_data: Dict[str, Any],
        overwrite_existing: bool = False,
        validate_only: bool = False,
        requesting_user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Import users from JSON data.

        Args:
            import_data: Dictionary with users data (format from export_users)
            overwrite_existing: Whether to overwrite existing users with same ID
            validate_only: Only validate the import data without saving
            requesting_user_id: ID of user requesting import (for permission checks and logging)

        Returns:
            Dictionary with import results (success_count, failure_count, errors)
        """
        self._ensure_table_exists()

        # Check permissions if requesting_user_id provided
        if requesting_user_id:
            requesting_user = self.get_user(requesting_user_id)
            if not requesting_user:
                raise ValueError("Requesting user not found")

            if requesting_user["role"] != UserRole.ADMIN.value:
                raise PermissionError("Only admin users can import users")

        result = {
            "success_count": 0,
            "failure_count": 0,
            "errors": [],
            "imported_users": [],
        }

        # Validate import data structure
        if "users" not in import_data or not isinstance(import_data["users"], list):
            raise ValueError("Invalid import format: missing 'users' array")

        # Validate user IDs are unique in import
        import_user_ids = [u["id"] for u in import_data["users"] if u.get("id")]
        if len(import_user_ids) != len(set(import_user_ids)):
            raise ValueError("Duplicate user IDs in import data")

        with self.db.get_session() as session:
            try:
                # Check existing users
                existing_ids = set()
                if not overwrite_existing:
                    existing = (
                        session.query(UserTable.id)
                        .filter(UserTable.id.in_(import_user_ids))
                        .all()
                    )
                    existing_ids = {e[0] for e in existing}

                # Validate parent references
                all_ids_in_import = set(import_user_ids)

                for user_data in import_data["users"]:
                    try:
                        # Skip if user exists and we're not overwriting
                        if user_data["id"] in existing_ids and not overwrite_existing:
                            result["failure_count"] += 1
                            result["errors"].append(
                                f"User '{user_data['id']}' already exists (use overwrite_existing=True to replace)"
                            )
                            continue

                        # Validate required fields
                        if not user_data.get("id"):
                            raise ValueError("Missing user ID")
                        if not user_data.get("name"):
                            raise ValueError(f"Missing name for user {user_data['id']}")

                        # Validate role
                        if user_data["role"] not in [r.value for r in UserRole]:
                            raise ValueError(
                                f"Invalid role '{user_data['role']}' for user {user_data['id']}"
                            )

                        # Validate parent reference
                        if user_data.get("parent_id"):
                            # Parent must exist either in import or already in DB
                            if user_data["parent_id"] not in all_ids_in_import:
                                parent_exists = (
                                    session.query(UserTable)
                                    .filter_by(id=user_data["parent_id"])
                                    .first()
                                    is not None
                                )
                                if not parent_exists:
                                    raise ValueError(
                                        f"Parent '{user_data['parent_id']}' not found for user {user_data['id']}"
                                    )

                        # Validate normal users have parent
                        if user_data[
                            "role"
                        ] == UserRole.NORMAL.value and not user_data.get("parent_id"):
                            raise ValueError(
                                f"Normal user {user_data['id']} must have a parent"
                            )

                        # If only validating, continue to next user
                        if validate_only:
                            result["success_count"] += 1
                            continue

                        # Prepare user data
                        user = UserTable(
                            id=user_data["id"],
                            name=user_data["name"],
                            email=user_data.get("email"),
                            role=user_data["role"],
                            parent_id=user_data.get("parent_id"),
                            is_active=user_data.get("is_active", True),
                            profile=user_data.get("profile", {}),
                            user_metadata=user_data.get("metadata", {}),
                            created_at=datetime.utcnow(),
                        )

                        # Merge or add user
                        session.merge(user)
                        result["success_count"] += 1
                        result["imported_users"].append(user_data["id"])

                    except Exception as e:
                        result["failure_count"] += 1
                        result["errors"].append(
                            f"Error importing user {user_data.get('id', 'unknown')}: {str(e)}"
                        )

                if not validate_only:
                    session.commit()
                    log(
                        "info",
                        f"Imported {result['success_count']} users, {result['failure_count']} failures",
                    )

                    # Log the import
                    if requesting_user_id:
                        self.log_user_action(
                            user_id=requesting_user_id,
                            action=UserAction.IMPORT_USERS.value,
                            details={
                                "success_count": result["success_count"],
                                "failure_count": result["failure_count"],
                            },
                            success=result["failure_count"] == 0,
                        )

            except Exception as e:
                session.rollback()
                raise e

        return result

    def auto_import_users_from_config(self, config=None) -> bool:
        """Auto-import users from JSON file specified in config, only if no users exist.

        Called during system initialization to replace create_default_users.

        Returns:
            bool: True if import was successful or no import needed, False on error
        """
        self._ensure_table_exists()

        with self.db.get_session() as session:
            user_count = session.query(UserTable).count()
            if user_count > 0:
                log("debug", "Users already exist, skipping auto-import")
                return True

        if config is None:
            log("error", "No config provided to auto_import_users_from_config")
            return False

        auto_import_config = config.get("database.auto_import_users")
        if not auto_import_config or not auto_import_config.get("enabled", False):
            log("debug", "Auto-import not enabled in config")
            return True

        import_file = auto_import_config.get("file")
        if not import_file:
            log("error", "Auto-import enabled but no import file specified")
            return False

        # Resolve file path
        shared_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.dirname(shared_dir)

        if not os.path.isabs(import_file):
            import_file = os.path.join(root_dir, import_file)

        if not os.path.exists(import_file):
            log("error", f"Auto-import file not found: {import_file}")
            return False

        try:
            import json

            with open(import_file, "r", encoding="utf-8") as f:
                import_data = json.load(f)

            # Validate import format
            if import_data.get("version") == "1.0" and "users" in import_data:
                # This is our export format
                result = self.import_users(
                    import_data,
                    overwrite_existing=auto_import_config.get("overwrite", False),
                )
            elif isinstance(import_data, list):
                # Legacy format: array of user objects
                legacy_data = {
                    "version": "legacy",
                    "users": import_data,
                    "exported_at": datetime.utcnow().isoformat(),
                }
                result = self.import_users(
                    legacy_data,
                    overwrite_existing=auto_import_config.get("overwrite", False),
                )
            else:
                log("error", f"Unknown import file format: {import_file}")
                return False

            if result["failure_count"] > 0:
                for error in result["errors"][:5]:  # Log first 5 errors
                    log("error", f"Auto-import error: {error}")
                if result["failure_count"] > 5:
                    log("error", f"... and {result['failure_count'] - 5} more errors")

            log(
                "info",
                f"Auto-import completed: {result['success_count']} users imported, "
                f"{result['failure_count']} failures",
            )
            return result["failure_count"] == 0

        except Exception as e:
            log("error", f"Auto-import failed: {e}", stacktrace=True)
            return False

    def create_default_users(self, config=None):
        if config and config.get("database.auto_import_users.enabled", False):
            log(
                "debug",
                "Auto-import is configured, using it instead of create_default_users",
            )
            success = self.auto_import_users_from_config(config)
            if success:
                return True
        return self._create_default_users_fallback()

    def _create_default_users_fallback(self):
        """Original create_default_users implementation."""
        if not self.db.is_initialized():
            log("error", "Cannot create default users: database not initialized")
            return False

        with self.db.get_session() as session:
            try:
                # Check if we have any users
                user_count = session.query(UserTable).count()

                if user_count == 0:
                    # Create admin user with default password
                    admin_password = self._hash_password("admin123")
                    admin_user = UserTable(
                        id="admin",
                        name="System Administrator",
                        email="admin@example.com",
                        password_hash=admin_password,
                        role=UserRole.ADMIN.value,
                        parent_id=None,
                        created_at=datetime.utcnow(),
                        is_active=True,
                        profile={"language": "en"},
                        user_metadata={"is_default": True, "created_by": "system"},
                    )
                    session.add(admin_user)

                    # Create master users
                    master1 = UserTable(
                        id="master1",
                        name="Master User 1",
                        email="master1@example.com",
                        password_hash=self._hash_password("master123"),
                        role=UserRole.MASTER.value,
                        parent_id=None,
                        created_at=datetime.utcnow(),
                        is_active=True,
                        profile={"language": "en"},
                        user_metadata={"is_default": True, "created_by": "system"},
                    )
                    session.add(master1)

                    master2 = UserTable(
                        id="master2",
                        name="Master User 2",
                        email="master2@example.com",
                        password_hash=self._hash_password("master123"),
                        role=UserRole.MASTER.value,
                        parent_id=None,
                        created_at=datetime.utcnow(),
                        is_active=True,
                        profile={"language": "fr"},
                        user_metadata={"is_default": True, "created_by": "system"},
                    )
                    session.add(master2)

                    # Create normal users for master1
                    normal1_m1 = UserTable(
                        id="normal1_m1",
                        name="Normal User 1 (Master 1)",
                        email="normal1_m1@example.com",
                        password_hash=self._hash_password("normal123"),
                        role=UserRole.NORMAL.value,
                        parent_id="master1",
                        created_at=datetime.utcnow(),
                        is_active=True,
                        profile={"language": "en"},
                        user_metadata={"is_default": True, "created_by": "system"},
                    )
                    session.add(normal1_m1)

                    normal2_m1 = UserTable(
                        id="normal2_m1",
                        name="Normal User 2 (Master 1)",
                        email="normal2_m1@example.com",
                        password_hash=self._hash_password("normal123"),
                        role=UserRole.NORMAL.value,
                        parent_id="master1",
                        created_at=datetime.utcnow(),
                        is_active=True,
                        profile={"language": "es"},
                        user_metadata={"is_default": True, "created_by": "system"},
                    )
                    session.add(normal2_m1)

                    # Create normal users for master2
                    normal1_m2 = UserTable(
                        id="normal1_m2",
                        name="Test User 1",
                        email="normal1_m2@example.com",
                        password_hash=self._hash_password("normal123"),
                        role=UserRole.NORMAL.value,
                        parent_id="master2",
                        created_at=datetime.utcnow(),
                        is_active=True,
                        profile={"language": "de"},
                        user_metadata={"is_default": True, "created_by": "system"},
                    )
                    session.add(normal1_m2)

                    normal2_m2 = UserTable(
                        id="normal2_m2",
                        name="Test User 2",
                        email="normal2_m2@example.com",
                        password_hash=self._hash_password("normal123"),
                        role=UserRole.NORMAL.value,
                        parent_id="master2",
                        created_at=datetime.utcnow(),
                        is_active=True,
                        profile={"language": "it"},
                        user_metadata={"is_default": True, "created_by": "system"},
                    )
                    session.add(normal2_m2)

                    log(
                        "info",
                        f"Created 7 default users with passwords: 1 admin, 2 masters, 4 normal users",
                    )
                    return True
                else:
                    log("debug", "Default users already exist, skipping creation")
                    return False
            except Exception as e:
                log("error", f"Failed to create default users: {e}")
                return False

    def _user_to_dict(
        self, user: UserTable, include_children: bool = False
    ) -> Dict[str, Any]:
        """Convert SQLAlchemy user object to dictionary."""
        result = {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "registration_status": user.registration_status or "approved",
            "parent_id": user.parent_id,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "last_login": user.last_login.isoformat() if user.last_login else None,
            "is_active": user.is_active,
            "profile": user.profile or {},
            "metadata": user.user_metadata or {},
            "parent_name": user.parent.name if user.parent else None,
            "has_password": user.password_hash is not None,
        }

        # Add reset code information safely
        if hasattr(user, "reset_code") and hasattr(user, "reset_code_expires"):
            reset_code_info = {
                "has_code": user.reset_code is not None
                and user.reset_code_expires is not None,
                "expires_at": user.reset_code_expires.isoformat()
                if user.reset_code_expires
                else None,
                "is_valid": False,
            }

            # Only try to compare if reset_code_expires is a datetime
            if user.reset_code_expires:
                if isinstance(user.reset_code_expires, dt_datetime):
                    reset_code_info["is_valid"] = (
                        user.reset_code_expires > dt_datetime.utcnow()
                    )

                    # Only include the actual code if it's valid and we have it
                    if user.reset_code and reset_code_info["is_valid"]:
                        reset_code_info["code"] = user.reset_code

            result["reset_code_info"] = reset_code_info
        else:
            # If attributes don't exist, provide default values
            result["reset_code_info"] = {
                "has_code": False,
                "expires_at": None,
                "is_valid": False,
            }

        if include_children and hasattr(user, "children") and user.children:
            result["children"] = [self._user_to_dict(child) for child in user.children]

        return result

    def get_user(
        self, user_id: str, include_children: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Get a user by ID."""
        self._ensure_table_exists()

        with self.db.get_session() as session:
            query = session.query(UserTable).options(joinedload(UserTable.parent))
            if include_children:
                query = query.options(joinedload(UserTable.children))

            user = query.filter_by(id=user_id).first()
            if user:
                return self._user_to_dict(user, include_children)
            return None

    def get_user_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a user by name (case-insensitive)."""
        self._ensure_table_exists()

        with self.db.get_session() as session:
            user = (
                session.query(UserTable)
                .options(joinedload(UserTable.parent))
                .filter(func.lower(UserTable.name) == name.lower())
                .first()
            )
            if user:
                return self._user_to_dict(user)
            return None

    def authenticate_user_with_status(
        self, user_id: str, password: str
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """Authenticate a user by user_id/password and return explicit status.

        Returns:
            Tuple of (user, status) where status is one of:
            - success
            - pending_approval
            - invalid_credentials
        """
        self._ensure_table_exists()

        with self.db.get_session() as session:
            user = (
                session.query(UserTable)
                .filter(func.lower(UserTable.id) == user_id.lower())
                .first()
            )

            if not user:
                user = (
                    session.query(UserTable)
                    .filter(func.lower(UserTable.email) == user_id.lower())
                    .first()
                )

            if not user:
                self.log_user_action(
                    user_id=None,
                    action=UserAction.LOGIN_FAILED.value,
                    details={"user_id": user_id, "reason": "user_not_found"},
                    success=False,
                )
                return None, "invalid_credentials"

            if not user.is_active:
                expiry_message = self._check_deadline_expiry(session, user)
                if expiry_message:
                    self.log_user_action(
                        user_id=user.id,
                        action=UserAction.LOGIN_FAILED.value,
                        details={"reason": "deadline_expired"},
                        success=False,
                    )
                    return None, f"deadline_expired::{expiry_message}"
                self.log_user_action(
                    user_id=user.id,
                    action=UserAction.LOGIN_FAILED.value,
                    details={"reason": "inactive_account"},
                    success=False,
                )
                return None, "invalid_credentials"

            if not user.password_hash:
                self.log_user_action(
                    user_id=user.id,
                    action=UserAction.LOGIN_FAILED.value,
                    details={"reason": "no_password_set"},
                    success=False,
                )
                return None, "invalid_credentials"

            if not self._verify_password(password, user.password_hash):
                self.log_user_action(
                    user_id=user.id,
                    action=UserAction.LOGIN_FAILED.value,
                    details={"reason": "invalid_password"},
                    success=False,
                )
                return None, "invalid_credentials"

            expiry_message = self._check_deadline_expiry(session, user)
            if expiry_message:
                self.log_user_action(
                    user_id=user.id,
                    action=UserAction.LOGIN_FAILED.value,
                    details={"reason": "deadline_expired"},
                    success=False,
                )
                return None, f"deadline_expired::{expiry_message}"

            if (user.registration_status or "approved") != "approved":
                self.log_user_action(
                    user_id=user.id,
                    action=UserAction.LOGIN_FAILED.value,
                    details={
                        "reason": "registration_not_approved",
                        "registration_status": user.registration_status,
                    },
                    success=False,
                )
                return None, "pending_approval"

            # Update last login
            user.last_login = datetime.utcnow()
            session.commit()

            self.log_user_action(
                user_id=user.id, action=UserAction.LOGIN.value, success=True
            )

            return self._user_to_dict(user), "success"

    def authenticate_user(
        self, user_id: str, password: str
    ) -> Optional[Dict[str, Any]]:
        """Authenticate a user by user_id and password.

        Returns:
            User dict if authentication successful, None otherwise
        """
        user, _ = self.authenticate_user_with_status(user_id, password)
        return user

    def get_pending_users(self) -> List[Dict[str, Any]]:
        """Return users awaiting manual registration approval."""
        self._ensure_table_exists()

        with self.db.get_session() as session:
            users = (
                session.query(UserTable)
                .filter(UserTable.registration_status == "pending")
                .all()
            )
            return [self._user_to_dict(user) for user in users]

    def set_registration_status(self, user_id: str, status: str) -> bool:
        """Set registration status for a user."""
        if status not in {"approved", "pending", "rejected"}:
            raise ValueError("Invalid registration status")

        self._ensure_table_exists()
        with self.db.get_session() as session:
            user = session.query(UserTable).filter_by(id=user_id).first()
            if not user:
                return False
            previous_status = user.registration_status or "approved"
            user.registration_status = status
            session.commit()
            if previous_status != "approved" and status == "approved":
                notify_account_approved(user.email, user.name)
            return True

    def import_preregistered_emails(
        self, csv_content: str, requesting_user_id: str = None
    ) -> Dict[str, Any]:
        """Import pre-registered emails from CSV content."""
        self._ensure_preregistered_emails_table()

        result = {"imported": 0, "skipped": 0, "invalid": [], "errors": []}
        if not csv_content or not csv_content.strip():
            return result

        email_column_aliases = {
            "email",
            "e-mail",
            "mail",
            "email address",
            "e-mail address",
            "courriel",
        }
        email_regex = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

        try:
            reader = csv.DictReader(io.StringIO(csv_content))
        except Exception as error:
            result["errors"].append(f"invalid_csv: {error}")
            return result

        if not reader.fieldnames:
            return result

        normalized = {
            name.strip().lower(): name
            for name in reader.fieldnames
            if name and name.strip()
        }
        email_header = next(
            (normalized[name] for name in email_column_aliases if name in normalized),
            None,
        )
        if not email_header:
            result["errors"].append("missing_email_column")
            return result

        with self.db.get_session() as session:
            for row in reader:
                raw_email = (row.get(email_header) or "").strip()
                if not raw_email:
                    continue

                email = raw_email.lower()
                if not email_regex.match(email):
                    result["invalid"].append(raw_email)
                    continue

                existing = (
                    session.query(PreregisteredEmail)
                    .filter(func.lower(PreregisteredEmail.email) == email)
                    .first()
                )
                if existing:
                    result["skipped"] += 1
                    continue

                session.add(
                    PreregisteredEmail(
                        email=email,
                        added_at=datetime.utcnow(),
                        added_by=requesting_user_id,
                    )
                )
                result["imported"] += 1
            session.commit()

        return result

    def is_email_preregistered(self, email: str) -> bool:
        """Check if an email is preregistered in DB or config."""
        if not email:
            return False

        normalized_email = email.strip().lower()
        if not normalized_email:
            return False

        self._ensure_preregistered_emails_table()

        with self.db.get_session() as session:
            db_match = (
                session.query(PreregisteredEmail)
                .filter(func.lower(PreregisteredEmail.email) == normalized_email)
                .first()
            )
            if db_match:
                return True

        config = get_config()
        config_emails = config.get("registration.preregistered_emails", []) or []
        return normalized_email in {
            str(item).strip().lower() for item in config_emails if str(item).strip()
        }

    def get_preregistered_email_owner(self, email: str) -> Optional[str]:
        """Get the user_id of who added this preregistered email.

        Returns:
            The added_by user_id if found in DB, None if not in DB or from config
        """
        if not email:
            return None

        normalized_email = email.strip().lower()
        if not normalized_email:
            return None

        self._ensure_preregistered_emails_table()

        with self.db.get_session() as session:
            db_match = (
                session.query(PreregisteredEmail)
                .filter(func.lower(PreregisteredEmail.email) == normalized_email)
                .first()
            )
            if db_match:
                return db_match.added_by

        return None

    def get_preregistered_email_policy(self, email: str) -> Dict[str, Any]:
        """Return preregistration policy for an email."""
        default_policy = {"deadline_months": 6, "expiry_message": None}
        if not email:
            return default_policy

        normalized_email = email.strip().lower()
        if not normalized_email:
            return default_policy

        self._ensure_preregistered_emails_table()

        with self.db.get_session() as session:
            db_match = (
                session.query(PreregisteredEmail)
                .filter(func.lower(PreregisteredEmail.email) == normalized_email)
                .first()
            )
            if not db_match:
                return default_policy

            return {
                "deadline_months": db_match.deadline_months or 6,
                "expiry_message": db_match.expiry_message,
            }

    def is_email_registered(self, email: str) -> bool:
        """Check if an email is already registered to a user."""
        if not email:
            return False

        normalized_email = email.strip().lower()
        if not normalized_email:
            return False

        self._ensure_table_exists()

        with self.db.get_session() as session:
            existing = (
                session.query(UserTable)
                .filter(func.lower(UserTable.email) == normalized_email)
                .first()
            )
            return existing is not None

    def get_preregistered_emails(self) -> List[Dict[str, Any]]:
        """Get all pre-registered emails from DB."""
        self._ensure_preregistered_emails_table()

        with self.db.get_session() as session:
            rows = (
                session.query(PreregisteredEmail)
                .order_by(PreregisteredEmail.email.asc())
                .all()
            )
            return [
                {
                    "email": row.email,
                    "added_at": row.added_at.isoformat() if row.added_at else None,
                    "added_by": row.added_by,
                    "deadline_months": row.deadline_months or 6,
                    "expiry_message": row.expiry_message,
                }
                for row in rows
            ]

    def delete_preregistered_email(self, email: str) -> bool:
        """Delete one preregistered email by value."""
        if not email:
            log("info", "delete_preregistered_email called with empty email")
            return False

        normalized_email = email.strip().lower()
        if not normalized_email:
            log("info", "delete_preregistered_email called with invalid email")
            return False

        self._ensure_preregistered_emails_table()

        with self.db.get_session() as session:
            row = (
                session.query(PreregisteredEmail)
                .filter(func.lower(PreregisteredEmail.email) == normalized_email)
                .first()
            )
            if not row:
                return False
            session.delete(row)
            log("info", f"Deleted preregistered email: {email}")
            return True

    def delete_all_preregistered_emails(self) -> int:
        """Delete all pre-registered emails. Returns count of deleted rows."""
        self._ensure_preregistered_emails_table()

        with self.db.get_session() as session:
            count = session.query(PreregisteredEmail).delete()
            log("info", f"Deleted {count} preregistered emails")
            return count

    def add_preregistered_email(
        self,
        email: str,
        requesting_user_id: Optional[str] = None,
        deadline_months: int = 6,
        expiry_message: Optional[str] = None,
    ) -> bool:
        """Add a single pre-registered email.

        Args:
            email: Email address to add
            requesting_user_id: ID of user adding the email

        Returns:
            True if email was added, False if it already exists or is invalid
        """
        if not email:
            return False

        normalized_email = email.strip().lower()
        if not normalized_email:
            return False

        email_regex = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
        if not email_regex.match(normalized_email):
            return False

        safe_deadline_months = max(1, int(deadline_months or 6))
        normalized_message = (expiry_message or "").strip() or None

        self._ensure_preregistered_emails_table()

        with self.db.get_session() as session:
            existing = (
                session.query(PreregisteredEmail)
                .filter(func.lower(PreregisteredEmail.email) == normalized_email)
                .first()
            )
            if existing:
                return False

            session.add(
                PreregisteredEmail(
                    email=normalized_email,
                    added_at=datetime.utcnow(),
                    added_by=requesting_user_id,
                    deadline_months=safe_deadline_months,
                    expiry_message=normalized_message,
                )
            )
            session.commit()
            return True

    def generate_reset_code(
        self, user_id: str, requesting_user_id: Optional[str] = None
    ) -> Optional[str]:
        """Generate a password reset code for a user.

        Args:
            user_id: ID of user to generate code for
            requesting_user_id: ID of user requesting the code (for permission checks)

        Returns:
            Reset code string if successful, None otherwise
        """
        self._ensure_table_exists()

        with self.db.get_session() as session:
            user = (
                session.query(UserTable)
                .filter(func.lower(UserTable.id) == user_id.lower())
                .first()
            )
            if not user:
                user = (
                    session.query(UserTable)
                    .filter(func.lower(UserTable.email) == user_id.lower())
                    .first()
                )
            if not user:
                return None

            # Check permissions if requesting_user_id provided
            if requesting_user_id:
                requesting_user = (
                    session.query(UserTable).filter_by(id=requesting_user_id).first()
                )
                if not requesting_user:
                    return None

                # Admin can generate for anyone
                if requesting_user.role == UserRole.ADMIN.value:
                    pass
                # Master can generate for themselves and their children
                elif requesting_user.role == UserRole.MASTER.value:
                    if (
                        user_id != requesting_user_id
                        and user.parent_id != requesting_user_id
                    ):
                        return None
                # Users can request reset code for themselves
                elif user_id == requesting_user_id:
                    pass
                else:
                    # Normal users cannot generate reset codes for others
                    return None

            # Generate reset code
            reset_code = self._generate_reset_code()
            user.reset_code = reset_code
            user.reset_code_expires = datetime.utcnow() + timedelta(days=1)

            session.commit()

            self.log_user_action(
                user_id=requesting_user_id or user_id,
                action=UserAction.GENERATE_RESET_CODE.value,
                target_user_id=user_id,
                target_username=user.name,
                success=True,
            )

            return reset_code

    def reset_password_with_code(
        self, user_id: str, reset_code: str, new_password: str
    ) -> bool:
        """Reset a user's password using a reset code.

        Args:
            user_id: User ID of the user
            reset_code: The reset code
            new_password: New password to set

        Returns:
            True if successful, False otherwise
        """
        log(
            "info",
            f"Resetting password for user '{user_id}' '{reset_code}' '{new_password}'",
        )
        self._ensure_table_exists()

        with self.db.get_session() as session:
            user = (
                session.query(UserTable)
                .filter(func.lower(UserTable.id) == user_id.lower())
                .first()
            )

            if not user:
                user = (
                    session.query(UserTable)
                    .filter(func.lower(UserTable.email) == user_id.lower())
                    .first()
                )

            if not user:
                self.log_user_action(
                    user_id=None,
                    action=UserAction.RESET_PASSWORD.value,
                    details={"username": user_id, "reason": "user_not_found"},
                    success=False,
                )
                log("error", f"User '{user_id}' not found")
                return False

            if not user.reset_code or not user.reset_code_expires:
                self.log_user_action(
                    user_id=user.id,
                    action=UserAction.RESET_PASSWORD.value,
                    details={"reason": "no_reset_code"},
                    success=False,
                )
                log("error", f"User '{user_id}' has no reset code")
                return False

            if user.reset_code_expires < datetime.utcnow():
                self.log_user_action(
                    user_id=user.id,
                    action=UserAction.RESET_PASSWORD.value,
                    details={"reason": "code_expired"},
                    success=False,
                )
                log("error", f"Reset code for user '{user_id}' has expired")
                return False

            if not secrets.compare_digest(user.reset_code, reset_code):
                self.log_user_action(
                    user_id=user.id,
                    action=UserAction.RESET_PASSWORD.value,
                    details={"reason": "invalid_code"},
                    success=False,
                )
                log("error", f"Invalid reset code for user '{user_id}'")
                return False

            # Set new password
            user.password_hash = self._hash_password(new_password)
            user.reset_code = None
            user.reset_code_expires = None

            session.commit()

            self.log_user_action(
                user_id=user.id,
                action=UserAction.RESET_PASSWORD.value,
                target_user_id=user.id,
                target_username=user.name,
                success=True,
            )

            return True

    def change_password(
        self, user_id: str, current_password: str, new_password: str
    ) -> bool:
        """Change a user's password (requires current password)."""
        self._ensure_table_exists()

        with self.db.get_session() as session:
            user = session.query(UserTable).filter_by(id=user_id).first()
            if not user:
                return False

            if not user.password_hash:
                return False

            if not self._verify_password(current_password, user.password_hash):
                self.log_user_action(
                    user_id=user_id,
                    action=UserAction.CHANGE_PASSWORD.value,
                    details={"reason": "invalid_current_password"},
                    success=False,
                )
                return False

            user.password_hash = self._hash_password(new_password)
            session.commit()

            self.log_user_action(
                user_id=user_id, action=UserAction.CHANGE_PASSWORD.value, success=True
            )

            return True

    def set_password(
        self, user_id: str, new_password: str, requesting_user_id: Optional[str] = None
    ) -> bool:
        """Set a user's password directly (admin/master function).

        Args:
            user_id: ID of user to set password for
            new_password: New password to set
            requesting_user_id: ID of user performing the action (for permission checks)

        Returns:
            True if successful, False otherwise
        """
        self._ensure_table_exists()

        with self.db.get_session() as session:
            user = session.query(UserTable).filter_by(id=user_id).first()
            if not user:
                return False

            # Check permissions if requesting_user_id provided
            if requesting_user_id:
                requesting_user = (
                    session.query(UserTable).filter_by(id=requesting_user_id).first()
                )
                if not requesting_user:
                    return False

                # Admin can set for anyone
                if requesting_user.role == UserRole.ADMIN.value:
                    pass
                # Master can set for themselves and their children
                elif requesting_user.role == UserRole.MASTER.value:
                    if (
                        user_id != requesting_user_id
                        and user.parent_id != requesting_user_id
                    ):
                        return False
                else:
                    return False

            user.password_hash = self._hash_password(new_password)
            session.commit()

            self.log_user_action(
                user_id=requesting_user_id or user_id,
                action=UserAction.CHANGE_PASSWORD.value,
                target_user_id=user_id,
                target_username=user.name,
                success=True,
            )

            return True

    def get_all_users(
        self, current_user_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get all users, with filtering based on current user's role."""
        self._ensure_table_exists()

        with self.db.get_session() as session:
            query = session.query(UserTable).options(joinedload(UserTable.parent))

            # Apply role-based filtering
            if current_user_id:
                current_user = (
                    session.query(UserTable).filter_by(id=current_user_id).first()
                )
                if current_user:
                    if current_user.role == UserRole.ADMIN.value:
                        # Admin sees all users
                        pass
                    elif current_user.role == UserRole.MASTER.value:
                        # Master sees themselves and their children
                        query = query.filter(
                            (UserTable.id == current_user_id)
                            | (UserTable.parent_id == current_user_id)
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
            users = (
                session.query(UserTable)
                .options(joinedload(UserTable.parent))
                .filter(UserTable.role == role)
                .order_by(UserTable.created_at)
                .all()
            )
            return [self._user_to_dict(user) for user in users]

    def get_children(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all children of a user."""
        self._ensure_table_exists()

        with self.db.get_session() as session:
            user = (
                session.query(UserTable)
                .options(joinedload(UserTable.children))
                .filter_by(id=user_id)
                .first()
            )
            if user and hasattr(user, "children") and user.children:
                return [self._user_to_dict(child) for child in user.children]
            return []

    def get_descendants(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all descendants of a user (children, grandchildren, etc.)."""
        self._ensure_table_exists()

        with self.db.get_session() as session:
            all_users = (
                session.query(UserTable).options(joinedload(UserTable.parent)).all()
            )

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

    def create_user(
        self,
        name: str,
        role: str = UserRole.NORMAL.value,
        email: Optional[str] = None,
        parent_id: Optional[str] = None,
        profile: Optional[Dict] = None,
        password: Optional[str] = None,
        requesting_user_id: Optional[str] = None,
        user_id: Optional[str] = None,
        allow_orphan_normal: bool = False,
        registration_status: str = "approved",
        user_metadata: Optional[Dict] = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        """Create a new user with validation.

        Args:
            name: Username (required)
            role: User role
            email: Optional email
            parent_id: Parent user ID (required for normal users)
            profile: User profile preferences
            password: Optional password (if not provided, will require reset)
            requesting_user_id: ID of user creating this user (for permission checks and logging)

        Returns:
            Tuple of (user_id, reset_code) where reset_code is generated if no password provided
        """
        # Validate name
        if not name or not name.strip():
            raise ValueError("User name cannot be empty")

        # Validate role
        valid_roles = [role.value for role in UserRole]
        if role not in valid_roles:
            raise ValueError(f"Invalid role. Must be one of: {', '.join(valid_roles)}")

        # Validate parent for normal users
        if role == UserRole.NORMAL.value and not parent_id and not allow_orphan_normal:
            raise ValueError("Normal users must have a parent (master)")

        if registration_status not in {"approved", "pending", "rejected"}:
            raise ValueError("Invalid registration_status")

        # Validate parent exists and is a master
        if parent_id:
            self._ensure_table_exists()
            with self.db.get_session() as session:
                parent = session.query(UserTable).filter_by(id=parent_id).first()
                if not parent:
                    raise ValueError(f"Parent user with ID {parent_id} not found")
                if parent.role != UserRole.MASTER.value:
                    raise ValueError(f"Parent user must be a master, not {parent.role}")

        # Check if username already exists
        existing = self.get_user_by_name(name)
        if existing:
            raise ValueError(f"Username '{name}' already exists")

        self._ensure_table_exists()

        explicit_user_id = user_id is not None
        user_id = user_id or str(uuid.uuid4())
        reset_code = None

        with self.db.get_session() as session:
            if (
                explicit_user_id
                and session.query(UserTable).filter_by(id=user_id).first()
            ):
                raise ValueError(f"User ID '{user_id}' already exists")

            # Hash password if provided
            password_hash = None
            if password:
                password_hash = self._hash_password(password)
            else:
                # Generate reset code
                reset_code = self._generate_reset_code()

            user = UserTable(
                id=user_id,
                name=name.strip(),
                email=email,
                password_hash=password_hash,
                role=role,
                registration_status=registration_status,
                parent_id=parent_id,
                created_at=datetime.utcnow(),
                is_active=True,
                profile=profile or {"language": "en"},
                user_metadata={"created_via": "ui", **(user_metadata or {})},
                reset_code=reset_code,
                reset_code_expires=datetime.utcnow() + timedelta(days=1)
                if reset_code
                else None,
            )
            session.add(user)

        log("info", f"Created user: {name.strip()} (ID: {user_id}, Role: {role})")

        # Log the creation
        self.log_user_action(
            user_id=requesting_user_id or user_id,
            action=UserAction.CREATE_USER.value,
            target_user_id=user_id,
            target_username=name.strip(),
            details={"role": role, "has_password": password is not None},
            success=True,
        )

        return user_id, reset_code

    def update_user(
        self, user_id: str, current_user_id: Optional[str] = None, **kwargs
    ) -> bool:
        """Update user information with permission checks."""
        self._ensure_table_exists()

        with self.db.get_session() as session:
            user = session.query(UserTable).filter_by(id=user_id).first()
            if not user:
                return False

            # Check permissions if current_user_id is provided
            if current_user_id:
                current_user = (
                    session.query(UserTable).filter_by(id=current_user_id).first()
                )
                if not self.can_manage_user(current_user, user):
                    log(
                        "warning",
                        f"User {current_user_id} cannot manage user {user_id}",
                    )
                    self.log_user_action(
                        user_id=current_user_id,
                        action=UserAction.UPDATE_USER.value,
                        target_user_id=user_id,
                        details={"reason": "permission_denied"},
                        success=False,
                    )
                    return False

            # Handle ID change specially
            new_id = kwargs.get("new_id")
            if new_id and new_id != user_id:
                # Only admin can change user IDs
                if current_user_id and current_user.role != UserRole.ADMIN.value:
                    raise ValueError("Only admin users can change user IDs")

                # Check if new ID already exists
                existing_user = session.query(UserTable).filter_by(id=new_id).first()
                if existing_user:
                    raise ValueError(f"User ID '{new_id}' already exists")

                # Store old ID for logging
                old_id = user_id
            else:
                new_id = None

            # Validate role changes
            if "role" in kwargs:
                new_role = kwargs["role"]
                valid_roles = [role.value for role in UserRole]
                if new_role not in valid_roles:
                    raise ValueError(
                        f"Invalid role. Must be one of: {', '.join(valid_roles)}"
                    )

                # Normal users must have a parent
                if (
                    new_role == UserRole.NORMAL.value
                    and not user.parent_id
                    and "parent_id" not in kwargs
                ):
                    raise ValueError("Normal users must have a parent")

                # If changing from normal to another role, keep parent for reference but can be None
                if (
                    user.role == UserRole.NORMAL.value
                    and new_role != UserRole.NORMAL.value
                ):
                    kwargs["parent_id"] = None

            # Validate parent changes
            if "parent_id" in kwargs:
                parent_id = kwargs["parent_id"]
                if parent_id:
                    parent = session.query(UserTable).filter_by(id=parent_id).first()
                    if not parent:
                        raise ValueError(f"Parent user with ID {parent_id} not found")
                    if parent.role != UserRole.MASTER.value:
                        raise ValueError(
                            f"Parent user must be a master, not {parent.role}"
                        )
                    if user.role != UserRole.NORMAL.value:
                        raise ValueError("Only normal users can have a parent")

            # Track changes for logging
            changes = {}
            if new_id:
                changes["id"] = {"old": old_id, "new": new_id}

            for key, value in kwargs.items():
                if key in [
                    "password_hash",
                    "reset_code",
                    "reset_code_expires",
                    "new_id",
                ]:
                    continue  # Skip sensitive or special fields in logging

                if key == "user_metadata":
                    key_display = "metadata"
                elif key == "key":
                    key_display = key
                else:
                    key_display = key

                old_value = getattr(user, key, None)
                if old_value != value:
                    changes[key_display] = {"old": str(old_value), "new": str(value)}

            # Update fields (including ID if requested)
            if new_id:
                # Update the ID - this requires special handling
                # First, update any foreign key references if needed
                # Then update the user's ID
                user.id = new_id

            for key, value in kwargs.items():
                if key in [
                    "new_id",
                    "password_hash",
                    "reset_code",
                    "reset_code_expires",
                ]:
                    continue
                elif key == "user_metadata":
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

            # Log the update
            self.log_user_action(
                user_id=current_user_id or user_id,
                action=UserAction.UPDATE_USER.value,
                target_user_id=new_id or user_id,
                target_username=user.name,
                details={"changes": changes},
                success=True,
            )

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
        if not hasattr(self, "_profile_preferences_callbacks"):
            self._profile_preferences_callbacks = []

        callback_name = getattr(callback_func, "__name__", str(callback_func))

        # Check by object identity first
        if callback_func in self._profile_preferences_callbacks:
            log(
                "debug",
                f"Profile preferences callback {callback_name} already registered (by object identity)",
            )
            return

        # Check by function name and handle duplicates
        for i, existing_cb in enumerate(self._profile_preferences_callbacks):
            existing_name = getattr(existing_cb, "__name__", str(existing_cb))
            if existing_name == callback_name:
                log(
                    "debug",
                    f"Profile preferences callback with name '{callback_name}' already registered. "
                    f"Replacing existing callback with new one.",
                )
                self._profile_preferences_callbacks[i] = callback_func
                return

        self._profile_preferences_callbacks.append(callback_func)
        log("debug", f"Registered profile preferences callback: {callback_name}")

    def get_profile_preferences_schema(self) -> Dict[str, Any]:
        """Get the schema for profile preferences from all registered callbacks."""
        schema = {
            "language": {
                "type": "select",
                "options": ["en", "fr", "de", "es", "it", "zh", "ja", "ko"],
                "default": "en",
                "label": "Preferred Language",
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
        register_callback(
            callback_list=self._before_delete_callbacks,
            callback_func=callback_func,
            callback_type="before_delete callback",
            allow_replace=True,
        )

    def unregister_before_delete_callback(self, callback_func):
        """Unregister a before_delete callback."""
        return unregister_callback(
            callback_list=self._before_delete_callbacks,
            callback_func=callback_func,
            callback_type="before_delete callback",
        )

    def clear_before_delete_callbacks(self) -> int:
        """Clear all before_delete callbacks."""
        return clear_callbacks(self._before_delete_callbacks, "before_delete callback")

    def delete_user(self, user_id: str, current_user_id: Optional[str] = None) -> bool:
        """Delete a user with permission checks."""
        self._ensure_table_exists()

        # Check permissions
        target_user = None
        if current_user_id:
            with self.db.get_session() as session:
                current_user = (
                    session.query(UserTable).filter_by(id=current_user_id).first()
                )
                target_user = session.query(UserTable).filter_by(id=user_id).first()
                if not current_user or not target_user:
                    return False
                if not self.can_manage_user(current_user, target_user):
                    log(
                        "warning",
                        f"User {current_user_id} cannot delete user {user_id}",
                    )
                    self.log_user_action(
                        user_id=current_user_id,
                        action=UserAction.DELETE_USER.value,
                        target_user_id=user_id,
                        details={"reason": "permission_denied"},
                        success=False,
                    )
                    return False
        else:
            # Get target user for logging
            target_user_dict = self.get_user(user_id)
            if not target_user_dict:
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
            log(
                "error",
                f"Aborting user deletion for {user_id} due to callback failures",
            )
            return False

        with self.db.get_session() as session:
            user = session.query(UserTable).filter_by(id=user_id).first()
            if not user:
                return False

            # Delete action logs where user is actor or target
            session.query(UserActionLog).filter(
                (UserActionLog.user_id == user_id)
                | (UserActionLog.target_user_id == user_id)
            ).delete(synchronize_session=False)

            user_name = user.name
            session.delete(user)
            session.commit()

            log("info", f"Deleted user: {user_name} (ID: {user_id})")
            return True

    def update_last_login(self, user_id: str):
        """Update user's last login timestamp and remove from preregistered list."""
        user = self.get_user(user_id)
        if user and user.get("email"):
            self.delete_preregistered_email(user["email"])
        self.update_user(user_id, last_login=datetime.utcnow())

    def get_all_users_dict(
        self, current_user_id: Optional[str] = None
    ) -> Dict[str, Dict[str, Any]]:
        """Get all users as a dictionary with user_id as key."""
        users = self.get_all_users(current_user_id)
        return {user["id"]: user for user in users}

    def search_users(
        self, query: str, current_user_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Search users by name or email."""
        users = self.get_all_users(current_user_id)
        query_lower = query.lower()

        return [
            user
            for user in users
            if query_lower in user["name"].lower()
            or (user["email"] and query_lower in user["email"].lower())
        ]

    def get_active_users(
        self, current_user_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get all active users."""
        users = self.get_all_users(current_user_id)
        return [user for user in users if user.get("is_active", True)]

    def get_user_count(self, current_user_id: Optional[str] = None) -> int:
        """Get total number of users."""
        users = self.get_all_users(current_user_id)
        return len(users)


def get_user_manager():
    return UserManager()
