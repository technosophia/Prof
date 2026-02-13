"""
Database models for LLM monitoring.
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Float, Integer, JSON, ForeignKey, Index, BigInteger
from sqlalchemy.orm import Session

from core.database import Base
from core.logging import log


class LLMCallTable(Base):
    """Table to store LLM call information."""
    __tablename__ = 'llm_calls'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey('users.id'), nullable=True, index=True)
    conversation_id = Column(String, ForeignKey('conversations.id'), nullable=True, index=True)

    # LLM information
    llm_id = Column(String, nullable=False)
    llm_type = Column(String, nullable=False)  # ollama, groq, gemini, etc.
    model = Column(String, nullable=False)
    engine_type = Column(String, nullable=False)

    # Call details
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    duration_ms = Column(Integer, nullable=True)  # Duration in milliseconds

    # Token usage
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)

    # Cost calculation (per million tokens)
    input_cost = Column(Float, default=0.0)
    output_cost = Column(Float, default=0.0)
    total_cost = Column(Float, default=0.0)

    # Message data (stored as JSON for flexibility)
    messages = Column(JSON, nullable=False)  # Full message history sent to LLM
    context_messages = Column(JSON, nullable=True)  # Additional context added by callbacks
    response = Column(Text, nullable=False)

    # Metadata (renamed from 'metadata' to avoid SQLAlchemy conflict)
    call_metadata = Column(JSON, nullable=True)  # Additional metadata
    success = Column(Integer, default=1)  # 1 for success, 0 for failure
    error_message = Column(Text, nullable=True)
    rate_limit_info = Column(JSON, nullable=True)  # Rate limit headers if available

    # Indexes
    __table_args__ = (
        Index('idx_llm_calls_user_timestamp', 'user_id', 'timestamp'),
        Index('idx_llm_calls_llm_type', 'llm_type'),
        Index('idx_llm_calls_conversation', 'conversation_id'),
        Index('idx_llm_calls_model', 'model'),
        Index('idx_llm_calls_date', 'timestamp'),
    )


class UserLLMStatsTable(Base):
    """Table to store aggregated LLM usage statistics per user."""
    __tablename__ = 'user_llm_stats'

    user_id = Column(String, ForeignKey('users.id'), primary_key=True)
    llm_type = Column(String, primary_key=True)

    # Token counts
    total_input_tokens = Column(BigInteger, default=0)
    total_output_tokens = Column(BigInteger, default=0)
    total_calls = Column(Integer, default=0)

    # Cost totals (per million tokens)
    total_cost = Column(Float, default=0.0)

    # Last updated
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Indexes
    __table_args__ = (
        Index('idx_user_llm_stats_user', 'user_id'),
        Index('idx_user_llm_stats_type', 'llm_type'),
    )


class RateLimitUsageTable(Base):
    """Table to track rate limit usage per API provider per period."""
    __tablename__ = 'rate_limit_usage'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    provider = Column(String, nullable=False, index=True)  # groq, gemini, etc.
    model = Column(String, nullable=False, index=True)
    plan_type = Column(String, nullable=False, default='free')  # free, developer, etc.

    # Time period identifiers
    period_date = Column(String, nullable=False)  # YYYY-MM-DD format for daily tracking
    period_hour = Column(Integer, nullable=True)  # Hour for hourly tracking

    # Usage metrics
    requests_count = Column(Integer, default=0)
    tokens_count = Column(BigInteger, default=0)

    # Reset timestamps (from API headers)
    requests_reset_at = Column(DateTime, nullable=True)
    tokens_reset_at = Column(DateTime, nullable=True)

    # Last updated
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # User tracking (if per-user tracking is enabled)
    user_id = Column(String, ForeignKey('users.id'), nullable=True, index=True)

    # Composite unique constraint
    __table_args__ = (
        Index('idx_rate_limit_lookup', 'provider', 'model', 'plan_type', 'period_date', 'user_id'),
        Index('idx_rate_limit_period', 'period_date'),
    )


class DailyCostSummaryTable(Base):
    """Table to store daily cost summaries."""
    __tablename__ = 'daily_cost_summary'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    date = Column(String, nullable=False, index=True)  # YYYY-MM-DD
    provider = Column(String, nullable=False, index=True)
    model = Column(String, nullable=False)

    # Usage metrics
    total_calls = Column(Integer, default=0)
    total_input_tokens = Column(BigInteger, default=0)
    total_output_tokens = Column(BigInteger, default=0)
    total_tokens = Column(BigInteger, default=0)

    # Cost metrics (per million tokens)
    total_input_cost = Column(Float, default=0.0)
    total_output_cost = Column(Float, default=0.0)
    total_cost = Column(Float, default=0.0)

    # Last updated
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index('idx_daily_cost_summary_date', 'date'),
        Index('idx_daily_cost_summary_provider', 'provider'),
    )
