"""Integration tests for benchmarker runner with real driver and real LLM."""

from __future__ import annotations

from pathlib import Path

import pytest

from modules.benchmarker.runner import ScenarioRunner
from modules.rag_manager import rag_manager
from shared.cached import get_config, get_db_manager
from shared.common import get_user_manager, log


SCENARIOS = [
    Path("modules/benchmarker/scenarios/example_basic.yaml"),
    Path("modules/benchmarker/scenarios/full_nexoria.yaml"),
]
NEXORIA_DOC = Path("modules/benchmarker/tests/nexoria.md")


def _assert_database_ready() -> None:
    db_cfg = get_config().get("database", {})
    db_url_or_path = db_cfg.get("url") or db_cfg.get("path", "")

    if db_url_or_path.startswith("sqlite:///"):
        db_file = db_url_or_path.removeprefix("sqlite:///")
    else:
        db_file = db_url_or_path

    assert db_file, "Database path must be configured for integration tests"
    assert Path(db_file).exists(), f"Database file does not exist: {db_file}"

    # Do not initialize DB here: the environment must already provide a ready DB session.
    assert get_db_manager().is_initialized(), (
        "Database manager is not initialized in this process. "
        "This test expects the test harness to initialize it before execution."
    )


def _trainer_user_id_from_scenario(runner: ScenarioRunner, scenario_path: Path) -> str:
    scenario = runner._load_scenario(str(scenario_path))
    trainer_name = scenario.get("setup", {}).get("trainer_id")
    if not trainer_name:
        pytest.skip(f"No trainer_id in setup for {scenario_path}")

    trainer = get_user_manager().get_user(trainer_name)
    assert trainer is not None, f"Trainer '{trainer_name}' not found for {scenario_path}"

    return trainer["id"]


def _preload_nexoria_rag(owner_user_id: str) -> None:
    filename = rag_manager.upload_document(
        source_path=str(NEXORIA_DOC),
        original_filename="nexoria.md",
        user_id=owner_user_id,
        is_public=False,
    )
    if not filename:
        pytest.skip("RAG document upload failed in this environment")

    indexed = rag_manager.index_document(filename, "classic", owner_user_id)
    if not indexed:
        pytest.skip("Classic RAG indexing unavailable (embedding model/service not ready)")


def _assert_full_success(runner: ScenarioRunner, scenario_path: Path):
    scenario = runner._load_scenario(str(scenario_path))
    result = runner.run(str(scenario_path))

    log(
        "info",
        (
            "Benchmarker integration result "
            f"scenario={scenario.get('meta', {}).get('name', scenario_path.name)} "
            f"success={result.success} "
            f"assertions={result.assertions_passed}/{result.assertions_total} "
            f"errors={result.errors}"
        ),
    )

    scenario_assertions = scenario.get("assertions", [])
    assert result.assertions_total == len(scenario_assertions)
    assert result.assertions_passed == result.assertions_total
    assert result.success


@pytest.mark.integration
@pytest.mark.ollama
@pytest.mark.parametrize("scenario_path", SCENARIOS, ids=[p.stem for p in SCENARIOS])
def test_full_run_real_driver_scenarios(tmp_path, scenario_path: Path):
    _assert_database_ready()

    runner = ScenarioRunner()
    runner.config["sessions_dir"] = str(tmp_path)

    trainer_user_id = _trainer_user_id_from_scenario(runner, scenario_path)
    _preload_nexoria_rag(trainer_user_id)

    _assert_full_success(runner, scenario_path)
