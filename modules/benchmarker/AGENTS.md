# Benchmarker module

## Goal
Provide a scenario replay engine with assertions, session serialization,
LLM-as-judge scoring, and cross-run comparisons.

## Architecture
One-way dependency flow:
1. **driver** receives option/context/action commands
2. **runner** validates + replays scenario steps and computes assertions
3. **session** serializes run result + raw driver events to YAML
4. **scorer** loads rubrics, renders judge prompts, scores sessions, stores score history
5. **comparer** groups runs by option value and computes report statistics
6. **ui** renders run, history, judge, and compare views

Do not reverse dependencies (UI must not directly run driver internals).

## Core actions
Core scenario actions are implemented in `core_actions.py` and registered by
`initialize()` in `__init__.py`. They are benchmarker-level actions and must not
import app modules directly.

## LLM as option
- LLM options are registered by benchmarker during `initialize()` using `get_available_llms()`.
- Option group name is `"llm"`.
- No mid-session LLM switching: set once in scenario `options:` at scenario start.

## Scorer
- Implemented in `scorer.py`.
- Rubrics are YAML files under `rubrics/`.
- Judge prompt is rendered automatically and stored in session YAML and DB.
- Score sources: `llm_auto`, `llm_paste`, `manual`.
- Parsing is graceful on failure and never raises.

## Comparer
- Implemented in `comparer.py`.
- Groups by option group value (e.g., `memory_backend`, `llm`).
- Requires `BenchmarkRun` records; scores are optional.
- Report YAML is written to `data/benchmarker/sessions/`.

## Add a new scenario
1. Copy `scenarios/example_basic.yaml`
2. Keep `meta`, `setup`, `steps`, and `assertions` blocks
3. Use `bench_` prefixed user IDs only
4. Use only driver-registered actions/options

## Add a new assertion type
1. Extend `_evaluate_assertions()` in `runner.py`
2. Document required params in this file
3. Add matching unit tests in `tests/benchmarker/test_runner.py`

## Avoid
- Do NOT import trainer, RAG, or any app module directly
- Do NOT switch LLM mid-scenario — set it in `options:` at scenario start
- Do NOT call LLM during assertion evaluation (scorer only)
- Do NOT store full LLM responses in session YAML (truncate)
- Do NOT use production user IDs in scenarios (`bench_` prefix only)
