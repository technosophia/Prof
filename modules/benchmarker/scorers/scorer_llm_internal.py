"""Internal LLM judge scorer plugin."""

import asyncio
from typing import Dict, List, Tuple

from shared.common import get_current_llm_id, get_llm_manager
from modules.benchmarker.scorers.base import ScorerPlugin as BaseScorerPlugin, ScoringResult


class ScorerPlugin(BaseScorerPlugin):
    """Use currently selected internal LLM to judge one or many rubrics."""

    id = "llm_internal"
    name = "Internal LLM Judge"

    def compute_score(self, session: Dict, config: Dict, container) -> None:
        from modules.benchmarker.scorers.prompt_renderer import RubricLoader, JudgePromptRenderer

        session_path = config["session_path"]
        loader = RubricLoader()
        available_rubrics = loader.list_available()
        if not available_rubrics:
            container.warning("No rubrics found.")
            return

        selected = container.multiselect(
            "Rubrics",
            available_rubrics,
            default=available_rubrics[:1],
            key=f"llm_internal_rubrics_{session_path}",
        )
        if not selected:
            container.info("Select at least one rubric.")
            return

        renderer = JudgePromptRenderer()
        preview_rubric = loader.load(selected[0])
        prompt = renderer.render(session, preview_rubric)
        prompt_expander = container.expander("Judge prompt — copy this to your LLM", expanded=False)
        prompt_expander.code(prompt, language="text")

        if not container.button("Score selected rubrics", key=f"llm_internal_submit_{session_path}"):
            return

        llm_id = get_current_llm_id()
        manager = get_llm_manager()
        for rubric_name in selected:
            rubric = loader.load(rubric_name)
            self._score_rubric(session, session_path, rubric_name, rubric, llm_id, manager, renderer, container)

    def compute_score_all_rubrics(self, session: Dict, config: Dict, container) -> None:
        """Score all available rubrics without rubric selection UI."""
        from modules.benchmarker.scorers.prompt_renderer import RubricLoader, JudgePromptRenderer

        session_path = config["session_path"]
        loader = RubricLoader()
        available_rubrics = loader.list_available()
        if not available_rubrics:
            container.warning("No rubrics found.")
            return

        renderer = JudgePromptRenderer()
        llm_id = get_current_llm_id()
        manager = get_llm_manager()

        completed = 0
        with_errors = 0
        for rubric_name in available_rubrics:
            rubric = loader.load(rubric_name)
            parse_errors = self._score_rubric(
                session,
                session_path,
                rubric_name,
                rubric,
                llm_id,
                manager,
                renderer,
                container,
            )
            completed += 1
            if parse_errors:
                with_errors += 1

        container.info(
            f"Internal LLM Judge completed: {completed} rubric(s), {with_errors} with parsing/call errors."
        )

    def _score_rubric(self, session, session_path, rubric_name, rubric, llm_id, manager, renderer, container) -> List[str]:
        prompt = renderer.render(session, rubric)
        response_text, response_error = self._call_llm(manager, llm_id, prompt)
        scores, parse_errors = self._parse_response(response_text, rubric)
        if response_error:
            parse_errors.append(response_error)

        # step-level pass for user exchanges
        qualifying_steps = [
            step
            for step in session.get("steps", [])
            if step.get("action") == "user_send_message"
            and str((step.get("result") or {}).get("llm_response", "")).strip()
        ]
        for step in qualifying_steps:
            step_prompt = self._build_step_prompt(step, rubric)
            step_response_text, step_response_error = self._call_llm(manager, llm_id, step_prompt)
            step_scores, step_parse_errors = self._parse_response(step_response_text, rubric)
            if step_response_error:
                step_parse_errors.append(step_response_error)
            step_result = ScoringResult(
                scorer_id=self.id,
                session_path=session_path,
                scores=step_scores,
                scorer_config={
                    "rubric": rubric_name,
                    "llm_id": llm_id,
                    "level": "step",
                    "step_id": step.get("id"),
                },
                source="llm_internal",
                notes=None,
                scored_at=self._now(),
                parse_errors=step_parse_errors,
                complete=not step_parse_errors,
            )
            self._write_score(step_result)

        result = ScoringResult(
            scorer_id=self.id,
            session_path=session_path,
            scores=scores,
            scorer_config={"rubric": rubric_name, "llm_id": llm_id, "level": "session"},
            source="llm_internal",
            notes=None,
            scored_at=self._now(),
            parse_errors=parse_errors,
            complete=not parse_errors,
        )
        self._write_score(result)

        if parse_errors:
            container.warning(f"{rubric_name}: saved with errors: {parse_errors}")
        else:
            container.success(f"{rubric_name}: scored. Overall: {result.overall:.2f}")
        return parse_errors

    def _build_step_prompt(self, step: Dict, rubric: Dict) -> str:
        """Render a focused judging prompt for a single user->assistant exchange."""
        step_id = step.get("id", "unknown")
        user_message = str((step.get("params") or {}).get("content", "")).strip()
        llm_response = str((step.get("result") or {}).get("llm_response", "")).strip()
        expected_response = str(step.get("expected_response", "")).strip()

        dims = rubric.get("dimensions", [])
        dims_block = "\n".join(
            f"- {dim.get('id')}: {dim.get('description', '')}"
            for dim in dims
        )

        expected_block = f"\nExpected answer guidance:\n{expected_response}\n" if expected_response else ""

        return (
            "You are judging a single tutoring exchange.\n"
            f"Rubric: {rubric.get('name', '')}\n\n"
            "Dimensions:\n"
            f"{dims_block}\n\n"
            f"Step ID: {step_id}\n"
            "Student message:\n"
            f"{user_message}\n\n"
            "Assistant response:\n"
            f"{llm_response}\n"
            f"{expected_block}\n"
            "Return ONLY YAML in this exact structure:\n"
            "scores:\n"
            "  dimensions:\n"
            "    <dimension_id>: <0-5 float>\n"
        )

    def _call_llm(self, manager, llm_id: str, prompt: str) -> Tuple[str, str | None]:
        messages = [{"role": "user", "content": prompt}]
        try:
            text = asyncio.run(manager.internal_response(llm_id, messages))
            return text, None
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                text = loop.run_until_complete(manager.internal_response(llm_id, messages))
                return text, None
            finally:
                loop.close()
        except Exception as exc:
            return "", f"LLM call failed: {exc}"

    def _parse_response(self, text: str, rubric: dict):
        import yaml

        dimensions = [d["id"] for d in rubric.get("dimensions", [])]
        scores = {d: None for d in dimensions}
        parse_errors = []
        try:
            cleaned = text.strip()
            if cleaned.startswith("```"):
                lines = cleaned.splitlines()
                cleaned = "\n".join(line for line in lines if not line.strip().startswith("```"))
            parsed = yaml.safe_load(cleaned) or {}
            dim_scores = (parsed.get("scores") or {}).get("dimensions") or {}
            for dim in dimensions:
                val = dim_scores.get(dim)
                if val is None:
                    parse_errors.append(f"Missing dimension: {dim}")
                else:
                    try:
                        scores[dim] = float(val)
                    except (TypeError, ValueError):
                        parse_errors.append(f"Non-numeric value for {dim}: {val}")
        except Exception as exc:
            parse_errors.append(f"YAML parse error: {exc}")
        return scores, parse_errors
