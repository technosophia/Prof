"""External LLM judge scorer plugin."""

from typing import Dict

from modules.benchmarker.scorers.base import ScorerPlugin as BaseScorerPlugin, ScoringResult


class ScorerPlugin(BaseScorerPlugin):
    """External LLM scoring workflow."""

    id = "llm_external"
    name = "External LLM Judge"

    def compute_score(self, session: Dict, config: Dict, container) -> None:
        from modules.benchmarker.scorers.prompt_renderer import RubricLoader, JudgePromptRenderer

        session_path = config["session_path"]
        loader = RubricLoader()
        available_rubrics = loader.list_available()

        if not available_rubrics:
            container.warning("No rubrics found.")
            return

        rubric_key = f"llm_ext_rubric_{session_path}"
        rubric_name = container.selectbox("Rubric", available_rubrics, key=rubric_key)
        rubric = loader.load(rubric_name)

        prompt = JudgePromptRenderer().render(session, rubric)
        with container.expander("Judge prompt — copy this to your LLM", expanded=False):
            container.code(prompt, language="text")

        paste_key = f"llm_ext_paste_{session_path}"
        pasted = container.text_area(
            "Paste the LLM response here (YAML format expected)",
            height=200,
            key=paste_key,
        )

        submit_key = f"llm_ext_submit_{session_path}"
        if container.button("Import scores", key=submit_key) and pasted:
            scores, parse_errors = self._parse_response(pasted, rubric)
            result = ScoringResult(
                scorer_id=self.id,
                session_path=session_path,
                scores=scores,
                scorer_config={"rubric": rubric_name},
                source="llm_paste",
                notes=None,
                scored_at=self._now(),
                parse_errors=parse_errors,
                complete=not parse_errors,
            )
            self._write_score(result)
            if parse_errors:
                container.warning(f"Saved with errors: {parse_errors}")
            else:
                container.success(f"Scores imported. Overall: {result.overall:.2f}")

    def _parse_response(self, text: str, rubric: dict):
        """Parse YAML judge response. Returns (scores_dict, parse_errors)."""
        import yaml

        dimensions = [d["id"] for d in rubric.get("dimensions", [])]
        scores = {d: None for d in dimensions}
        parse_errors = []
        try:
            cleaned = text.strip()
            if cleaned.startswith("```"):
                lines = cleaned.splitlines()
                cleaned = "\n".join(
                    line for line in lines
                    if not line.strip().startswith("```")
                )
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
