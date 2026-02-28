# Scorer Plugin Contract

Scorers live in `modules/benchmarker/scorers/` and must implement `ScorerPlugin`.

## Rules
- Never import Streamlit in scorer files.
- Never mutate session dicts or session YAML files.
- Read configuration values from JSON config (`config.json`) or scorer config dict.
- Return `ScoringResult` from `score()` and never raise.
- Use `core.logging.log()` for diagnostics.

## Score keys
- Rubric scorers: keys are rubric dimension IDs.
- Embedding scorer: keys are scenario step IDs.

## Persistence
- Normal path: pipeline calls `persist_result()` after `score()`.
- `ManualScorer.import_from_session_yaml()` persists directly for explicit import action.
