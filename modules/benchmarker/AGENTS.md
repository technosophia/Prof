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


## Assertion types

| Type | Params | Meaning |
|---|---|---|
| `action_succeeded` | `step_id` | Step completed without errors |
| `llm_calls_made` | `min` (opt), `max` (opt) | Number of LLM calls is in range |
| `plugin_event_occurred` | `plugin_id`, `event` | Driver plugin event occurred |
| `option_was_active` | `group`, `name` | Option switch event was recorded |
| `context_field_set` | `field`, `value` (opt) | Context switch set field (and value if provided) |
| `injected_context_contains` | `step_id`, `contains` (opt), `source_contains` (opt) | Context matching criteria was injected into LLM for that step |

### How `injected_context_contains` works

`action_user_send_message` registers a one-shot monitor callback on the
LLM manager before each LLM call. The monitor callback captures all messages
in `filtered_messages` that have a `source` field — these are the injected
context messages added by `_add_llm_context()` in `shared/llm.py`.

The `source` field is the `__name__` of the registered callback, e.g.:
- `"get_memory_context"` — from the memory plugin
- `"get_student_notes_context"` — from the student_pad plugin
- `"rag_context_callback"` — from the RAG engine (verify actual name in RAG code)

Use `source_contains` with a substring (e.g. `"rag"`, `"memory"`, `"student_pad"`)
rather than the exact callback name, which may change.


## Actor semantics

Scenarios use three actor values:

| actor | context fields used | typical actions |
|---|---|---|
| `student` | `student_id`, `conversation_id` | `user_send_message`, `create_conversation` |
| `teacher` | `trainer_id`, `student_id`, `conversation_id` | `teacher_send_message`, `trigger_memory_analysis`, `set_training_program`, `add_student_note` |
| `system` | any | `create_conversation`, `set_training_program`, `switch_option` |

`actor: teacher` means the action runs with `trainer_id` from the driver
context (set from `setup.trainer_id` at scenario start). It does NOT require
a separate `teacher_id` field — the trainer IS the teacher in this app.

Actor validation: violations log a WARNING and record a step error.
The run continues (does not abort).
