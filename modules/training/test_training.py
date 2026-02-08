"""
Tests for the training module.
"""
import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime

from core.database import init_database, get_db_manager
from shared.users import get_user_manager, UserRole
from shared.conversation import get_conversation_manager

from modules.training.training_logic import TrainingManager
from modules.training.training_models import (
    TrainingMasterConfigTable,
    StudentStateTable,
    AnalyzedMessageTable
)


@pytest.fixture
def training_manager():
    """Create a training manager instance."""
    return TrainingManager()


@pytest.fixture
def db_session():
    """Create a database session for testing."""
    init_database(use_memory=True)
    db = get_db_manager()
    with db.get_session() as session:
        yield session


@pytest.fixture
def test_users():
    """Create test users."""
    user_manager = get_user_manager()

    # Create master user
    master_id = user_manager.create_user(
        name="Test Master",
        role=UserRole.MASTER.value,
        email="master@test.com"
    )

    # Create student user
    student_id = user_manager.create_user(
        name="Test Student",
        role=UserRole.NORMAL.value,
        email="student@test.com",
        parent_id=master_id
    )

    return {"master_id": master_id, "student_id": student_id}


class TestTrainingManager:
    """Test TrainingManager functionality."""

    def test_is_master_user(self, training_manager, test_users):
        """Test master user detection."""
        master_id = test_users["master_id"]
        student_id = test_users["student_id"]

        assert training_manager.is_master_user(master_id) == True
        assert training_manager.is_master_user(student_id) == False
        assert training_manager.is_master_user("nonexistent") == False

    def test_is_student_of_master(self, training_manager, test_users):
        """Test student-master relationship verification."""
        master_id = test_users["master_id"]
        student_id = test_users["student_id"]

        assert training_manager.is_student_of_master(master_id, student_id) == True
        assert training_manager.is_student_of_master(master_id, "other") == False

    def test_save_and_get_master_config(self, training_manager, test_users):
        """Test saving and retrieving master configuration."""
        master_id = test_users["master_id"]

        # Save config
        config_id = training_manager.save_master_config(
            master_id=master_id,
            system_prompt="Test system prompt",
            learning_path="Test learning path",
            analyzer_prompt="Test analyzer prompt",
            merging_prompt="Test merging prompt"
        )

        assert config_id is not None

        # Retrieve config
        config = training_manager.get_master_config(master_id)

        assert config is not None
        assert config["master_id"] == master_id
        assert config["system_prompt"] == "Test system prompt"
        assert config["learning_path"] == "Test learning path"
        assert config["analyzer_prompt"] == "Test analyzer prompt"
        assert config["merging_prompt"] == "Test merging prompt"

    def test_initialize_student_state(self, training_manager, test_users):
        """Test student state initialization."""
        master_id = test_users["master_id"]
        student_id = test_users["student_id"]

        state_id = training_manager.initialize_student_state(master_id, student_id)

        assert state_id is not None

        # Verify state was created
        state = training_manager.get_student_state(master_id, student_id)
        assert state is not None
        assert state["student_id"] == student_id
        assert state["master_id"] == master_id
        assert "New student" in state["current_state"]

    @pytest.mark.asyncio
    async def test_analyze_student_messages(self, training_manager, test_users):
        """Test message analysis functionality."""
        master_id = test_users["master_id"]
        student_id = test_users["student_id"]

        # Initialize state first
        training_manager.initialize_student_state(master_id, student_id)

        # Save master config
        training_manager.save_master_config(
            master_id=master_id,
            system_prompt="Test",
            learning_path="Test",
            analyzer_prompt="Test",
            merging_prompt="Test"
        )

        # Mock the LLM calls
        with patch('modules.training.training_logic.llm_generate') as mock_llm:
            mock_llm.side_effect = [
                "Test analysis result",
                "Test merged state"
            ]

            # Run analysis
            new_state, analyzed = await training_manager.analyze_student_messages(
                master_id, student_id
            )

            assert new_state == "Test merged state"
            assert isinstance(analyzed, list)

            # Verify LLM was called twice (analysis + merging)
            assert mock_llm.call_count == 2

    def test_clear_student_state(self, training_manager, test_users):
        """Test clearing student state."""
        master_id = test_users["master_id"]
        student_id = test_users["student_id"]

        # Initialize state
        training_manager.initialize_student_state(master_id, student_id)

        # Clear state
        result = training_manager.clear_student_state(master_id, student_id)
        assert result == True

        # Verify state was cleared
        state = training_manager.get_student_state(master_id, student_id)
        assert "reset" in state["current_state"]

    def test_get_student_status_board(self, training_manager, test_users):
        """Test status board generation."""
        master_id = test_users["master_id"]
        student_id = test_users["student_id"]

        # Initialize state
        training_manager.initialize_student_state(master_id, student_id)

        # Get status board
        status_list = training_manager.get_student_status_board(master_id)

        assert len(status_list) == 1
        status = status_list[0]

        assert status.student_id == student_id
        assert status.student_name == "Test Student"
        assert status.unanalyzed_messages == 0  # No messages yet

    def test_cleanup_student_data(self, training_manager, test_users, db_session):
        """Test cleanup when student is deleted."""
        student_id = test_users["student_id"]
        master_id = test_users["master_id"]

        # Create some test data
        state = StudentStateTable(
            id="test_state_id",
            master_id=master_id,
            student_id=student_id,
            current_state="Test state",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db_session.add(state)
        db_session.commit()

        # Run cleanup
        result = training_manager.cleanup_student_data(student_id)
        assert result == True

        # Verify data was deleted
        remaining = db_session.query(StudentStateTable).filter_by(student_id=student_id).all()
        assert len(remaining) == 0

    def test_cleanup_master_data(self, training_manager, test_users, db_session):
        """Test cleanup when master is deleted."""
        master_id = test_users["master_id"]
        student_id = test_users["student_id"]

        # Create some test data
        config = TrainingMasterConfigTable(
            id="test_config_id",
            master_id=master_id,
            system_prompt="Test",
            learning_path="Test",
            analyzer_prompt="Test",
            merging_prompt="Test",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db_session.add(config)
        db_session.commit()

        # Run cleanup
        result = training_manager.cleanup_master_data(master_id)
        assert result == True

        # Verify data was deleted
        remaining = db_session.query(TrainingMasterConfigTable).filter_by(master_id=master_id).all()
        assert len(remaining) == 0


class TestTrainingModels:
    """Test database models."""

    def test_training_master_config_model(self, db_session):
        """Test TrainingMasterConfigTable model."""
        config = TrainingMasterConfigTable(
            id="test_id",
            master_id="master_123",
            system_prompt="Test system",
            learning_path="Test path",
            analyzer_prompt="Test analyzer",
            merging_prompt="Test merge",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )

        db_session.add(config)
        db_session.commit()

        # Retrieve and verify
        saved = db_session.query(TrainingMasterConfigTable).filter_by(id="test_id").first()
        assert saved is not None
        assert saved.master_id == "master_123"
        assert saved.system_prompt == "Test system"
        assert saved.is_active == True

    def test_student_state_model(self, db_session):
        """Test StudentStateTable model."""
        state = StudentStateTable(
            id="test_state_id",
            master_id="master_123",
            student_id="student_456",
            current_state="Learning progress...",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )

        db_session.add(state)
        db_session.commit()

        # Retrieve and verify
        saved = db_session.query(StudentStateTable).filter_by(id="test_state_id").first()
        assert saved is not None
        assert saved.master_id == "master_123"
        assert saved.student_id == "student_456"
        assert "progress" in saved.current_state

    def test_analyzed_message_model(self, db_session):
        """Test AnalyzedMessageTable model."""
        analyzed = AnalyzedMessageTable(
            id="test_analyzed_id",
            student_id="student_456",
            message_id="msg_123",
            conversation_id="conv_456",
            analyzed_at=datetime.utcnow(),
            analysis_summary="Test analysis"
        )

        db_session.add(analyzed)
        db_session.commit()

        # Retrieve and verify
        saved = db_session.query(AnalyzedMessageTable).filter_by(id="test_analyzed_id").first()
        assert saved is not None
        assert saved.student_id == "student_456"
        assert saved.message_id == "msg_123"
        assert saved.analysis_summary == "Test analysis"


def test_integration_with_user_system(training_manager, test_users):
    """Test integration with user management system."""
    master_id = test_users["master_id"]
    student_id = test_users["student_id"]

    # Verify the module correctly identifies the hierarchy
    assert training_manager.is_master_user(master_id) == True
    assert training_manager.is_student_of_master(master_id, student_id) == True

    # Test that non-master cannot save config
    with pytest.raises(ValueError):
        training_manager.save_master_config(
            master_id=student_id,  # Student trying to save master config
            system_prompt="Test",
            learning_path="Test",
            analyzer_prompt="Test",
            merging_prompt="Test"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
