"""Orchestrates scorer plugins: runs them, persists ScoringRun records, loads results."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

import yaml

from core.logging import log
from modules.benchmarker.benchmarker import BenchmarkRun, ScoringRun
from modules.benchmarker.scorers.base import ScorerPlugin, ScoringResult
from st_shared.cached import get_db_manager


class ScoringPipeline:
    """Pipeline that executes registered scorers against immutable session files."""

    def __init__(self):
        self._registry: Dict[str, ScorerPlugin] = {}

    def register(self, scorer: ScorerPlugin) -> None:
        self._registry[scorer.id] = scorer

    def get_scorer(self, scorer_id: str) -> Optional[ScorerPlugin]:
        return self._registry.get(scorer_id)

    def list_scorers(self) -> List[Dict]:
        return [
            {"id": scorer.id, "name": scorer.name, "available": scorer.is_available()}
            for scorer in self._registry.values()
        ]

    def run(self, session_path: str, scorer_ids: List[str], config: Dict) -> List[ScoringResult]:
        results: List[ScoringResult] = []
        with open(session_path, "r", encoding="utf-8") as handle:
            session = yaml.safe_load(handle) or {}

        for scorer_id in scorer_ids:
            scorer = self._registry.get(scorer_id)
            if scorer is None:
                log("warning", f"Unknown scorer id: {scorer_id}")
                continue
            if not scorer.is_available():
                log("warning", f"Scorer unavailable and skipped: {scorer_id}")
                continue

            try:
                result = scorer.score(session, config)
            except Exception as exc:
                log("error", f"Scorer {scorer_id} failed: {exc}", exc_info=True)
                result = ScoringResult(
                    scorer_id=scorer_id,
                    session_path=session_path,
                    scores={},
                    overall=None,
                    scorer_config=config,
                    source="pipeline",
                    notes=None,
                    scored_at=datetime.utcnow().isoformat() + "Z",
                    parse_errors=[str(exc)],
                    complete=False,
                )

            self.persist_result(session_path, result)
            results.append(result)

        return results

    def persist_result(self, session_path: str, result: ScoringResult) -> None:
        try:
            with get_db_manager().get_session() as db:
                run = (
                    db.query(BenchmarkRun)
                    .filter(BenchmarkRun.session_file == session_path)
                    .order_by(BenchmarkRun.run_at.desc())
                    .first()
                )
                run_id = run.id if run else None
                scored_at_dt = datetime.fromisoformat(result.scored_at.replace("Z", "+00:00"))
                db.add(
                    ScoringRun(
                        run_id=run_id,
                        session_file=session_path,
                        scorer_id=result.scorer_id,
                        scorer_config=result.scorer_config,
                        scores=result.scores,
                        overall_score=result.overall,
                        scored_at=scored_at_dt,
                        source=result.source,
                        notes=result.notes,
                        parse_errors=result.parse_errors,
                    )
                )
        except Exception as exc:
            log("error", f"Failed to persist scoring result for {session_path}: {exc}", exc_info=True)

    def load_results(self, session_path: str) -> List[ScoringResult]:
        with get_db_manager().get_session() as db:
            rows = db.query(ScoringRun).filter(ScoringRun.session_file == session_path).all()
            return [self._row_to_result(r) for r in rows]

    def load_results_for_scenario(self, scenario_name: str, scorer_id: str = None) -> List[ScoringResult]:
        with get_db_manager().get_session() as db:
            query = db.query(ScoringRun).join(BenchmarkRun, ScoringRun.run_id == BenchmarkRun.id)
            query = query.filter(BenchmarkRun.scenario_name == scenario_name)
            if scorer_id:
                query = query.filter(ScoringRun.scorer_id == scorer_id)
            rows = query.all()
            return [self._row_to_result(r) for r in rows]

    @staticmethod
    def _row_to_result(row: ScoringRun) -> ScoringResult:
        return ScoringResult(
            scorer_id=row.scorer_id,
            session_path=row.session_file,
            scores=row.scores or {},
            overall=row.overall_score,
            scorer_config=row.scorer_config or {},
            source=row.source,
            notes=row.notes,
            scored_at=row.scored_at.isoformat().replace("+00:00", "Z") if row.scored_at else "",
            parse_errors=row.parse_errors or [],
            complete=bool((row.parse_errors or []) == []),
        )


_SCORING_PIPELINE: Optional[ScoringPipeline] = None


def get_scoring_pipeline() -> ScoringPipeline:
    """Return singleton scoring pipeline instance."""
    global _SCORING_PIPELINE
    if _SCORING_PIPELINE is None:
        _SCORING_PIPELINE = ScoringPipeline()
    return _SCORING_PIPELINE
