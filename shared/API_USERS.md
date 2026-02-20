<!-- shared/users.py -->

<!-- GENERATED FILE - do not edit manually -->
<!-- Source: shared/users.py -->

# API — users

User management with database backend.

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
