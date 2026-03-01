"""Tests for benchmarker session serialization."""

import os
import re

import yaml

from modules.benchmarker.runner import AssertionResult, RunResult, StepResult
from modules.benchmarker.session import SessionSerializer


def _run_result(tmp_path):
    return RunResult(
        scenario_name="basic_student_teacher",
        session_path="",
        steps=[
            StepResult(
                step_id="s1",
                action="user_send_message",
                actor="student",
                success=True,
                result={"llm_response": "x" * 900, "injected_contexts": [{"source": "rag_mock", "role": "system", "content": "y"*200}]},
                params={"content": "hi"},
            )
        ],
        assertions=[AssertionResult(id="a1", passed=True, message="ok", assertion_type="action_succeeded")],
        assertions_passed=1,
        assertions_total=1,
        errors=[],
        summary={"total_llm_calls": 1, "total_tokens": 10, "duration_seconds": 0.5},
        success=True,
    )


def test_serialise_run_result_to_yaml(tmp_path):
    serializer = SessionSerializer()
    path = serializer.write(_run_result(tmp_path), events=[{"type": "action"}], output_dir=str(tmp_path))

    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    assert data["meta"]["scenario"] == "basic_student_teacher"
    assert data["summary"]["assertions_passed"] == 1


def test_llm_response_not_truncated_in_yaml(tmp_path):
    serializer = SessionSerializer()
    path = serializer.write(_run_result(tmp_path), events=[], output_dir=str(tmp_path))

    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    assert len(data["steps"][0]["result"]["llm_response"]) == 900


def test_session_file_named_correctly(tmp_path):
    serializer = SessionSerializer()
    path = serializer.write(_run_result(tmp_path), events=[], output_dir=str(tmp_path))

    assert re.match(r"basic_student_teacher__\d{8}T\d{6}Z\.yaml", os.path.basename(path))


def test_all_events_present_in_session(tmp_path):
    serializer = SessionSerializer()
    events = [{"type": "action", "name": "x"}, {"type": "llm_call", "llm_id": "groq"}]
    path = serializer.write(_run_result(tmp_path), events=events, output_dir=str(tmp_path))

    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    assert len(data["events"]) == 2


def test_injected_contexts_serialized_with_full_content_only(tmp_path):
    serializer = SessionSerializer()
    path = serializer.write(_run_result(tmp_path), events=[], output_dir=str(tmp_path))

    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    assert "injected_contexts" in data["steps"][0]
    assert data["steps"][0]["injected_contexts"][0]["source"] == "rag_mock"
    assert "content_preview" not in data["steps"][0]["injected_contexts"][0]
    assert "injected_contexts" not in data["steps"][0]["result"]


def test_session_excludes_scoring_fields_and_includes_configuration(tmp_path):
    serializer = SessionSerializer()
    path = serializer.write(
        _run_result(tmp_path),
        events=[],
        output_dir=str(tmp_path),
        options_snapshot={"llm": "mock-llm", "memory_backend": "memory"},
    )

    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    assert "judge_prompt" not in data
    assert "scores" not in data
    assert data["meta"]["configuration"]["llm"] == "mock-llm"
    assert "student_id" in data["meta"]
    assert "trainer_id" in data["meta"]


def test_expected_response_is_optional_and_not_null(tmp_path):
    serializer = SessionSerializer()
    scenario_steps = [{"id": "s1", "expected_response": "Expected answer"}]
    path = serializer.write(_run_result(tmp_path), events=[], output_dir=str(tmp_path), scenario_steps=scenario_steps)

    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    assert data["steps"][0]["expected_response"] == "Expected answer"

    path_without = serializer.write(_run_result(tmp_path), events=[], output_dir=str(tmp_path), scenario_steps=[{"id": "s1"}])
    with open(path_without, "r", encoding="utf-8") as handle:
        data_without = yaml.safe_load(handle)

    assert "expected_response" not in data_without["steps"][0]
