"""comparer.py — Cross-run comparison and report generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from typing import Dict, List, Optional

import yaml

from modules.benchmarker.benchmarker import BenchmarkRun, ScoringRun

from st_shared.cached import get_db_manager


@dataclass
class ScorerStats:
    runs_scored: int
    dimensions: Dict[str, Optional[float]] = field(default_factory=dict)
    overall: Optional[float] = None


@dataclass
class GroupStats:
    option_value: str
    run_count: int
    assertions_pass_rate: float
    avg_duration_seconds: float
    avg_tokens: float
    scorer_ids: List[str]
    scoring: Dict[str, ScorerStats]


@dataclass
class ComparisonReport:
    scenario_name: str
    group_by: str
    scorer_id: Optional[str]
    generated_at: str
    groups: List[GroupStats]


class Comparer:
    """Compare benchmark runs grouped by option values."""

    def compare(self, scenario_name: str, group_by: str = "memory_backend", scorer_id: str = None) -> ComparisonReport:
        with get_db_manager().get_session() as db:
            runs = db.query(BenchmarkRun).filter(BenchmarkRun.scenario_name == scenario_name).all()
            if not runs:
                return ComparisonReport(scenario_name, group_by, scorer_id, self._now(), [])

            run_ids = [run.id for run in runs]
            score_query = db.query(ScoringRun).filter(ScoringRun.run_id.in_(run_ids))
            if scorer_id:
                score_query = score_query.filter(ScoringRun.scorer_id == scorer_id)
            scores = score_query.all()

            global_scorer_ids = sorted({score.scorer_id for score in scores})
            grouped: Dict[str, List[BenchmarkRun]] = {}
            for run in runs:
                option_value = (run.options or {}).get(group_by, "<unset>")
                grouped.setdefault(option_value, []).append(run)

            score_by_run: Dict[str, List[ScoringRun]] = {}
            for score in scores:
                if score.run_id:
                    score_by_run.setdefault(score.run_id, []).append(score)

            groups: List[GroupStats] = []
            for option_value, option_runs in grouped.items():
                pass_rates = [self._pass_rate(r) for r in option_runs]
                durations = [float(r.duration_seconds or 0.0) for r in option_runs]
                tokens = [float((r.summary or {}).get("total_tokens", 0)) for r in option_runs]

                attached_scores: List[ScoringRun] = []
                for run in option_runs:
                    attached_scores.extend(score_by_run.get(run.id, []))

                group_scorer_ids = sorted({score.scorer_id for score in attached_scores})
                all_scorer_ids = sorted(set(global_scorer_ids) | set(group_scorer_ids))
                scoring: Dict[str, ScorerStats] = {}

                for scorer_name in all_scorer_ids:
                    scorer_scores = [score for score in attached_scores if score.scorer_id == scorer_name]
                    dim_keys = sorted({k for s in scorer_scores for k in (s.scores or {}).keys()})
                    dim_means: Dict[str, Optional[float]] = {}
                    for key in dim_keys:
                        vals = [float(s.scores.get(key)) for s in scorer_scores if s.scores and s.scores.get(key) is not None]
                        dim_means[key] = (sum(vals) / len(vals)) if vals else None

                    overall_vals = [float(s.overall_score) for s in scorer_scores if s.overall_score is not None]
                    overall_mean = (sum(overall_vals) / len(overall_vals)) if overall_vals else None
                    scoring[scorer_name] = ScorerStats(
                        runs_scored=len(scorer_scores),
                        dimensions=dim_means,
                        overall=overall_mean,
                    )

                groups.append(
                    GroupStats(
                        option_value=option_value,
                        run_count=len(option_runs),
                        assertions_pass_rate=sum(pass_rates) / len(pass_rates) if pass_rates else 0.0,
                        avg_duration_seconds=sum(durations) / len(durations) if durations else 0.0,
                        avg_tokens=sum(tokens) / len(tokens) if tokens else 0.0,
                        scorer_ids=all_scorer_ids,
                        scoring=scoring,
                    )
                )

        return ComparisonReport(scenario_name, group_by, scorer_id, self._now(), groups)

    def to_yaml(self, report: ComparisonReport) -> str:
        data = {
            "scenario": report.scenario_name,
            "group_by": report.group_by,
            "scorer_id": report.scorer_id,
            "generated_at": report.generated_at,
            "groups": {},
        }
        all_scorer_ids = sorted({scorer_id for g in report.groups for scorer_id in g.scorer_ids})

        for g in report.groups:
            group_scoring = {}
            for scorer_name in all_scorer_ids:
                scorer_stats = g.scoring.get(scorer_name, ScorerStats(runs_scored=0, dimensions={}, overall=None))
                group_scoring[scorer_name] = {
                    "runs_scored": scorer_stats.runs_scored,
                    "dimensions": scorer_stats.dimensions,
                    "overall": scorer_stats.overall,
                }

            data["groups"][g.option_value] = {
                "runs": g.run_count,
                "assertions_pass_rate": g.assertions_pass_rate,
                "avg_duration_seconds": g.avg_duration_seconds,
                "avg_tokens": g.avg_tokens,
                "scoring": group_scoring,
            }
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)

    def save_report(self, report: ComparisonReport, output_dir: str) -> str:
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe = report.scenario_name.replace(" ", "_")
        path = os.path.join(output_dir, f"compare__{safe}__{report.group_by}__{ts}.yaml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self.to_yaml(report))
        return path

    @staticmethod
    def _pass_rate(run: BenchmarkRun) -> float:
        total = int(run.assertions_total or 0)
        passed = int(run.assertions_passed or 0)
        return (passed / total) if total else 0.0

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
