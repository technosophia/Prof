"""Headless benchmark run analysis utilities."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import math
from statistics import mean, stdev
from typing import Dict, List, Optional, Tuple

import yaml

from core.logging import log
from modules.benchmarker.benchmarker import BenchmarkRun, ScoringRun
from modules.benchmarker.scoring_pipeline import get_scoring_pipeline
from st_shared.cached import get_db_manager


@dataclass
class AnalysisRow:
    run_id: str
    scenario_name: str
    session_file: str
    llm_id: str
    memory_backend: str
    rag_engine: str
    success: bool
    assertions_passed: int
    assertions_total: int
    assertions_pass_rate: float
    duration_seconds: float
    total_tokens: int
    is_matrix_run: bool
    scores: Dict[str, Dict[str, float]]
    overall_scores: Dict[str, float]


@dataclass
class AnalysisDataset:
    rows: List[AnalysisRow] = field(default_factory=list)


@dataclass
class MetricStats:
    mean: float
    std: float
    min: float
    max: float
    n: int
    confidence_low: float
    confidence_high: float
    low_confidence: bool = False


@dataclass
class DimensionReport:
    metric_name: str
    scorer_id: Optional[str]
    best_config: str
    worst_config: str
    config_stats: Dict[str, MetricStats]


@dataclass
class PairwiseComparison:
    config_a: str
    config_b: str
    metrics_a_wins: int
    metrics_b_wins: int
    metrics_tied: int
    a_always_better: bool
    b_always_better: bool


@dataclass
class DominanceResult:
    config: str
    dominated_by: Optional[str]
    dominates: List[str]
    rank_by_wins: int


@dataclass
class ConfigComparisonReport:
    pairwise: List[PairwiseComparison]
    dominance: List[DominanceResult]


@dataclass
class AnalysisReport:
    generated_at: str
    n_runs: int
    n_scenarios: int
    configurations: List[str]
    dimensions: List[DimensionReport]
    config_comparison: ConfigComparisonReport
    raw_rows: List[AnalysisRow]


class Analyser:
    """Load benchmark + scoring rows and build aggregate reports."""

    def __init__(self):
        self.pipeline = get_scoring_pipeline()
        self._warned_no_scipy = False

    def load_data(
        self,
        scenario_filter: Optional[List[str]] = None,
        matrix_only: bool = False,
    ) -> AnalysisDataset:
        with get_db_manager().get_session() as db:
            query = db.query(BenchmarkRun)
            if scenario_filter:
                query = query.filter(BenchmarkRun.scenario_name.in_(scenario_filter))
            run_rows_db = query.order_by(BenchmarkRun.run_at.desc()).all()

            run_rows = [
                {
                    "id": str(row.id),
                    "scenario_name": str(row.scenario_name),
                    "session_file": str(row.session_file),
                    "options": dict(row.options or {}),
                    "success": bool(row.success),
                    "assertions_passed": int(row.assertions_passed or 0),
                    "assertions_total": int(row.assertions_total or 0),
                    "duration_seconds": float(row.duration_seconds or 0.0),
                    "summary": dict(row.summary or {}),
                }
                for row in run_rows_db
            ]

            if matrix_only:
                run_rows = [row for row in run_rows if bool((row.get("summary") or {}).get("matrix_run"))]

            run_ids = [row["id"] for row in run_rows]
            scoring_rows_db = db.query(ScoringRun).filter(ScoringRun.run_id.in_(run_ids)).all() if run_ids else []
            scoring_rows = [
                {
                    "run_id": str(score.run_id) if score.run_id else "",
                    "scorer_id": str(score.scorer_id),
                    "scores": dict(score.scores or {}),
                    "overall_score": (float(score.overall_score) if score.overall_score is not None else None),
                }
                for score in scoring_rows_db
            ]

        scores_by_run: Dict[str, List[Dict]] = {}
        for score in scoring_rows:
            if score["run_id"]:
                scores_by_run.setdefault(score["run_id"], []).append(score)

        rows: List[AnalysisRow] = []
        for run in run_rows:
            options = dict(run.get("options") or {})
            scorer_scores: Dict[str, Dict[str, List[float]]] = {}
            scorer_overalls: Dict[str, List[float]] = {}

            for srow in scores_by_run.get(run["id"], []):
                sid = str(srow["scorer_id"])
                scorer_scores.setdefault(sid, {})
                for metric_key, metric_value in (srow.get("scores") or {}).items():
                    if metric_value is None:
                        continue
                    scorer_scores[sid].setdefault(str(metric_key), []).append(float(metric_value))
                if srow.get("overall_score") is not None:
                    scorer_overalls.setdefault(sid, []).append(float(srow["overall_score"]))

            rows.append(
                AnalysisRow(
                    run_id=str(run["id"]),
                    scenario_name=str(run["scenario_name"]),
                    session_file=str(run["session_file"]),
                    llm_id=str(options.get("llm", "") or ""),
                    memory_backend=str(options.get("memory_backend", "") or ""),
                    rag_engine=str(options.get("rag_engine", "") or ""),
                    success=bool(run["success"]),
                    assertions_passed=int(run["assertions_passed"] or 0),
                    assertions_total=int(run["assertions_total"] or 0),
                    assertions_pass_rate=self._safe_rate(run["assertions_passed"], run["assertions_total"]),
                    duration_seconds=float(run["duration_seconds"] or 0.0),
                    total_tokens=int((run.get("summary") or {}).get("total_tokens", 0) or 0),
                    is_matrix_run=bool((run.get("summary") or {}).get("matrix_run")),
                    scores={
                        sid: {m: mean(vals) for m, vals in metrics.items() if vals}
                        for sid, metrics in scorer_scores.items()
                    },
                    overall_scores={sid: mean(vals) for sid, vals in scorer_overalls.items() if vals},
                )
            )

        return AnalysisDataset(rows=rows)

    def analyse(self, dataset: AnalysisDataset) -> AnalysisReport:
        rows = list(dataset.rows)
        configs = sorted({self._config_label(row.llm_id, row.memory_backend, row.rag_engine) for row in rows})

        metric_values: Dict[Tuple[Optional[str], str], Dict[str, List[float]]] = {}
        for metric_name in ["assertions_pass_rate", "duration_seconds", "total_tokens"]:
            metric_values[(None, metric_name)] = {}

        for row in rows:
            config = self._config_label(row.llm_id, row.memory_backend, row.rag_engine)
            metric_values[(None, "assertions_pass_rate")].setdefault(config, []).append(float(row.assertions_pass_rate))
            metric_values[(None, "duration_seconds")].setdefault(config, []).append(float(row.duration_seconds))
            metric_values[(None, "total_tokens")].setdefault(config, []).append(float(row.total_tokens))

            for scorer_id, metrics in row.scores.items():
                for metric_name, metric_value in metrics.items():
                    key = (scorer_id, f"{scorer_id}.{metric_name}")
                    metric_values.setdefault(key, {})
                    metric_values[key].setdefault(config, []).append(float(metric_value))

        dimensions: List[DimensionReport] = []
        for (scorer_id, metric_name), values_by_config in sorted(metric_values.items(), key=lambda x: x[0][1]):
            if not values_by_config:
                continue
            stats_by_config = {config: self._compute_stats(values) for config, values in values_by_config.items()}
            ranked = sorted(stats_by_config.items(), key=lambda item: item[1].mean, reverse=True)
            dimensions.append(
                DimensionReport(
                    metric_name=metric_name,
                    scorer_id=scorer_id,
                    best_config=ranked[0][0],
                    worst_config=ranked[-1][0],
                    config_stats=stats_by_config,
                )
            )

        config_comparison = self._build_config_comparison(rows, configs, dimensions)

        return AnalysisReport(
            generated_at=self._now(),
            n_runs=len(rows),
            n_scenarios=len({row.scenario_name for row in rows}),
            configurations=configs,
            dimensions=dimensions,
            config_comparison=config_comparison,
            raw_rows=rows,
        )

    def to_yaml(self, report: AnalysisReport) -> str:
        data = {
            "generated_at": report.generated_at,
            "n_runs": report.n_runs,
            "n_scenarios": report.n_scenarios,
            "configurations": report.configurations,
            "dimensions": [self._dimension_to_dict(item) for item in report.dimensions],
            "config_comparison": {
                "pairwise": [asdict(item) for item in report.config_comparison.pairwise],
                "dominance": [asdict(item) for item in report.config_comparison.dominance],
            },
        }
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)

    def _build_config_comparison(
        self,
        rows: List[AnalysisRow],
        configs: List[str],
        dimensions: List[DimensionReport],
    ) -> ConfigComparisonReport:
        metric_lookup: Dict[str, Dict[str, float]] = {
            dimension.metric_name: {config: stat.mean for config, stat in dimension.config_stats.items()}
            for dimension in dimensions
        }

        pairwise: List[PairwiseComparison] = []
        total_wins: Dict[str, int] = {config: 0 for config in configs}

        for i, config_a in enumerate(configs):
            for config_b in configs[i + 1 :]:
                a_wins = 0
                b_wins = 0
                tied = 0
                for metric_name, means in metric_lookup.items():
                    a_mean = means.get(config_a)
                    b_mean = means.get(config_b)
                    if a_mean is None or b_mean is None:
                        continue
                    if a_mean > b_mean:
                        a_wins += 1
                    elif b_mean > a_mean:
                        b_wins += 1
                    else:
                        tied += 1

                total_wins[config_a] += a_wins
                total_wins[config_b] += b_wins

                a_always = self._always_better(rows, config_a, config_b, dimensions)
                b_always = self._always_better(rows, config_b, config_a, dimensions)
                pairwise.append(
                    PairwiseComparison(
                        config_a=config_a,
                        config_b=config_b,
                        metrics_a_wins=a_wins,
                        metrics_b_wins=b_wins,
                        metrics_tied=tied,
                        a_always_better=a_always,
                        b_always_better=b_always,
                    )
                )

        sorted_by_wins = sorted(total_wins.items(), key=lambda item: item[1], reverse=True)
        rank_by_config = {}
        rank = 1
        for idx, (config, wins) in enumerate(sorted_by_wins):
            if idx > 0 and wins < sorted_by_wins[idx - 1][1]:
                rank = idx + 1
            rank_by_config[config] = rank

        dominance: List[DominanceResult] = []
        for config in configs:
            dominates = [other for other in configs if other != config and self._dominates_means(config, other, metric_lookup)]
            dominated_candidates = [other for other in configs if other != config and self._dominates_means(other, config, metric_lookup)]
            dominance.append(
                DominanceResult(
                    config=config,
                    dominated_by=sorted(dominated_candidates)[0] if dominated_candidates else None,
                    dominates=sorted(dominates),
                    rank_by_wins=rank_by_config.get(config, len(configs) or 1),
                )
            )

        dominance.sort(key=lambda item: (item.rank_by_wins, item.config))
        return ConfigComparisonReport(pairwise=pairwise, dominance=dominance)

    def _always_better(
        self,
        rows: List[AnalysisRow],
        config_a: str,
        config_b: str,
        dimensions: List[DimensionReport],
    ) -> bool:
        by_scenario_a = {}
        by_scenario_b = {}
        for row in rows:
            config = self._config_label(row.llm_id, row.memory_backend, row.rag_engine)
            if config == config_a:
                by_scenario_a.setdefault(row.scenario_name, []).append(row)
            elif config == config_b:
                by_scenario_b.setdefault(row.scenario_name, []).append(row)

        shared_scenarios = sorted(set(by_scenario_a.keys()) & set(by_scenario_b.keys()))
        if not shared_scenarios:
            return False

        for dimension in dimensions:
            metric = dimension.metric_name
            for scenario_name in shared_scenarios:
                a_values = self._metric_values_for_rows(by_scenario_a[scenario_name], metric)
                b_values = self._metric_values_for_rows(by_scenario_b[scenario_name], metric)
                if not a_values or not b_values:
                    return False
                for value_a in a_values:
                    for value_b in b_values:
                        if value_a <= value_b:
                            return False
        return True

    def _metric_values_for_rows(self, rows: List[AnalysisRow], metric_name: str) -> List[float]:
        values = []
        for row in rows:
            if metric_name == "assertions_pass_rate":
                values.append(float(row.assertions_pass_rate))
            elif metric_name == "duration_seconds":
                values.append(float(row.duration_seconds))
            elif metric_name == "total_tokens":
                values.append(float(row.total_tokens))
            elif "." in metric_name:
                scorer_id, inner_metric = metric_name.split(".", 1)
                score = row.scores.get(scorer_id, {}).get(inner_metric)
                if score is not None:
                    values.append(float(score))
        return values

    @staticmethod
    def _dominates_means(config_a: str, config_b: str, metric_lookup: Dict[str, Dict[str, float]]) -> bool:
        saw_metric = False
        for _metric_name, means in metric_lookup.items():
            a_mean = means.get(config_a)
            b_mean = means.get(config_b)
            if a_mean is None or b_mean is None:
                return False
            saw_metric = True
            if a_mean <= b_mean:
                return False
        return saw_metric

    def _compute_stats(self, values: List[float]) -> MetricStats:
        n = len(values)
        metric_mean = mean(values)
        metric_std = stdev(values) if n > 1 else 0.0
        stderr = metric_std / math.sqrt(n) if n > 0 else 0.0

        if n == 1:
            conf_low = metric_mean
            conf_high = metric_mean
        elif stderr == 0:
            conf_low = metric_mean
            conf_high = metric_mean
        else:
            conf_low, conf_high = self._confidence_interval(metric_mean, metric_std, n)

        return MetricStats(
            mean=metric_mean,
            std=metric_std,
            min=min(values),
            max=max(values),
            n=n,
            confidence_low=conf_low,
            confidence_high=conf_high,
            low_confidence=n < 3,
        )

    def _confidence_interval(self, metric_mean: float, metric_std: float, n: int) -> Tuple[float, float]:
        stderr = metric_std / math.sqrt(n)
        try:
            from scipy import stats  # type: ignore

            low, high = stats.t.interval(0.95, df=n - 1, loc=metric_mean, scale=stderr)
            return float(low), float(high)
        except Exception:
            if not self._warned_no_scipy:
                self._warned_no_scipy = True
                log("warning", "scipy is unavailable, using normal approximation for confidence intervals")
            margin = 1.96 * stderr
            return metric_mean - margin, metric_mean + margin

    @staticmethod
    def _safe_rate(passed: int, total: int) -> float:
        total_i = int(total or 0)
        return (float(passed or 0) / total_i) if total_i else 0.0

    @staticmethod
    def _config_label(llm_id: str, memory_backend: str, rag_engine: str) -> str:
        return f"{llm_id or '-'} / {memory_backend or '-'} / {rag_engine or '-'}"

    @staticmethod
    def _dimension_to_dict(item: DimensionReport) -> Dict:
        return {
            "metric_name": item.metric_name,
            "scorer_id": item.scorer_id,
            "best_config": item.best_config,
            "worst_config": item.worst_config,
            "config_stats": {
                config: asdict(stats)
                for config, stats in item.config_stats.items()
            },
        }

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
