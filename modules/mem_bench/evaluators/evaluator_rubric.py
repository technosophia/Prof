"""Rubric LLM-judge evaluator for mem_bench."""

from __future__ import annotations

import asyncio
import json
from typing import Dict

from core.logging import log
from shared.common import get_llm_manager

from .base import EvalCheck, EvalResult, MemEvaluator


class RubricEvaluator(MemEvaluator):
    id = "rubric"
    label = "Rubric LLM judge"

    def evaluate(self, memory_content: str, scenario: dict, context: dict) -> EvalResult:
        rubric = context.get("rubric")
        if not rubric:
            return EvalResult(
                evaluator_id=self.id,
                passed=False,
                score=0.0,
                checks=[],
                details={"status": "skipped", "reason": "No rubric provided"},
            )

        dimensions = rubric.get("dimensions") or []
        if not dimensions:
            return EvalResult(
                evaluator_id=self.id,
                passed=False,
                score=0.0,
                checks=[],
                details={"status": "error", "reason": "Rubric has no dimensions"},
            )

        try:
            manager = get_llm_manager()
            llm_id = getattr(manager, "current_llm", "")
            prompt = self._build_prompt(memory_content=memory_content, scenario=scenario, context=context, dimensions=dimensions)
            response_text = self._run_internal_response(manager, llm_id, prompt)
            parsed = json.loads(response_text)
        except Exception as exc:
            log("error", f"mem_bench.rubric_evaluator failed: {exc}", stacktrace=True)
            return EvalResult(
                evaluator_id=self.id,
                passed=False,
                score=0.0,
                checks=[],
                details={"status": "error", "error": str(exc)},
            )

        checks = []
        weighted_sum = 0.0
        weight_total = 0.0
        rubric_scores: Dict = {}
        for dim in dimensions:
            dim_id = str(dim.get("id") or "")
            if not dim_id:
                continue
            raw = parsed.get(dim_id, {}) if isinstance(parsed, dict) else {}
            score = int(raw.get("score", 0)) if str(raw.get("score", "")).isdigit() else 0
            score = max(0, min(4, score))
            normalized = score / 4.0
            reasoning = str(raw.get("reasoning") or "")
            weight = float(dim.get("weight", 1.0))
            weighted_sum += normalized * weight
            weight_total += weight
            rubric_scores[dim_id] = {"score": score, "reasoning": reasoning, "weight": weight}
            checks.append(
                EvalCheck(
                    term=dim_id,
                    passed=score >= 3,
                    score=normalized,
                    method="llm_judge",
                    note=reasoning,
                )
            )

        overall = (weighted_sum / weight_total) if weight_total > 0 else 0.0
        return EvalResult(
            evaluator_id=self.id,
            passed=overall >= 0.6,
            score=overall,
            checks=checks,
            details={"rubric_scores": rubric_scores, "raw": parsed},
        )

    @staticmethod
    def _run_internal_response(manager, llm_id: str, prompt: str) -> str:
        messages = [{"role": "user", "content": prompt}]
        coro = manager.internal_response(llm_id, messages, response_format="json")
        try:
            return asyncio.run(coro)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()

    @staticmethod
    def _build_prompt(memory_content: str, scenario: dict, context: dict, dimensions: list) -> str:
        training_program = str(context.get("training_program") or scenario.get("setup", {}).get("training_program") or "")
        lines = [
            "You are a strict evaluator for pedagogical memory quality.",
            "Score each dimension from 1 to 4, and respond ONLY valid JSON.",
            "Expected JSON schema:",
            '{"dimension_id": {"score": 1-4, "reasoning": "short explanation"}, ...}',
            "",
            "Training program:",
            training_program,
            "",
            "Memory content:",
            memory_content or "(empty)",
            "",
            "Dimensions:",
        ]
        for dim in dimensions:
            levels = dim.get("levels") or {}
            level_lines = [f"  level {k}: {v}" for k, v in sorted(levels.items(), key=lambda kv: int(kv[0]))]
            lines.append(f"- id: {dim.get('id')}")
            lines.append(f"  question: {dim.get('question', '')}")
            lines.extend(level_lines)
        return "\n".join(lines)
