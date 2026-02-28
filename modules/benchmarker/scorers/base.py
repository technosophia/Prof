"""Base class and result dataclass for scorer plugins."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional


@dataclass
class ScoringResult:
    scorer_id: str
    session_path: str
    scores: Dict[str, Optional[float]]
    overall: Optional[float]
    scorer_config: Dict
    source: str
    notes: Optional[str]
    scored_at: str
    parse_errors: List[str] = field(default_factory=list)
    complete: bool = False


class ScorerPlugin(ABC):
    """Base class for all scorer plugins.

    Each scorer is an independent, stateless object.
    Scorers must never import Streamlit.
    Scorers must never modify the session file.
    """

    id: str
    name: str

    @abstractmethod
    def score(self, session: Dict, config: Dict) -> ScoringResult:
        """Produce a ScoringResult from a loaded session dict and scorer config."""

    def is_available(self) -> bool:
        """Return False if required dependencies or credentials are missing."""
        return True

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _compute_overall(scores: Dict[str, Optional[float]]) -> Optional[float]:
        vals = [v for v in scores.values() if v is not None]
        return (sum(vals) / len(vals)) if vals else None
