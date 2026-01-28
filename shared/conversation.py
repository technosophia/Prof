# file name: shared/conversation.py
"""
Conversation management with database backend.
Handles multiple conversations per user with LLM interactions.
"""
import uuid
import json
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime
from dataclasses import dataclass, asdict

from sqlalchemy import Column, String, Integer, Text, DateTime, Boolean, JSON, ForeignKey
from sqlalchemy.orm import Session, relationship

from shared.database import Base, db_manager
from shared.logging import log


class ConversationTable(Base):
    """Conversation model for database."""
    __tablename__ = 'conversations'

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey('users.id'), nullable=False, index=True)
    title = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    conv_metadata = Column(JSON, default={})  # Renamed from 'metadata' to avoid SQLAlchemy conflict
    system_prompt = Column(Text, nullable=True)
    llm_config = Column(JSON, default={})  # Stores LLM configuration used for this conversation


class MessageTable(Base):
    """Message model for database."""
    __tablename__ = 'messages'

    id = Column(String, primary_key=True)
    conversation_id = Column(String, ForeignKey('conversations.id'), nullable=False, index=True)
    role = Column(String, nullable=False)  # 'user', 'assistant', 'system'
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    tokens = Column(Integer, nullable=True)  # Token count for this message
    message_metadata = Column(JSON, default={})  # Renamed from 'metadata' to avoid conflicts


@dataclass
class Message:
    """Message data class for easier manipulation."""
    role: str  # 'user', 'assistant', 'system'
    content: str
    timestamp: Optional[datetime] = None
    tokens: Optional[int] = None
    metadata: Optional[Dict] = None  # External API uses 'metadata', we'll handle conversion

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "role": self.role,
            "content": self.content,
        }
        if self.timestamp:
            result["timestamp"] = self.timestamp.isoformat()
        if self.tokens is not None:
            result["tokens"] = self.tokens
        if self.metadata:
            result["metadata"] = self.metadata
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Message':
        """Create from dictionary."""
        return cls(
            role=data["role"],
            content=data["content"],
            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else None,
            tokens=data.get("tokens"),
            metadata=data.get("metadata", {})
        )


@dataclass
class Conversation:
    """Conversation data class."""
    id: str
    user_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    is_active: bool
    metadata: Dict[str, Any]  # External API uses 'metadata'
    system_prompt: Optional[str]
    llm_config: Dict[str, Any]
    messages: List[Message] = None

    def __post_init__(self):
        if self.messages is None:
            self.messages = []

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "title": self.title,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "is_active": self.is_active,
            "metadata": self.metadata,
            "system_prompt": self.system_prompt,
            "llm_config": self.llm_config,
            "messages": [msg.to_dict() for msg in self.messages]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Conversation':
        """Create from dictionary."""
        messages = [Message.from_dict(msg) for msg in data.get("messages", [])]
        return cls(
            id=data["id"],
            user_id=data["user_id"],
            title=data["title"],
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            is_active=data["is_active"],
            metadata=data.get("metadata", {}),
            system_prompt=data.get("system_prompt"),
            llm_config=data.get("llm_config", {}),
            messages=messages
        )


class ConversationManager:
    """Manages conversation operations."""

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

    def _ensure_tables_exist(self):
        """Ensure the conversation tables exist."""
        if not self.db.is_initialized():
            log("warning", "Database not initialized, cannot ensure conversation tables exist")
            return False

        try:
            ConversationTable.__table__.create(bind=self.db._engine, checkfirst=True)
            MessageTable.__table__.create(bind=self.db._engine, checkfirst=True)
            log("debug", "Conversation tables ensured to exist")
            return True
        except Exception as e:
            log("error", f"Failed to ensure conversation tables exist: {e}")
            return False

    def create_conversation(self, user_id: str, title: str,
                          system_prompt: Optional[str] = None,
                          llm_config: Optional[Dict] = None,
                          initial_message: Optional[Message] = None) -> str:
        """Create a new conversation for a user."""
        # Validate user_id and title
        if not user_id or not user_id.strip():
            raise ValueError("User ID cannot be empty")
        if not title or not title.strip():
            raise ValueError("Conversation title cannot be empty")

        # Ensure tables exist before creating
        self._ensure_tables_exist()

        conversation_id = str(uuid.uuid4())

        with self.db.get_session() as session:
            # Create conversation
            conversation = ConversationTable(
                id=conversation_id,
                user_id=user_id.strip(),
                title=title.strip(),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                is_active=True,
                conv_metadata={"created_via": "ui"},  # Use conv_metadata
                system_prompt=system_prompt,
                llm_config=llm_config or {}
            )
            session.add(conversation)

            # Add initial message if provided
            if initial_message:
                message_id = str(uuid.uuid4())
                message = MessageTable(
                    id=message_id,
                    conversation_id=conversation_id,
                    role=initial_message.role,
                    content=initial_message.content,
                    timestamp=initial_message.timestamp or datetime.utcnow(),
                    tokens=initial_message.tokens,
                    message_metadata=initial_message.metadata or {}  # Use message_metadata
                )
                session.add(message)

        log("info", f"Created conversation: {title.strip()} (ID: {conversation_id}) for user {user_id}")
        return conversation_id

    def get_conversation(self, conversation_id: str, include_messages: bool = True) -> Optional[Conversation]:
        """Get a conversation by ID with its messages."""
        # Ensure tables exist before querying
        self._ensure_tables_exist()

        with self.db.get_session() as session:
            # Get conversation
            conv_db = session.query(ConversationTable).filter_by(id=conversation_id).first()
            if not conv_db:
                return None

            messages = []
            if include_messages:
                # Get all messages for this conversation
                messages_db = session.query(MessageTable).filter_by(
                    conversation_id=conversation_id
                ).order_by(MessageTable.timestamp).all()

                messages = [
                    Message(
                        role=msg.role,
                        content=msg.content,
                        timestamp=msg.timestamp,
                        tokens=msg.tokens,
                        metadata=msg.message_metadata or {}  # Map from message_metadata
                    )
                    for msg in messages_db
                ]

            return Conversation(
                id=conv_db.id,
                user_id=conv_db.user_id,
                title=conv_db.title,
                created_at=conv_db.created_at,
                updated_at=conv_db.updated_at,
                is_active=conv_db.is_active,
                metadata=conv_db.conv_metadata or {},  # Map from conv_metadata
                system_prompt=conv_db.system_prompt,
                llm_config=conv_db.llm_config or {},
                messages=messages
            )

    def get_user_conversations(self, user_id: str, include_inactive: bool = False) -> List[Dict[str, Any]]:
        """Get all conversations for a user."""
        # Ensure tables exist before querying
        self._ensure_tables_exist()

        with self.db.get_session() as session:
            query = session.query(ConversationTable).filter_by(user_id=user_id)

            if not include_inactive:
                query = query.filter_by(is_active=True)

            conversations_db = query.order_by(ConversationTable.updated_at.desc()).all()

            conversations = []
            for conv_db in conversations_db:
                # Get message count for each conversation
                message_count = session.query(MessageTable).filter_by(
                    conversation_id=conv_db.id
                ).count()

                # Get last message timestamp
                last_message = session.query(MessageTable).filter_by(
                    conversation_id=conv_db.id
                ).order_by(MessageTable.timestamp.desc()).first()

                conversations.append({
                    "id": conv_db.id,
                    "user_id": conv_db.user_id,
                    "title": conv_db.title,
                    "created_at": conv_db.created_at.isoformat() if conv_db.created_at else None,
                    "updated_at": conv_db.updated_at.isoformat() if conv_db.updated_at else None,
                    "is_active": conv_db.is_active,
                    "message_count": message_count,
                    "last_message_at": last_message.timestamp.isoformat() if last_message else None,
                    "system_prompt": conv_db.system_prompt,
                    "llm_config": conv_db.llm_config or {},
                    "metadata": conv_db.conv_metadata or {}  # Include metadata in response
                })

            return conversations

    def add_message(self, conversation_id: str, message: Message) -> str:
        """Add a message to a conversation."""
        # Ensure tables exist before adding
        self._ensure_tables_exist()

        message_id = str(uuid.uuid4())

        with self.db.get_session() as session:
            # Check if conversation exists
            conversation = session.query(ConversationTable).filter_by(id=conversation_id).first()
            if not conversation:
                raise ValueError(f"Conversation {conversation_id} not found")

            # Add message
            message_db = MessageTable(
                id=message_id,
                conversation_id=conversation_id,
                role=message.role,
                content=message.content,
                timestamp=message.timestamp or datetime.utcnow(),
                tokens=message.tokens,
                message_metadata=message.metadata or {}  # Use message_metadata
            )
            session.add(message_db)

            # Update conversation's updated_at timestamp
            conversation.updated_at = datetime.utcnow()

        log("debug", f"Added {message.role} message to conversation {conversation_id}")
        return message_id

    def add_message_pair(self, conversation_id: str, user_message: str, assistant_message: str,
                        user_tokens: Optional[int] = None, assistant_tokens: Optional[int] = None) -> None:
        """Add a user-assistant message pair to a conversation."""
        # Add user message
        self.add_message(conversation_id, Message(
            role="user",
            content=user_message,
            tokens=user_tokens,
            metadata={}
        ))

        # Add assistant message
        self.add_message(conversation_id, Message(
            role="assistant",
            content=assistant_message,
            tokens=assistant_tokens,
            metadata={}
        ))

    def update_conversation_title(self, conversation_id: str, new_title: str) -> bool:
        """Update conversation title."""
        if not new_title or not new_title.strip():
            raise ValueError("Conversation title cannot be empty")

        # Ensure tables exist before updating
        self._ensure_tables_exist()

        with self.db.get_session() as session:
            conversation = session.query(ConversationTable).filter_by(id=conversation_id).first()
            if not conversation:
                return False

            conversation.title = new_title.strip()
            conversation.updated_at = datetime.utcnow()

            log("info", f"Updated conversation {conversation_id} title to: {new_title.strip()}")
            return True

    def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation and all its messages."""
        # Ensure tables exist before deleting
        self._ensure_tables_exist()

        with self.db.get_session() as session:
            # Delete all messages first
            session.query(MessageTable).filter_by(conversation_id=conversation_id).delete()

            # Delete conversation
            result = session.query(ConversationTable).filter_by(id=conversation_id).delete()

            if result > 0:
                log("info", f"Deleted conversation {conversation_id} and its messages")
                return True
            return False

    def deactivate_conversation(self, conversation_id: str) -> bool:
        """Deactivate a conversation (soft delete)."""
        # Ensure tables exist before updating
        self._ensure_tables_exist()

        with self.db.get_session() as session:
            conversation = session.query(ConversationTable).filter_by(id=conversation_id).first()
            if not conversation:
                return False

            conversation.is_active = False
            conversation.updated_at = datetime.utcnow()

            log("info", f"Deactivated conversation {conversation_id}")
            return True

    def clear_conversation_messages(self, conversation_id: str) -> bool:
        """Clear all messages from a conversation."""
        # Ensure tables exist before clearing
        self._ensure_tables_exist()

        with self.db.get_session() as session:
            # Check if conversation exists
            conversation = session.query(ConversationTable).filter_by(id=conversation_id).first()
            if not conversation:
                return False

            # Delete all messages
            session.query(MessageTable).filter_by(conversation_id=conversation_id).delete()

            # Update conversation timestamp
            conversation.updated_at = datetime.utcnow()

            log("info", f"Cleared all messages from conversation {conversation_id}")
            return True

    def get_conversation_message_count(self, conversation_id: str) -> int:
        """Get the number of messages in a conversation."""
        # Ensure tables exist before counting
        self._ensure_tables_exist()

        with self.db.get_session() as session:
            count = session.query(MessageTable).filter_by(conversation_id=conversation_id).count()
            return count

    def get_conversation_token_count(self, conversation_id: str) -> int:
        """Get total token count for a conversation."""
        # Ensure tables exist before counting
        self._ensure_tables_exist()

        with self.db.get_session() as session:
            messages = session.query(MessageTable).filter_by(conversation_id=conversation_id).all()
            total_tokens = sum(msg.tokens for msg in messages if msg.tokens)
            return total_tokens

    def get_conversation_summary(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """Get a summary of a conversation."""
        conversation = self.get_conversation(conversation_id, include_messages=True)
        if not conversation:
            return None

        return {
            "id": conversation.id,
            "title": conversation.title,
            "message_count": len(conversation.messages),
            "total_tokens": self.get_conversation_token_count(conversation_id),
            "created_at": conversation.created_at.isoformat(),
            "updated_at": conversation.updated_at.isoformat(),
            "last_user_message": next(
                (msg.content for msg in reversed(conversation.messages) if msg.role == "user"),
                None
            ),
            "metadata": conversation.metadata  # Include metadata
        }


# Global conversation manager instance
conversation_manager = ConversationManager()


def init_conversation_manager():
    """Initialize the conversation manager."""
    # Just return the instance - tables will be created when needed
    return conversation_manager

# Initialize conversation manager
init_conversation_manager()
