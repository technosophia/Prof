"""scorer.py — LLM-as-judge scoring for benchmark sessions.

Responsibilities:
- Load rubrics from YAML files
- Render judge prompts using get_prompt()
- Call the app LLM to get scores (via get_llm_manager().internal_response())
- Parse scores from LLM response
- Export judge-ready text block (for copy-paste or API use)
- Store scores in BenchmarkScore table
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from typing import Dict, List, Optional

import yaml

from shared.common import get_current_llm_id, get_db_manager, get_llm_manager, get_prompt, log

from modules.benchmarker.benchmarker import BenchmarkRun, BenchmarkScore


@dataclass
class ScoringResult:
    session_path: str
    rubric_name: str
    scores: Dict[str, Optional[float]]
    overall: Optional[float]
    judge_prompt: str
    llm_used: Optional[str]
    scored_at: str
    parse_errors: List[str]
    complete: bool


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


class Scorer:
    """Runs LLM-as-judge scoring on a session using a rubric."""

    def __init__(self):
        self.loader = RubricLoader()
        self.renderer = JudgePromptRenderer()

    def score_session(self, session_path: str, rubric_name: str, use_llm: bool = True) -> ScoringResult:
        """Score a session."""
        scored_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        parse_errors: List[str] = []

        with open(session_path, "r", encoding="utf-8") as handle:
            session = yaml.safe_load(handle) or {}

        rubric = self.loader.load(rubric_name)
        judge_prompt = self.renderer.render(session, rubric)

        dims = [d["id"] for d in rubric.get("dimensions", [])]
        scores = {d: None for d in dims}
        llm_used: Optional[str] = None

        if use_llm:
            llm_used = get_current_llm_id()
            response = self._call_llm(llm_used, judge_prompt)
            parsed = self._parse_llm_score_response(response, rubric)
            scores.update(parsed)
            if any(v is None for v in parsed.values()):
                parse_errors.append("One or more dimensions were missing or unparsable")
            self._store_score(session_path, rubric_name, scores, judge_prompt, llm_used, "llm_auto", parse_errors, scored_at)

        overall = self._compute_overall(scores)
        complete = all(v is not None for v in scores.values())

        return ScoringResult(
            session_path=session_path,
            rubric_name=rubric_name,
            scores=scores,
            overall=overall,
            judge_prompt=judge_prompt,
            llm_used=llm_used,
            scored_at=scored_at,
            parse_errors=parse_errors,
            complete=complete,
        )

    def import_scores_from_yaml(self, session_path: str, rubric_name: Optional[str] = None) -> ScoringResult:
        """Import prefilled scores block from a session file."""
        scored_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        parse_errors: List[str] = []

        with open(session_path, "r", encoding="utf-8") as handle:
            session = yaml.safe_load(handle) or {}

        scores_block = session.get("scores", {}) or {}
        selected_rubric = scores_block.get("rubric") or rubric_name
        if not selected_rubric:
            parse_errors.append("scores.rubric is required")
            selected_rubric = "unknown"

        rubric = self.loader.load(selected_rubric) if selected_rubric != "unknown" else {"dimensions": []}
        dims = [d["id"] for d in rubric.get("dimensions", [])]
        provided = (scores_block.get("dimensions") or {})

        scores: Dict[str, Optional[float]] = {}
        for dim in dims:
            value = provided.get(dim)
            if value is None:
                parse_errors.append(f"Missing dimension score: {dim}")
                scores[dim] = None
            else:
                try:
                    scores[dim] = float(value)
                except (TypeError, ValueError):
                    parse_errors.append(f"Non-numeric dimension score: {dim}")
                    scores[dim] = None

        llm_used = scores_block.get("judge")
        judge_prompt = session.get("judge_prompt") or ""
        source = scores_block.get("source") or "manual"

        self._store_score(session_path, selected_rubric, scores, judge_prompt, llm_used, source, parse_errors, scored_at)
        overall = self._compute_overall(scores)
        complete = bool(scores) and all(v is not None for v in scores.values())

        return ScoringResult(
            session_path=session_path,
            rubric_name=selected_rubric,
            scores=scores,
            overall=overall,
            judge_prompt=judge_prompt,
            llm_used=llm_used,
            scored_at=scored_at,
            parse_errors=parse_errors,
            complete=complete,
        )



    def import_scores_from_text(self, session_path: str, rubric_name: str, response_text: str) -> ScoringResult:
        """Parse pasted judge YAML response and store scores for a session."""
        scored_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        parse_errors: List[str] = []

        with open(session_path, "r", encoding="utf-8") as handle:
            session = yaml.safe_load(handle) or {}

        rubric = self.loader.load(rubric_name)
        parsed = self._parse_llm_score_response(response_text, rubric)
        if any(v is None for v in parsed.values()):
            parse_errors.append("One or more dimensions were missing or unparsable")

        judge_prompt = session.get("judge_prompt") or self.renderer.render(session, rubric)

        self._store_score(
            session_path=session_path,
            rubric_name=rubric_name,
            scores=parsed,
            judge_prompt=judge_prompt,
            llm_used=None,
            source="llm_paste",
            parse_errors=parse_errors,
            scored_at=scored_at,
        )

        overall = self._compute_overall(parsed)
        complete = all(v is not None for v in parsed.values())

        return ScoringResult(
            session_path=session_path,
            rubric_name=rubric_name,
            scores=parsed,
            overall=overall,
            judge_prompt=judge_prompt,
            llm_used=None,
            scored_at=scored_at,
            parse_errors=parse_errors,
            complete=complete,
        )

    def _parse_llm_score_response(self, response: str, rubric: Dict) -> Dict:
        """Parse yaml score response from LLM; never raises."""
        dimensions = [d.get("id") for d in rubric.get("dimensions", [])]
        out = {d: None for d in dimensions}

        try:
            text = (response or "").strip()
            if text.startswith("```"):
                lines = text.splitlines()
                if lines and lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip().startswith("```"):
                    lines = lines[:-1]
                text = "\n".join(lines)

            parsed = yaml.safe_load(text) or {}
            scores = ((parsed.get("scores") or {}).get("dimensions") or {})
            for dim in dimensions:
                val = scores.get(dim)
                if val is None:
                    log("warning", f"Judge response missing dimension score: {dim}")
                    out[dim] = None
                else:
                    try:
                        out[dim] = float(val)
                    except (TypeError, ValueError):
                        log("warning", f"Judge response has non-numeric score for {dim}: {val}")
                        out[dim] = None
        except Exception as exc:
            log("error", f"Failed to parse judge score response: {exc}", exc_info=True)

        return out

    def _call_llm(self, llm_id: str, prompt: str) -> str:
        manager = get_llm_manager()
        messages = [{"role": "user", "content": prompt}]
        try:
            return asyncio.run(manager.internal_response(llm_id, messages))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(manager.internal_response(llm_id, messages))
            finally:
                loop.close()

    def _store_score(
        self,
        session_path: str,
        rubric_name: str,
        scores: Dict[str, Optional[float]],
        judge_prompt: str,
        llm_used: Optional[str],
        source: str,
        parse_errors: List[str],
        scored_at: str,
    ) -> None:
        run_id = None
        with get_db_manager().get_session() as db:
            run = db.query(BenchmarkRun).filter(BenchmarkRun.session_file == session_path).order_by(BenchmarkRun.run_at.desc()).first()
            if run:
                run_id = run.id
            dt = datetime.fromisoformat(scored_at.replace("Z", "+00:00"))
            db.add(
                BenchmarkScore(
                    run_id=run_id,
                    session_file=session_path,
                    rubric_name=rubric_name,
                    scores=scores,
                    overall_score=self._compute_overall(scores),
                    judge_llm=llm_used,
                    scored_at=dt,
                    judge_prompt=judge_prompt,
                    source=source,
                    parse_errors=parse_errors,
                )
            )

    @staticmethod
    def _compute_overall(scores: Dict[str, Optional[float]]) -> Optional[float]:
        vals = [v for v in scores.values() if v is not None]
        if not vals:
            return None
        return sum(vals) / len(vals)
