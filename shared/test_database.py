"""
Simplified tests for the database module.
"""
import pytest
import tempfile
import os
import uuid
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# We need to import after patching to avoid initialization
from shared.database import DatabaseManager, init_database


class TestDatabaseManager:
    """Test the DatabaseManager class."""

    def test_singleton(self):
        """Test that DatabaseManager is a singleton."""
        # Clear any existing instance by reimporting
        import importlib
        import sys
        if 'shared.database' in sys.modules:
            del sys.modules['shared.database']

        from shared.database import DatabaseManager
        db1 = DatabaseManager()
        db2 = DatabaseManager()
        assert db1 is db2

    def test_initialize_in_memory(self):
        """Test in-memory database initialization."""
        # Clear module and create fresh instance
        import importlib
        import sys
        if 'shared.database' in sys.modules:
            del sys.modules['shared.database']

        from shared.database import DatabaseManager
        db = DatabaseManager()

        with patch('shared.database.create_engine') as mock_engine:
            with patch('shared.database.Base.metadata.create_all') as mock_create:
                with patch('shared.database.sessionmaker') as mock_sessionmaker:
                    # Mock the log to avoid output
                    with patch('shared.database.log'):
                        db.initialize(use_memory=True, create_default_users=False)

                        # Check that in-memory URL was used
                        mock_engine.assert_called_once_with('sqlite:///:memory:', echo=False)
                        mock_create.assert_called_once()
                        mock_sessionmaker.assert_called_once()
                        assert db._in_memory == True

    def test_initialize_persistent(self):
        """Test persistent database initialization."""
        # Clear module and create fresh instance
        import importlib
        import sys
        if 'shared.database' in sys.modules:
            del sys.modules['shared.database']

        from shared.database import DatabaseManager
        db = DatabaseManager()

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")

            with patch('shared.database.create_engine') as mock_engine:
                with patch('shared.database.Base.metadata.create_all') as mock_create:
                    with patch('shared.database.sessionmaker') as mock_sessionmaker:
                        with patch('shared.database.Path.mkdir'):
                            with patch('shared.database.log'):
                                db.initialize(use_memory=False, db_path=db_path, create_default_users=False)

                                # Check that file URL was used
                                expected_url = f'sqlite:///{db_path}'
                                mock_engine.assert_called_once_with(expected_url, echo=False)
                                mock_create.assert_called_once()
                                mock_sessionmaker.assert_called_once()
                                assert db._in_memory == False


class TestDatabaseOperations:
    """Test database operations with mocked session."""

    def setup_method(self):
        """Setup for each test."""
        # Clear module and create fresh instance
        import importlib
        import sys
        if 'shared.database' in sys.modules:
            del sys.modules['shared.database']

        from shared.database import DatabaseManager
        self.db = DatabaseManager()

        # Mock engine and session
        self.mock_engine = MagicMock()
        self.mock_session = MagicMock()
        self.mock_session_factory = MagicMock(return_value=self.mock_session)

        # Set up the db with mocks
        self.db._engine = self.mock_engine
        self.db._session_factory = self.mock_session_factory
        self.db._initialized_flag = True

        # Mock query
        self.mock_query = MagicMock()
        self.mock_session.query.return_value = self.mock_query

        # Mock commit behavior
        self.mock_session.commit = MagicMock()

        # Mock context manager
        class MockContextManager:
            def __init__(self, session):
                self.session = session

            def __enter__(self):
                return self.session

            def __exit__(self, exc_type, exc_val, exc_tb):
                if exc_type is None:
                    self.session.commit()
                else:
                    self.session.rollback()

        # Patch get_session to return our mock context manager
        self.get_session_patch = patch.object(
            self.db, 'get_session',
            return_value=MockContextManager(self.mock_session)
        )
        self.get_session_patch.start()

    def teardown_method(self):
        """Cleanup after each test."""
        self.get_session_patch.stop()

    def test_create_user(self):
        """Test creating a user."""
        # Patch uuid.uuid4 at the right location
        with patch('uuid.uuid4') as mock_uuid:
            mock_uuid.return_value = 'test-uuid-123'

            # Mock _user_to_dict
            with patch.object(self.db, '_user_to_dict', return_value={'id': 'test-uuid-123', 'name': 'Test User'}):
                user_id = self.db.create_user("Test User", "test@example.com")

                assert user_id == 'test-uuid-123'
                self.mock_session.add.assert_called_once()

    def test_get_user(self):
        """Test getting a user."""
        # Mock user object
        mock_user = MagicMock()
        mock_user.id = 'test1'
        mock_user.name = 'Test User'
        mock_user.email = 'test@example.com'
        mock_user.created_at = None
        mock_user.last_login = None
        mock_user.is_active = True
        mock_user.profile = {}
        mock_user.user_metadata = {}

        # Setup query
        self.mock_query.filter_by.return_value.first.return_value = mock_user

        # Mock _user_to_dict
        with patch.object(self.db, '_user_to_dict', return_value={
            'id': 'test1',
            'name': 'Test User',
            'email': 'test@example.com'
        }):
            user = self.db.get_user('test1')

            assert user['id'] == 'test1'
            assert user['name'] == 'Test User'
            self.mock_query.filter_by.assert_called_once_with(id='test1')

    def test_get_all_users(self):
        """Test getting all users."""
        # Mock users
        mock_user1 = MagicMock()
        mock_user2 = MagicMock()

        self.mock_query.order_by.return_value.all.return_value = [mock_user1, mock_user2]

        # Mock _user_to_dict for each user
        with patch.object(self.db, '_user_to_dict', side_effect=[
            {'id': 'test1', 'name': 'User 1'},
            {'id': 'test2', 'name': 'User 2'}
        ]):
            users = self.db.get_all_users()

            assert len(users) == 2
            assert users[0]['name'] == 'User 1'
            assert users[1]['name'] == 'User 2'

    def test_update_user_success(self):
        """Test successful user update."""
        # Mock user
        mock_user = MagicMock()
        mock_user.profile = {}
        mock_user.user_metadata = {}

        self.mock_query.filter_by.return_value.first.return_value = mock_user

        success = self.db.update_user(
            'test1',
            name='Updated Name',
            profile={'role': 'admin'}
        )

        assert success == True
        assert mock_user.name == 'Updated Name'
        assert mock_user.profile == {'role': 'admin'}

    def test_update_user_not_found(self):
        """Test updating non-existent user."""
        self.mock_query.filter_by.return_value.first.return_value = None

        success = self.db.update_user('nonexistent', name='New Name')

        assert success == False

    def test_delete_user_success(self):
        """Test successful user deletion."""
        # Mock user
        mock_user = MagicMock()
        mock_user.name = 'Test User'

        self.mock_query.filter_by.return_value.first.return_value = mock_user

        success = self.db.delete_user('test1')

        assert success == True
        self.mock_session.delete.assert_called_once_with(mock_user)

    def test_delete_user_not_found(self):
        """Test deleting non-existent user."""
        self.mock_query.filter_by.return_value.first.return_value = None

        success = self.db.delete_user('nonexistent')

        assert success == False
        self.mock_session.delete.assert_not_called()


def test_init_database():
    """Test the init_database function."""
    # Clear module
    import importlib
    import sys
    if 'shared.database' in sys.modules:
        del sys.modules['shared.database']

    # Mock the db_manager that will be imported
    with patch('shared.database.db_manager') as mock_db:
        mock_db.initialize = MagicMock()
        mock_db.create_default_users = MagicMock()

        # Re-import after patching
        from shared.database import init_database
        result = init_database(use_memory=True)

        assert result is mock_db
        mock_db.initialize.assert_called_once_with(use_memory=True, db_path=None, create_default_users=True)
