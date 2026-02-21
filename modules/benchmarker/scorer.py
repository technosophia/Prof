"""Scoring helpers for benchmark results."""

from typing import Any, Dict


def score_run(run_result: Dict[str, Any]) -> Dict[str, Any]:
    """Compute a simple pass/fail summary from runner output."""
    steps = run_result.get("steps", [])
    total = len(steps)
    errors = sum(1 for step in steps if step.get("status") == "error")
    return {
        "total_steps": total,
        "error_steps": errors,
        "success_rate": 0.0 if total == 0 else (total - errors) / total,
    }
