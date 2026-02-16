"""
Tests for the user management module.
"""
import pytest
import sys
import os
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch, Mock

from shared.users import UserManager, UserTable, UserRole, UserAction


class TestUserManager:
    """Test the UserManager class."""

    def setup_method(self):
        """Setup for each test."""
        # Clear the singleton instance
        UserManager._instance = None

        # Create a fresh instance with proper mocking
        self.user_manager = UserManager()

        # Mock the database manager completely to avoid any real DB operations
        self.user_manager.db = MagicMock()
        self.user_manager.db.is_initialized = MagicMock(return_value=True)
        self.user_manager.db._engine = MagicMock()

        # Mock _ensure_table_exists to do nothing
        self.user_manager._ensure_table_exists = MagicMock()

        # Set up a proper mock for the session context manager
        self.mock_session = MagicMock()

        # Create a context manager class
        class MockSessionContext:
            def __init__(self, session):
                self.session = session
                self.commit_called = False
                self.rollback_called = False

            def __enter__(self):
                return self.session

            def __exit__(self, exc_type, exc_val, exc_tb):
                if exc_type is None:
                    self.session.commit()
                else:
                    self.session.rollback()
                self.session.close()
                return False  # Don't suppress exceptions

        # Create the context manager instance
        self.mock_context = MockSessionContext(self.mock_session)

        # Mock get_session to return our context manager
        self.user_manager.db.get_session = MagicMock(return_value=self.mock_context)

    def teardown_method(self):
        """Cleanup after each test."""
        # Clear the singleton to avoid test contamination
        UserManager._instance = None

    def test_singleton(self):
        """Test that UserManager is a singleton."""
        # Clear singleton first
        UserManager._instance = None

        user_manager1 = UserManager()
        user_manager2 = UserManager()
        assert user_manager1 is user_manager2

    def test_create_default_users(self):
        """Test creating 7 default users."""
        # Mock query count
        mock_query = MagicMock()
        mock_query.count.return_value = 0
        self.mock_session.query.return_value = mock_query

        # Mock the log to avoid output
        with patch('shared.users.log'):
            self.user_manager._create_default_users_fallback()

        # Verify session.add was called 7 times
        assert self.mock_session.add.call_count == 7

    def test_create_default_users_when_users_exist(self):
        """Test creating default users when users already exist."""
        # Mock query count to return 1 (users already exist)
        mock_query = MagicMock()
        mock_query.count.return_value = 1
        self.mock_session.query.return_value = mock_query

        # Mock the log to avoid output
        with patch('shared.users.log'):
            self.user_manager.create_default_users()

        # Verify session.add was NOT called
        self.mock_session.add.assert_not_called()

    def test_get_user(self):
        """Test getting a user."""
        # Mock parent user
        mock_parent = MagicMock(spec=UserTable)
        mock_parent.id = 'master1'
        mock_parent.name = 'Master User'

        # Mock user object
        mock_user = MagicMock(spec=UserTable)
        mock_user.id = 'test1'
        mock_user.name = 'Test User'
        mock_user.email = 'test@example.com'
        mock_user.role = UserRole.NORMAL.value
        mock_user.parent_id = 'master1'
        mock_user.parent = mock_parent
        mock_user.created_at = datetime(2023, 1, 1)
        mock_user.last_login = datetime(2023, 1, 2)
        mock_user.is_active = True
        mock_user.profile = {"language": "en"}
        mock_user.user_metadata = {"key": "value"}
        mock_user.child_users = []

        # Setup query
        mock_query = MagicMock()
        mock_query.options.return_value.filter_by.return_value.first.return_value = mock_user
        self.mock_session.query.return_value = mock_query

        user = self.user_manager.get_user('test1')

        assert user['id'] == 'test1'
        assert user['name'] == 'Test User'
        assert user['email'] == 'test@example.com'
        assert user['role'] == UserRole.NORMAL.value
        assert user['parent_id'] == 'master1'
        assert user['parent_name'] == 'Master User'
        assert user['is_active'] == True
        assert user['profile'] == {"language": "en"}
        assert user['metadata'] == {"key": "value"}

    def test_get_user_not_found(self):
        """Test getting a non-existent user."""
        # Setup query to return None
        mock_query = MagicMock()
        mock_query.options.return_value.filter_by.return_value.first.return_value = None
        self.mock_session.query.return_value = mock_query

        user = self.user_manager.get_user('nonexistent')
        assert user is None

    def test_get_all_users(self):
        """Test getting all users."""
        # Mock users
        mock_parent = MagicMock(spec=UserTable)
        mock_parent.id = 'master1'
        mock_parent.name = 'Master User'

        mock_user1 = MagicMock(spec=UserTable)
        mock_user1.id = 'test1'
        mock_user1.name = 'User 1'
        mock_user1.email = 'user1@example.com'
        mock_user1.role = UserRole.ADMIN.value
        mock_user1.parent_id = None
        mock_user1.parent = None
        mock_user1.created_at = datetime(2023, 1, 1)
        mock_user1.last_login = None
        mock_user1.is_active = True
        mock_user1.profile = {}
        mock_user1.user_metadata = {}

        mock_user2 = MagicMock(spec=UserTable)
        mock_user2.id = 'test2'
        mock_user2.name = 'User 2'
        mock_user2.email = 'user2@example.com'
        mock_user2.role = UserRole.NORMAL.value
        mock_user2.parent_id = 'master1'
        mock_user2.parent = mock_parent
        mock_user2.created_at = datetime(2023, 1, 2)
        mock_user2.last_login = datetime(2023, 1, 3)
        mock_user2.is_active = False
        mock_user2.profile = {"language": "en"}
        mock_user2.user_metadata = {"is_default": True}

        # Setup query
        mock_query = MagicMock()
        mock_query.options.return_value.order_by.return_value.all.return_value = [mock_user1, mock_user2]
        self.mock_session.query.return_value = mock_query

        users = self.user_manager.get_all_users()

        assert len(users) == 2
        assert users[0]['id'] == 'test1'
        assert users[0]['name'] == 'User 1'
        assert users[0]['role'] == UserRole.ADMIN.value
        assert users[0]['is_active'] == True
        assert users[1]['id'] == 'test2'
        assert users[1]['name'] == 'User 2'
        assert users[1]['role'] == UserRole.NORMAL.value
        assert users[1]['parent_name'] == 'Master User'
        assert users[1]['is_active'] == False

    def test_create_user_success(self):
        """Test successful user creation."""
        # Test UUID
        test_uuid_str = '123e4567-e89b-12d3-a456-426614174000'

        # Create a UUID object that when converted to string returns our test string
        mock_uuid = MagicMock()
        mock_uuid.__str__ = MagicMock(return_value=test_uuid_str)

        # Mock parent check
        mock_parent = MagicMock(spec=UserTable)
        mock_parent.id = 'master1'
        mock_parent.role = UserRole.MASTER.value

        mock_query = MagicMock()
        mock_query.filter_by.return_value.first.return_value = mock_parent
        self.mock_session.query.return_value = mock_query

        # Mock get_user_by_name to return None (username doesn't exist)
        with patch.object(self.user_manager, 'get_user_by_name', return_value=None):
            with patch('uuid.uuid4', return_value=mock_uuid):
                with patch('shared.users.log'):
                    user_id, reset_code = self.user_manager.create_user(
                        name="New User",
                        role=UserRole.NORMAL.value,
                        email="new@example.com",
                        parent_id="master1",
                        profile={"language": "fr"}
                    )

        # Verify the user ID matches
        assert user_id == test_uuid_str
        assert reset_code is not None  # Since no password provided, reset code should be generated

        # Now add is called twice: once for user, once for action log
        assert self.mock_session.add.call_count == 2

        # Verify the user object was created with correct data
        # The first call should be the user
        added_user = self.mock_session.add.call_args_list[0][0][0]
        assert added_user.name == "New User"
        assert added_user.email == "new@example.com"
        assert added_user.role == UserRole.NORMAL.value
        assert added_user.parent_id == "master1"
        assert added_user.profile == {"language": "fr"}
        assert added_user.is_active == True

        # The second call should be the action log
        added_log = self.mock_session.add.call_args_list[1][0][0]
        assert added_log.action == UserAction.CREATE_USER.value
        assert added_log.target_user_id == test_uuid_str
        assert added_log.target_username == "New User"

    def test_create_user_admin(self):
        """Test creating an admin user."""
        test_uuid_str = '123e4567-e89b-12d3-a456-426614174000'
        mock_uuid = MagicMock()
        mock_uuid.__str__ = MagicMock(return_value=test_uuid_str)

        # Mock get_user_by_name to return None (username doesn't exist)
        with patch.object(self.user_manager, 'get_user_by_name', return_value=None):
            with patch('uuid.uuid4', return_value=mock_uuid):
                with patch('shared.users.log'):
                    user_id, reset_code = self.user_manager.create_user(
                        name="New Admin",
                        role=UserRole.ADMIN.value,
                        email="admin@example.com"
                    )

        assert user_id == test_uuid_str
        assert reset_code is not None  # Since no password provided, reset code should be generated

        # Now add is called twice: once for user, once for action log
        assert self.mock_session.add.call_count == 2

        # Verify the user object was created with correct data
        # The first call should be the user
        added_user = self.mock_session.add.call_args_list[0][0][0]
        assert added_user.role == UserRole.ADMIN.value
        assert added_user.parent_id is None

        # The second call should be the action log
        added_log = self.mock_session.add.call_args_list[1][0][0]
        assert added_log.action == UserAction.CREATE_USER.value
        assert added_log.target_user_id == test_uuid_str
        assert added_log.target_username == "New Admin"

    def test_create_user_empty_name(self):
        """Test user creation with empty name."""
        with pytest.raises(ValueError, match="User name cannot be empty"):
            self.user_manager.create_user("")

    def test_create_user_whitespace_name(self):
        """Test user creation with whitespace only name."""
        with pytest.raises(ValueError, match="User name cannot be empty"):
            self.user_manager.create_user("   ")

    def test_create_user_invalid_role(self):
        """Test user creation with invalid role."""
        with pytest.raises(ValueError, match="Invalid role"):
            self.user_manager.create_user("Test User", role="invalid_role")

    def test_create_user_normal_without_parent(self):
        """Test normal user creation without parent."""
        with pytest.raises(ValueError, match="Normal users must have a parent"):
            self.user_manager.create_user("Test User", role=UserRole.NORMAL.value)

    def test_create_user_with_invalid_parent(self):
        """Test user creation with invalid parent."""
        # Mock parent check to return a non-master
        mock_parent = MagicMock(spec=UserTable)
        mock_parent.id = 'normal_user'
        mock_parent.role = UserRole.NORMAL.value

        mock_query = MagicMock()
        mock_query.filter_by.return_value.first.return_value = mock_parent
        self.mock_session.query.return_value = mock_query

        with pytest.raises(ValueError, match="Parent user must be a master"):
            self.user_manager.create_user(
                "Test User",
                role=UserRole.NORMAL.value,
                parent_id="normal_user"
            )

    def test_create_user_with_nonexistent_parent(self):
        """Test user creation with nonexistent parent."""
        # Mock parent check to return None
        mock_query = MagicMock()
        mock_query.filter_by.return_value.first.return_value = None
        self.mock_session.query.return_value = mock_query

        with pytest.raises(ValueError, match="Parent user with ID"):
            self.user_manager.create_user(
                "Test User",
                role=UserRole.NORMAL.value,
                parent_id="nonexistent"
            )

    def test_update_user_success(self):
        """Test successful user update."""
        # Mock user
        mock_user = MagicMock(spec=UserTable)
        mock_user.id = 'test1'
        mock_user.role = UserRole.NORMAL.value
        mock_user.parent_id = 'master1'
        mock_user.profile = {"old": "value"}
        mock_user.user_metadata = {}
        mock_user.name = "Test User"  # Add name for logging

        # Setup query to return the user
        mock_query = MagicMock()
        mock_query.filter_by.return_value.first.return_value = mock_user
        self.mock_session.query.return_value = mock_query

        # We need to handle the fact that log_user_action will create its own session
        # and commit. Let's mock the logger to avoid extra commits in our test session
        with patch('shared.users.get_user_manager') as mock_get_user_manager:
            mock_user_manager = MagicMock()
            mock_get_user_manager.return_value = mock_user_manager

            success = self.user_manager.update_user(
                'test1',
                name='Updated Name',
                profile={'language': 'fr'},
                metadata={'new': 'metadata'}
            )

        assert success == True
        assert mock_user.name == 'Updated Name'
        assert mock_user.profile == {'language': 'fr'}
        assert mock_user.user_metadata == {'new': 'metadata'}

        # Verify the user update happened
        self.mock_session.commit.assert_called()

    def test_update_user_role_change(self):
        """Test updating user role."""
        # Mock user
        mock_user = MagicMock(spec=UserTable)
        mock_user.id = 'test1'
        mock_user.role = UserRole.NORMAL.value
        mock_user.parent_id = 'master1'

        # Setup query
        mock_query = MagicMock()
        mock_query.filter_by.return_value.first.return_value = mock_user
        self.mock_session.query.return_value = mock_query

        success = self.user_manager.update_user(
            'test1',
            role=UserRole.MASTER.value
        )

        assert success == True
        assert mock_user.role == UserRole.MASTER.value
        assert mock_user.parent_id is None  # Master shouldn't have a parent

    def test_update_user_normal_without_parent(self):
        """Test updating normal user without parent."""
        # Mock user
        mock_user = MagicMock(spec=UserTable)
        mock_user.id = 'test1'
        mock_user.role = UserRole.NORMAL.value
        mock_user.parent_id = None  # No parent!

        # Setup query
        mock_query = MagicMock()
        mock_query.filter_by.return_value.first.return_value = mock_user
        self.mock_session.query.return_value = mock_query

        with pytest.raises(ValueError, match="Normal users must have a parent"):
            self.user_manager.update_user(
                'test1',
                role=UserRole.NORMAL.value  # Trying to keep as normal without parent
            )

    def test_update_user_not_found(self):
        """Test updating non-existent user."""
        # Setup query to return None
        mock_query = MagicMock()
        mock_query.filter_by.return_value.first.return_value = None
        self.mock_session.query.return_value = mock_query

        success = self.user_manager.update_user('nonexistent', name='New Name')

        assert success == False

    def test_update_user_with_permission_check(self):
        """Test updating user with permission check."""
        # Mock current user (admin)
        mock_current_user = MagicMock(spec=UserTable)
        mock_current_user.id = 'admin1'
        mock_current_user.role = UserRole.ADMIN.value

        # Mock target user
        mock_target_user = MagicMock(spec=UserTable)
        mock_target_user.id = 'normal1'
        mock_target_user.role = UserRole.NORMAL.value
        mock_target_user.parent_id = 'master1'

        # Setup queries
        def query_side_effect(*args, **kwargs):
            if kwargs.get('id') == 'admin1':
                return MagicMock(first=MagicMock(return_value=mock_current_user))
            elif kwargs.get('id') == 'normal1':
                return MagicMock(first=MagicMock(return_value=mock_target_user))
            return MagicMock(first=MagicMock(return_value=None))

        mock_filter_by = MagicMock(side_effect=query_side_effect)
        mock_query = MagicMock()
        mock_query.filter_by = mock_filter_by
        self.mock_session.query.return_value = mock_query

        # Admin should be able to update normal user
        success = self.user_manager.update_user(
            'normal1',
            current_user_id='admin1',
            name='Updated Name'
        )

        assert success == True
        assert mock_target_user.name == 'Updated Name'

    def test_update_user_permission_denied(self):
        """Test updating user without permission."""
        # Mock current user (normal user)
        mock_current_user = MagicMock(spec=UserTable)
        mock_current_user.id = 'normal1'
        mock_current_user.role = UserRole.NORMAL.value

        # Mock target user (different normal user)
        mock_target_user = MagicMock(spec=UserTable)
        mock_target_user.id = 'normal2'
        mock_target_user.role = UserRole.NORMAL.value
        mock_target_user.parent_id = 'master1'

        # Setup queries
        def query_side_effect(*args, **kwargs):
            if kwargs.get('id') == 'normal1':
                return MagicMock(first=MagicMock(return_value=mock_current_user))
            elif kwargs.get('id') == 'normal2':
                return MagicMock(first=MagicMock(return_value=mock_target_user))
            return MagicMock(first=MagicMock(return_value=None))

        mock_filter_by = MagicMock(side_effect=query_side_effect)
        mock_query = MagicMock()
        mock_query.filter_by = mock_filter_by
        self.mock_session.query.return_value = mock_query

        # Normal user should NOT be able to update another normal user
        success = self.user_manager.update_user(
            'normal2',
            current_user_id='normal1',
            name='Updated Name'
        )

        assert success == False

    def test_can_manage_user(self):
        """Test can_manage_user method."""
        # Create mock users
        admin_user = MagicMock(spec=UserTable)
        admin_user.id = 'admin1'
        admin_user.role = UserRole.ADMIN.value

        master_user = MagicMock(spec=UserTable)
        master_user.id = 'master1'
        master_user.role = UserRole.MASTER.value

        normal_user1 = MagicMock(spec=UserTable)
        normal_user1.id = 'normal1'
        normal_user1.role = UserRole.NORMAL.value
        normal_user1.parent_id = 'master1'

        normal_user2 = MagicMock(spec=UserTable)
        normal_user2.id = 'normal2'
        normal_user2.role = UserRole.NORMAL.value
        normal_user2.parent_id = 'master2'  # Different master

        # Admin can manage everyone
        assert self.user_manager.can_manage_user(admin_user, admin_user) == True
        assert self.user_manager.can_manage_user(admin_user, master_user) == True
        assert self.user_manager.can_manage_user(admin_user, normal_user1) == True

        # Master can manage themselves and their children
        assert self.user_manager.can_manage_user(master_user, master_user) == True
        assert self.user_manager.can_manage_user(master_user, normal_user1) == True  # His child
        assert self.user_manager.can_manage_user(master_user, normal_user2) == False  # Not his child
        assert self.user_manager.can_manage_user(master_user, admin_user) == False

        # Normal user can only manage themselves
        assert self.user_manager.can_manage_user(normal_user1, normal_user1) == True
        assert self.user_manager.can_manage_user(normal_user1, normal_user2) == False
        assert self.user_manager.can_manage_user(normal_user1, master_user) == False
        assert self.user_manager.can_manage_user(normal_user1, admin_user) == False

    def test_get_manageable_users(self):
        """Test getting manageable users."""
        # Mock get_user for admin
        admin_user = {
            "id": "admin1",
            "name": "Admin",
            "role": UserRole.ADMIN.value
        }

        # Mock get_user for master
        master_user = {
            "id": "master1",
            "name": "Master",
            "role": UserRole.MASTER.value
        }

        # Mock get_user for normal user
        normal_user = {
            "id": "normal1",
            "name": "Normal",
            "role": UserRole.NORMAL.value
        }

        # Mock get_all_users
        all_users = [
            {"id": "admin1", "name": "Admin", "role": UserRole.ADMIN.value},
            {"id": "master1", "name": "Master", "role": UserRole.MASTER.value},
            {"id": "master2", "name": "Master 2", "role": UserRole.MASTER.value},
            {"id": "normal1", "name": "Normal 1", "role": UserRole.NORMAL.value},
            {"id": "normal2", "name": "Normal 2", "role": UserRole.NORMAL.value},
        ]

        # Mock get_children for master
        master_children = [
            {"id": "normal1", "name": "Normal 1", "role": UserRole.NORMAL.value},
            {"id": "normal2", "name": "Normal 2", "role": UserRole.NORMAL.value},
        ]

        # Test admin
        with patch.object(self.user_manager, 'get_user', return_value=admin_user):
            with patch.object(self.user_manager, 'get_all_users', return_value=all_users):
                manageable = self.user_manager.get_manageable_users('admin1')
                assert len(manageable) == 5  # All users
                assert manageable[0]['id'] == 'admin1'

        # Test master
        with patch.object(self.user_manager, 'get_user', return_value=master_user):
            with patch.object(self.user_manager, 'get_children', return_value=master_children):
                manageable = self.user_manager.get_manageable_users('master1')
                assert len(manageable) == 3  # Master + 2 children
                assert manageable[0]['id'] == 'normal1'
                assert manageable[1]['id'] == 'normal2'
                assert manageable[2]['id'] == 'master1'

        # Test normal user
        with patch.object(self.user_manager, 'get_user', return_value=normal_user):
            manageable = self.user_manager.get_manageable_users('normal1')
            assert len(manageable) == 1  # Only themselves
            assert manageable[0]['id'] == 'normal1'

    def test_get_users_by_role(self):
        """Test getting users by role."""
        # Mock users
        mock_user1 = MagicMock(spec=UserTable)
        mock_user1.id = 'admin1'
        mock_user1.role = UserRole.ADMIN.value
        # ... setup other attributes

        mock_user2 = MagicMock(spec=UserTable)
        mock_user2.id = 'master1'
        mock_user2.role = UserRole.MASTER.value
        # ... setup other attributes

        # Setup query
        mock_query = MagicMock()
        mock_query.options.return_value.filter.return_value.order_by.return_value.all.return_value = [mock_user1]
        self.mock_session.query.return_value = mock_query

        admins = self.user_manager.get_users_by_role(UserRole.ADMIN.value)

        assert len(admins) == 1
        assert admins[0]['role'] == UserRole.ADMIN.value

    def test_get_children(self):
        """Test getting children of a user."""
        # Mock children
        mock_child1 = MagicMock(spec=UserTable)
        mock_child1.id = 'child1'
        mock_child1.role = UserRole.NORMAL.value
        # ... setup other attributes

        mock_child2 = MagicMock(spec=UserTable)
        mock_child2.id = 'child2'
        mock_child2.role = UserRole.NORMAL.value
        # ... setup other attributes

        # Mock parent user with children
        mock_parent = MagicMock(spec=UserTable)
        mock_parent.child_users = [mock_child1, mock_child2]

        # Setup query
        mock_query = MagicMock()
        mock_query.options.return_value.filter_by.return_value.first.return_value = mock_parent
        self.mock_session.query.return_value = mock_query

        children = self.user_manager.get_children('parent1')

        assert len(children) == 2
        assert children[0]['id'] == 'child1'
        assert children[1]['id'] == 'child2'

    def test_get_descendants(self):
        """Test getting descendants of a user."""
        # Create mock users with proper parent relationships
        mock_master1 = MagicMock(spec=UserTable)
        mock_master1.id = "master1"
        mock_master1.name = "Master 1"
        mock_master1.role = UserRole.MASTER.value
        mock_master1.parent_id = None

        mock_master2 = MagicMock(spec=UserTable)
        mock_master2.id = "master2"
        mock_master2.name = "Master 2"
        mock_master2.role = UserRole.MASTER.value
        mock_master2.parent_id = None

        user1 = MagicMock(spec=UserTable)
        user1.id = "normal1"
        user1.parent_id = "master1"
        user1.parent = None  # Will be set by joinedload

        user2 = MagicMock(spec=UserTable)
        user2.id = "normal2"
        user2.parent_id = "master1"
        user2.parent = None

        user3 = MagicMock(spec=UserTable)
        user3.id = "normal3"
        user3.parent_id = "master2"
        user3.parent = None

        # Setup the query chain
        mock_query = MagicMock()
        mock_options = MagicMock()
        mock_all = MagicMock(return_value=[user1, user2, user3])

        mock_query.options.return_value.all = mock_all
        self.mock_session.query.return_value = mock_query

        # Mock _user_to_dict to return simple dicts
        with patch.object(self.user_manager, '_user_to_dict') as mock_to_dict:
            mock_to_dict.side_effect = lambda u: {"id": u.id, "parent_id": u.parent_id}

            descendants = self.user_manager.get_descendants('master1')

            # Should find normal1 and normal2 as descendants of master1
            assert len(descendants) == 2
            descendant_ids = {d['id'] for d in descendants}
            assert descendant_ids == {'normal1', 'normal2'}

    def test_delete_user_with_permission(self):
        """Test deleting user with permission check."""
        # Mock users
        mock_current_user = MagicMock(spec=UserTable)
        mock_current_user.id = 'admin1'
        mock_current_user.role = UserRole.ADMIN.value

        mock_target_user = MagicMock(spec=UserTable)
        mock_target_user.id = 'normal1'
        mock_target_user.name = 'Normal User'
        mock_target_user.role = UserRole.NORMAL.value
        mock_target_user.parent_id = 'master1'

        # Setup queries
        def query_side_effect(*args, **kwargs):
            if kwargs.get('id') == 'admin1':
                return MagicMock(first=MagicMock(return_value=mock_current_user))
            elif kwargs.get('id') == 'normal1':
                return MagicMock(first=MagicMock(return_value=mock_target_user))
            return MagicMock(first=MagicMock(return_value=None))

        mock_filter_by = MagicMock(side_effect=query_side_effect)
        mock_query = MagicMock()
        mock_query.filter_by = mock_filter_by
        self.mock_session.query.return_value = mock_query

        # Mock before_delete callbacks to succeed
        self.user_manager._before_delete_callbacks = [MagicMock(return_value=True)]

        with patch('shared.users.log'):
            success = self.user_manager.delete_user('normal1', 'admin1')

            assert success == True
            self.mock_session.delete.assert_called_once_with(mock_target_user)

    def test_delete_user_permission_denied(self):
        """Test deleting user without permission."""
        # Mock users
        mock_current_user = MagicMock(spec=UserTable)
        mock_current_user.id = 'normal1'
        mock_current_user.role = UserRole.NORMAL.value

        mock_target_user = MagicMock(spec=UserTable)
        mock_target_user.id = 'normal2'
        mock_target_user.role = UserRole.NORMAL.value
        mock_target_user.parent_id = 'master1'

        # Setup queries
        def query_side_effect(*args, **kwargs):
            if kwargs.get('id') == 'normal1':
                return MagicMock(first=MagicMock(return_value=mock_current_user))
            elif kwargs.get('id') == 'normal2':
                return MagicMock(first=MagicMock(return_value=mock_target_user))
            return MagicMock(first=MagicMock(return_value=None))

        mock_filter_by = MagicMock(side_effect=query_side_effect)
        mock_query = MagicMock()
        mock_query.filter_by = mock_filter_by
        self.mock_session.query.return_value = mock_query

        with patch('shared.users.log'):
            success = self.user_manager.delete_user('normal2', 'normal1')

            assert success == False
            self.mock_session.delete.assert_not_called()

    def test_profile_preferences_schema(self):
        """Test profile preferences schema."""
        # Test default schema
        schema = self.user_manager.get_profile_preferences_schema()

        assert 'language' in schema
        assert schema['language']['type'] == 'select'
        assert 'en' in schema['language']['options']

        # Test with custom callback
        def custom_callback():
            return {
                "theme": {
                    "type": "select",
                    "options": ["light", "dark"],
                    "default": "light",
                    "label": "Theme"
                }
            }

        self.user_manager.register_profile_preferences_callback(custom_callback)

        schema = self.user_manager.get_profile_preferences_schema()
        assert 'language' in schema
        assert 'theme' in schema
        assert schema['theme']['type'] == 'select'

    def test_update_last_login(self):
        """Test updating last login."""
        with patch.object(self.user_manager, 'update_user') as mock_update:
            # Mock datetime.utcnow
            test_time = datetime(2023, 1, 1, 12, 0, 0)
            with patch('shared.users.datetime') as mock_datetime:
                mock_datetime.utcnow.return_value = test_time

                self.user_manager.update_last_login("test1")
                mock_update.assert_called_once_with("test1", last_login=test_time)

    def test_get_all_users_dict(self):
        """Test getting all users as dictionary."""
        # Mock get_all_users to return a list
        mock_users_list = [
            {"id": "test1", "name": "User 1", "role": UserRole.ADMIN.value},
            {"id": "test2", "name": "User 2", "role": UserRole.NORMAL.value}
        ]

        with patch.object(self.user_manager, 'get_all_users', return_value=mock_users_list):
            users_dict = self.user_manager.get_all_users_dict()

            assert len(users_dict) == 2
            assert users_dict["test1"]["name"] == "User 1"
            assert users_dict["test2"]["name"] == "User 2"

    def test_search_users(self):
        """Test searching users."""
        # Mock get_all_users
        mock_users = [
            {"id": "1", "name": "John Doe", "email": "john@example.com", "role": UserRole.ADMIN.value},
            {"id": "2", "name": "Jane Smith", "email": "jane@example.com", "role": UserRole.MASTER.value},
            {"id": "3", "name": "Bob Johnson", "email": "bob@test.com", "role": UserRole.NORMAL.value},
            {"id": "4", "name": "No Email", "email": None, "role": UserRole.NORMAL.value}
        ]

        with patch.object(self.user_manager, 'get_all_users', return_value=mock_users):
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
        # Mock get_all_users
        mock_users = [
            {"id": "1", "name": "Active User", "is_active": True, "role": UserRole.ADMIN.value},
            {"id": "2", "name": "Inactive User", "is_active": False, "role": UserRole.MASTER.value},
            {"id": "3", "name": "Another Active", "is_active": True, "role": UserRole.NORMAL.value},
            {"id": "4", "name": "No Status", "role": UserRole.NORMAL.value}  # Should default to active
        ]

        with patch.object(self.user_manager, 'get_all_users', return_value=mock_users):
            active_users = self.user_manager.get_active_users()
            assert len(active_users) == 3  # Two active + one without status

    def test_get_user_count(self):
        """Test getting user count."""
        # Mock get_all_users
        mock_users = [
            {"id": "1", "name": "User 1", "role": UserRole.ADMIN.value},
            {"id": "2", "name": "User 2", "role": UserRole.MASTER.value},
            {"id": "3", "name": "User 3", "role": UserRole.NORMAL.value}
        ]

        with patch.object(self.user_manager, 'get_all_users', return_value=mock_users):
            count = self.user_manager.get_user_count()
            assert count == 3


def test_user_to_dict():
    """Test the _user_to_dict method."""
    # Reset singleton
    UserManager._instance = None

    # Create instance and mock dependencies
    user_manager = UserManager()
    user_manager.db = MagicMock()
    user_manager._ensure_table_exists = MagicMock()

    # Create a mock user
    mock_parent = MagicMock(spec=UserTable)
    mock_parent.id = 'master1'
    mock_parent.name = 'Master User'

    mock_user = MagicMock(spec=UserTable)
    mock_user.id = 'test1'
    mock_user.name = 'Test User'
    mock_user.email = 'test@example.com'
    mock_user.role = UserRole.NORMAL.value
    mock_user.parent_id = 'master1'
    mock_user.parent = mock_parent
    mock_user.created_at = datetime(2023, 1, 1, 12, 0, 0)
    mock_user.last_login = datetime(2023, 1, 2, 14, 30, 0)
    mock_user.is_active = True
    mock_user.profile = {"language": "en", "theme": "dark"}
    mock_user.user_metadata = {"key": "value"}
    mock_user.child_users = []

    # Call _user_to_dict
    result = user_manager._user_to_dict(mock_user)

    assert result['id'] == 'test1'
    assert result['name'] == 'Test User'
    assert result['email'] == 'test@example.com'
    assert result['role'] == UserRole.NORMAL.value
    assert result['parent_id'] == 'master1'
    assert result['parent_name'] == 'Master User'
    assert result['created_at'] == '2023-01-01T12:00:00'
    assert result['last_login'] == '2023-01-02T14:30:00'
    assert result['is_active'] == True
    assert result['profile'] == {"language": "en", "theme": "dark"}
    assert result['metadata'] == {"key": "value"}


def test_user_to_dict_with_none_values():
    """Test _user_to_dict with None values."""
    # Reset singleton
    UserManager._instance = None

    # Create instance and mock dependencies
    user_manager = UserManager()
    user_manager.db = MagicMock()
    user_manager._ensure_table_exists = MagicMock()

    # Create a mock user with None values
    mock_user = MagicMock(spec=UserTable)
    mock_user.id = 'test1'
    mock_user.name = 'Test User'
    mock_user.email = None
    mock_user.role = UserRole.ADMIN.value
    mock_user.parent_id = None
    mock_user.parent = None
    mock_user.created_at = None
    mock_user.last_login = None
    mock_user.is_active = True
    mock_user.profile = None
    mock_user.user_metadata = None
    mock_user.child_users = []

    # Call _user_to_dict
    result = user_manager._user_to_dict(mock_user)

    assert result['id'] == 'test1'
    assert result['name'] == 'Test User'
    assert result['email'] is None
    assert result['role'] == UserRole.ADMIN.value
    assert result['parent_id'] is None
    assert result['parent_name'] is None
    assert result['created_at'] is None
    assert result['last_login'] is None
    assert result['is_active'] == True
    assert result['profile'] == {}
    assert result['metadata'] == {}


def test_init_user_manager():
    """Test the init_user_manager function."""
    from shared.common import get_user_manager, init_user_manager

    # Mock the database to avoid initialization issues during tests
    with patch.object(get_user_manager().db, 'is_initialized', return_value=False):
        # init_user_manager should return the singleton without trying to create default users
        result = init_user_manager(create_default_users=False)
        assert result is get_user_manager()

    # Test with database "initialized" (mocked)
    with patch.object(get_user_manager().db, 'is_initialized', return_value=True):
        with patch.object(get_user_manager(), 'init_default_users') as mock_init:
            result = init_user_manager(create_default_users=True)
            assert result is get_user_manager()
            mock_init.assert_called_once()
