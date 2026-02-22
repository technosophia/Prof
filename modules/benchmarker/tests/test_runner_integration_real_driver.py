"""Integration tests for benchmarker runner with real driver and real LLM."""

from __future__ import annotations

from pathlib import Path
import tempfile
import uuid

import pytest

from modules.benchmarker.runner import ScenarioRunner
from modules.rag_manager import rag_manager
from shared.cached import get_config, get_db_manager
from shared.common import get_user_manager, init_database


SCENARIO_PATH = Path("modules/benchmarker/scenarios/example_basic.yaml")


def _ensure_database_initialized() -> None:
    if get_db_manager().is_initialized():
        return

    db_cfg = get_config().get("database", {})
    db_url_or_path = db_cfg.get("url") or db_cfg.get("path")
    if db_url_or_path:
        init_database(use_memory=False, db_path=db_url_or_path)
    else:
        init_database(use_memory=False)


def _preload_rag_document_for_user(owner_user_id: str) -> str:
    """Upload and index a small document with the classic RAG engine."""
    content = (
        "Benchmarker integration RAG note.\\n"
        "The benchmarker test validates an end-to-end run with real services.\\n"
        "Keyword: benchmarker_real_driver."
    )

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as handle:
        handle.write(content)
        source_path = handle.name

    filename = rag_manager.upload_document(
        source_path=source_path,
        original_filename=f"benchmarker_real_driver_{uuid.uuid4().hex}.txt",
        user_id=owner_user_id,
        is_public=False,
    )
    if not filename:
        pytest.skip("RAG document upload failed in this environment")

    indexed = rag_manager.index_document(filename, "classic", owner_user_id)
    if not indexed:
        pytest.skip("Classic RAG indexing unavailable (embedding model/service not ready)")
    return source_path


@pytest.mark.integration
@pytest.mark.ollama
def test_full_run_example_basic_real_driver(tmp_path):
    _ensure_database_initialized()

    runner = ScenarioRunner()
    runner.config["sessions_dir"] = str(tmp_path)

    scenario = runner._load_scenario(str(SCENARIO_PATH))
    scenario_setup = dict(scenario.get("setup", {}))

    trainer_seed = scenario_setup.get("trainer_id", "trainer")
    student_seed = scenario_setup.get("student_id", "student")

    trainer_id = f"bench_{trainer_seed}_{uuid.uuid4().hex[:8]}"
    student_id = f"bench_{student_seed}_{uuid.uuid4().hex[:8]}"

    user_manager = get_user_manager()
    trainer_user_id, _ = user_manager.create_user(name=trainer_id, role="master")
    student_user_id, _ = user_manager.create_user(name=student_id, role="normal", parent_id=trainer_user_id)

    temp_doc_path = _preload_rag_document_for_user(trainer_user_id)

    try:
        result = runner.run(
            str(SCENARIO_PATH),
            setup_overrides={"trainer_id": trainer_id, "student_id": student_id},
        )
    finally:
        Path(temp_doc_path).unlink(missing_ok=True)
        user_manager.delete_user(student_user_id)
        user_manager.delete_user(trainer_user_id)

    scenario_assertions = scenario.get("assertions", [])
    assert result.assertions_total == len(scenario_assertions)
    assert result.assertions_passed == result.assertions_total
    assert result.success
