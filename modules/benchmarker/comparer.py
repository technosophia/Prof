"""comparer.py — Cross-run comparison and report generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from typing import Dict, List, Optional

import yaml



from modules.benchmarker.benchmarker import BenchmarkRun, BenchmarkScore


from st_shared.cached import get_db_manager
@dataclass
class GroupStats:
    option_value: str
    run_count: int
    assertions_pass_rate: float
    avg_duration_seconds: float
    avg_tokens: float
    score_count: int
    dimension_scores: Dict[str, Optional[float]]
    overall_score: Optional[float]


@dataclass
class ComparisonReport:
    scenario_name: str
    group_by: str
    rubric_name: Optional[str]
    generated_at: str
    groups: List[GroupStats]
    winner: Optional[str]
    delta: Optional[float]


class Comparer:
    """Compare benchmark runs grouped by option values."""

    def compare(self, scenario_name: str, group_by: str = "memory_backend", rubric_name: str = None) -> ComparisonReport:
        with get_db_manager().get_session() as db:
            runs = db.query(BenchmarkRun).filter(BenchmarkRun.scenario_name == scenario_name).all()
            if not runs:
                return ComparisonReport(scenario_name, group_by, rubric_name, self._now(), [], None, None)

            scores = db.query(BenchmarkScore).all()

            grouped: Dict[str, List[BenchmarkRun]] = {}
            for run in runs:
                option_value = (run.options or {}).get(group_by, "<unset>")
                grouped.setdefault(option_value, []).append(run)

            score_by_run: Dict[str, List[BenchmarkScore]] = {}
            for score in scores:
                if rubric_name and score.rubric_name != rubric_name:
                    continue
                if score.run_id:
                    score_by_run.setdefault(score.run_id, []).append(score)

            groups: List[GroupStats] = []
            for option_value, option_runs in grouped.items():
                pass_rates = [self._pass_rate(r) for r in option_runs]
                durations = [float(r.duration_seconds or 0.0) for r in option_runs]
                tokens = [float((r.summary or {}).get("total_tokens", 0)) for r in option_runs]

                attached_scores: List[BenchmarkScore] = []
                for run in option_runs:
                    attached_scores.extend(score_by_run.get(run.id, []))

                dim_keys = sorted({k for s in attached_scores for k in (s.scores or {}).keys()})
                dim_means: Dict[str, Optional[float]] = {}
                for key in dim_keys:
                    vals = [float(s.scores.get(key)) for s in attached_scores if s.scores and s.scores.get(key) is not None]
                    dim_means[key] = (sum(vals) / len(vals)) if vals else None

                overall_vals = [float(s.overall_score) for s in attached_scores if s.overall_score is not None]
                overall_mean = (sum(overall_vals) / len(overall_vals)) if overall_vals else None

                groups.append(
                    GroupStats(
                        option_value=option_value,
                        run_count=len(option_runs),
                        assertions_pass_rate=sum(pass_rates) / len(pass_rates) if pass_rates else 0.0,
                        avg_duration_seconds=sum(durations) / len(durations) if durations else 0.0,
                        avg_tokens=sum(tokens) / len(tokens) if tokens else 0.0,
                        score_count=len(attached_scores),
                        dimension_scores=dim_means,
                        overall_score=overall_mean,
                    )
                )

        winner, delta = self._winner(groups)
        return ComparisonReport(scenario_name, group_by, rubric_name, self._now(), groups, winner, delta)

    def to_yaml(self, report: ComparisonReport) -> str:
        data = {
            "scenario": report.scenario_name,
            "group_by": report.group_by,
            "rubric": report.rubric_name,
            "generated_at": report.generated_at,
            "groups": {},
            "winner": report.winner,
            "delta": report.delta,
        }
        for g in report.groups:
            data["groups"][g.option_value] = {
                "runs": g.run_count,
                "assertions_pass_rate": g.assertions_pass_rate,
                "avg_duration_seconds": g.avg_duration_seconds,
                "avg_tokens": g.avg_tokens,
                "scores": {
                    "runs_scored": g.score_count,
                    **g.dimension_scores,
                    "overall": g.overall_score,
                },
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
    def _winner(groups: List[GroupStats]) -> tuple[Optional[str], Optional[float]]:
        if not groups:
            return None, None
        scored = [g for g in groups if g.overall_score is not None]
        ranked = sorted(scored or groups, key=lambda g: g.overall_score if g.overall_score is not None else g.assertions_pass_rate, reverse=True)
        if not ranked:
            return None, None
        if len(ranked) == 1:
            return ranked[0].option_value, None
        a, b = ranked[0], ranked[1]
        top = a.overall_score if a.overall_score is not None else a.assertions_pass_rate
        second = b.overall_score if b.overall_score is not None else b.assertions_pass_rate
        return a.option_value, top - second

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
