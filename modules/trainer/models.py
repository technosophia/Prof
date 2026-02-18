"""
Trainer module database models.
Defines tables for plugin data.
"""

from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, JSON, Boolean, ForeignKey, Index
from sqlalchemy.orm import relationship
from shared.common import Base
import uuid


class PluginData(Base):
    """Generic storage for plugin data."""
    __tablename__ = 'trainer_plugin_data'
    __table_args__ = (
        Index('ix_trainer_plugin_data_user_id', 'user_id'),  # Define index explicitly
        {'extend_existing': True}
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))  # UUID length
    plugin_id = Column(String(100), nullable=False, index=True)  # Plugin identifier (e.g., 'youtube', 'pdf')
    user_id = Column(String(36), nullable=True, index=False)  # UUID length, can be null for global data
    key = Column(String(255), nullable=False)  # Data key name
    value = Column(JSON, nullable=False)  # JSON data, no length needed
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    data_metadata = Column(JSON, default={})  # Additional metadata


class PluginActivation(Base):
    """Store plugin activation status per trainer."""
    __tablename__ = 'trainer_plugin_activations'
    __table_args__ = {'extend_existing': True}

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))  # UUID length
    trainer_id = Column(String(36), nullable=False, index=True)  # UUID length
    plugin_id = Column(String(100), nullable=False)  # Plugin identifier
    is_active = Column(Boolean, default=True)
    config = Column(JSON, default={})  # Plugin configuration
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    activation_metadata = Column(JSON, default={})  # Additional metadata
