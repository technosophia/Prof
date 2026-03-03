"""Scorer auto-discovery and score result loaders."""

from __future__ import annotations

import importlib
import os
import pkgutil
from typing import Dict, List, Optional

from core.logging import log
from modules.benchmarker.benchmarker import BenchmarkRun, ScoringRun
from modules.benchmarker.scorers.base import ScoringResult


def _do_build_registry() -> Dict[str, object]:
    """Discover and instantiate all scorer plugins. Pure function, no cache dependency."""
    import modules.benchmarker.scorers as scorers_pkg

    registry: Dict[str, object] = {}
    scorers_dir = os.path.dirname(scorers_pkg.__file__)

    for _finder, module_name, _ in pkgutil.iter_modules([scorers_dir]):
        if not module_name.startswith("scorer_"):
            continue
        full_name = f"modules.benchmarker.scorers.{module_name}"
        try:
            module = importlib.import_module(full_name)
            cls = getattr(module, "ScorerPlugin", None)
            if cls is None:
                log("warning", f"Scorer module {module_name} has no ScorerPlugin class — skipped")
                continue
            instance = cls()
            registry[instance.id] = instance
            log("info", f"Scorer registered: {instance.id} ({instance.name})")
        except Exception as exc:
            log("warning", f"Failed to load scorer module {module_name}: {exc}", stacktrace=True)

    return registry


class ScoringPipeline:
    """Discovers scorer plugins and provides result-loading helpers."""

    def __init__(self, db_manager=None, cache_fn=None):
        if db_manager is None:
            from shared.common import _get_service

            db_manager = _get_service("db_manager")
        if db_manager is None:
            raise RuntimeError("benchmarker: 'db_manager' service not available")
        self._db_manager = db_manager
        build = cache_fn(_do_build_registry) if cache_fn else _do_build_registry
        self._registry = build()

    def get_scorer(self, scorer_id: str):
        return self._registry.get(scorer_id)

    def list_scorers(self) -> List[Dict]:
        return [
            {"id": scorer.id, "name": scorer.name, "available": scorer.is_available()}
            for scorer in self._registry.values()
        ]

    def load_results(self, session_path: str) -> List[ScoringResult]:
        with self._db_manager.get_session() as db:
            rows = db.query(ScoringRun).filter(ScoringRun.session_file == session_path).all()
            return [self._row_to_result(row) for row in rows]

    def load_results_for_scenario(self, scenario_name: str, scorer_id: str = None) -> List[ScoringResult]:
        with self._db_manager.get_session() as db:
            query = db.query(ScoringRun).join(BenchmarkRun, ScoringRun.run_id == BenchmarkRun.id)
            query = query.filter(BenchmarkRun.scenario_name == scenario_name)
            if scorer_id:
                query = query.filter(ScoringRun.scorer_id == scorer_id)
            rows = query.all()
            return [self._row_to_result(row) for row in rows]

    @staticmethod
    def _row_to_result(row: ScoringRun) -> ScoringResult:
        return ScoringResult(
            scorer_id=row.scorer_id,
            session_path=row.session_file,
            scores=row.scores or {},
            scorer_config=row.scorer_config or {},
            source=row.source,
            notes=row.notes,
            scored_at=row.scored_at.isoformat().replace("+00:00", "Z") if row.scored_at else "",
            parse_errors=row.parse_errors or [],
            complete=not (row.parse_errors or []),
        )


_SCORING_PIPELINE: Optional[ScoringPipeline] = None


def configure_scoring_pipeline(db_manager, cache_fn=None) -> None:
    """Configure singleton dependencies from module activation."""
    global _SCORING_PIPELINE
    _SCORING_PIPELINE = ScoringPipeline(db_manager=db_manager, cache_fn=cache_fn)


def get_scoring_pipeline() -> ScoringPipeline:
    if _SCORING_PIPELINE is None:
        raise RuntimeError("benchmarker: scoring pipeline is not configured; activate module first")
    return _SCORING_PIPELINE
