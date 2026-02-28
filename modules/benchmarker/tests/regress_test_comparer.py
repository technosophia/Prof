"""Tests for benchmarker comparer."""

from datetime import datetime, timezone

from modules.benchmarker.benchmarker import BenchmarkRun, ScoringRun, ensure_tables_exist
from modules.benchmarker.comparer import Comparer

from core.database import init_database
from st_shared.cached import get_db_manager


def setup_function(_):
    init_database(use_memory=True)
    ensure_tables_exist()
    get_db_manager().empty_all_tables()


def _add_run(scenario, opt, passed, total, duration=1.0, tokens=10):
    with get_db_manager().get_session() as db:
        run = BenchmarkRun(
            scenario_name=scenario,
            run_at=datetime.now(timezone.utc),
            options={"memory_backend": opt},
            assertions_passed=passed,
            assertions_total=total,
            duration_seconds=duration,
            summary={"total_tokens": tokens},
            success=1,
            errors=[],
            session_file=f"/tmp/{scenario}-{opt}-{passed}.yaml",
        )
        db.add(run)
        db.flush()
        return run.id


def _add_score(run_id, scorer_id, overall, dims):
    with get_db_manager().get_session() as db:
        db.add(
            ScoringRun(
                run_id=run_id,
                session_file="/tmp/x.yaml",
                scorer_id=scorer_id,
                scorer_config={},
                scores=dims,
                overall_score=overall,
                source="manual",
                notes=None,
                parse_errors=[],
            )
        )


def test_compare_no_runs_returns_empty_groups():
    report = Comparer().compare("none")
    assert report.groups == []


def test_compare_groups_by_option():
    _add_run("s", "memory", 6, 6)
    _add_run("s", "pedagogical_memory", 6, 6)
    report = Comparer().compare("s")
    assert len(report.groups) == 2


def test_compare_includes_scores_matrix_with_empty_slots():
    run_memory = _add_run("s", "memory", 6, 6)
    run_ped = _add_run("s", "pedagogical_memory", 6, 6)
    _add_score(run_memory, "manual", 4.0, {"relevance": 4})
    _add_score(run_ped, "embedding_similarity", 0.8, {"s1": 0.8})

    report = Comparer().compare("s")
    as_yaml = Comparer().to_yaml(report)

    assert "manual" in as_yaml
    assert "embedding_similarity" in as_yaml
    assert "runs_scored: 0" in as_yaml


def test_compare_filters_by_scorer_id():
    run_id = _add_run("s", "memory", 6, 6)
    _add_score(run_id, "manual", 4.0, {"relevance": 4})
    _add_score(run_id, "embedding_similarity", 0.9, {"s1": 0.9})
    report = Comparer().compare("s", scorer_id="manual")
    group = [g for g in report.groups if g.option_value == "memory"][0]
    assert list(group.scoring.keys()) == ["manual"]
