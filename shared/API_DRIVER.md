<!-- shared/driver.py -->

<!-- GENERATED FILE - do not edit manually -->
<!-- Source: shared/driver.py -->

# API — driver

Programmatic app driver for Professor that can run interactions without Streamlit UI.

## Data Models

### `DriverContext`
Execution context used by actions.

Fields:
- `student_id: Optional[str]`
- `trainer_id: Optional[str]`
- `conversation_id: Optional[str]`
- `llm_id: Optional[str]`

### `ContextSwitchEvent`
Fields:
- `timestamp: str` (ISO UTC)
- `type: str = "context_switch"`
- `data: Dict`

### `OptionSwitchEvent`
Fields:
- `timestamp: str`
- `type: str = "option_switch"`
- `group: str`
- `option: str`
- `previous: Optional[str]`

### `ActionEvent`
Fields:
- `timestamp: str`
- `type: str = "action"`
- `name: str`
- `params: Dict`
- `result: Dict`
- `error: Optional[str]`

### `PluginEvent`
Fields:
- `timestamp: str`
- `type: str = "plugin_event"`
- `plugin_id: str`
- `event: str`
- `data: Dict`

### `LLMCallEvent`
Fields:
- `timestamp: str`
- `type: str = "llm_call"`
- `llm_id: str`
- `prompt_tokens: int`
- `completion_tokens: int`
- `action_ref: Optional[str]`

All event dataclasses support YAML-serialisable export with `to_dict()`.

## Exceptions

- `DriverError`: base class for driver failures
- `DriverContextError`: missing/invalid execution context
- `DriverOptionError`: option registration/switch failure
- `DriverActionError`: action registration/execution failure

## Public API

### `get_driver() -> AppDriver`
Returns the global `AppDriver` singleton (cached streamlit resource).

### `AppDriver.register_option(group, name, activate_fn, deactivate_fn, description="")`
Register a switchable option in a logical group.

### `AppDriver.register_action(name, handler_fn, description="", required_context=None)`
Register an action callable executed by `do_action()`.

Registration responsibility:
- Modules register options and actions for themselves and their plugins.
- Plugins implement handler methods only.
- A plugin never calls register_option() or register_action() directly.

### `AppDriver.set_context(**kwargs)`
Set one or more context fields and record a `context_switch` event.

### `AppDriver.get_context() -> DriverContext`
Return a copy of current context.

### `AppDriver.clear_context()`
Reset context to all `None` and record a `context_switch` event.

### `AppDriver.switch_option(group, name)`
Deactivate currently active option for a group, activate target option, then record an `option_switch` event.

### `AppDriver.get_active_option(group) -> Optional[str]`
Get active option name for a group.

### `AppDriver.list_options() -> Dict[str, List[Dict]]`
List registered options by group as:
`{"name": str, "description": str, "active": bool}`.

### `AppDriver.do_action(name, **params) -> Dict`
Execute a registered action with context validation and action event recording.

### `AppDriver.list_actions() -> List[Dict]`
List registered actions as:
`{"name": str, "description": str, "required_context": List[str]}`.

### `AppDriver.start_session(scenario_name="")`
Clear session events and start a new in-memory session.

### `AppDriver.record_plugin_event(plugin_id, event, data=None)`
Record plugin-specific event into current session.

### `AppDriver.record_llm_call(llm_id, prompt_tokens, completion_tokens, action_ref=None)`
Record an LLM usage event into current session.

### `AppDriver.get_session_events() -> List[Dict]`
Get full in-memory event log as plain dictionaries.

### `AppDriver.get_session_summary() -> Dict`
Return aggregate metrics:
- `total_actions`
- `total_llm_calls`
- `total_tokens`
- `active_options`
- `facts_created`
- `facts_updated`
- `duration_seconds`

## Usage example

```python
from shared.common import get_driver


def activate_memory():
    print("memory on")


def deactivate_memory():
    print("memory off")


def send_student_message(context, content: str):
    return {
        "student_id": context.student_id,
        "conversation_id": context.conversation_id,
        "echo": content,
    }


driver = get_driver()
driver.start_session("demo")

driver.register_option("memory_backend", "memory", activate_memory, deactivate_memory,
                       "Pedagogical SQL memory")
driver.register_action("send_student_message", send_student_message,
                       required_context=["student_id", "conversation_id"])

driver.set_context(student_id="s1", trainer_id="t1", conversation_id="c1", llm_id="groq")
driver.switch_option("memory_backend", "memory")
result = driver.do_action("send_student_message", content="Hello")
events = driver.get_session_events()
```
