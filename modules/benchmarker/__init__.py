"""Benchmarker module initialization and persistence model."""

from datetime import datetime
import os
import uuid

from sqlalchemy import Column, DateTime, Float, Integer, JSON, String

from shared.common import Base, get_db_manager, get_section, log, register_action

from .core_actions import (
    action_create_conversation,
    action_set_training_program,
    action_switch_option,
    action_teacher_send_message,
    action_user_send_message,
)


class BenchmarkRun(Base):
    """Database record for one benchmark scenario run."""

    __tablename__ = "benchmark_runs"
    __table_args__ = {"extend_existing": True}

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    scenario_name = Column(String(255), nullable=False)
    run_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    duration_seconds = Column(Float, default=0.0)
    options = Column(JSON, default={})
    success = Column(Integer, default=0)
    assertions_passed = Column(Integer, default=0)
    assertions_total = Column(Integer, default=0)
    errors = Column(JSON, default=[])
    session_file = Column(String(512), nullable=False)
    summary = Column(JSON, default={})


def initialize() -> bool:
    """Initialize benchmarker module: tables, directories, and actions."""
    try:
        config = get_section("benchmarker")
        sessions_dir = config.get("sessions_dir", "data/benchmarker/sessions")
        os.makedirs(sessions_dir, exist_ok=True)

        db = get_db_manager()
        if db.is_initialized() and db._engine is not None:
            Base.metadata.create_all(bind=db._engine, tables=[BenchmarkRun.__table__])

        register_action(
            "create_conversation",
            action_create_conversation,
            "Create a conversation for the current student",
            required_context=["student_id"],
        )
        register_action(
            "user_send_message",
            action_user_send_message,
            "Send a student message and get LLM response",
            required_context=["student_id", "conversation_id"],
        )
        register_action(
            "teacher_send_message",
            action_teacher_send_message,
            "Inject a teacher message into a conversation",
            required_context=["trainer_id", "student_id", "conversation_id"],
        )
        register_action(
            "set_training_program",
            action_set_training_program,
            "Set the training program for the current trainer",
            required_context=["trainer_id"],
        )
        register_action(
            "switch_option",
            action_switch_option,
            "Switch a driver option mid-scenario (system only)",
            required_context=[],
        )

        log("info", "Benchmarker module initialized")
        return True
    except Exception as exc:
        log("error", f"Failed to initialize benchmarker module: {exc}", exc_info=True)
        return False
