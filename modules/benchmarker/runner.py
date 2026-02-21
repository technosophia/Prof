"""Scenario runner for benchmarker."""

from typing import Any, Dict, List

import yaml

from shared.common import get_driver, log


ALLOWED_ACTIONS_BY_ACTOR = {
    "student": {"user_send_message", "create_conversation"},
    "teacher": {
        "teacher_send_message",
        "trigger_memory_analysis",
        "add_student_note",
        "set_training_program",
    },
    "system": {"create_conversation", "set_training_program"},
}


class ScenarioRunner:
    """Execute benchmark scenarios through the app driver."""

    def __init__(self, driver=None):
        self.driver = driver or get_driver()

    def load_scenario(self, scenario_path: str) -> Dict[str, Any]:
        with open(scenario_path, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)

    def validate_scenario(self, scenario: Dict[str, Any]) -> List[str]:
        errors: List[str] = []
        steps = scenario.get("steps")
        if not isinstance(steps, list):
            return ["Scenario must define a list of steps"]

        for index, step in enumerate(steps):
            actor = step.get("actor")
            action = step.get("action")
            step_id = step.get("id", f"step_{index}")

            if actor not in ALLOWED_ACTIONS_BY_ACTOR:
                errors.append(f"Step '{step_id}' has invalid actor '{actor}'")
                continue

            allowed_actions = ALLOWED_ACTIONS_BY_ACTOR[actor]
            is_option_switch = bool(step.get("option_group") and step.get("option_name"))
            if action in allowed_actions:
                continue
            if actor == "system" and is_option_switch:
                continue

            errors.append(
                f"Step '{step_id}' actor '{actor}' cannot execute action '{action}'"
            )

        return errors

    def run(self, scenario: Dict[str, Any]) -> Dict[str, Any]:
        scenario_name = scenario.get("name", "benchmarker_scenario")
        self.driver.start_session(scenario_name)

        results: List[Dict[str, Any]] = []
        for index, step in enumerate(scenario.get("steps", [])):
            step_id = step.get("id", f"step_{index}")
            actor = step.get("actor")
            action = step.get("action")
            params = step.get("params", {})
            step_result: Dict[str, Any] = {"id": step_id, "actor": actor, "action": action, "status": "ok"}

            allowed_actions = ALLOWED_ACTIONS_BY_ACTOR.get(actor, set())
            is_option_switch = bool(step.get("option_group") and step.get("option_name"))
            if action not in allowed_actions and not (actor == "system" and is_option_switch):
                message = f"Actor '{actor}' cannot execute action '{action}'"
                log("warning", message)
                step_result["status"] = "error"
                step_result["error"] = message
                results.append(step_result)
                continue

            try:
                if is_option_switch:
                    self.driver.switch_option(step["option_group"], step["option_name"])
                    step_result["result"] = {
                        "option_group": step["option_group"],
                        "option_name": step["option_name"],
                    }
                else:
                    step_result["result"] = self.driver.do_action(action, **params)
            except Exception as exc:
                step_result["status"] = "error"
                step_result["error"] = str(exc)

            results.append(step_result)

        return {
            "scenario": scenario_name,
            "steps": results,
            "session_summary": self.driver.get_session_summary(),
        }
