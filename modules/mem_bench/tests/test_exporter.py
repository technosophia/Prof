"""Unit tests for mem_bench exporter helpers."""

from modules.mem_bench.exporter import build_export_dict, to_yaml_str
from modules.mem_bench.runner import MemBenchCheck, MemBenchResult


def test_build_export_dict_minimal():
    result = MemBenchResult(
        scenario_name="s",
        memory_backend="b",
        memory_content="mem",
        success=True,
        error=None,
        expected_contains=["a"],
        checks=[MemBenchCheck(term="a", found=True)],
        trace_logs=[],
        cleared_conversation_count=0,
    )
    out = build_export_dict(result, {"setup": {}, "conversation": []})
    assert out["meta"]["scenario_name"] == "s"
    assert "summary" in out
    assert "rounds" in out


def test_to_yaml_str_serializes():
    rendered = to_yaml_str({"a": "x\ny"})
    assert "a:" in rendered
