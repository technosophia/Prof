"""Base types for mem_bench evaluator plugins."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class EvalCheck:
    term: str
    passed: bool
    score: float
    method: str
    note: str


@dataclass
class EvalResult:
    evaluator_id: str
    passed: bool
    score: float
    checks: List[EvalCheck] = field(default_factory=list)
    details: Dict = field(default_factory=dict)


class MemEvaluator:
    id: str = ""
    label: str = ""

    def evaluate(self, memory_content: str, scenario: dict, context: dict) -> EvalResult:
        """Evaluate memory content against one evaluator strategy."""
        raise NotImplementedError
