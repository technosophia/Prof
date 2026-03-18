"""
Result Limits Manager for RAG

Handles configurable and dynamic result limits per user, per query, and per context.
"""
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum
import time
from datetime import datetime, timedelta


class ResultLimitContext(Enum):
    """Different contexts where result limits apply"""
    SEARCH = "search"
    CONTEXT_INJECTION = "context_injection"
    SEARCH_TEST = "search_test"
    ADMIN_OVERRIDE = "admin_override"
    USER_PREFERENCE = "user_preference"


@dataclass
class ResultLimitConfig:
    """Configuration for result limits"""
    default: int = 5
    min: int = 1
    max: int = 20
    context_injection: int = 3
    search_test: int = 10
    per_engine: Dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> 'ResultLimitConfig':
        """Create config from dictionary (from config.json)"""
        return cls(
            default=config.get("default", 5),
            min=config.get("min", 1),
            max=config.get("max", 20),
            context_injection=config.get("context_injection", 3),
            search_test=config.get("search_test", 10),
            per_engine=config.get("per_engine", {})
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for saving"""
        return {
            "default": self.default,
            "min": self.min,
            "max": self.max,
            "context_injection": self.context_injection,
            "search_test": self.search_test,
            "per_engine": self.per_engine
        }


class QueryOverride:
    """Temporary override for a specific query"""
    def __init__(self, limit: int, ttl_seconds: int = 300):  # 5 minutes default TTL
        self.limit = limit
        self.created_at = time.time()
        self.ttl_seconds = ttl_seconds

    @property
    def is_expired(self) -> bool:
        """Check if this override has expired"""
        return time.time() - self.created_at > self.ttl_seconds


class ResultLimitManager:
    """
    Manages result limits with multiple override layers:
    1. Global default (lowest priority)
    2. Engine-specific default
    3. User preference (if enabled)
    4. Query-specific override (highest priority)
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        limits_config = config.get("result_limits", {}) if config else {}
        self.config = ResultLimitConfig.from_dict(limits_config)

        # User preferences (could be stored in user manager)
        self._user_preferences: Dict[str, int] = {}

        # Query-specific overrides (temporary)
        self._query_overrides: Dict[str, QueryOverride] = {}

        # Default TTL for query overrides (5 minutes)
        self._query_override_ttl = 300

    def set_user_preference(self, user_id: str, limit: int) -> bool:
        """Set a user's preferred result limit (for normal users)"""
        if self.config.min <= limit <= self.config.max:
            self._user_preferences[user_id] = limit
            return True
        return False

    def get_user_preference(self, user_id: str) -> Optional[int]:
        """Get a user's preferred result limit"""
        return self._user_preferences.get(user_id)

    def clear_user_preference(self, user_id: str) -> None:
        """Clear a user's preference (revert to defaults)"""
        self._user_preferences.pop(user_id, None)

    def set_query_override(self, query_id: str, limit: int, ttl_seconds: Optional[int] = None) -> bool:
        """
        Set a temporary override for a specific query.

        Args:
            query_id: Unique identifier for this query
            limit: Result limit to apply
            ttl_seconds: How long this override should last (default: 5 minutes)

        Returns:
            bool: True if override was set successfully
        """
        if self.config.min <= limit <= self.config.max:
            ttl = ttl_seconds or self._query_override_ttl
            self._query_overrides[query_id] = QueryOverride(limit, ttl)
            self._clean_expired_overrides()
            return True
        return False

    def get_query_override(self, query_id: str) -> Optional[int]:
        """Get the override limit for a query if it exists and is not expired"""
        self._clean_expired_overrides()
        override = self._query_overrides.get(query_id)
        if override and not override.is_expired:
            return override.limit
        return None

    def clear_query_override(self, query_id: str) -> None:
        """Clear a specific query override"""
        self._query_overrides.pop(query_id, None)

    def _clean_expired_overrides(self) -> None:
        """Remove expired query overrides"""
        expired = [qid for qid, override in self._query_overrides.items()
                  if override.is_expired]
        for qid in expired:
            self._query_overrides.pop(qid, None)

    def get_limit(
        self,
        context: ResultLimitContext,
        user_id: Optional[str] = None,
        engine_type: Optional[str] = None,
        query_id: Optional[str] = None,
    ) -> int:
        """
        Get the effective result limit based on context and overrides.

        Priority (highest to lowest):
        1. Query-specific override
        2. User preference
        3. Engine-specific default
        4. Context-specific default
        5. Global default
        """

        # 1. Query override (highest priority)
        if query_id:
            query_limit = self.get_query_override(query_id)
            if query_limit is not None:
                return query_limit

        # 2. User preference
        if user_id and user_id in self._user_preferences:
            return self._user_preferences[user_id]

        # 3. Engine-specific default
        if engine_type and engine_type in self.config.per_engine:
            return self.config.per_engine[engine_type]

        # 4. Context-specific default
        if context == ResultLimitContext.CONTEXT_INJECTION:
            return self.config.context_injection
        elif context == ResultLimitContext.SEARCH_TEST:
            return self.config.search_test

        # 5. Global default
        return self.config.default

    def validate_limit(self, limit: int) -> int:
        """Ensure limit is within configured bounds"""
        return max(self.config.min, min(limit, self.config.max))

    def get_all_user_preferences(self) -> Dict[str, int]:
        """Get all user preferences (for admin view)"""
        return self._user_preferences.copy()

    def get_active_overrides_count(self) -> int:
        """Get number of active query overrides"""
        self._clean_expired_overrides()
        return len(self._query_overrides)

    def update_config(self, new_config: Dict[str, Any]) -> None:
        """Update the configuration dynamically"""
        self.config = ResultLimitConfig.from_dict(new_config)

        # Validate existing preferences against new limits
        users_to_remove = []
        for user_id, limit in self._user_preferences.items():
            if limit < self.config.min or limit > self.config.max:
                users_to_remove.append(user_id)

        for user_id in users_to_remove:
            self._user_preferences.pop(user_id, None)

        # Clean expired overrides
        self._clean_expired_overrides()
