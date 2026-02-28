"""Cross-run comparison and report generation for benchmarker."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from typing import Dict, List, Optional

import yaml

from modules.benchmarker.benchmarker import BenchmarkRun, ScoringRun
from modules.benchmarker.scoring_pipeline import get_scoring_pipeline
from st_shared.cached import get_db_manager


@dataclass
class GroupStats:
    option_value: str
    run_count: int
    assertions_pass_rate: float
    avg_duration_seconds: float
    avg_tokens: float
    scoring: Dict[str, Dict]


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
            scores_query = db.query(ScoringRun).filter(ScoringRun.run_id.in_(run_ids))
            if scorer_id:
                scores_query = scores_query.filter(ScoringRun.scorer_id == scorer_id)
            scores = scores_query.all()

            known_scorer_ids = [item["id"] for item in get_scoring_pipeline().list_scorers()]
            if scorer_id:
                known_scorer_ids = [sid for sid in known_scorer_ids if sid == scorer_id]
            if not known_scorer_ids:
                known_scorer_ids = sorted({score.scorer_id for score in scores})

            grouped_runs: Dict[str, List[BenchmarkRun]] = {}
            for run in runs:
                option_value = (run.options or {}).get(group_by, "<unset>")
                grouped_runs.setdefault(option_value, []).append(run)

            score_by_run: Dict[str, List[ScoringRun]] = {}
            for score in scores:
                if score.run_id:
                    score_by_run.setdefault(score.run_id, []).append(score)

            groups: List[GroupStats] = []
            for option_value, option_runs in grouped_runs.items():
                attached_scores: List[ScoringRun] = []
                for run in option_runs:
                    attached_scores.extend(score_by_run.get(run.id, []))

                scoring: Dict[str, Dict] = {}
                for sid in known_scorer_ids:
                    scorer_rows = [row for row in attached_scores if row.scorer_id == sid]
                    if not scorer_rows:
                        scoring[sid] = {"runs_scored": 0, "scores": {}, "overall": None}
                        continue

                    score_keys = sorted({k for row in scorer_rows for k in (row.scores or {}).keys()})
                    averaged_scores: Dict[str, Optional[float]] = {}
                    for key in score_keys:
                        values = [
                            float((row.scores or {}).get(key))
                            for row in scorer_rows
                            if (row.scores or {}).get(key) is not None
                        ]
                        averaged_scores[key] = (sum(values) / len(values)) if values else None

                    overall_values = [float(row.overall_score) for row in scorer_rows if row.overall_score is not None]
                    scoring[sid] = {
                        "runs_scored": len(scorer_rows),
                        "scores": averaged_scores,
                        "overall": (sum(overall_values) / len(overall_values)) if overall_values else None,
                    }

                pass_rates = [self._pass_rate(run) for run in option_runs]
                durations = [float(run.duration_seconds or 0.0) for run in option_runs]
                tokens = [float((run.summary or {}).get("total_tokens", 0)) for run in option_runs]

                groups.append(
                    GroupStats(
                        option_value=option_value,
                        run_count=len(option_runs),
                        assertions_pass_rate=(sum(pass_rates) / len(pass_rates)) if pass_rates else 0.0,
                        avg_duration_seconds=(sum(durations) / len(durations)) if durations else 0.0,
                        avg_tokens=(sum(tokens) / len(tokens)) if tokens else 0.0,
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
        for group in report.groups:
            data["groups"][group.option_value] = {
                "runs": group.run_count,
                "assertions_pass_rate": group.assertions_pass_rate,
                "avg_duration_seconds": group.avg_duration_seconds,
                "avg_tokens": group.avg_tokens,
                "scoring": group.scoring,
            }
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)

    def save_report(self, report: ComparisonReport, output_dir: str) -> str:
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_name = report.scenario_name.replace(" ", "_")
        path = os.path.join(output_dir, f"compare__{safe_name}__{report.group_by}__{ts}.yaml")
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
