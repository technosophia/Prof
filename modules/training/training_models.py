"""
Training models for database persistence.
"""
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any

from sqlalchemy import Column, String, Text, DateTime, Boolean, JSON, ForeignKey, Integer, Index
from sqlalchemy.orm import relationship

from core.database import Base
from core.logging import log


class TrainingMasterConfigTable(Base):
    """Master training configuration."""
    __tablename__ = 'training_master_configs'

    id = Column(String, primary_key=True)
    master_id = Column(String, ForeignKey('users.id'), nullable=False, index=True)
    system_prompt = Column(Text, nullable=False)
    learning_path = Column(Text, nullable=False)
    analyzer_prompt = Column(Text, nullable=False)
    merging_prompt = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    config_metadata = Column(JSON, default={})


class StudentStateTable(Base):
    """Student learning state."""
    __tablename__ = 'student_states'

    id = Column(String, primary_key=True)
    master_id = Column(String, ForeignKey('users.id'), nullable=False, index=True)
    student_id = Column(String, ForeignKey('users.id'), nullable=False, index=True)
    current_state = Column(Text, nullable=False, default="")
    last_analyzed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    state_metadata = Column(JSON, default={})


class StudentStateHistoryTable(Base):
    """History of student state changes."""
    __tablename__ = 'student_state_history'

    id = Column(String, primary_key=True)
    master_id = Column(String, ForeignKey('users.id'), nullable=False, index=True)
    student_id = Column(String, ForeignKey('users.id'), nullable=False, index=True)
    previous_state = Column(Text, nullable=True)  # State before this update
    new_state = Column(Text, nullable=False)  # State after this update
    change_reason = Column(Text, nullable=True)  # Why the change happened
    analyzed_message_count = Column(Integer, default=0)  # Number of messages analyzed
    analyzed_message_ids = Column(JSON, default=[])  # List of message IDs that were analyzed
    created_at = Column(DateTime, default=datetime.utcnow)
    history_metadata = Column(JSON, default={})  # CHANGED: Renamed from 'metadata' to 'history_metadata'

    # Index for faster retrieval by student and timestamp
    __table_args__ = (
        Index('idx_student_state_history_student_timestamp', 'student_id', 'created_at'),
    )


class AnalyzedMessageTable(Base):
    """Tracks which messages have been analyzed."""
    __tablename__ = 'analyzed_messages'

    id = Column(String, primary_key=True)
    student_id = Column(String, ForeignKey('users.id'), nullable=False, index=True)
    message_id = Column(String, nullable=False, index=True)  # Reference to messages.id
    conversation_id = Column(String, nullable=False, index=True)
    analyzed_at = Column(DateTime, default=datetime.utcnow)
    analysis_summary = Column(Text, nullable=True)
    message_metadata = Column(JSON, default={})
    # Link to state history entry
    state_history_id = Column(String, ForeignKey('student_state_history.id'), nullable=True, index=True)
