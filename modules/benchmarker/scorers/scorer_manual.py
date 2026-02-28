"""Manual rubric scorer plugin."""

from typing import Dict

from modules.benchmarker.scorers.base import ScorerPlugin as BaseScorerPlugin, ScoringResult


class ScorerPlugin(BaseScorerPlugin):
    """Manual scoring with rubric sliders."""

    id = "manual"
    name = "Manual Scoring"

    def compute_score(self, session: Dict, config: Dict, container) -> None:
        import streamlit as st
        from modules.benchmarker.scorers.prompt_renderer import RubricLoader

        del session
        del st

        session_path = config["session_path"]
        loader = RubricLoader()
        available_rubrics = loader.list_available()

        if not available_rubrics:
            container.warning("No rubrics found in rubrics/ directory.")
            return

        rubric_key = f"manual_rubric_{session_path}"
        rubric_name = container.selectbox("Rubric", available_rubrics, key=rubric_key)
        rubric = loader.load(rubric_name)
        dimensions = rubric.get("dimensions", [])

        scores = {}
        for dim in dimensions:
            slider_key = f"manual_{session_path}_{dim['id']}"
            scores[dim["id"]] = container.slider(
                label=f"{dim['id']} — {dim['question']}",
                min_value=1,
                max_value=int(dim.get("scale", 5)),
                value=3,
                key=slider_key,
                help=dim.get("guidance", ""),
            )

        notes_key = f"manual_notes_{session_path}"
        notes = container.text_area("Notes (optional)", key=notes_key)

        submit_key = f"manual_submit_{session_path}"
        if container.button("Save scores", key=submit_key):
            result = ScoringResult(
                scorer_id=self.id,
                session_path=session_path,
                scores=scores,
                scorer_config={"rubric": rubric_name},
                source="manual",
                notes=notes or None,
                scored_at=self._now(),
                parse_errors=[],
                complete=True,
            )
            self._write_score(result)
            container.success(f"Scores saved. Overall: {result.overall:.2f}")
