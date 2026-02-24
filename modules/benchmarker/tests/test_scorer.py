"""Tests for benchmarker scorer."""

from datetime import datetime

import pytest
import yaml



from modules.benchmarker.benchmarker import ensure_tables_exist, BenchmarkScore
from modules.benchmarker.scorer import JudgePromptRenderer, RubricLoader, Scorer


from core.database import init_database
from st_shared.cached import get_db_manager
def _session_fixture(tmp_path):
    session_path = tmp_path / "session.yaml"
    session = {
        "meta": {"scenario": "basic", "run_at": datetime.utcnow().isoformat() + "Z", "options": {"memory_backend": "memory"}},
        "summary": {"assertions_passed": 1, "assertions_total": 1},
        "steps": [
            {
                "id": "s1",
                "actor": "student",
                "action": "user_send_message",
                "params": {"content": "What is a tuple?"},
                "result": {"llm_response": "A tuple is immutable."},
            }
        ],
        "assertions": [{"id": "a1", "passed": True, "message": "ok", "type": "action_succeeded"}],
        "events": [{"type": "plugin_event", "plugin_id": "memory", "event": "analysis_complete", "data": {"success": True}}],
        "judge_prompt": None,
        "scores": {"rubric": None, "dimensions": {}},
    }
    session_path.write_text(yaml.safe_dump(session, sort_keys=False), encoding="utf-8")
    return str(session_path)


def setup_function(_):
    init_database(use_memory=True)
    ensure_tables_exist()
    get_db_manager().empty_all_tables()


def test_rubric_loader_finds_example_rubrics():
    names = RubricLoader().list_available()
    assert "memory_quality" in names
    assert "llm_response_quality" in names


def test_rubric_loader_validates_required_fields(tmp_path):
    rubrics = tmp_path / "rubrics"
    rubrics.mkdir()
    (rubrics / "bad.yaml").write_text("name: bad\n", encoding="utf-8")
    loader = RubricLoader(str(rubrics))
    with pytest.raises(ValueError):
        loader.load("bad")


def test_judge_prompt_renderer_produces_nonempty_output(tmp_path):
    path = _session_fixture(tmp_path)
    session = yaml.safe_load(open(path, "r", encoding="utf-8"))
    rubric = RubricLoader().load("memory_quality")
    output = JudgePromptRenderer().render(session, rubric)
    assert isinstance(output, str)
    assert output.strip()


def test_judge_prompt_contains_evidence(tmp_path):
    path = _session_fixture(tmp_path)
    session = yaml.safe_load(open(path, "r", encoding="utf-8"))
    rubric = RubricLoader().load("memory_quality")
    output = JudgePromptRenderer().render(session, rubric)
    assert "What is a tuple?" in output


def test_parse_llm_response_clean_yaml():
    scorer = Scorer()
    rubric = RubricLoader().load("memory_quality")
    parsed = scorer._parse_llm_score_response(
        "scores:\n  dimensions:\n    relevance: 4\n    precision: 5\n    coverage: 3\n    noise: 4\n", rubric
    )
    assert parsed["relevance"] == 4


def test_parse_llm_response_markdown_fenced():
    scorer = Scorer()
    rubric = RubricLoader().load("memory_quality")
    parsed = scorer._parse_llm_score_response(
        "```yaml\nscores:\n  dimensions:\n    relevance: 4\n    precision: 5\n    coverage: 3\n    noise: 4\n```", rubric
    )
    assert parsed["precision"] == 5


def test_parse_llm_response_partial():
    scorer = Scorer()
    rubric = RubricLoader().load("memory_quality")
    parsed = scorer._parse_llm_score_response("scores:\n  dimensions:\n    relevance: 4\n", rubric)
    assert parsed["relevance"] == 4
    assert parsed["precision"] is None


def test_parse_llm_response_garbage():
    scorer = Scorer()
    rubric = RubricLoader().load("memory_quality")
    parsed = scorer._parse_llm_score_response("garbage ###", rubric)
    assert all(v is None for v in parsed.values())


def test_import_scores_from_yaml_valid(tmp_path):
    path = _session_fixture(tmp_path)
    data = yaml.safe_load(open(path, "r", encoding="utf-8"))
    data["scores"] = {
        "rubric": "memory_quality",
        "judge": "mock",
        "source": "manual",
        "dimensions": {"relevance": 4, "precision": 4, "coverage": 4, "noise": 4},
    }
    open(path, "w", encoding="utf-8").write(yaml.safe_dump(data, sort_keys=False))

    result = Scorer().import_scores_from_yaml(path)
    assert result.complete


def test_import_scores_from_yaml_missing_dimensions(tmp_path):
    path = _session_fixture(tmp_path)
    data = yaml.safe_load(open(path, "r", encoding="utf-8"))
    data["scores"] = {"rubric": "memory_quality", "dimensions": {"relevance": 4}}
    open(path, "w", encoding="utf-8").write(yaml.safe_dump(data, sort_keys=False))

    result = Scorer().import_scores_from_yaml(path)
    assert not result.complete
    assert result.parse_errors


def test_score_session_no_llm(tmp_path):
    path = _session_fixture(tmp_path)
    result = Scorer().score_session(path, "memory_quality", use_llm=False)
    assert result.judge_prompt
    assert all(v is None for v in result.scores.values())
    assert result.llm_used is None



    with get_db_manager().get_session() as db:
        assert db.query(BenchmarkScore).count() == 0


def test_import_scores_from_yaml_uses_selected_rubric_fallback(tmp_path):
    path = _session_fixture(tmp_path)
    data = yaml.safe_load(open(path, "r", encoding="utf-8"))
    data["scores"] = {"rubric": None, "dimensions": {"relevance": 4, "precision": 4, "coverage": 4, "noise": 4}}
    open(path, "w", encoding="utf-8").write(yaml.safe_dump(data, sort_keys=False))

    result = Scorer().import_scores_from_yaml(path, rubric_name="memory_quality")
    assert result.rubric_name == "memory_quality"
    assert result.complete


def test_import_scores_from_text(tmp_path):
    path = _session_fixture(tmp_path)
    pasted = """```yaml
scores:
  dimensions:
    relevance: 5
    precision: 4
    coverage: 4
    noise: 5
```"""

    result = Scorer().import_scores_from_text(path, "memory_quality", pasted)
    assert result.complete
    assert result.scores["relevance"] == 5
