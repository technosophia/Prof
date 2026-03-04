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
