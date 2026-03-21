# SCENARIO.md

<!-- /modules/benchmarker/SCENARIO.md -->

## Purpose
Define the YAML format for benchmark scenarios: reusable test sequences that simulate student-teacher interactions and validate system behavior through assertions.

## Principles
1. **Deterministic replay** – Scenarios must produce identical behavior given the same configuration
2. **Self-contained validation** – Assertions verify both execution success and semantic content
3. **Actor-based execution** – Each step runs with specific context (student/teacher/system)
4. **Plugin integration** – Test RAG, memory plugins, and student pad through realistic flows

## File structure

```yaml
meta:
  name: "scenario_name"           # Required: unique identifier
  description: "..."               # Optional: human-readable purpose
  version: "1.0"                   # Optional: scenario format version
  fixture_doc: "path/to/doc.md"    # Optional: document that must be ingested before run
  prerequisite: "..."               # Optional: free-text setup instructions

llm: "ollama_qwen"                  # Optional: default LLM (can be overridden)

options:                            # Optional: plugin configuration
  memory_backend: "pedagogical_memory+student_pad"
  rag_engine: "classic"

setup:
  student_id: "normal2_m1"         # Required: user ID for student actions
  trainer_id: "master1"             # Required: user ID for teacher actions

steps:
  - id: "s1"                        # Required: unique step identifier
    actor: system                    # Required: student/teacher/system
    action: create_conversation      # Required: action name
    params:                          # Action-specific parameters
      title: "Week 1 - Introduction"
    expected_response: "..."         # Optional: for response-based scorers
    expected_memory: "..."           # Optional: auto-generates memory assertion

assertions:                          # Optional: validation rules
  - id: "a1"
    type: action_succeeded
    description: "Conversation created"
    params:
      step_id: "s1"
```

## Actors and context

| Actor | Context used | Typical actions |
|-------|--------------|-----------------|
| `student` | `student_id`, `conversation_id` | `user_send_message`, `create_conversation`, `add_student_note` |
| `teacher` | `trainer_id`, `student_id`, `conversation_id` | `teacher_send_message`, `trigger_memory_analysis` |
| `system` | any (can set context fields) | `create_conversation`, `switch_option` |

Context is automatically set from `setup` before steps run. The driver maintains current `student_id`, `trainer_id`, `conversation_id`, and `llm_id` throughout execution.

## Available actions

### `create_conversation` (system, student)
Creates a new conversation and sets `conversation_id` in driver context.
```yaml
params:
  title: "Conversation title"
```

### `user_send_message` (student)
Sends a student message, triggers LLM generation, and captures injected context.
```yaml
params:
  content: "What is a tuple?"
```
The LLM response is saved; all context injected by plugins (RAG, memory, student pad) is captured in `injected_contexts` for assertions.

### `teacher_send_message` (teacher)
Injects a teacher/system message without LLM call.
```yaml
params:
  content: "Great question!"
```

### `trigger_memory_analysis` (teacher)
Runs memory analysis on recent conversations to update student memory.
```yaml
params: {}  # No parameters needed
```

### `add_student_note` (student)
Adds a personal note to the student pad (injected in future conversations).
```yaml
params:
  content: "Remember: Voss Review triggers at 400 lines"
  topic: "voss_review"  # Optional
```

### `switch_option` (system)
Changes a driver option mid-scenario (rarely needed – options usually set at scenario start).
```yaml
params:
  group: "memory_backend"
  name: "pedagogical_memory"
```

## Assertion types

### Execution assertions

| Type | Params | Description |
|------|--------|-------------|
| `action_succeeded` | `step_id` | Step completed without errors |
| `llm_calls_made` | `min`, `max` | Number of LLM calls is in range |
| `plugin_event_occurred` | `plugin_id`, `event` | Driver plugin event was recorded |
| `option_was_active` | `group`, `name` | Option switch event was recorded |
| `context_field_set` | `field`, `value` | Context field was set (optionally to specific value) |

### Content assertions

| Type | Params | Description |
|------|--------|-------------|
| `injected_context_contains` | `step_id`, `contains`, `not_contains`, `source_contains` | Substring matching in injected context |
| `injected_context_contains_semantics` | `step_id`, `contains`, `threshold`, `source_contains` | Semantic similarity (embedding-based) in injected context |
| `response_contains_semantic` | `step_id`, `contains`, `threshold` | LLM response semantically contains concept |
| `memory_contains_semantic` | `step_id`, `contains`, `threshold` | Memory analysis output semantically contains concept |
| `response_similarity` | `step_id`, `threshold` | Full-document cosine similarity vs `expected_response` |

### Parameter details

- **`contains`**: string or list of strings to search for
- **`not_contains`**: string or list of strings that must NOT appear
- **`source_contains`**: filter context by source (e.g., `"rag"`, `"memory"`, `"student_pad"`)
- **`threshold`**: similarity threshold (default varies by assertion, typically 0.45–0.70)
- **`step_id`**: which step to examine

## Examples

### Basic example (from `example_basic.yaml`)
```yaml
meta:
  name: "basic_student_teacher"
  description: "One student sends two messages"

llm: "ollama_qwen"

setup:
  student_id: "normal2_m1"
  trainer_id: "master1"

steps:
  - id: "s1"
    actor: system
    action: create_conversation
    params:
      title: "Week 1 - Introduction"

  - id: "s2"
    actor: student
    action: user_send_message
    params:
      content: "What is the difference between a list and a tuple?"

assertions:
  - id: "a1"
    type: action_succeeded
    params:
      step_id: "s1"
```

## Common pitfalls

### Context injection fails
`injected_contexts` will be empty if:
- `llm_conversation_generate()` is called without `user_id`
- The call routes to `internal_response()` instead of `generate()`
- The monitor callback isn't registered (automatic for `user_send_message`)

### Options not activating
If options are applied before `set_context(trainer_id=...)`, plugins won't activate. The runner handles this correctly by setting context BEFORE applying options.

### RAG "no results" markers
Assertions automatically fail if injected context contains phrases like "no rag results found" – this ensures RAG actually retrieved content.

## See also
- `AGENTS.md` – Benchmarker module overview
- `full_nexoria.yaml` – Complete example with RAG+memory+pad
- `runner.py` – Assertion evaluation implementation
- `driver_assertions.py` – Semantic assertion handlers
