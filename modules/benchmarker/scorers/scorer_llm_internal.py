"""Internal LLM judge scorer plugin."""

import asyncio
from typing import Dict

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
            prompt = renderer.render(session, rubric)
            response_text, response_error = self._call_llm(manager, llm_id, prompt)
            scores, parse_errors = self._parse_response(response_text, rubric)
            if response_error:
                parse_errors.append(response_error)

            result = ScoringResult(
                scorer_id=self.id,
                session_path=session_path,
                scores=scores,
                scorer_config={"rubric": rubric_name, "llm_id": llm_id},
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

    def _call_llm(self, manager, llm_id: str, prompt: str):
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
