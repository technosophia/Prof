# modules/benchmarker/scorers/base.py
"""Base class and result dataclass for scorer plugins.

Design principles:
- The scorer owns its full workflow, including any UI it needs to display.
- The scorer writes scores to the DB itself via _write_score().
- Scores are always dicts — single values use a one-key dict.
- The benchmarker provides a Streamlit container; the scorer renders into it.
- No workflow type declarations. No return values from compute_score().
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from core.logging import log
from st_shared.cached import get_db_manager
from modules.benchmarker.benchmarker import ScoringRun, BenchmarkRun


@dataclass
class ScoringResult:
    scorer_id: str
    session_path: str
    # Always a dict. Keys are dimension ids, step ids, or any metric names.
    # Single-value scorers use {"score": value} or {"similarity": value}.
    scores: Dict[str, Optional[float]]
    scorer_config: Dict          # rubric name, model, threshold, anything relevant
    source: str                  # free string: "manual", "llm_paste", "embedding", etc.
    notes: Optional[str]
    scored_at: str
    parse_errors: List[str] = field(default_factory=list)
    complete: bool = False

    @property
    def overall(self) -> Optional[float]:
        """Mean of all non-None score values. Computed on the fly."""
        vals = [v for v in self.scores.values() if v is not None]
        return (sum(vals) / len(vals)) if vals else None


class ScorerPlugin(ABC):
    """Base class for all scorer plugins.

    Each scorer:
    - Has a unique string `id` and a human-readable `name`
    - Implements `compute_score()` which owns the full workflow:
        * May render Streamlit UI into the provided container
        * Computes scores (automatically or via user interaction)
        * Calls self._write_score(result) when done
    - Never modifies the session file or dict
    - Never imports from other scorer plugins
    """

    id: str    # unique snake_case, e.g. "manual", "llm_external"
    name: str  # shown in UI scorer selector

    @abstractmethod
    def compute_score(self, session: Dict, config: Dict, container) -> None:
        """Own the full scoring workflow for this session.

        Args:
            session: Full parsed session YAML as a read-only dict.
            config:  Dict of inputs collected by the benchmarker before
                     handing off (currently only {"session_path": str}).
                     The scorer may read extra keys it placed in st.session_state.
            container: A Streamlit container (st.container() or a tab).
                       Render all UI here. Use container.subheader(),
                       container.button(), etc. — not st.* directly.

        The scorer must call self._write_score(result) when it has a result
        to persist. It may call it zero times (user hasn't submitted yet)
        or once (result ready). Never call it more than once per interaction.
        """
        ...

    def is_available(self) -> bool:
        """Return False if required dependencies or credentials are missing.
        Unavailable scorers are shown as disabled in the UI.
        Default: True.
        """
        return True

    def _write_score(self, result: ScoringResult) -> None:
        """Persist a ScoringResult to the scoring_runs table.

        Called by the plugin itself when the score is ready.
        Links the score to its BenchmarkRun via session_file match.
        Logs on error, never raises.
        """
        try:
            with get_db_manager().get_session() as db:
                run = (
                    db.query(BenchmarkRun)
                    .filter(BenchmarkRun.session_file == result.session_path)
                    .order_by(BenchmarkRun.run_at.desc())
                    .first()
                )
                run_id = run.id if run else None
                db.add(ScoringRun(
                    run_id=run_id,
                    session_file=result.session_path,
                    scorer_id=result.scorer_id,
                    scorer_config=result.scorer_config,
                    scores=result.scores,
                    overall_score=result.overall,
                    scored_at=datetime.fromisoformat(
                        result.scored_at.replace("Z", "+00:00")
                    ),
                    source=result.source,
                    notes=result.notes,
                    parse_errors=result.parse_errors,
                ))
            log("info", f"Scorer '{result.scorer_id}' wrote score for {result.session_path}")
        except Exception as exc:
            log("error", f"Scorer '{result.scorer_id}' failed to write score: {exc}", exc_info=True)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _compute_overall(scores: Dict[str, Optional[float]]) -> Optional[float]:
        vals = [v for v in scores.values() if v is not None]
        return (sum(vals) / len(vals)) if vals else None
