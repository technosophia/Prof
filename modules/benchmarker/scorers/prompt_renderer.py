"""Prompt rendering utilities for rubric-based scorer plugins."""

from __future__ import annotations

import os
from typing import Dict, List

import yaml

from shared.common import get_prompt


class RubricLoader:
    """Load and validate rubric YAML files."""

    def __init__(self, rubrics_dir: str = "modules/benchmarker/rubrics"):
        self.rubrics_dir = rubrics_dir

    def load(self, rubric_name: str) -> Dict:
        """Load rubric by name and validate required fields."""
        path = os.path.join(self.rubrics_dir, f"{rubric_name}.yaml")
        if not os.path.exists(path):
            raise FileNotFoundError(f"Rubric not found: {rubric_name}")

        with open(path, "r", encoding="utf-8") as handle:
            rubric = yaml.safe_load(handle) or {}

        if "name" not in rubric:
            raise ValueError("Rubric missing required field: name")
        if "dimensions" not in rubric:
            raise ValueError("Rubric missing required field: dimensions")

        for i, dim in enumerate(rubric.get("dimensions", [])):
            for key in ["id", "question", "guidance", "scale"]:
                if key not in dim:
                    raise ValueError(f"Rubric dimension #{i + 1} missing required field: {key}")

        return rubric

    def list_available(self) -> List[str]:
        """Return list of rubric names (filenames without .yaml)."""
        if not os.path.isdir(self.rubrics_dir):
            return []
        return sorted(f[:-5] for f in os.listdir(self.rubrics_dir) if f.endswith(".yaml"))


class JudgePromptRenderer:
    """Render a self-contained judge prompt from a session and rubric."""

    def render(self, session: Dict, rubric: Dict) -> str:
        """Render full judge prompt."""
        dimensions_block = "\n\n".join(
            [
                f"- {d['id']}\n  Question: {d['question']}\n  Guidance:\n{self._indent(d['guidance'].rstrip(), 4)}"
                for d in rubric.get("dimensions", [])
            ]
        )
        dimension_lines = "\n".join([f"      {d['id']}: <1-{d.get('scale', 5)}>" for d in rubric.get("dimensions", [])])
        max_scale = max([int(d.get("scale", 5)) for d in rubric.get("dimensions", [])] or [5])

        template = get_prompt("benchmarker.judge_prompt_template", "{scenario_name}\n{evidence_block}\n")
        response_format_block = get_prompt("benchmarker.judge_response_format", "scores:\n  dimensions:\n{dimension_lines}")

        scenario_meta = session.get("meta", {})
        scenario_name = scenario_meta.get("scenario", "unknown")
        scenario_description = scenario_meta.get("description", "")
        options_summary = str(scenario_meta.get("options", {}))

        response_format = response_format_block.format(
            rubric_name=rubric.get("name", ""),
            dimension_lines=dimension_lines,
        )

        return template.format(
            scenario_name=scenario_name,
            scenario_description=scenario_description,
            options_summary=options_summary,
            evidence_block=self.render_evidence_block(session),
            rubric_name=rubric.get("name", ""),
            max_scale=max_scale,
            dimensions_block=dimensions_block,
            response_format_block=response_format,
        )

    def render_evidence_block(self, session: Dict) -> str:
        """Extract and format evidence from session events."""
        lines: List[str] = []
        lines.append("CONVERSATION EXCERPT")

        for step in session.get("steps", []):
            if step.get("action") == "user_send_message":
                params = step.get("params", {})
                result = step.get("result", {})
                student = str(params.get("content", "")).strip()
                assistant = str(result.get("llm_response", "")).strip()
                if student:
                    lines.append(f"[student] {student[:300]}")
                if assistant:
                    lines.append(f"[llm] {assistant[:300]}")

        reference_answers = []
        for step in session.get("steps", []):
            expected = step.get("expected_response")
            if isinstance(expected, str) and expected.strip():
                reference_answers.append(f"[{step.get('id', '?')}] {expected.strip()}")

        if reference_answers:
            lines.append("")
            lines.append("REFERENCE ANSWERS")
            lines.extend(reference_answers)

        lines.append("")
        lines.append("PLUGIN EVENTS")
        for event in session.get("events", []):
            if event.get("type") == "plugin_event":
                plugin_id = event.get("plugin_id", "plugin")
                name = event.get("event", "event")
                data = event.get("data", {})
                lines.append(f"{plugin_id}: {name} ({', '.join(f'{k}={v}' for k, v in data.items())})")

        lines.append("")
        lines.append("ASSERTION RESULTS")
        for assertion in session.get("assertions", []):
            mark = "✓" if assertion.get("passed") else "✗"
            lines.append(f"{mark} {assertion.get('id', '?')}: {assertion.get('message', '')}")

        return "\n".join(lines)

    @staticmethod
    def _indent(text: str, n: int) -> str:
        pad = " " * n
        return "\n".join(f"{pad}{line}" for line in text.splitlines())
