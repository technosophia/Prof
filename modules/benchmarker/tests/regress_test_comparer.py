"""Tests for benchmarker comparer.

TODO : makge regression in modules/benchmarker/tests/test_runner_integration_real_driver.py::test_full_run_real_driver_scenarios[full_nexoria]

"""

from datetime import datetime, timezone

import yaml



from modules.benchmarker.benchmarker import BenchmarkRun, BenchmarkScore, ensure_tables_exist
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


def _add_score(run_id, rubric, overall, dims):
    with get_db_manager().get_session() as db:
        db.add(
            BenchmarkScore(
                run_id=run_id,
                session_file="/tmp/x.yaml",
                rubric_name=rubric,
                scores=dims,
                overall_score=overall,
                judge_llm="mock",
                judge_prompt="prompt",
                source="manual",
                parse_errors=[],
            )
        )


def test_compare_no_runs_returns_empty_groups():
    report = Comparer().compare("none")
    assert report.groups == []


def test_compare_groups_by_option():
    _add_run("s", "memory", 6, 6)
    _add_run("s", "memory", 6, 6)
    _add_run("s", "pedagogical_memory", 6, 6)
    _add_run("s", "pedagogical_memory", 6, 6)
    report = Comparer().compare("s")
    assert len(report.groups) == 2


def test_compare_computes_pass_rate():
    _add_run("s", "memory", 6, 6)
    _add_run("s", "memory", 4, 6)
    report = Comparer().compare("s")
    group = [g for g in report.groups if g.option_value == "memory"][0]
    assert round(group.assertions_pass_rate, 3) == 0.833


def test_compare_includes_scores_when_available():
    run1 = _add_run("s", "memory", 6, 6)
    run2 = _add_run("s", "memory", 6, 6)
    _add_score(run1, "memory_quality", 4.0, {"relevance": 4, "precision": 4})
    _add_score(run2, "memory_quality", 2.0, {"relevance": 2, "precision": 2})
    report = Comparer().compare("s", rubric_name="memory_quality")
    group = [g for g in report.groups if g.option_value == "memory"][0]
    assert group.dimension_scores["relevance"] == 3.0


def test_compare_winner_by_overall_score():
    run1 = _add_run("s", "memory", 6, 6)
    run2 = _add_run("s", "pedagogical_memory", 6, 6)
    _add_score(run1, "memory_quality", 2.0, {"relevance": 2})
    _add_score(run2, "memory_quality", 4.0, {"relevance": 4})
    report = Comparer().compare("s", rubric_name="memory_quality")
    assert report.winner == "pedagogical_memory"


def test_compare_winner_by_pass_rate_when_no_scores():
    _add_run("s", "memory", 3, 6)
    _add_run("s", "pedagogical_memory", 5, 6)
    report = Comparer().compare("s")
    assert report.winner == "pedagogical_memory"


def test_to_yaml_is_valid_yaml():
    _add_run("s", "memory", 6, 6)
    report = Comparer().compare("s")
    rendered = Comparer().to_yaml(report)
    parsed = yaml.safe_load(rendered)
    assert parsed["scenario"] == "s"


def test_save_report_writes_file(tmp_path):
    _add_run("s", "memory", 6, 6)
    report = Comparer().compare("s")
    path = Comparer().save_report(report, str(tmp_path))
    assert (tmp_path / path.split('/')[-1]).exists()
