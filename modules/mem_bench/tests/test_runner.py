"""Unit tests for mem_bench runner helpers."""

from modules.mem_bench.runner import MemBenchRunner


def test_extract_memory_content_prefers_plugin_payload():
    payload = {
        "success": True,
        "details": {
            "memory": {"success": True, "memory_content": "Learner understands list comprehensions."}
        },
    }
    assert MemBenchRunner._extract_memory_content(payload) == "Learner understands list comprehensions."


def test_build_checks_case_insensitive():
    checks = MemBenchRunner._build_checks(
        "The student now compares list comprehensions against for loop readability.",
        ["list comprehensions", "FOR LOOP", "dict comprehension"],
    )
    assert checks[0].found is True
    assert checks[1].found is True
    assert checks[2].found is False


def test_build_checks_supports_excludes():
    checks = MemBenchRunner._build_checks("contains alpha", ["alpha"], ["beta"])
    assert checks[0].check_type == "contains"
    assert checks[1].check_type == "excludes"
    assert checks[1].found is True


def test_run_matrix_calls_run_for_all_combinations():
    runner = MemBenchRunner.__new__(MemBenchRunner)
    calls = []

    class FakeResult:
        def __init__(self):
            self.scenario_path = ""

    def fake_run(scenario_path, memory_backend_option, rubric_path=None):
        calls.append((scenario_path, memory_backend_option, rubric_path))
        return FakeResult()

    runner.run = fake_run
    outputs = MemBenchRunner.run_matrix(runner, ["s1.yaml", "s2.yaml"], ["memory", "pedagogical_memory"], rubric_path="r.yaml")

    assert len(calls) == 4
    assert len(outputs) == 4
    assert calls[0] == ("s1.yaml", "memory", "r.yaml")
    assert calls[-1] == ("s2.yaml", "pedagogical_memory", "r.yaml")


def test_is_valid_rounds_scenario(tmp_path):
    path = tmp_path / "scenario.yaml"
    path.write_text(
        """
setup: {student_id: bench_mem_student_x, trainer_id: bench_mem_trainer_x}
rounds:
  - round: 1
    conversation:
      - role: user
        content: hello
    expected_memory_contains: [hello]
""",
        encoding="utf-8",
    )
    runner = MemBenchRunner.__new__(MemBenchRunner)
    assert runner.is_valid_scenario(str(path)) is True
