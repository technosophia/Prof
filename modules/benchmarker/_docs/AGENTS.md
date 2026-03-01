# Benchmarker assertions and scenario step fields

## Assertion types

| Type | Params | Meaning |
|---|---|---|
| `action_succeeded` | `step_id` | Step completed without errors |
| `llm_calls_made` | `min` (opt), `max` (opt) | Number of LLM calls is in range |
| `plugin_event_occurred` | `plugin_id`, `event` | Driver plugin event occurred |
| `option_was_active` | `group`, `name` | Option switch event was recorded |
| `context_field_set` | `field`, `value` (opt) | Context switch set field (and value if provided) |
| `injected_context_contains` | `step_id`, `contains` (opt), `not_contains` (opt), `source_contains` (opt) | Injected context matching criteria |
| `response_contains_semantic` | `step_id`, `contains`, `threshold` (opt, default 0.70), `mode` (opt, "embedding"/"substring") | LLM response semantically contains expected concept |
| `memory_contains_semantic` | `step_id`, `contains`, `threshold` (opt, default 0.70), `mode` (opt) | Memory content semantically contains expected concept |

## Step expected fields

- `expected_response`: used on `user_send_message` steps.
- `expected_memory`: used on `trigger_memory_analysis` steps and auto-generates `auto_memory_<step_id>` assertions.
