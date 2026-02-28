"""Tests for benchmarker prompt renderer utilities."""

from datetime import datetime

import pytest
import yaml

from modules.benchmarker.scorers.prompt_renderer import JudgePromptRenderer, RubricLoader


def _session_fixture(tmp_path, include_expected: bool = False):
    session_path = tmp_path / "session.yaml"
    step = {
        "id": "s1",
        "actor": "student",
        "action": "user_send_message",
        "params": {"content": "What is a tuple?"},
        "result": {"llm_response": "A tuple is immutable."},
    }
    if include_expected:
        step["expected_response"] = "A tuple is an immutable ordered collection."

    session = {
        "meta": {"scenario": "basic", "run_at": datetime.utcnow().isoformat() + "Z", "options": {"memory_backend": "memory"}},
        "summary": {"assertions_passed": 1, "assertions_total": 1},
        "steps": [step],
        "assertions": [{"id": "a1", "passed": True, "message": "ok", "type": "action_succeeded"}],
        "events": [{"type": "plugin_event", "plugin_id": "memory", "event": "analysis_complete", "data": {"success": True}}],
    }
    session_path.write_text(yaml.safe_dump(session, sort_keys=False), encoding="utf-8")
    return str(session_path)


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


def test_judge_prompt_renderer_contains_conversation(tmp_path):
    path = _session_fixture(tmp_path)
    session = yaml.safe_load(open(path, "r", encoding="utf-8"))
    rubric = RubricLoader().load("memory_quality")
    output = JudgePromptRenderer().render(session, rubric)
    assert "What is a tuple?" in output


def test_judge_prompt_renderer_adds_reference_answers_when_available(tmp_path):
    path = _session_fixture(tmp_path, include_expected=True)
    session = yaml.safe_load(open(path, "r", encoding="utf-8"))
    rubric = RubricLoader().load("memory_quality")
    output = JudgePromptRenderer().render(session, rubric)
    assert "REFERENCE ANSWERS" in output
    assert "[s1] A tuple is an immutable ordered collection." in output


def test_judge_prompt_renderer_omits_reference_answers_when_missing(tmp_path):
    path = _session_fixture(tmp_path, include_expected=False)
    session = yaml.safe_load(open(path, "r", encoding="utf-8"))
    rubric = RubricLoader().load("memory_quality")
    output = JudgePromptRenderer().render(session, rubric)
    assert "REFERENCE ANSWERS" not in output
