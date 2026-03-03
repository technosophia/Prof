"""
Trainer module database models.
Defines tables for plugin data and trainer configurations.
"""

from datetime import datetime
import uuid

from sqlalchemy import Boolean, Column, DateTime, Index, JSON, String, Text

from core.database import Base
from core.logging import log


class TrainerConfig(Base):
    """Store trainer-specific configuration."""

    __tablename__ = "trainer_config"
    __table_args__ = {"extend_existing": True}

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    trainer_id = Column(String(36), nullable=False, unique=True, index=True)
    training_program = Column(Text, nullable=True)
    config = Column(JSON, default={})
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PluginData(Base):
    """Generic storage for plugin data."""

    __tablename__ = "trainer_plugin_data"
    __table_args__ = (
        Index("ix_trainer_plugin_data_user_id", "user_id"),
        {"extend_existing": True},
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    plugin_id = Column(String(100), nullable=False, index=True)
    user_id = Column(String(36), nullable=True, index=False)
    key = Column(String(255), nullable=False)
    value = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    data_metadata = Column(JSON, default={})


class PluginActivation(Base):
    """Store plugin activation status per trainer."""

    __tablename__ = "trainer_plugin_activations"
    __table_args__ = {"extend_existing": True}

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    trainer_id = Column(String(36), nullable=False, index=True)
    plugin_id = Column(String(100), nullable=False)
    is_active = Column(Boolean, default=True)
    config = Column(JSON, default={})
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    activation_metadata = Column(JSON, default={})


def ensure_tables_exist(db_manager) -> bool:
    """Create Trainer core tables when a database engine is available."""
    if db_manager is None:
        raise RuntimeError("trainer: 'db_manager' service not available")
    if not db_manager.is_initialized() or db_manager._engine is None:
        return False

    TrainerConfig.__table__.create(bind=db_manager._engine, checkfirst=True)
    PluginData.__table__.create(bind=db_manager._engine, checkfirst=True)
    PluginActivation.__table__.create(bind=db_manager._engine, checkfirst=True)
    log("debug", "Trainer tables ensured: trainer_config, trainer_plugin_data, trainer_plugin_activations")
    return True
