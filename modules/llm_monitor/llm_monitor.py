"""
LLM Monitoring and Cost Tracking Core Module
"""
import json
import time
from datetime import datetime, date, timedelta
from typing import Dict, List, Any, Optional, Callable, Tuple
import tiktoken  # For token estimation
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, text

from core.logging import log

# Import models
from modules.llm_monitor.models import (
    LLMCallTable,
    UserLLMStatsTable,
    RateLimitUsageTable,
    DailyCostSummaryTable
)


class LLMMonitor:
    """Main class for monitoring LLM usage, costs, and rate limits."""

    def __init__(self, config, db_manager):
        """Initialize with injected dependencies."""
        self.config = config
        self.db = db_manager
        self._ensure_tables_exist()

        # Get LLM configurations from the config
        module_config = config.get("llm_monitor", {})
        self.llm_configs = module_config.get("llms", {})

        self.enabled = module_config.get("enabled", True)
        self.auto_collect = module_config.get("auto_collect", True)
        self.rate_limit_tracking = module_config.get("rate_limit_tracking", {"enabled": True})
        self._token_encoder_cache = {}

        log("info", "LLMMonitor initialized with injected dependencies")

    def _ensure_tables_exist(self):
        """Ensure monitoring tables exist, including safe column migrations."""
        if not self.db.is_initialized():
            return False

        try:
            LLMCallTable.__table__.create(bind=self.db._engine, checkfirst=True)
            UserLLMStatsTable.__table__.create(bind=self.db._engine, checkfirst=True)
            RateLimitUsageTable.__table__.create(bind=self.db._engine, checkfirst=True)
            DailyCostSummaryTable.__table__.create(bind=self.db._engine, checkfirst=True)

            # Safe migration: add new columns to existing tables if they are absent.
            # SQLite does not support ADD COLUMN IF NOT EXISTS, so we inspect first.
            self._migrate_add_column_if_missing(
                table="llm_calls",
                column="raw_response",
                column_def="TEXT NULL",
            )
            self._migrate_add_column_if_missing(
                table="llm_calls",
                column="no_thinking",
                column_def="INTEGER NOT NULL DEFAULT 0",
            )

            log("debug", "LLM monitor tables ensured")
            return True
        except Exception as e:
            log("error", f"Failed to create LLM monitor tables: {e}")
            return False

    def _migrate_add_column_if_missing(self, table: str, column: str, column_def: str):
        """Add a column to an existing table when it does not already exist.

        Works for both SQLite and MySQL/Postgres (PRAGMA vs information_schema).
        Silently skips if the column is already present.
        """
        try:
            with self.db._engine.connect() as conn:
                dialect = self.db._engine.dialect.name

                if dialect == "sqlite":
                    result = conn.execute(text(f"PRAGMA table_info({table})"))
                    existing_columns = {row[1] for row in result}
                else:
                    # MySQL / Postgres
                    result = conn.execute(text(
                        "SELECT column_name FROM information_schema.columns "
                        f"WHERE table_name = '{table}'"
                    ))
                    existing_columns = {row[0] for row in result}

                if column not in existing_columns:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {column_def}"))
                    conn.commit()
                    log("info", f"Migration: added column '{column}' to table '{table}'")
                else:
                    log("debug", f"Migration: column '{column}' already exists in '{table}', skipping")

        except Exception as e:
            log("warning", f"Migration warning for {table}.{column}: {e}")

    def _get_token_encoder(self, model: str):
        """Get token encoder for a model."""
        model_to_encoder = {
            "gpt-3.5": "cl100k_base",
            "gpt-4": "cl100k_base",
            "llama": "cl100k_base",
            "qwen": "cl100k_base",
            "gemini": "cl100k_base",
            "default": "cl100k_base"
        }

        model_lower = model.lower()
        encoder_name = "cl100k_base"  # Default

        for key, encoder in model_to_encoder.items():
            if key in model_lower:
                encoder_name = encoder
                break

        if encoder_name not in self._token_encoder_cache:
            try:
                self._token_encoder_cache[encoder_name] = tiktoken.get_encoding(encoder_name)
            except Exception as e:
                log("warning", f"Failed to get encoder {encoder_name}: {e}")
                return None

        return self._token_encoder_cache.get(encoder_name)

    def estimate_tokens(self, text: str, model: str) -> int:
        """Estimate token count for text."""
        if not text:
            return 0

        encoder = self._get_token_encoder(model)
        if encoder:
            return len(encoder.encode(text))

        return len(text) // 4

    def estimate_message_tokens(self, messages: List[Dict[str, str]], model: str) -> int:
        """Estimate total tokens for a list of messages."""
        total_tokens = 0
        tokens_per_message = 3
        tokens_per_name = 1

        for message in messages:
            total_tokens += tokens_per_message
            content = message.get("content", "")
            total_tokens += self.estimate_tokens(content, model)
            total_tokens += self.estimate_tokens(message.get("role", ""), model)

            if "name" in message:
                total_tokens += tokens_per_name
                total_tokens += self.estimate_tokens(message["name"], model)

        total_tokens += 3
        return total_tokens

    def get_llm_config(self, llm_id: str) -> Dict[str, Any]:
        """Get configuration for a specific LLM by its ID."""
        return self.llm_configs.get(llm_id, {})

    def is_free_provider(self, llm_type: str) -> bool:
        """Check if the provider is free (no cost)."""
        llm_config = self.get_llm_config(llm_type)
        input_cost = llm_config.get("input_cost_per_million_tokens", 0)
        output_cost = llm_config.get("output_cost_per_million_tokens", 0)
        return input_cost == 0 and output_cost == 0

    def calculate_cost(self, llm_type: str, input_tokens: int, output_tokens: int) -> Dict[str, float]:
        """Calculate cost based on token usage (per million tokens)."""
        llm_config = self.get_llm_config(llm_type)

        input_cost_per_million = llm_config.get("input_cost_per_million_tokens", 0)
        output_cost_per_million = llm_config.get("output_cost_per_million_tokens", 0)

        input_cost = (input_tokens / 1_000_000) * input_cost_per_million
        output_cost = (output_tokens / 1_000_000) * output_cost_per_million
        total_cost = input_cost + output_cost

        return {
            "input_cost": input_cost,
            "output_cost": output_cost,
            "total_cost": total_cost
        }

    def get_rate_limits(self, provider: str, model: str) -> Dict[str, Any]:
        """Get rate limits for a specific provider and model."""
        llm_config = self.get_llm_config(provider)
        return {
            "rpm": llm_config.get("rpm", 0),
            "rpd": llm_config.get("rpd", 0),
            "tpm": llm_config.get("tpm", 0),
            "tpd": llm_config.get("tpd", 0)
        }

    def update_rate_limit_usage(self, provider: str, model: str,
                               tokens_used: int, user_id: Optional[str] = None,
                               rate_limit_headers: Optional[Dict] = None):
        """Update rate limit usage for a provider using estimated tokens."""
        if not self.rate_limit_tracking.get("enabled", True):
            return

        try:
            limits = self.get_rate_limits(provider, model)
            has_limits = any(limits.get(k, 0) > 0 for k in ["rpm", "rpd", "tpm", "tpd"])

            if not has_limits:
                log("debug", f"No rate limits configured for {provider}, skipping tracking")
                return

            with self.db.get_session() as session:
                self._update_rate_limit_usage_internal(
                    session, provider, model, tokens_used, user_id
                )
                session.commit()

        except Exception as e:
            log("error", f"Failed to update rate limit usage: {e}", stacktrace=True)

    def _update_rate_limit_usage_internal(self, session: Session, provider: str,
                                         model: str, tokens_used: int,
                                         user_id: Optional[str] = None):
        """Internal method to update rate limit usage within an existing session."""
        try:
            today = datetime.utcnow().strftime("%Y-%m-%d")
            current_hour = datetime.utcnow().hour

            limits = self.get_rate_limits(provider, model)
            has_limits = any(limits.get(k, 0) > 0 for k in ["rpm", "rpd", "tpm", "tpd"])

            if not has_limits:
                return

            # Update daily usage
            daily_usage = session.query(RateLimitUsageTable).filter_by(
                provider=provider,
                model=model,
                period_date=today,
                period_hour=None,
                user_id=user_id if self.rate_limit_tracking.get("track_per_user", False) else None
            ).first()

            if not daily_usage:
                daily_usage = RateLimitUsageTable(
                    provider=provider,
                    model=model,
                    plan_type="free",
                    period_date=today,
                    requests_count=0,
                    tokens_count=0,
                    user_id=user_id if self.rate_limit_tracking.get("track_per_user", False) else None
                )
                session.add(daily_usage)

            daily_usage.requests_count = (daily_usage.requests_count or 0) + 1
            daily_usage.tokens_count = (daily_usage.tokens_count or 0) + tokens_used
            daily_usage.last_updated = datetime.utcnow()

            # Update hourly usage
            hourly_usage = session.query(RateLimitUsageTable).filter_by(
                provider=provider,
                model=model,
                period_date=today,
                period_hour=current_hour,
                user_id=user_id if self.rate_limit_tracking.get("track_per_user", False) else None
            ).first()

            if not hourly_usage:
                hourly_usage = RateLimitUsageTable(
                    provider=provider,
                    model=model,
                    plan_type="free",
                    period_date=today,
                    period_hour=current_hour,
                    requests_count=0,
                    tokens_count=0,
                    user_id=user_id if self.rate_limit_tracking.get("track_per_user", False) else None
                )
                session.add(hourly_usage)

            hourly_usage.requests_count = (hourly_usage.requests_count or 0) + 1
            hourly_usage.tokens_count = (hourly_usage.tokens_count or 0) + tokens_used
            hourly_usage.last_updated = datetime.utcnow()

            log("debug", f"Updated rate limit usage for {provider}: +1 request, +{tokens_used} tokens")

        except Exception as e:
            log("error", f"Failed to update rate limit usage (internal): {e}", stacktrace=True)
            raise

    def get_rate_limit_usage(self, provider: str, model: str,
                            user_id: Optional[str] = None) -> Dict[str, Any]:
        """Get current rate limit usage for a provider."""
        try:
            with self.db.get_session() as session:
                today = datetime.utcnow().strftime("%Y-%m-%d")
                current_hour = datetime.utcnow().hour

                limits = self.get_rate_limits(provider, model)
                has_limits = any(limits.get(k, 0) > 0 for k in ["rpm", "rpd", "tpm", "tpd"])

                if not has_limits:
                    return {
                        "provider": provider,
                        "model": model,
                        "limits": {},
                        "daily": {"requests": 0, "tokens": 0, "requests_limit": None, "tokens_limit": None},
                        "hourly": {"requests": 0, "tokens": 0, "requests_limit": None, "tokens_limit": None}
                    }

                tracked_user_id = user_id if self.rate_limit_tracking.get("track_per_user", False) else None

                daily_totals = session.query(
                    func.coalesce(func.sum(RateLimitUsageTable.requests_count), 0).label("requests"),
                    func.coalesce(func.sum(RateLimitUsageTable.tokens_count), 0).label("tokens")
                ).filter(
                    RateLimitUsageTable.provider == provider,
                    RateLimitUsageTable.period_date == today,
                    RateLimitUsageTable.period_hour.is_(None),
                    RateLimitUsageTable.user_id == tracked_user_id
                ).one()

                hourly_totals = session.query(
                    func.coalesce(func.sum(RateLimitUsageTable.requests_count), 0).label("requests"),
                    func.coalesce(func.sum(RateLimitUsageTable.tokens_count), 0).label("tokens")
                ).filter(
                    RateLimitUsageTable.provider == provider,
                    RateLimitUsageTable.period_date == today,
                    RateLimitUsageTable.period_hour == current_hour,
                    RateLimitUsageTable.user_id == tracked_user_id
                ).one()

                # Fallback to LLM calls if no rate limit records
                if daily_totals.requests == 0 and daily_totals.tokens == 0:
                    daily_call_query = session.query(
                        func.count(LLMCallTable.id).label("requests"),
                        func.coalesce(func.sum(LLMCallTable.total_tokens), 0).label("tokens")
                    ).filter(LLMCallTable.llm_type == provider)

                    if tracked_user_id:
                        daily_call_query = daily_call_query.filter(LLMCallTable.user_id == tracked_user_id)

                    day_start = datetime.strptime(today, "%Y-%m-%d")
                    day_end = day_start + timedelta(days=1)

                    daily_call_query = daily_call_query.filter(
                        LLMCallTable.timestamp >= day_start,
                        LLMCallTable.timestamp < day_end
                    )
                    daily_totals = daily_call_query.one()

                result = {
                    "provider": provider,
                    "model": model,
                    "limits": limits,
                    "daily": {
                        "requests": int(daily_totals.requests or 0),
                        "tokens": int(daily_totals.tokens or 0),
                        "requests_limit": limits.get("rpd") if limits.get("rpd", 0) > 0 else None,
                        "tokens_limit": limits.get("tpd") if limits.get("tpd", 0) > 0 else None,
                    },
                    "hourly": {
                        "requests": int(hourly_totals.requests or 0),
                        "tokens": int(hourly_totals.tokens or 0),
                        "requests_limit": limits.get("rpm") if limits.get("rpm", 0) > 0 else None,
                        "tokens_limit": limits.get("tpm") if limits.get("tpm", 0) > 0 else None,
                    }
                }

                # Calculate percentages
                for period in ["daily", "hourly"]:
                    for metric in ["requests", "tokens"]:
                        limit_key = f"{metric}_limit"
                        if result[period].get(limit_key) and result[period][limit_key] > 0:
                            result[period][f"{metric}_percentage"] = (
                                result[period][metric] / result[period][limit_key] * 100
                            )
                        else:
                            result[period][f"{metric}_percentage"] = 0

                return result

        except Exception as e:
            log("error", f"Failed to get rate limit usage: {e}")
            return {}

    def extract_context_messages(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Extract context messages (system messages and LLM callbacks) from conversation."""
        return [msg.copy() for msg in messages if msg.get("role") == "system"]

    def extract_user_assistant_messages(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Extract only user and assistant messages (for display)."""
        return [msg.copy() for msg in messages if msg.get("role") in ["user", "assistant"]]

    def log_llm_call(self, data: Dict[str, Any]):
        """Log an LLM call to the database.

        Expected keys in data (from monitor callback):
            llm_id, llm_type, model, engine_type, messages, response,
            raw_response, no_thinking, timestamp, success, error, user_id,
            conversation_id (optional), response_format (optional).

        Token accounting uses raw_response when available so that thinking
        content (which the model generated and the API billed for) is counted,
        not the stripped version shown to the user.
        """
        if not self.enabled or not self.auto_collect:
            return

        try:
            with self.db.get_session() as session:
                user_id = data.get("user_id")
                conversation_id = data.get("conversation_id")

                # ----------------------------------------------------------------
                # Token estimation
                # For output tokens we always use raw_response when present.
                # This ensures thinking content is accounted for in cost
                # calculations — the model generated those tokens and the
                # provider billed for them regardless of whether we strip them.
                # ----------------------------------------------------------------
                input_tokens = data.get("input_tokens")
                output_tokens = data.get("output_tokens")

                if input_tokens is None:
                    input_tokens = self.estimate_message_tokens(data["messages"], data["model"])

                if output_tokens is None:
                    # Prefer raw_response for accurate billing; fall back to response.
                    text_for_output_count = data.get("raw_response") or data.get("response", "")
                    output_tokens = self.estimate_tokens(text_for_output_count, data["model"])

                total_tokens = (input_tokens or 0) + (output_tokens or 0)

                # Calculate costs
                costs = self.calculate_cost(data["llm_type"], input_tokens or 0, output_tokens or 0)

                # Extract messages
                all_messages = data["messages"]
                context_messages = self.extract_context_messages(all_messages)
                display_messages = self.extract_user_assistant_messages(all_messages)

                # raw_response — None when it equals response (saves storage for
                # engines that do no post-processing, e.g. Groq/Gemini/xAI/Mock).
                raw_response = data.get("raw_response")
                response = data.get("response", "")
                if raw_response == response:
                    raw_response = None  # identical → no need to store twice

                no_thinking_flag = 1 if data.get("no_thinking", False) else 0

                # Create LLM call record
                llm_call = LLMCallTable(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    llm_id=data["llm_id"],
                    llm_type=data["llm_type"],
                    model=data["model"],
                    engine_type=data["engine_type"],
                    timestamp=datetime.fromisoformat(data["timestamp"]) if isinstance(data["timestamp"], str) else data["timestamp"],
                    duration_ms=data.get("duration_ms"),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    input_cost=costs["input_cost"],
                    output_cost=costs["output_cost"],
                    total_cost=costs["total_cost"],
                    messages=display_messages,
                    context_messages=context_messages,
                    response=response,
                    raw_response=raw_response,
                    no_thinking=no_thinking_flag,
                    success=data.get("success", 1),
                    error_message=data.get("error"),
                    call_metadata=data.get("metadata", {}),
                    rate_limit_info=data.get("rate_limit_info", {})
                )

                session.add(llm_call)

                # Update user stats
                if user_id:
                    self._update_user_stats(session, user_id, data["llm_type"],
                                          input_tokens or 0, output_tokens or 0,
                                          costs["total_cost"])

                # Update daily cost summary
                self._update_daily_cost_summary(session, data["llm_type"], data["model"],
                                               input_tokens or 0, output_tokens or 0,
                                               costs["total_cost"])

                # Update rate limit usage if configured
                limits = self.get_rate_limits(data["llm_type"], data["model"])
                if any(limits.get(k, 0) > 0 for k in ["rpm", "rpd", "tpm", "tpd"]):
                    self._update_rate_limit_usage_internal(
                        session=session,
                        provider=data["llm_type"],
                        model=data["model"],
                        tokens_used=total_tokens,
                        user_id=user_id
                    )

                session.commit()
                log("debug", f"Logged LLM call: {data['llm_id']} for user {user_id}")

        except Exception as e:
            log("error", f"Failed to log LLM call: {e}", stacktrace=True)

    def _update_daily_cost_summary(self, session: Session, provider: str, model: str,
                                  input_tokens: int, output_tokens: int, total_cost: float):
        """Update daily cost summary."""
        try:
            today = datetime.utcnow().strftime("%Y-%m-%d")
            llm_config = self.get_llm_config(provider)
            input_cost_per_million = llm_config.get("input_cost_per_million_tokens", 0)
            output_cost_per_million = llm_config.get("output_cost_per_million_tokens", 0)

            summary = session.query(DailyCostSummaryTable).filter_by(
                date=today,
                provider=provider,
                model=model
            ).first()

            if summary:
                summary.total_calls += 1
                summary.total_input_tokens += input_tokens
                summary.total_output_tokens += output_tokens
                summary.total_tokens += (input_tokens + output_tokens)
                summary.total_input_cost += (input_tokens / 1_000_000) * input_cost_per_million
                summary.total_output_cost += (output_tokens / 1_000_000) * output_cost_per_million
                summary.total_cost += total_cost
            else:
                summary = DailyCostSummaryTable(
                    date=today,
                    provider=provider,
                    model=model,
                    total_calls=1,
                    total_input_tokens=input_tokens,
                    total_output_tokens=output_tokens,
                    total_tokens=(input_tokens + output_tokens),
                    total_input_cost=(input_tokens / 1_000_000) * input_cost_per_million,
                    total_output_cost=(output_tokens / 1_000_000) * output_cost_per_million,
                    total_cost=total_cost
                )
                session.add(summary)

        except Exception as e:
            log("error", f"Failed to update daily cost summary: {e}")

    def _update_user_stats(self, session: Session, user_id: str, llm_type: str,
                          input_tokens: int, output_tokens: int, cost: float):
        """Update user LLM statistics."""
        try:
            stats = session.query(UserLLMStatsTable).filter_by(
                user_id=user_id,
                llm_type=llm_type
            ).first()

            if stats:
                stats.total_input_tokens += input_tokens
                stats.total_output_tokens += output_tokens
                stats.total_calls += 1
                stats.total_cost += cost
                stats.last_updated = datetime.utcnow()
            else:
                stats = UserLLMStatsTable(
                    user_id=user_id,
                    llm_type=llm_type,
                    total_input_tokens=input_tokens,
                    total_output_tokens=output_tokens,
                    total_calls=1,
                    total_cost=cost,
                    last_updated=datetime.utcnow()
                )
                session.add(stats)

        except Exception as e:
            log("error", f"Failed to update user stats: {e}")

    def get_user_stats(self, user_id: str) -> Dict[str, Any]:
        """Get LLM usage statistics for a user."""
        try:
            with self.db.get_session() as session:
                stats = session.query(UserLLMStatsTable).filter_by(
                    user_id=user_id
                ).all()

                total_by_type = {}
                overall = {
                    "total_input_tokens": 0,
                    "total_output_tokens": 0,
                    "total_calls": 0,
                    "total_cost": 0.0
                }

                for stat in stats:
                    total_by_type[stat.llm_type] = {
                        "total_input_tokens": stat.total_input_tokens,
                        "total_output_tokens": stat.total_output_tokens,
                        "total_calls": stat.total_calls,
                        "total_cost": stat.total_cost,
                        "last_updated": stat.last_updated.isoformat() if stat.last_updated else None
                    }

                    overall["total_input_tokens"] += stat.total_input_tokens
                    overall["total_output_tokens"] += stat.total_output_tokens
                    overall["total_calls"] += stat.total_calls
                    overall["total_cost"] += stat.total_cost

                return {
                    "by_llm_type": total_by_type,
                    "overall": overall
                }

        except Exception as e:
            log("error", f"Failed to get user stats: {e}")
            return {"by_llm_type": {}, "overall": {}}

    def get_daily_costs(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get daily cost summary for the last N days."""
        try:
            with self.db.get_session() as session:
                cutoff_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

                results = session.query(
                    DailyCostSummaryTable
                ).filter(
                    DailyCostSummaryTable.date >= cutoff_date
                ).order_by(
                    DailyCostSummaryTable.date.desc()
                ).all()

                return [
                    {
                        "date": r.date,
                        "provider": r.provider,
                        "model": r.model,
                        "total_calls": r.total_calls,
                        "total_tokens": r.total_tokens,
                        "total_cost": r.total_cost
                    }
                    for r in results
                ]
        except Exception as e:
            log("error", f"Failed to get daily costs: {e}")
            return []

    def get_monthly_cost(self, provider: Optional[str] = None) -> float:
        """Get total cost for current month."""
        try:
            with self.db.get_session() as session:
                current_month = datetime.utcnow().strftime("%Y-%m")

                query = session.query(
                    func.sum(DailyCostSummaryTable.total_cost)
                ).filter(
                    DailyCostSummaryTable.date.like(f"{current_month}%")
                )

                if provider:
                    query = query.filter(DailyCostSummaryTable.provider == provider)

                total = query.scalar() or 0.0
                return total
        except Exception as e:
            log("error", f"Failed to get monthly cost: {e}")
            return 0.0

    def get_llm_calls(self, user_id: Optional[str] = None,
                     llm_type: Optional[str] = None,
                     conversation_id: Optional[str] = None,
                     model: Optional[str] = None,
                     start_date: Optional[datetime] = None,
                     end_date: Optional[datetime] = None,
                     limit: int = 100,
                     offset: int = 0) -> List[Dict[str, Any]]:
        """Get LLM calls with filters."""
        try:
            with self.db.get_session() as session:
                query = session.query(LLMCallTable)

                if user_id:
                    query = query.filter_by(user_id=user_id)
                if llm_type:
                    query = query.filter_by(llm_type=llm_type)
                if model:
                    query = query.filter_by(model=model)
                if conversation_id:
                    query = query.filter_by(conversation_id=conversation_id)
                if start_date:
                    query = query.filter(LLMCallTable.timestamp >= start_date)
                if end_date:
                    query = query.filter(LLMCallTable.timestamp <= end_date)

                calls = query.order_by(LLMCallTable.timestamp.desc()).limit(limit).offset(offset).all()

                result = []
                for call in calls:
                    # Reconstruct the effective raw_response for callers.
                    # We store NULL when raw == response to save space; restore
                    # the full value here so display code never has to care.
                    stored_raw = call.raw_response
                    effective_raw = stored_raw if stored_raw is not None else call.response

                    result.append({
                        "id": call.id,
                        "user_id": call.user_id,
                        "conversation_id": call.conversation_id,
                        "llm_id": call.llm_id,
                        "llm_type": call.llm_type,
                        "model": call.model,
                        "timestamp": call.timestamp.isoformat() if call.timestamp else None,
                        "duration_ms": call.duration_ms,
                        "input_tokens": call.input_tokens,
                        "output_tokens": call.output_tokens,
                        "total_tokens": call.total_tokens,
                        "input_cost": call.input_cost,
                        "output_cost": call.output_cost,
                        "total_cost": call.total_cost,
                        "messages": call.messages,
                        "context_messages": call.context_messages,
                        "response_preview": call.response[:100] + "..." if len(call.response) > 100 else call.response,
                        "response": call.response,
                        # raw_response is always populated here (never None).
                        # For engines without post-processing it equals response.
                        "raw_response": effective_raw,
                        # True when no_thinking was requested for this call.
                        "no_thinking": bool(call.no_thinking),
                        # True when the model thought despite no_thinking=True.
                        "thinking_detected": bool(call.no_thinking) and stored_raw is not None,
                        "success": bool(call.success),
                        "error_message": call.error_message,
                        "metadata": call.call_metadata or {},
                        "rate_limit_info": call.rate_limit_info or {}
                    })

                return result

        except Exception as e:
            log("error", f"Failed to get LLM calls: {e}")
            return []



    def get_llm_call_for_message(self, conversation_id: str, message_index: int,
                                 message_timestamp: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Resolve the most likely LLM call for one assistant message in a conversation."""
        calls = self.get_llm_calls(conversation_id=conversation_id, limit=200)
        if not calls:
            return None

        target_ts = None
        if message_timestamp:
            try:
                target_ts = datetime.fromisoformat(message_timestamp.replace("Z", "+00:00"))
            except Exception:
                target_ts = None

        if target_ts is not None:
            selected_call = None
            closest_delta = None
            for call in calls:
                call_timestamp = call.get("timestamp")
                if not call_timestamp:
                    continue
                try:
                    call_ts = datetime.fromisoformat(call_timestamp.replace("Z", "+00:00"))
                except Exception:
                    continue
                delta = abs((call_ts - target_ts).total_seconds())
                if closest_delta is None or delta < closest_delta:
                    closest_delta = delta
                    selected_call = call
            if selected_call is not None:
                return selected_call

        assistant_calls = list(reversed(calls))
        if 0 <= message_index < len(assistant_calls):
            return assistant_calls[message_index]

        return None

    def get_total_cost_by_user(self, user_id: str) -> float:
        """Get total cost for a user."""
        try:
            with self.db.get_session() as session:
                result = session.query(
                    func.sum(UserLLMStatsTable.total_cost)
                ).filter_by(user_id=user_id).scalar()
                return result or 0.0
        except Exception as e:
            log("error", f"Failed to get total cost: {e}")
            return 0.0

    def get_last_user_call(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get the last LLM call for a user."""
        try:
            calls = self.get_llm_calls(user_id=user_id, limit=1)
            return calls[0] if calls else None
        except Exception as e:
            log("error", f"Failed to get last user call: {e}")
            return None

    def get_total_calls_count(self) -> int:
        """Get total number of LLM calls in the system."""
        try:
            with self.db.get_session() as session:
                count = session.query(LLMCallTable).count()
                return count
        except Exception as e:
            log("error", f"Failed to get total calls count: {e}")
            return 0

    def clear_user_logs(self, user_id: str) -> int:
        """Clear all LLM logs for a specific user."""
        if not self.enabled:
            return 0

        try:
            with self.db.get_session() as session:
                deleted = session.query(LLMCallTable).filter_by(user_id=user_id).delete()
                session.query(UserLLMStatsTable).filter_by(user_id=user_id).delete()

                if self.rate_limit_tracking.get("track_per_user", False):
                    session.query(RateLimitUsageTable).filter_by(user_id=user_id).delete()

                session.commit()
                log("info", f"Cleared {deleted} LLM calls for user {user_id}")
                return deleted
        except Exception as e:
            log("error", f"Failed to clear user logs: {e}")
            return 0

    def clear_all_logs(self) -> Dict[str, int]:
        """Clear all LLM logs from the system."""
        if not self.enabled:
            return {"llm_calls": 0, "user_stats": 0, "rate_limit_usage": 0, "daily_summary": 0}

        try:
            with self.db.get_session() as session:
                llm_calls_count = session.query(LLMCallTable).count()
                user_stats_count = session.query(UserLLMStatsTable).count()
                rate_limit_count = session.query(RateLimitUsageTable).count()
                daily_summary_count = session.query(DailyCostSummaryTable).count()

                session.query(LLMCallTable).delete()
                session.query(UserLLMStatsTable).delete()
                session.query(RateLimitUsageTable).delete()
                session.query(DailyCostSummaryTable).delete()

                session.commit()

                log("info", f"Cleared all LLM logs: {llm_calls_count} calls, {user_stats_count} user stats")

                return {
                    "llm_calls": llm_calls_count,
                    "user_stats": user_stats_count,
                    "rate_limit_usage": rate_limit_count,
                    "daily_summary": daily_summary_count
                }
        except Exception as e:
            log("error", f"Failed to clear all logs: {e}")
            return {"llm_calls": 0, "user_stats": 0, "rate_limit_usage": 0, "daily_summary": 0}
