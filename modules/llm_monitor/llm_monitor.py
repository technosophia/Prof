"""
LLM Monitoring and Cost Tracking Core Module
"""
import asyncio
import json
import time
from datetime import datetime
from typing import Dict, List, Any, Optional, Callable
import tiktoken  # For token estimation
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from shared.common import get_db_manager, Base
from shared.common import log
from shared.common import get_config
from shared.common import get_user_manager
from shared.common import get_conversation_manager

# Import models
from modules.llm_monitor.models import LLMCallTable, UserLLMStatsTable


class LLMMonitor:
    """Main class for monitoring LLM usage and costs."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized'):
            self.config = get_config().get("llm_monitor", {})
            self.db = get_db_manager()
            self._ensure_tables_exist()
            self.cost_config = self.config.get("costs", {})
            self.enabled = self.config.get("enabled", True)
            self.auto_collect = self.config.get("auto_collect", True)
            self._token_encoder_cache = {}
            self._initialized = True
            log("info", "LLMMonitor initialized")

    def _ensure_tables_exist(self):
        """Ensure monitoring tables exist."""
        if not self.db.is_initialized():
            return False

        try:
            LLMCallTable.__table__.create(bind=self.db._engine, checkfirst=True)
            UserLLMStatsTable.__table__.create(bind=self.db._engine, checkfirst=True)
            log("debug", "LLM monitor tables ensured")
            return True
        except Exception as e:
            log("error", f"Failed to create LLM monitor tables: {e}")
            return False

    def _get_token_encoder(self, model: str):
        """Get token encoder for a model."""
        # Simple model to encoder mapping
        model_to_encoder = {
            "gpt-3.5": "cl100k_base",
            "gpt-4": "cl100k_base",
            "llama": "cl100k_base",  # Llama models use similar tokenization
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

        # Fallback: rough estimate (4 chars per token)
        return len(text) // 4

    def estimate_message_tokens(self, messages: List[Dict[str, str]], model: str) -> int:
        """Estimate total tokens for a list of messages."""
        total_tokens = 0

        # Format similar to OpenAI's API
        tokens_per_message = 3  # Every message follows <|start|>{role/name}\n{content}<|end|>\n
        tokens_per_name = 1     # If there's a name, the role is omitted

        for message in messages:
            total_tokens += tokens_per_message
            content = message.get("content", "")
            total_tokens += self.estimate_tokens(content, model)

            # Add tokens for role
            total_tokens += self.estimate_tokens(message.get("role", ""), model)

            # Add tokens for name if present
            if "name" in message:
                total_tokens += tokens_per_name
                total_tokens += self.estimate_tokens(message["name"], model)

        # Add tokens for the final assistant prompt
        total_tokens += 3  # For the final assistant message

        return total_tokens

    def calculate_cost(self, llm_type: str, input_tokens: int, output_tokens: int) -> Dict[str, float]:
        """Calculate cost based on token usage."""
        costs = self.cost_config.get(llm_type, {})

        input_cost_per_million = costs.get("input_cost_per_million_tokens", 0)
        output_cost_per_million = costs.get("output_cost_per_million_tokens", 0)

        input_cost = (input_tokens / 1_000_000) * input_cost_per_million
        output_cost = (output_tokens / 1_000_000) * output_cost_per_million
        total_cost = input_cost + output_cost

        return {
            "input_cost": input_cost,
            "output_cost": output_cost,
            "total_cost": total_cost
        }

    def extract_context_messages(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Extract context messages (system messages and LLM callbacks) from conversation."""
        context_messages = []

        for msg in messages:
            if msg.get("role") == "system":
                context_messages.append(msg.copy())
            # You can add more conditions here for other context types

        return context_messages

    def extract_user_assistant_messages(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Extract only user and assistant messages (for display)."""
        display_messages = []

        for msg in messages:
            if msg.get("role") in ["user", "assistant"]:
                display_messages.append(msg.copy())

        return display_messages

    def log_llm_call(self, data: Dict[str, Any]):
        """Log an LLM call to the database."""
        if not self.enabled or not self.auto_collect:
            return

        try:
            with self.db.get_session() as session:
                # Extract user_id from conversation if available
                user_id = data.get("user_id")
                conversation_id = data.get("conversation_id")

                if conversation_id and not user_id:
                    # Try to get user_id from conversation
                    try:
                        conv_manager = get_conversation_manager()
                        conversation = conv_manager.get_conversation(conversation_id, include_messages=False)
                        if conversation:
                            user_id = conversation.user_id
                    except:
                        pass

                # Estimate tokens
                input_tokens = data.get("input_tokens")
                output_tokens = data.get("output_tokens")

                if input_tokens is None:
                    input_tokens = self.estimate_message_tokens(data["messages"], data["model"])

                if output_tokens is None and "response" in data:
                    output_tokens = self.estimate_tokens(data["response"], data["model"])

                total_tokens = (input_tokens or 0) + (output_tokens or 0)

                # Calculate costs
                costs = self.calculate_cost(data["llm_type"], input_tokens or 0, output_tokens or 0)

                # Extract context messages
                all_messages = data["messages"]
                context_messages = self.extract_context_messages(all_messages)
                display_messages = self.extract_user_assistant_messages(all_messages)

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
                                    messages=display_messages,  # Store only user/assistant messages for display
                                    context_messages=context_messages,  # Store context separately
                                    response=data["response"],
                                    success=data.get("success", 1),
                                    error_message=data.get("error"),
                                    call_metadata=data.get("metadata", {})  # Changed from metadata to call_metadata
                                )

                session.add(llm_call)

                # Update user stats
                if user_id:
                    self._update_user_stats(session, user_id, data["llm_type"],
                                          input_tokens or 0, output_tokens or 0,
                                          costs["total_cost"])

                log("debug", f"Logged LLM call: {data['llm_id']} for user {user_id}")

        except Exception as e:
            log("error", f"Failed to log LLM call: {e}", exc_info=True)

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

    def get_llm_calls(self, user_id: Optional[str] = None,
                     llm_type: Optional[str] = None,
                     conversation_id: Optional[str] = None,
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

                if conversation_id:
                    query = query.filter_by(conversation_id=conversation_id)

                calls = query.order_by(LLMCallTable.timestamp.desc()).limit(limit).offset(offset).all()

                result = []
                for call in calls:
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
                        "messages": call.messages,  # User/assistant messages only
                        "context_messages": call.context_messages,  # Context messages
                        "response_preview": call.response[:100] + "..." if len(call.response) > 100 else call.response,
                        "response": call.response,
                        "success": bool(call.success),
                        "error_message": call.error_message,
                        "metadata": call.call_metadata or {}  # Changed from call.metadata to call.call_metadata
                    })

                return result

        except Exception as e:
            log("error", f"Failed to get LLM calls: {e}")
            return []

    def get_total_cost_by_user(self, user_id: str) -> float:
        """Get total cost for a user."""
        try:
            with self.db.get_session() as session:
                result = session.query(
                    UserLLMStatsTable.total_cost
                ).filter_by(user_id=user_id).all()

                total = sum(row[0] for row in result)
                return total
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
                count = session.query(LLMCallTable).count()  # Use the table class
                return count
        except Exception as e:
            log("error", f"Failed to get total calls count: {e}")
            return 0


def get_llm_monitor():
    """Get the LLM monitor instance."""
    return LLMMonitor()
