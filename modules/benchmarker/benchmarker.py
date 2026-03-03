"""Benchmarker persistence models and DB table initialization helpers."""

from datetime import datetime
import uuid

from sqlalchemy import Column, DateTime, Float, Integer, JSON, String, Text

from core.logging import log
from core.database import Base


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


class ScoringRun(Base):
    """Database record for one scorer execution on a benchmark session."""

    __tablename__ = "scoring_runs"
    __table_args__ = {"extend_existing": True}

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id = Column(String(36), nullable=True)
    session_file = Column(String(512), nullable=False)
    scorer_id = Column(String(64), nullable=False)
    scorer_config = Column(JSON, default={})
    scores = Column(JSON, default={})
    overall_score = Column(Float, nullable=True)
    scored_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    source = Column(String(64), nullable=False)
    notes = Column(Text, nullable=True)
    parse_errors = Column(JSON, default=[])


def ensure_tables_exist(db_manager) -> None:
    """Create benchmarker tables when DB engine is available."""
    if db_manager.is_initialized() and db_manager._engine is not None:
        BenchmarkRun.__table__.create(bind=db_manager._engine, checkfirst=True)
        ScoringRun.__table__.create(bind=db_manager._engine, checkfirst=True)
        log("debug", "Benchmarker table ensured: benchmark_runs")
        log("debug", "Benchmarker table ensured: scoring_runs")
