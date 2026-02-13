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

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    plugin_id = Column(String, nullable=False, index=True)
    user_id = Column(String, nullable=True, index=False)  # Remove index=True from column
    key = Column(String, nullable=False)
    value = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    data_metadata = Column(JSON, default={})

class PluginActivation(Base):
    """Store plugin activation status per trainer."""
    __tablename__ = 'trainer_plugin_activations'
    __table_args__ = {'extend_existing': True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    trainer_id = Column(String, nullable=False, index=True)
    plugin_id = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    config = Column(JSON, default={})
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    activation_metadata = Column(JSON, default={})
