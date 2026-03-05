"""Unit test stubs for mem_bench evaluators."""

from modules.mem_bench.evaluators import get_evaluator, get_evaluators
from modules.mem_bench.evaluators.base import EvalCheck, EvalResult


def test_evaluator_discovery_finds_embedding_rubric_and_llm_judge():
    ids = {ev.id for ev in get_evaluators()}
    assert "embedding" in ids
    assert "rubric" in ids
    assert "llm_judge" in ids
    assert get_evaluator("embedding") is not None
    assert get_evaluator("llm_judge") is not None


def test_eval_dataclasses_construct():
    check = EvalCheck(term="x", passed=True, score=1.0, method="substring", note="ok")
    result = EvalResult(evaluator_id="embedding", passed=True, score=1.0, checks=[check], details={})
    assert result.checks[0].term == "x"
