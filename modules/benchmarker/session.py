"""Session YAML serializer for benchmarker runs."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import os
from typing import Dict, List

import yaml

from shared.common import get_section


class SessionSerializer:
    """Converts run result and driver events to a YAML session artifact."""

    def write(
        self,
        run_result,
        events: List[Dict],
        output_dir: str,
        options_snapshot: Dict | None = None,
        llm_id: str | None = None,
        run_duration: float = 0.0,
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
                    "error": step.error,
                }
            )

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
            "events": events,
        }

        with open(path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=True)

        return path
