"""Session YAML serializer for benchmarker runs.

Session YAML format (v2, phase 2):
Includes judge_prompt: block (rendered if rubric_name provided to write())
and scores: block (empty, filled by user or LLM, reimported via Scorer).
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Dict, List

import yaml

from shared.common import get_section, log


class SessionSerializer:
    """Converts run result and driver events to a YAML session artifact."""

    def _serialise_injected_contexts(self, injected: List[Dict]) -> List[Dict]:
        """Serialise injected contexts for YAML output — preview only."""
        result: List[Dict] = []
        for ctx in injected:
            result.append(
                {
                    "source": ctx.get("source", "unknown"),
                    "role": ctx.get("role", "system"),
                    "content_preview": ctx.get("content", "")[:150],
                }
            )
        return result

    def write(
        self,
        run_result,
        events: List[Dict],
        output_dir: str,
        options_snapshot: Dict | None = None,
        llm_id: str | None = None,
        run_duration: float = 0.0,
        rubric_name: str = None,
    ) -> str:
        """Write session yaml file and return path."""
        os.makedirs(output_dir, exist_ok=True)
        now = datetime.now(timezone.utc)
        filename = f"{run_result.scenario_name}__{now.strftime('%Y%m%dT%H%M%SZ')}.yaml"
        path = os.path.join(output_dir, filename)

        truncate_chars = get_section("benchmarker").get("llm_response_truncate_chars", 500)
        steps_payload = []
        for step in run_result.steps:
            result = dict(step.result)
            injected_contexts = result.pop("injected_contexts", [])
            if isinstance(result.get("llm_response"), str) and len(result["llm_response"]) > truncate_chars:
                result["llm_response"] = result["llm_response"][:truncate_chars]

            steps_payload.append(
                {
                    "id": step.step_id,
                    "actor": step.actor,
                    "action": step.action,
                    "success": step.success,
                    "duration_seconds": round(step.duration_seconds, 3),
                    "params": step.params,
                    "result": result,
                    "injected_contexts": self._serialise_injected_contexts(injected_contexts),
                    "error": step.error,
                }
            )

        judge_prompt = None
        if rubric_name:
            try:
                from modules.benchmarker.scorer import JudgePromptRenderer, RubricLoader

                rubric = RubricLoader().load(rubric_name)
                prompt_session = {
                    "meta": {
                        "scenario": run_result.scenario_name,
                        "description": "",
                        "run_at": now.isoformat().replace("+00:00", "Z"),
                        "options": options_snapshot or {},
                        "llm": llm_id,
                    },
                    "summary": {
                        "assertions_passed": run_result.assertions_passed,
                        "assertions_total": run_result.assertions_total,
                    },
                    "steps": steps_payload,
                    "assertions": [
                        {
                            "id": a.id,
                            "type": a.assertion_type,
                            "passed": a.passed,
                            "message": a.message,
                        }
                        for a in run_result.assertions
                    ],
                    "events": events,
                }
                judge_prompt = JudgePromptRenderer().render(prompt_session, rubric)
            except Exception as exc:
                log("warning", f"Failed to render judge prompt for session serialization: {exc}", exc_info=True)
                judge_prompt = None

        payload = {
            "meta": {
                "scenario": run_result.scenario_name,
                "run_at": now.isoformat().replace("+00:00", "Z"),
                "duration_seconds": round(run_duration, 3),
                "options": options_snapshot or {},
                "llm": llm_id,
                "success": run_result.success,
            },
            "summary": {
                "total_steps": len(run_result.steps),
                "steps_succeeded": len([s for s in run_result.steps if s.success]),
                "total_llm_calls": run_result.summary.get("total_llm_calls", 0),
                "total_tokens": run_result.summary.get("total_tokens", 0),
                "assertions_passed": run_result.assertions_passed,
                "assertions_total": run_result.assertions_total,
            },
            "steps": steps_payload,
            "assertions": [
                {
                    "id": a.id,
                    "type": a.assertion_type,
                    "passed": a.passed,
                    "message": a.message,
                }
                for a in run_result.assertions
            ],
            "judge_prompt": judge_prompt,
            "scores": {
                "rubric": None,
                "judge": None,
                "scored_at": None,
                "source": None,
                "dimensions": {},
                "overall": None,
                "notes": None,
            },
            "events": events,
        }

        with open(path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=True)

        return path
