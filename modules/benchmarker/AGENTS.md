# Benchmarker module

## Goal
Provide a minimal scenario replay engine with assertions and session serialization,
forming the foundation for future benchmark scoring and comparison phases.

## Architecture
One-way dependency flow:
1. **driver** receives option/context/action commands
2. **runner** validates + replays scenario steps and computes assertions
3. **session** serializes run result + raw driver events to YAML
4. **ui** renders run and history views

Do not reverse dependencies (UI must not directly run driver internals).

## Core actions
Core scenario actions are implemented in `core_actions.py` and registered by
`initialize()` in `__init__.py`. They are benchmarker-level actions and must not
import app modules directly.

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
- Do NOT make LLM calls during assertion evaluation
- Do NOT store full LLM responses in session YAML (truncate)
- Do NOT use production user IDs in scenarios (`bench_` prefix only)
- Do NOT add judge/scorer/reporter logic in this module

## Future phases (out of scope)
- Phase 2: LLM-as-judge scoring and rubrics
- Phase 3: comparison reporter across runs
- Phase 4: integration of trainer, RAG, student_pad option switching
