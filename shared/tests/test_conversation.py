# file name: test_conversation.py
"""
Tests for the conversation management module.
"""
import pytest
import sys
import os
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

# Import after patching to avoid initialization issues
from shared.conversation import ConversationManager, Conversation, Message, ConversationTable, MessageTable


class TestConversationManager:
    """Test the ConversationManager class."""

    def setup_method(self):
        """Setup for each test."""
        # Clear the singleton instance
        ConversationManager._instance = None

        # Create a fresh instance with proper mocking
        self.conv_manager = ConversationManager()

        # Mock the database manager completely to avoid any real DB operations
        self.conv_manager.db = MagicMock()
        self.conv_manager.db.is_initialized = MagicMock(return_value=True)
        self.conv_manager.db._engine = MagicMock()

        # Mock _ensure_tables_exists to do nothing
        self.conv_manager._ensure_tables_exist = MagicMock(return_value=True)

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
        self.conv_manager.db.get_session = MagicMock(return_value=self.mock_context)

    def teardown_method(self):
        """Cleanup after each test."""
        # Clear the singleton to avoid test contamination
        ConversationManager._instance = None

    def test_singleton(self):
        """Test that ConversationManager is a singleton."""
        # Clear singleton first
        ConversationManager._instance = None

        manager1 = ConversationManager()
        manager2 = ConversationManager()
        assert manager1 is manager2

    def test_create_conversation_success(self):
        """Test successful conversation creation."""
        # Test UUID
        test_uuid_str = '123e4567-e89b-12d3-a456-426614174000'

        # Create a UUID object that when converted to string returns our test string
        mock_uuid = MagicMock()
        mock_uuid.__str__ = MagicMock(return_value=test_uuid_str)

        with patch('uuid.uuid4', return_value=mock_uuid):
            with patch('shared.conversation.log'):
                # Create a test initial message
                initial_message = Message(
                    role="user",
                    content="Hello, this is a test message",
                    timestamp=datetime(2023, 1, 1, 12, 0, 0),
                    tokens=10
                )

                conversation_id = self.conv_manager.create_conversation(
                    user_id="test_user",
                    title="Test Conversation",
                    system_prompt="You are a helpful assistant.",
                    llm_config={"model": "test-model"},
                    initial_message=initial_message
                )

        # Verify the conversation ID matches
        assert conversation_id == test_uuid_str

        # Verify the conversation was added
        self.mock_session.add.assert_called()

        # Check that both conversation and message were added
        assert self.mock_session.add.call_count >= 2

    def test_create_conversation_empty_user_id(self):
        """Test conversation creation with empty user ID."""
        with pytest.raises(ValueError, match="User ID cannot be empty"):
            self.conv_manager.create_conversation("", "Test Title")

    def test_create_conversation_empty_title(self):
        """Test conversation creation with empty title."""
        with pytest.raises(ValueError, match="Conversation title cannot be empty"):
            self.conv_manager.create_conversation("test_user", "")

    def test_get_conversation(self):
        """Test getting a conversation."""
        # Mock conversation object
        mock_conv = MagicMock(spec=ConversationTable)
        mock_conv.id = 'conv1'
        mock_conv.user_id = 'user1'
        mock_conv.title = 'Test Conversation'
        mock_conv.created_at = datetime(2023, 1, 1, 12, 0, 0)
        mock_conv.updated_at = datetime(2023, 1, 2, 14, 30, 0)
        mock_conv.is_active = True
        mock_conv.metadata = {"key": "value"}
        mock_conv.system_prompt = "You are helpful"
        mock_conv.llm_config = {"model": "test"}

        # Setup query for conversation
        mock_conv_query = MagicMock()
        mock_conv_query.filter_by.return_value.first.return_value = mock_conv
        self.mock_session.query.return_value = mock_conv_query

        # Mock messages query to return empty list
        mock_msg_query = MagicMock()
        mock_msg_query.filter_by.return_value.order_by.return_value.all.return_value = []

        # Make query return different mocks for different calls
        query_calls = [mock_conv_query, mock_msg_query]
        self.mock_session.query.side_effect = lambda model: query_calls.pop(0) if query_calls else mock_conv_query

        conversation = self.conv_manager.get_conversation('conv1', include_messages=True)

        assert conversation.id == 'conv1'
        assert conversation.user_id == 'user1'
        assert conversation.title == 'Test Conversation'
        assert conversation.is_active == True
        assert conversation.system_prompt == "You are helpful"
        assert conversation.llm_config == {"model": "test"}

    def test_get_conversation_not_found(self):
        """Test getting a non-existent conversation."""
        # Setup query to return None
        mock_query = MagicMock()
        mock_query.filter_by.return_value.first.return_value = None
        self.mock_session.query.return_value = mock_query

        conversation = self.conv_manager.get_conversation('nonexistent')
        assert conversation is None

    def test_get_user_conversations(self):
        """Test getting conversations for a user."""
        # Mock conversations
        mock_conv1 = MagicMock(spec=ConversationTable)
        mock_conv1.id = 'conv1'
        mock_conv1.user_id = 'user1'
        mock_conv1.title = 'Conv 1'
        mock_conv1.created_at = datetime(2023, 1, 1)
        mock_conv1.updated_at = datetime(2023, 1, 2)
        mock_conv1.is_active = True
        mock_conv1.system_prompt = None
        mock_conv1.llm_config = {}

        mock_conv2 = MagicMock(spec=ConversationTable)
        mock_conv2.id = 'conv2'
        mock_conv2.user_id = 'user1'
        mock_conv2.title = 'Conv 2'
        mock_conv2.created_at = datetime(2023, 1, 3)
        mock_conv2.updated_at = datetime(2023, 1, 4)
        mock_conv2.is_active = False
        mock_conv2.system_prompt = "System prompt"
        mock_conv2.llm_config = {"model": "test"}

        # Setup query for conversations
        mock_conv_query = MagicMock()
        mock_conv_query.filter_by.return_value.order_by.return_value.all.return_value = [mock_conv1, mock_conv2]

        # Mock message count queries
        mock_count_query = MagicMock()
        mock_count_query.filter_by.return_value.count.side_effect = [3, 5]  # Different counts for different convs

        # Mock last message queries
        mock_last_msg_query = MagicMock()
        mock_last_msg1 = MagicMock()
        mock_last_msg1.timestamp = datetime(2023, 1, 2, 14, 0, 0)
        mock_last_msg2 = MagicMock()
        mock_last_msg2.timestamp = datetime(2023, 1, 4, 16, 0, 0)
        mock_last_msg_query.filter_by.return_value.order_by.return_value.first.side_effect = [mock_last_msg1, mock_last_msg2]

        # Make query return different mocks for different calls
        query_calls = [mock_conv_query, mock_count_query, mock_last_msg_query,
                      mock_count_query, mock_last_msg_query]

        def query_side_effect(model):
            return query_calls.pop(0) if query_calls else mock_conv_query

        self.mock_session.query.side_effect = query_side_effect

        conversations = self.conv_manager.get_user_conversations('user1', include_inactive=True)

        assert len(conversations) == 2
        assert conversations[0]['id'] == 'conv1'
        assert conversations[0]['title'] == 'Conv 1'
        assert conversations[0]['is_active'] == True
        assert conversations[0]['message_count'] == 3

        assert conversations[1]['id'] == 'conv2'
        assert conversations[1]['title'] == 'Conv 2'
        assert conversations[1]['is_active'] == False
        assert conversations[1]['message_count'] == 5

    def test_add_message(self):
        """Test adding a message to a conversation."""
        # Mock conversation exists
        mock_conv = MagicMock(spec=ConversationTable)
        mock_conv.updated_at = datetime(2023, 1, 1)

        mock_conv_query = MagicMock()
        mock_conv_query.filter_by.return_value.first.return_value = mock_conv
        self.mock_session.query.return_value = mock_conv_query

        # Test UUID for message
        test_msg_uuid = 'msg-12345'
        mock_msg_uuid = MagicMock()
        mock_msg_uuid.__str__ = MagicMock(return_value=test_msg_uuid)

        with patch('uuid.uuid4', return_value=mock_msg_uuid):
            with patch('shared.conversation.log'):
                # Create test message
                message = Message(
                    role="user",
                    content="Test message content",
                    tokens=15
                )

                message_id = self.conv_manager.add_message('conv1', message)

        assert message_id == test_msg_uuid
        self.mock_session.add.assert_called_once()

        # Check that conversation updated_at was updated
        assert mock_conv.updated_at != datetime(2023, 1, 1)

    def test_add_message_conversation_not_found(self):
        """Test adding message to non-existent conversation."""
        # Setup query to return None (conversation not found)
        mock_query = MagicMock()
        mock_query.filter_by.return_value.first.return_value = None
        self.mock_session.query.return_value = mock_query

        message = Message(role="user", content="Test")

        with pytest.raises(ValueError, match="Conversation conv1 not found"):
            self.conv_manager.add_message('conv1', message)

    def test_add_message_pair(self):
        """Test adding a message pair."""
        # Mock conversation exists
        mock_conv = MagicMock(spec=ConversationTable)
        mock_conv_query = MagicMock()
        mock_conv_query.filter_by.return_value.first.return_value = mock_conv
        self.mock_session.query.return_value = mock_conv_query

        # Mock UUIDs for messages
        test_uuid1 = 'msg-1'
        test_uuid2 = 'msg-2'
        mock_uuid1 = MagicMock()
        mock_uuid1.__str__ = MagicMock(return_value=test_uuid1)
        mock_uuid2 = MagicMock()
        mock_uuid2.__str__ = MagicMock(return_value=test_uuid2)

        # Patch uuid.uuid4 to return our mocks sequentially
        with patch('uuid.uuid4', side_effect=[mock_uuid1, mock_uuid2]):
            with patch('shared.conversation.log'):
                self.conv_manager.add_message_pair(
                    conversation_id='conv1',
                    user_message="Hello, assistant!",
                    assistant_message="Hello, user! How can I help?",
                    user_tokens=5,
                    assistant_tokens=10
                )

        # Should have added two messages
        assert self.mock_session.add.call_count == 2

    def test_update_conversation_title_success(self):
        """Test successful conversation title update."""
        # Mock conversation exists
        mock_conv = MagicMock(spec=ConversationTable)
        mock_conv.title = "Old Title"
        mock_conv.updated_at = datetime(2023, 1, 1)

        mock_query = MagicMock()
        mock_query.filter_by.return_value.first.return_value = mock_conv
        self.mock_session.query.return_value = mock_query

        with patch('shared.conversation.log'):
            success = self.conv_manager.update_conversation_title('conv1', 'New Title')

        assert success == True
        assert mock_conv.title == 'New Title'
        assert mock_conv.updated_at != datetime(2023, 1, 1)

    def test_update_conversation_title_empty(self):
        """Test conversation title update with empty title."""
        with pytest.raises(ValueError, match="Conversation title cannot be empty"):
            self.conv_manager.update_conversation_title('conv1', '')

    def test_update_conversation_title_not_found(self):
        """Test updating title of non-existent conversation."""
        # Setup query to return None
        mock_query = MagicMock()
        mock_query.filter_by.return_value.first.return_value = None
        self.mock_session.query.return_value = mock_query

        success = self.conv_manager.update_conversation_title('nonexistent', 'New Title')
        assert success == False

    def test_delete_conversation(self):
        """Test deleting a conversation."""
        # Mock delete operations
        mock_delete_query = MagicMock()
        mock_delete_query.filter_by.return_value.delete.return_value = 1  # 1 row deleted

        # First call deletes messages, second deletes conversation
        self.mock_session.query.side_effect = [mock_delete_query, mock_delete_query]

        with patch('shared.conversation.log'):
            success = self.conv_manager.delete_conversation('conv1')

        assert success == True
        # Should have called delete twice (for messages and conversation)
        assert mock_delete_query.filter_by.return_value.delete.call_count == 2

    def test_delete_conversation_not_found(self):
        """Test deleting non-existent conversation."""
        # Mock delete returns 0 rows
        mock_delete_query = MagicMock()
        mock_delete_query.filter_by.return_value.delete.return_value = 0

        self.mock_session.query.return_value = mock_delete_query

        success = self.conv_manager.delete_conversation('nonexistent')
        assert success == False

    def test_deactivate_conversation(self):
        """Test deactivating a conversation."""
        # Mock conversation exists
        mock_conv = MagicMock(spec=ConversationTable)
        mock_conv.is_active = True
        mock_conv.updated_at = datetime(2023, 1, 1)

        mock_query = MagicMock()
        mock_query.filter_by.return_value.first.return_value = mock_conv
        self.mock_session.query.return_value = mock_query

        with patch('shared.conversation.log'):
            success = self.conv_manager.deactivate_conversation('conv1')

        assert success == True
        assert mock_conv.is_active == False
        assert mock_conv.updated_at != datetime(2023, 1, 1)

    def test_deactivate_conversation_not_found(self):
        """Test deactivating non-existent conversation."""
        # Setup query to return None
        mock_query = MagicMock()
        mock_query.filter_by.return_value.first.return_value = None
        self.mock_session.query.return_value = mock_query

        success = self.conv_manager.deactivate_conversation('nonexistent')
        assert success == False

    def test_clear_conversation_messages(self):
        """Test clearing messages from a conversation."""
        # Mock conversation exists
        mock_conv = MagicMock(spec=ConversationTable)
        mock_conv.updated_at = datetime(2023, 1, 1)

        mock_conv_query = MagicMock()
        mock_conv_query.filter_by.return_value.first.return_value = mock_conv

        # Mock delete query
        mock_delete_query = MagicMock()

        # Make query return different mocks for different calls
        query_calls = [mock_conv_query, mock_delete_query]
        self.mock_session.query.side_effect = lambda model: query_calls.pop(0) if query_calls else mock_conv_query

        with patch('shared.conversation.log'):
            success = self.conv_manager.clear_conversation_messages('conv1')

        assert success == True
        assert mock_conv.updated_at != datetime(2023, 1, 1)
        mock_delete_query.filter_by.assert_called_once_with(conversation_id='conv1')

    def test_clear_conversation_messages_not_found(self):
        """Test clearing messages from non-existent conversation."""
        # Setup query to return None
        mock_query = MagicMock()
        mock_query.filter_by.return_value.first.return_value = None
        self.mock_session.query.return_value = mock_query

        success = self.conv_manager.clear_conversation_messages('nonexistent')
        assert success == False

    def test_get_conversation_message_count(self):
        """Test getting message count for a conversation."""
        # Mock count query
        mock_query = MagicMock()
        mock_query.filter_by.return_value.count.return_value = 42
        self.mock_session.query.return_value = mock_query

        count = self.conv_manager.get_conversation_message_count('conv1')
        assert count == 42

    def test_get_conversation_token_count(self):
        """Test getting token count for a conversation."""
        # Mock messages
        mock_msg1 = MagicMock(spec=MessageTable)
        mock_msg1.tokens = 10
        mock_msg2 = MagicMock(spec=MessageTable)
        mock_msg2.tokens = 20
        mock_msg3 = MagicMock(spec=MessageTable)
        mock_msg3.tokens = None  # Should be ignored

        mock_query = MagicMock()
        mock_query.filter_by.return_value.all.return_value = [mock_msg1, mock_msg2, mock_msg3]
        self.mock_session.query.return_value = mock_query

        total_tokens = self.conv_manager.get_conversation_token_count('conv1')
        assert total_tokens == 30  # 10 + 20 (None is ignored)

    def test_get_conversation_summary(self):
        """Test getting conversation summary."""
        # Mock get_conversation to return a conversation
        mock_conv = Conversation(
            id='conv1',
            user_id='user1',
            title='Test Conversation',
            created_at=datetime(2023, 1, 1),
            updated_at=datetime(2023, 1, 2),
            is_active=True,
            metadata={},
            system_prompt=None,
            llm_config={},
            messages=[
                Message(role="system", content="You are helpful", timestamp=datetime(2023, 1, 1, 10, 0, 0)),
                Message(role="user", content="Hello!", timestamp=datetime(2023, 1, 1, 10, 1, 0), tokens=5),
                Message(role="assistant", content="Hi there!", timestamp=datetime(2023, 1, 1, 10, 2, 0), tokens=8),
                Message(role="user", content="How are you?", timestamp=datetime(2023, 1, 1, 10, 3, 0), tokens=4),
            ]
        )

        # Mock get_conversation
        with patch.object(self.conv_manager, 'get_conversation', return_value=mock_conv):
            # Mock get_conversation_token_count
            with patch.object(self.conv_manager, 'get_conversation_token_count', return_value=17):
                summary = self.conv_manager.get_conversation_summary('conv1')

                assert summary['id'] == 'conv1'
                assert summary['title'] == 'Test Conversation'
                assert summary['message_count'] == 4
                assert summary['total_tokens'] == 17
                assert summary['last_user_message'] == 'How are you?'


class TestMessage:
    """Test the Message class."""

    def test_message_to_dict(self):
        """Test Message.to_dict() method."""
        message = Message(
            role="user",
            content="Hello world",
            timestamp=datetime(2023, 1, 1, 12, 0, 0),
            tokens=10,
            metadata={"key": "value"}
        )

        result = message.to_dict()

        assert result["role"] == "user"
        assert result["content"] == "Hello world"
        assert result["timestamp"] == "2023-01-01T12:00:00"
        assert result["tokens"] == 10
        assert result["metadata"] == {"key": "value"}

    def test_message_from_dict(self):
        """Test Message.from_dict() method."""
        data = {
            "role": "assistant",
            "content": "I'm here to help",
            "timestamp": "2023-01-01T12:00:00",
            "tokens": 15,
            "metadata": {"key": "value"}
        }

        message = Message.from_dict(data)

        assert message.role == "assistant"
        assert message.content == "I'm here to help"
        assert message.timestamp == datetime(2023, 1, 1, 12, 0, 0)
        assert message.tokens == 15
        assert message.metadata == {"key": "value"}

    def test_message_from_dict_minimal(self):
        """Test Message.from_dict() with minimal data."""
        data = {
            "role": "system",
            "content": "System message"
        }

        message = Message.from_dict(data)

        assert message.role == "system"
        assert message.content == "System message"
        assert message.timestamp is None
        assert message.tokens is None
        assert message.metadata == {}


class TestConversation:
    """Test the Conversation class."""

    def test_conversation_to_dict(self):
        """Test Conversation.to_dict() method."""
        messages = [
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi")
        ]

        conversation = Conversation(
            id="conv1",
            user_id="user1",
            title="Test Conversation",
            created_at=datetime(2023, 1, 1),
            updated_at=datetime(2023, 1, 2),
            is_active=True,
            metadata={"key": "value"},
            system_prompt="Be helpful",
            llm_config={"model": "test"},
            messages=messages
        )

        result = conversation.to_dict()

        assert result["id"] == "conv1"
        assert result["user_id"] == "user1"
        assert result["title"] == "Test Conversation"
        assert result["created_at"] == "2023-01-01T00:00:00"
        assert result["updated_at"] == "2023-01-02T00:00:00"
        assert result["is_active"] == True
        assert result["metadata"] == {"key": "value"}
        assert result["system_prompt"] == "Be helpful"
        assert result["llm_config"] == {"model": "test"}
        assert len(result["messages"]) == 2

    def test_conversation_from_dict(self):
        """Test Conversation.from_dict() method."""
        data = {
            "id": "conv1",
            "user_id": "user1",
            "title": "Test Conversation",
            "created_at": "2023-01-01T00:00:00",
            "updated_at": "2023-01-02T00:00:00",
            "is_active": True,
            "metadata": {"key": "value"},
            "system_prompt": "Be helpful",
            "llm_config": {"model": "test"},
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi"}
            ]
        }

        conversation = Conversation.from_dict(data)

        assert conversation.id == "conv1"
        assert conversation.user_id == "user1"
        assert conversation.title == "Test Conversation"
        assert conversation.created_at == datetime(2023, 1, 1)
        assert conversation.updated_at == datetime(2023, 1, 2)
        assert conversation.is_active == True
        assert conversation.metadata == {"key": "value"}
        assert conversation.system_prompt == "Be helpful"
        assert conversation.llm_config == {"model": "test"}
        assert len(conversation.messages) == 2
        assert conversation.messages[0].role == "user"
        assert conversation.messages[1].role == "assistant"
