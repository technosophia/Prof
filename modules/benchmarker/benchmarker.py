"""Benchmarker persistence model and DB table initialization helpers."""

from datetime import datetime
import uuid

from sqlalchemy import Column, DateTime, Float, Integer, JSON, String

from shared.common import Base, get_db_manager, log


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


def ensure_tables_exist() -> None:
    """Create benchmarker tables when DB engine is available."""
    db = get_db_manager()
    if db.is_initialized() and db._engine is not None:
        BenchmarkRun.__table__.create(bind=db._engine, checkfirst=True)
        log("debug", "Benchmarker table ensured: benchmark_runs")
