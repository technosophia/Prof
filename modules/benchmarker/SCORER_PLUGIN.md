<!-- /modules/benchmarker/SCORER_PLUGIN.md -->

## Purpose
Guide for creating scorer plugins. A scorer owns its full workflow:
it receives a session dict, renders any UI it needs into a Streamlit container,
and writes its scores to the DB itself.

## Key files
- `scorers/base.py` — ScorerPlugin ABC, ScoringResult dataclass
- `scorers/prompt_renderer.py` — RubricLoader, JudgePromptRenderer (optional, for rubric-based scorers)
- `scoring_pipeline.py` — auto-discovers scorers, lists them, loads results from DB

## Auto-discovery rule
Any file named `scorer_*.py` in `scorers/` is auto-discovered.
It must contain a class named exactly `ScorerPlugin`.
No registration needed anywhere else.

## Minimal scorer template

```python
# scorers/scorer_myname.py
from typing import Dict
from modules.benchmarker.scorers.base import ScorerPlugin, ScoringResult

class ScorerPlugin(ScorerPlugin):   # class name must be ScorerPlugin
    id = "myname"
    name = "My Scorer"

    def compute_score(self, session: Dict, config: Dict, container) -> None:
        session_path = config["session_path"]
        # render UI into container, compute scores, then:
        result = ScoringResult(
            scorer_id=self.id,
            session_path=session_path,
            scores={"my_metric": 0.85},
            scorer_config={},
            source="my_source",
            notes=None,
            scored_at=self._now(),
            complete=True,
        )
        self._write_score(result)
```

## scores dict conventions
- Rubric-based scorers: keys are dimension ids  `{"relevance": 4.0, "accuracy": 3.5}`
- Step-based scorers: keys are step ids  `{"s1": 0.82, "s2": 0.79}`
- Single metric: one descriptive key  `{"similarity": 0.81}`
- `overall` is computed automatically as mean of all non-None values

## Rubric usage (optional)
```python
from modules.benchmarker.scorers.prompt_renderer import RubricLoader, JudgePromptRenderer
rubric = RubricLoader().load(rubric_name)   # reads rubrics/*.yaml
prompt = JudgePromptRenderer().render(session, rubric)
```
The scorer decides when and whether to show a rubric selector.
The benchmarker judge tab does not manage rubrics.

## expected_response
Always optional. Never assume it exists.
```python
step.get("expected_response", "")   # safe access
```

## Do
- Name file `scorer_*.py`, class `ScorerPlugin`
- Render UI into `container`, not `st.*` directly
- Call `self._write_score(result)` when ready — only once per submit
- Populate `parse_errors` on failure, set `complete=False`
- Use `log()` from `core.logging`

## Don't
- Don't register manually anywhere
- Don't import other scorer plugins
- Don't modify the session dict or file
- Don't call `_write_score()` more than once per user interaction
- Don't hardcode config values — use app JSON config via `get_section()`
