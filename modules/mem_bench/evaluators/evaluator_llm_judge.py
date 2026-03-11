"""LLM-as-judge evaluator for mem_bench."""

from __future__ import annotations

import json
from statistics import mean
from typing import Tuple

from core.logging import log
from core.thread import run_async_safely
from shared.common import get_llm_manager

from .base import EvalCheck, EvalResult, MemEvaluator


class LLMJudgeEvaluator(MemEvaluator):
    id = "llm_judge"
    label = "LLM fact judge"

    def evaluate(self, memory_content: str, scenario: dict, context: dict) -> EvalResult:
        del context
        contains = [str(x) for x in (scenario.get("expected_memory_contains") or [])]
        excludes = [str(x) for x in (scenario.get("expected_memory_excludes") or [])]

        manager = get_llm_manager()
        llm_id = getattr(manager, "current_llm", "")

        checks = []
        for term in contains:
            try:
                found, reasoning = self._judge_term(manager, llm_id, memory_content, term, check_type="contains")
                checks.append(EvalCheck(term=term, passed=found, score=1.0 if found else 0.0, method="llm_judge", note=reasoning))
            except Exception as exc:
                log("warning", f"LLMJudgeEvaluator: call failed for contains term: {exc}")
                checks.append(EvalCheck(term=term, passed=False, score=0.0, method="llm_judge", note="llm_call_failed"))

        for term in excludes:
            try:
                found, reasoning = self._judge_term(manager, llm_id, memory_content, term, check_type="excludes")
                passed = not found
                checks.append(EvalCheck(term=term, passed=passed, score=1.0 if passed else 0.0, method="llm_judge", note=reasoning))
            except Exception as exc:
                log("warning", f"LLMJudgeEvaluator: call failed for excludes term: {exc}")
                checks.append(EvalCheck(term=term, passed=False, score=0.0, method="llm_judge", note="llm_call_failed"))

        return EvalResult(
            evaluator_id=self.id,
            passed=all(check.passed for check in checks),
            score=mean([check.score for check in checks] or [0.0]),
            checks=checks,
        )

    def _judge_term(self, manager, llm_id: str, memory: str, term: str, check_type: str) -> Tuple[bool, str]:
        system_prompt = (
            "You are a strict pedagogical memory auditor.\n"
            "Answer only with a JSON object — no explanation, no markdown, no preamble."
        )
        if check_type == "contains":
            user_prompt = (
                f"Memory:\n{memory}\n\n"
                f"Fact to verify: {term}\n\n"
                "Does this fact appear in the memory — directly stated or clearly implied by\n"
                "combining multiple sentences? A fact is \"found\" if a tutor reading the memory\n"
                "would unambiguously know this about the student.\n\n"
                "Answer: {\"found\": true/false, \"reasoning\": \"<one sentence>\"}"
            )
        else:
            user_prompt = (
                f"Memory:\n{memory}\n\n"
                f"Fact that should NOT be present: {term}\n\n"
                "Does this fact appear in the memory — directly stated or clearly implied?\n\n"
                "Answer: {\"found\": true/false, \"reasoning\": \"<one sentence>\"}"
            )

        response = self._run_internal_response(
            manager,
            llm_id,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return self._parse_response(response)

    @staticmethod
    def _run_internal_response(manager, llm_id: str, messages: list[dict]) -> str:
        return run_async_safely(manager.internal_response(llm_id, messages))

    def _parse_response(self, response: str) -> Tuple[bool, str]:
        clean = response.strip()
        if clean.startswith("```"):
            clean = "\n".join(clean.split("\n")[1:])
        if clean.endswith("```"):
            clean = clean[:-3].strip()
        try:
            parsed = json.loads(clean)
            return bool(parsed.get("found", False)), str(parsed.get("reasoning", ""))
        except Exception as e:
            log("warning", f"LLMJudgeEvaluator: parse error: {e}")
            return False, f"parse_error: {str(e)}"
