"""Tests for scorer plugins and scorer registration."""

from __future__ import annotations

import importlib

import yaml

from core.database import init_database
import modules.benchmarker as benchmarker_init
from modules.benchmarker.benchmarker import ScoringRun, ensure_tables_exist
from modules.benchmarker.scorers.embedding_similarity import EmbeddingSimilarityScorer
from modules.benchmarker.scorers.llm_external import LLMExternalScorer
from modules.benchmarker.scorers.manual import ManualScorer
from modules.benchmarker.scoring_pipeline import get_scoring_pipeline
from st_shared.cached import get_db_manager


def setup_function(_):
    init_database(use_memory=True)
    ensure_tables_exist()
    get_db_manager().empty_all_tables()


def _rubric_scores_config(session_path: str):
    return {
        "session_path": session_path,
        "rubric": "memory_quality",
        "scores": {
            "relevance": 4,
            "precision": 3,
            "coverage": 5,
            "noise": 4,
        },
    }


def test_manual_scorer_score_validates_against_rubric():
    result = ManualScorer().score({}, _rubric_scores_config("/tmp/session.yaml"))
    assert result.complete
    assert result.scores["relevance"] == 4.0
    assert result.scorer_config == {"rubric": "memory_quality"}


def test_manual_scorer_import_from_session_yaml_persists(tmp_path):
    path = tmp_path / "session.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "scores": {
                    "rubric": "memory_quality",
                    "dimensions": {
                        "relevance": 4,
                        "precision": 4,
                        "coverage": 4,
                        "noise": 4,
                    },
                    "notes": "manual import",
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = ManualScorer().import_from_session_yaml(str(path), rubric_name=None)
    assert result.complete

    with get_db_manager().get_session() as db:
        rows = db.query(ScoringRun).all()
        assert len(rows) == 1
        assert rows[0].scorer_id == "manual"


def test_llm_external_scorer_strips_fences_and_parses_yaml():
    scorer = LLMExternalScorer()
    response = """```yaml
scores:
  dimensions:
    relevance: 4
    precision: 3
    coverage: 2
    noise: 5
```"""
    result = scorer.score({}, {"session_path": "/tmp/s.yaml", "rubric": "memory_quality", "response_text": response})
    assert result.complete
    assert result.scores["precision"] == 3.0


def test_llm_external_scorer_returns_incomplete_on_parse_error():
    scorer = LLMExternalScorer()
    result = scorer.score({}, {"session_path": "/tmp/s.yaml", "rubric": "memory_quality", "response_text": ":::"})
    assert not result.complete
    assert result.parse_errors


def test_embedding_similarity_no_expected_response_returns_incomplete():
    scorer = EmbeddingSimilarityScorer()
    session = {
        "steps": [
            {
                "id": "s1",
                "action": "user_send_message",
                "result": {"llm_response": "hello"},
            }
        ]
    }
    result = scorer.score(session, {"session_path": "/tmp/s.yaml", "model": "any-model"})
    assert not result.complete
    assert "expected_response" in result.parse_errors[0]


def test_embedding_similarity_uses_step_ids_as_score_keys(monkeypatch):
    scorer = EmbeddingSimilarityScorer()

    class FakeModel:
        def encode(self, text, convert_to_tensor=True):
            del convert_to_tensor
            return text

    monkeypatch.setattr(scorer, "_get_model", lambda _model_name: FakeModel())
    monkeypatch.setattr(scorer, "_similarity", lambda a, b: 1.0 if a and b else 0.0)

    session = {
        "steps": [
            {
                "id": "s1",
                "action": "user_send_message",
                "expected_response": "expected",
                "result": {"llm_response": "answer"},
            }
        ]
    }
    result = scorer.score(session, {"session_path": "/tmp/s.yaml", "model": "any-model"})
    assert result.complete
    assert list(result.scores.keys()) == ["s1"]


def test_benchmarker_initialize_registers_three_scorers(monkeypatch):
    importlib.reload(benchmarker_init)
    pipeline = get_scoring_pipeline()
    pipeline._registry = {}

    monkeypatch.setattr(benchmarker_init, "_ACTIONS_REGISTERED", True)
    monkeypatch.setattr(benchmarker_init, "_LLM_OPTIONS_REGISTERED", True)
    monkeypatch.setattr(benchmarker_init, "_SCORERS_REGISTERED", False)

    assert benchmarker_init.initialize()
    scorer_ids = sorted(item["id"] for item in pipeline.list_scorers())
    assert scorer_ids == ["embedding_similarity", "llm_external", "manual"]
