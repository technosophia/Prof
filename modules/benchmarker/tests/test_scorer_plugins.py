"""Tests for scorer auto-discovery and plugin workflows."""

from __future__ import annotations

from core.database import init_database
from modules.benchmarker.benchmarker import BenchmarkRun, ScoringRun, ensure_tables_exist
from modules.benchmarker.scoring_pipeline import ScoringPipeline, get_scoring_pipeline
from modules.benchmarker.scorers.scorer_llm_external import ScorerPlugin as LLMExternalScorer
from modules.benchmarker.scorers.scorer_manual import ScorerPlugin as ManualScorer
from st_shared.cached import get_db_manager


class FakeContainer:
    """Minimal container test double for scorer UI methods."""

    def __init__(self):
        self.messages = []

    def warning(self, message):
        self.messages.append(("warning", message))

    def subheader(self, message):
        self.messages.append(("subheader", message))

    def code(self, message, language=None):
        self.messages.append(("code", message, language))

    def text_area(self, label, height=None, key=None):
        del label, height, key
        return ""

    def button(self, label, key=None):
        del label, key
        return False

    def info(self, message):
        self.messages.append(("info", message))

    def success(self, message):
        self.messages.append(("success", message))

    def dataframe(self, rows, **kwargs):
        self.messages.append(("dataframe", rows, kwargs))

    def selectbox(self, label, options, key=None):
        del label, key
        return options[0]

    def slider(self, label, min_value, max_value, value, key=None, help=None):
        del label, min_value, max_value, key, help
        return value


def setup_function(_):
    init_database(use_memory=True)
    ensure_tables_exist()
    get_db_manager().empty_all_tables()


def test_pipeline_autodiscovers_scorer_modules():
    pipeline = ScoringPipeline()
    ids = sorted(item["id"] for item in pipeline.list_scorers())
    assert ids == ["context_relevance", "embedding_similarity", "llm_external", "llm_internal", "manual"]


def test_llm_external_parser_handles_fenced_yaml():
    scorer = LLMExternalScorer()
    rubric = {
        "dimensions": [
            {"id": "relevance"},
            {"id": "accuracy"},
        ]
    }
    scores, errors = scorer._parse_response(
        """```yaml
scores:
  dimensions:
    relevance: 4
    accuracy: 3
```""",
        rubric,
    )
    assert errors == []
    assert scores == {"relevance": 4.0, "accuracy": 3.0}


def test_manual_scorer_compute_score_writes_result(monkeypatch):
    session_path = "/tmp/manual-session.yaml"
    with get_db_manager().get_session() as db:
        db.add(
            BenchmarkRun(
                scenario_name="s",
                options={"memory_backend": "memory"},
                assertions_passed=1,
                assertions_total=1,
                duration_seconds=1.0,
                summary={},
                success=1,
                errors=[],
                session_file=session_path,
            )
        )

    scorer = ManualScorer()
    fake = FakeContainer()
    monkeypatch.setattr(fake, "button", lambda label, key=None: True)
    monkeypatch.setattr(fake, "text_area", lambda label, key=None: "notes")

    scorer.compute_score(session={}, config={"session_path": session_path}, container=fake)

    with get_db_manager().get_session() as db:
        rows = db.query(ScoringRun).all()
        assert len(rows) == 1
        assert rows[0].scorer_id == "manual"
        assert rows[0].scores


def test_embedding_scorer_missing_expected_response_does_not_write():
    pipeline = get_scoring_pipeline()
    scorer = pipeline.get_scorer("embedding_similarity")
    fake = FakeContainer()
    scorer.compute_score(
        session={
            "steps": [
                {
                    "id": "s1",
                    "action": "user_send_message",
                    "result": {"llm_response": "hello"},
                }
            ]
        },
        config={"session_path": "/tmp/no-write.yaml"},
        container=fake,
    )

    with get_db_manager().get_session() as db:
        assert db.query(ScoringRun).count() == 0
    assert any(item[0] == "warning" for item in fake.messages)
