"""
Trainer module tests.

TODO : makge regression in modules/benchmarker/tests/test_runner_integration_real_driver.py::test_full_run_real_driver_scenarios[full_nexoria]

"""

import pytest
import yaml
import sys
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

# ============ CRITICAL: Mock ALL trainer-related modules BEFORE any imports ============
# This prevents any table creation attempts for trainer-related tables

# 1. Mock the entire trainer.models module
mock_trainer_models = MagicMock()
mock_trainer_models.PluginData = MagicMock()
mock_trainer_models.PluginActivation = MagicMock()
sys.modules['modules.trainer.models'] = mock_trainer_models

# 2. Mock the student pad plugin module completely
mock_student_pad_module = MagicMock()
mock_student_pad_module.StudentPadPlugin = MagicMock()
mock_student_pad_module.StudentNote = MagicMock()
sys.modules['modules.trainer.plugins.student_pad'] = mock_student_pad_module

# Now safe to import trainer modules
from shared.common import UserRole
from shared.cached import get_db_manager, get_user_manager
from modules.trainer.manager import get_trainer_manager
from modules.trainer.plugin_base import get_plugin_manager, PluginManifest


class TestTrainerManager:
    """Test TrainerManager functionality."""

    def setup_method(self):
        """Setup for each test."""
        # Clear the singleton instance
        from modules.trainer.manager import _trainer_manager
        global _trainer_manager
        _trainer_manager = None

        # Clear plugin manager
        from modules.trainer.plugin_base import _plugin_manager
        global _plugin_manager
        _plugin_manager = None

        # Create a fresh trainer manager
        self.trainer_manager = get_trainer_manager()

        # Mock the database manager completely to avoid any real DB operations
        self.trainer_manager.db = MagicMock()
        self.trainer_manager.db.is_initialized = MagicMock(return_value=True)
        self.trainer_manager.db._engine = MagicMock()
        self.trainer_manager.db._session_factory = MagicMock()

        # Mock the user manager
        self.trainer_manager.user_manager = MagicMock()

        # Mock conversation manager
        self.trainer_manager.conversation_manager = MagicMock()

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
                return False

        # Create the context manager instance
        self.mock_context = MockSessionContext(self.mock_session)

        # Mock get_session to return our context manager
        self.trainer_manager.db.get_session = MagicMock(return_value=self.mock_context)

    def teardown_method(self):
        """Cleanup after each test."""
        from modules.trainer.manager import _trainer_manager
        from modules.trainer.plugin_base import _plugin_manager
        global _trainer_manager, _plugin_manager
        _trainer_manager = None
        _plugin_manager = None

    def test_get_trainer_students(self):
        """Test retrieving students for a trainer."""
        # Mock students
        mock_students = [
            {
                'id': 'student_1',
                'name': 'Student One',
                'email': 'student1@test.com',
                'role': UserRole.NORMAL.value,
                'parent_id': 'trainer_123'
            },
            {
                'id': 'student_2',
                'name': 'Student Two',
                'email': 'student2@test.com',
                'role': UserRole.NORMAL.value,
                'parent_id': 'trainer_123'
            }
        ]

        # Mock get_children method
        self.trainer_manager.user_manager.get_children = MagicMock(return_value=mock_students)

        students = self.trainer_manager.get_trainer_students('trainer_123')

        assert len(students) == 2
        assert students[0]['name'] == 'Student One'
        assert students[1]['name'] == 'Student Two'
        self.trainer_manager.user_manager.get_children.assert_called_once_with('trainer_123')


class TestStudentPadPlugin:
    """Test StudentPadPlugin functionality."""

    def setup_method(self):
        """Setup for each test."""
        # Create mock plugin
        self.plugin = MagicMock()
        self.plugin.id = "student_pad"
        self.plugin.manifest = PluginManifest(
            id="student_pad",
            name="Student Pad",
            version="1.0.0",
            description="Student notes plugin",
            author="Test",
            enabled_by_default=True,
            category="general"
        )

        # Mock plugin methods
        self.plugin._save_student_note = MagicMock(return_value=True)
        self.plugin._get_student_note = MagicMock(return_value="Test note content")
        self.plugin.initialize = MagicMock(return_value=True)
        self.plugin.export_config = MagicMock(return_value={"student_pads": {}})
        self.plugin.import_config = MagicMock(return_value=True)

        # Mock plugin manager
        self.plugin_manager = get_plugin_manager()
        self.plugin_manager.plugins = {"student_pad": self.plugin}

    def teardown_method(self):
        """Cleanup after each test."""
        from modules.trainer.plugin_base import _plugin_manager
        global _plugin_manager
        _plugin_manager = None

    def test_student_notes_crud(self):
        """Test creating, reading, updating student notes."""
        plugin = self.plugin_manager.get_plugin("student_pad")
        assert plugin is not None

        # Configure mock returns for different calls
        plugin._get_student_note.side_effect = [
            "Test note content",  # First read
            "Updated content",     # Second read
            "Teacher note"         # Third read
        ]

        # Create note
        success = plugin._save_student_note("student_456", "trainer_123", "Test note content")
        assert success is True
        plugin._save_student_note.assert_called_with("student_456", "trainer_123", "Test note content")

        # Read note
        content = plugin._get_student_note("student_456", "trainer_123")
        assert content == "Test note content"
        plugin._get_student_note.assert_called_with("student_456", "trainer_123")

        # Update note
        success = plugin._save_student_note("student_456", "trainer_123", "Updated content")
        assert success is True
        plugin._save_student_note.assert_called_with("student_456", "trainer_123", "Updated content")

        content = plugin._get_student_note("student_456", "trainer_123")
        assert content == "Updated content"

        # Test teacher notes
        teacher_notes = "Student needs help with math"
        success = plugin._save_student_note("student_456", "trainer_123", teacher_notes, "teacher_notes")
        assert success is True
        plugin._save_student_note.assert_called_with("student_456", "trainer_123", teacher_notes, "teacher_notes")

        content = plugin._get_student_note("student_456", "trainer_123", "teacher_notes")
        assert content == "Teacher note"
        plugin._get_student_note.assert_called_with("student_456", "trainer_123", "teacher_notes")

    def test_student_notes_without_activation(self):
        """Test that notes can be saved/read even without plugin activation."""
        plugin = self.plugin_manager.get_plugin("student_pad")
        plugin._get_student_note.return_value = "Test without activation"

        success = plugin._save_student_note("student_456", "trainer_123", "Test without activation")
        assert success is True

        content = plugin._get_student_note("student_456", "trainer_123")
        assert content == "Test without activation"

    def test_plugin_activation(self):
        """Test plugin activation/deactivation."""
        trainer_manager = get_trainer_manager()
        trainer_manager.db = MagicMock()

        # Create mock context for this test
        mock_session = MagicMock()

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
                return False

        mock_context = MockSessionContext(mock_session)
        trainer_manager.db.get_session = MagicMock(return_value=mock_context)

        # Mock the database session and PluginActivation - patch at the source module
        with patch('modules.trainer.models.PluginActivation') as mock_activation:
            # Mock query results
            mock_query = MagicMock()
            mock_session.query.return_value = mock_query
            mock_query.filter_by.return_value.first.return_value = None

            # Test activation
            success = trainer_manager.set_plugin_active("trainer_123", "student_pad", True)
            assert success is True

            # Mock that plugin is now active
            mock_activation_instance = MagicMock()
            mock_activation_instance.is_active = True
            mock_query.filter_by.return_value.first.return_value = mock_activation_instance

            # Check if active
            is_active = trainer_manager.is_plugin_active("trainer_123", "student_pad")
            assert is_active is True

            # Test deactivation
            success = trainer_manager.set_plugin_active("trainer_123", "student_pad", False)
            assert success is True

            # Mock that plugin is now inactive
            mock_activation_instance.is_active = False
            is_active = trainer_manager.is_plugin_active("trainer_123", "student_pad")
            assert is_active is False

    def test_get_active_plugins(self):
        """Test retrieving active plugins for a trainer."""
        plugin_manager = get_plugin_manager()
        plugin_manager.get_active_plugins = MagicMock(return_value=[self.plugin])

        active_plugins = plugin_manager.get_active_plugins("trainer_123")
        assert len(active_plugins) == 1
        assert active_plugins[0].id == "student_pad"

    def test_export_import_configuration(self):
        """Test export and import of configuration."""
        trainer_manager = get_trainer_manager()
        trainer_manager.db = MagicMock()
        plugin = self.plugin_manager.get_plugin("student_pad")

        # Mock export
        mock_export_data = {
            'student_pads': {
                'student_456': {
                    'content': 'Note for Student One',
                    'teacher_notes': 'Teacher note for Student One'
                },
                'student_789': {
                    'content': 'Note for Student Two',
                    'teacher_notes': 'Teacher note for Student Two'
                }
            }
        }
        plugin.export_config.return_value = mock_export_data
        plugin.import_config.return_value = True

        # Mock get_active_plugins
        with patch.object(self.plugin_manager, 'get_active_plugins', return_value=[plugin]):
            # Export
            yaml_content = trainer_manager.export_configuration("trainer_123")
            assert yaml_content is not None
            assert isinstance(yaml_content, str)

            # Parse YAML to verify structure
            config = yaml.safe_load(yaml_content)
            assert 'plugins' in config
            assert 'student_pad' in config['plugins']
            assert 'student_pads' in config['plugins']['student_pad']

            # Import
            success = trainer_manager.import_configuration("trainer_123", yaml_content)
            assert success is True
            plugin.import_config.assert_called_once()


class TestTrainerManagerHelpers:
    """Test TrainerManager helper methods."""

    def setup_method(self):
        """Setup for each test."""
        self.trainer_manager = get_trainer_manager()
        self.trainer_manager.conversation_manager = MagicMock()

    def test_get_student_conversation_count(self):
        """Test getting student conversation count."""
        self.trainer_manager.conversation_manager.get_user_conversations.return_value = [
            {'id': 'conv1'},
            {'id': 'conv2'}
        ]

        count = self.trainer_manager.get_student_conversation_count("trainer_123", "student_456")
        assert count == 2

    def test_get_student_message_count(self):
        """Test getting student message count."""
        # Mock conversation
        mock_conversation = MagicMock()
        mock_message1 = MagicMock()
        mock_message1.role = "user"
        mock_message2 = MagicMock()
        mock_message2.role = "user"
        mock_message3 = MagicMock()
        mock_message3.role = "assistant"
        mock_conversation.messages = [mock_message1, mock_message2, mock_message3]

        self.trainer_manager.conversation_manager.get_user_conversations.return_value = [
            {'id': 'conv1'}
        ]
        self.trainer_manager.conversation_manager.get_conversation.return_value = mock_conversation

        count = self.trainer_manager.get_student_message_count("trainer_123", "student_456")
        assert count == 2

    def test_get_student_last_active(self):
        """Test getting student's last activity time."""
        now = datetime.utcnow().isoformat() + 'Z'
        self.trainer_manager.conversation_manager.get_user_conversations.return_value = [
            {'id': 'conv1', 'updated_at': now}
        ]

        last_active = self.trainer_manager.get_student_last_active("student_456")
        assert last_active is not None
        assert isinstance(last_active, datetime)

    def test_get_student_last_active_no_conversations(self):
        """Test getting last active with no conversations."""
        self.trainer_manager.conversation_manager.get_user_conversations.return_value = []

        last_active = self.trainer_manager.get_student_last_active("student_456")
        assert last_active is None


# Integration-like tests that verify interactions with mocks
def test_plugin_system_integration():
    """Test plugin system integration."""
    plugin_manager = get_plugin_manager()

    # Mock plugin discovery to avoid loading real plugins
    with patch.object(plugin_manager, 'discover_plugins') as mock_discover:
        mock_discover.return_value = None

        # Create test plugin
        mock_plugin = MagicMock()
        mock_plugin.id = "test_plugin"
        mock_plugin.manifest = PluginManifest(
            id="test_plugin",
            name="Test Plugin",
            version="1.0.0",
            description="Test",
            author="Test",
            enabled_by_default=True,
            category="test"
        )

        plugin_manager.plugins = {"test_plugin": mock_plugin}

        # Test get_plugin
        plugin = plugin_manager.get_plugin("test_plugin")
        assert plugin is not None
        assert plugin.id == "test_plugin"

        # Test get_all_plugins
        all_plugins = plugin_manager.get_all_plugins()
        assert len(all_plugins) == 1
        assert all_plugins[0].id == "test_plugin"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
