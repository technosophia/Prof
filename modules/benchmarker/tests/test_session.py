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
                result={"llm_response": "x" * 900},
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


def test_llm_response_truncated_in_yaml(tmp_path):
    serializer = SessionSerializer()
    path = serializer.write(_run_result(tmp_path), events=[], output_dir=str(tmp_path))

    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    assert len(data["steps"][0]["result"]["llm_response"]) == 500


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
