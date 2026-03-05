"""Export helpers for mem_bench results."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict

import yaml

from modules.mem_bench.runner import MemBenchResult


def build_export_dict(result: MemBenchResult, scenario: dict) -> dict:
    setup = scenario.get("setup") or {}
    rounds = scenario.get("rounds") or []
    if not rounds:
        rounds = [{
            "round": 1,
            "description": "Single round",
            "conversation": scenario.get("conversation") or [],
        }]

    out_rounds = []
    result_rounds = result.rounds or []
    for idx, scenario_round in enumerate(rounds, start=1):
        rr = result_rounds[idx - 1] if idx - 1 < len(result_rounds) else None
        out_rounds.append(
            {
                "round_index": idx,
                "description": scenario_round.get("description", f"Round {idx}"),
                "conversation": scenario_round.get("conversation") or [],
                "memory_content": rr.memory_content if rr else result.memory_content,
                "checks": [c.__dict__ for c in (rr.checks if rr else result.checks)],
            }
        )

    evaluations = {}
    rubric_scores = {}
    for evaluator_id, eval_result in result.eval_results.items():
        evaluations[evaluator_id] = {
            "id": evaluator_id,
            "passed": eval_result.passed,
            "score": eval_result.score,
            "checks": [c.__dict__ for c in eval_result.checks],
        }
        if evaluator_id == "rubric":
            rubric_scores = eval_result.details.get("rubric_scores", {})

    mean_score = sum(e["score"] for e in evaluations.values()) / max(len(evaluations), 1)
    return {
        "meta": {
            "scenario_name": result.scenario_name,
            "backend": result.memory_backend,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "is_cumulative": result.is_cumulative,
            "rubric_path": result.rubric_path,
        },
        "setup": {
            "student_id": setup.get("student_id"),
            "trainer_id": setup.get("trainer_id"),
            "training_program": str(setup.get("training_program") or "")[:500],
        },
        "rounds": out_rounds,
        "evaluations": evaluations,
        "rubric_scores": rubric_scores,
        "trace_logs": result.trace_logs,
        "summary": {
            "overall_passed": result.success,
            "mean_evaluator_score": mean_score,
            "evaluator_count": len(evaluations),
            "passed_checks": sum(1 for c in result.checks if c.found),
            "total_checks": len(result.checks),
        },
    }


def to_yaml_str(export_dict: Dict) -> str:
    def _literal_representer(dumper, data):
        if "\n" in data:
            return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
        return dumper.represent_scalar("tag:yaml.org,2002:str", data)

    yaml.SafeDumper.add_representer(str, _literal_representer)
    return yaml.safe_dump(export_dict, allow_unicode=True, sort_keys=False)
