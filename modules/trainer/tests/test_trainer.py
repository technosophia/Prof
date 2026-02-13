"""
Trainer module tests.
"""

import pytest
import yaml
from unittest.mock import Mock, patch
from datetime import datetime

from shared.common import init_database, get_db_manager, get_user_manager
from modules.trainer.manager import get_trainer_manager
from modules.trainer.models import StudentNote, PluginActivation


@pytest.fixture(autouse=True)
def setup_test_db():
    """Setup test database and clean between tests."""
    init_database(use_memory=True)
    db = get_db_manager()
    yield
    db.empty_all_tables()


@pytest.fixture
def test_users():
    """Create test users hierarchy."""
    user_manager = get_user_manager()

    # Create master (trainer)
    master = user_manager.create_user(
        name="Test Trainer",
        email="trainer@test.com",
        role="master"
    )

    # Create normal users (students)
    student1 = user_manager.create_user(
        name="Student One",
        email="student1@test.com",
        role="normal",
        parent_id=master['id']
    )

    student2 = user_manager.create_user(
        name="Student Two",
        email="student2@test.com",
        role="normal",
        parent_id=master['id']
    )

    return {
        'trainer': master,
        'students': [student1, student2]
    }


def test_get_trainer_students(test_users):
    """Test retrieving students for a trainer."""
    trainer_manager = get_trainer_manager()

    students = trainer_manager.get_trainer_students(test_users['trainer']['id'])

    assert len(students) == 2
    student_names = [s['name'] for s in students]
    assert "Student One" in student_names
    assert "Student Two" in student_names


def test_student_notes_crud(test_users):
    """Test creating, reading, updating student notes."""
    trainer_manager = get_trainer_manager()
    trainer_id = test_users['trainer']['id']
    student_id = test_users['students'][0]['id']

    # Create note
    trainer_manager.save_student_note(student_id, trainer_id, "Test note content")

    # Read note
    content = trainer_manager.get_student_note(student_id, trainer_id)
    assert content == "Test note content"

    # Update note
    trainer_manager.save_student_note(student_id, trainer_id, "Updated content")
    content = trainer_manager.get_student_note(student_id, trainer_id)
    assert content == "Updated content"


def test_plugin_activation(test_users):
    """Test plugin activation/deactivation."""
    trainer_manager = get_trainer_manager()
    trainer_id = test_users['trainer']['id']
    plugin_id = "student_pad"

    # Initially should be False (default for non-activated)
    assert not trainer_manager.is_plugin_active(trainer_id, plugin_id)

    # Activate
    trainer_manager.set_plugin_active(trainer_id, plugin_id, True)
    assert trainer_manager.is_plugin_active(trainer_id, plugin_id)

    # Deactivate
    trainer_manager.set_plugin_active(trainer_id, plugin_id, False)
    assert not trainer_manager.is_plugin_active(trainer_id, plugin_id)


def test_export_import_configuration(test_users):
    """Test export and import of configuration."""
    trainer_manager = get_trainer_manager()
    trainer_id = test_users['trainer']['id']

    # Create some data
    for student in test_users['students']:
        trainer_manager.save_student_note(
            student['id'], trainer_id,
            f"Note for {student['name']}",
            "student_pad"
        )

    # Export
    yaml_content = trainer_manager.export_configuration(trainer_id)
    assert yaml_content is not None

    # Clear data
    db = get_db_manager()
    with db.get_session() as session:
        session.query(StudentNote).delete()

    # Import
    success = trainer_manager.import_configuration(trainer_id, yaml_content)
    assert success

    # Verify import
    for student in test_users['students']:
        content = trainer_manager.get_student_note(
            student['id'], trainer_id, "student_pad"
        )
        assert f"Note for {student['name']}" in content
