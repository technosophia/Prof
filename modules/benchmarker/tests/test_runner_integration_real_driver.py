"""Integration tests for benchmarker runner with real driver and real LLM."""

from __future__ import annotations

from pathlib import Path

import pytest

from modules.benchmarker.runner import ScenarioRunner
from modules.rag_manager import rag_manager
from shared.cached import get_db_manager
from shared.common import get_user_manager, log


SCENARIOS = [
    Path("modules/benchmarker/scenarios/example_basic.yaml"),
    Path("modules/benchmarker/scenarios/full_nexoria.yaml"),
]
NEXORIA_DOC = Path("modules/benchmarker/tests/nexoria.md")


@pytest.fixture()
def _rag_setup():
    """Reset and reload RAG for each integration test."""
    from shared.cached import get_config

    cfg = get_config()
    classic_cfg = (cfg.get("modules.rag_manager", {}) or {}).get("engines", {}).get("classic", {})
    configured_threshold = classic_cfg.get("similarity_threshold", 0.3)

    classic_engine = rag_manager.get_engine("classic")
    if classic_engine is not None and hasattr(classic_engine, "similarity_threshold"):
        classic_engine.similarity_threshold = configured_threshold

    trainer = get_user_manager().get_user("master1")
    assert trainer is not None, "master1 user not found - DB not initialized correctly"

    rag_manager.clear_all_documents(trainer["id"])
    log("info", "[real_driver] Cleared trainer RAG docs")

    filename = rag_manager.upload_document(
        source_path=str(NEXORIA_DOC),
        original_filename="nexoria.md",
        user_id=trainer["id"],
        is_public=False,
    )
    if not filename:
        pytest.skip("RAG document upload failed in this environment")

    indexed = rag_manager.index_document(filename, "classic", trainer["id"])
    if not indexed:
        pytest.skip("Classic RAG indexing unavailable (embedding model/service not ready)")

    log("info", f"[real_driver] Nexoria doc indexed: {filename}")


def _assert_database_ready() -> None:
    assert get_db_manager().is_initialized(), (
        "Database manager is not initialized. "
        "It must be initialized by pytest bootstrap before tests execute."
    )


def _trainer_user_id_from_scenario(runner: ScenarioRunner, scenario_path: Path) -> str:
    scenario = runner._load_scenario(str(scenario_path))
    trainer_name = scenario.get("setup", {}).get("trainer_id")
    if not trainer_name:
        pytest.skip(f"No trainer_id in setup for {scenario_path}")

    trainer = get_user_manager().get_user(trainer_name)
    assert trainer is not None, f"Trainer '{trainer_name}' not found for {scenario_path}"

    return trainer["id"]


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

    failed_assertions = [a for a in result.assertions if not a.passed]
    if failed_assertions:
        failed_steps = [s for s in result.steps if not s.success]
        summary = [
            f"scenario={scenario.get('meta', {}).get('name', scenario_path.name)}",
            f"assertions={result.assertions_passed}/{result.assertions_total}",
            f"run_errors={result.errors}",
            f"failed_assertions={[{'id': a.id, 'type': a.assertion_type, 'message': a.message} for a in failed_assertions]}",
            f"failed_steps={[{'step_id': s.step_id, 'action': s.action, 'error': s.error} for s in failed_steps]}",
        ]
        pytest.fail(" | ".join(summary))

    assert result.assertions_passed == result.assertions_total
    assert result.success


@pytest.mark.integration
@pytest.mark.ollama
@pytest.mark.parametrize("scenario_path", SCENARIOS, ids=[p.stem for p in SCENARIOS])
def test_full_run_real_driver_scenarios(
    tmp_path,
    scenario_path: Path,
    integration_real_driver_setup,
    _rag_setup,
):
    _assert_database_ready()

    runner = ScenarioRunner()
    runner.config["sessions_dir"] = str(tmp_path)

    _trainer_user_id_from_scenario(runner, scenario_path)

    _assert_full_success(runner, scenario_path)
