"""
Trainer module database models.
Defines tables for student notes and plugin data.
"""

from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, JSON, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from shared.common import Base
import uuid


class StudentNote(Base):
    """Store notes/pad for each student."""
    __tablename__ = 'trainer_student_notes'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)  # Student ID
    trainer_id = Column(String, nullable=False, index=True)  # Trainer/Master ID
    content = Column(Text, default="")
    plugin_id = Column(String, default="core")  # Which plugin owns this note
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    note_metadata = Column(JSON, default={})  # Renamed from 'metadata' to avoid SQLAlchemy conflict


class PluginData(Base):
    """Generic storage for plugin data."""
    __tablename__ = 'trainer_plugin_data'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    plugin_id = Column(String, nullable=False, index=True)
    user_id = Column(String, nullable=True, index=True)
    key = Column(String, nullable=False)
    value = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    data_metadata = Column(JSON, default={})  # Renamed from 'metadata' to avoid SQLAlchemy conflict


class PluginActivation(Base):
    """Store plugin activation status per trainer."""
    __tablename__ = 'trainer_plugin_activations'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    trainer_id = Column(String, nullable=False, index=True)
    plugin_id = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    config = Column(JSON, default={})
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    activation_metadata = Column(JSON, default={})  # Renamed from 'metadata' to avoid SQLAlchemy conflict
