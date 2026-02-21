"""Programmatic app driver for non-UI interactions.
[api]
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


LLM option group:
The benchmarker module registers available LLMs as options in group "llm".
This is the canonical example of an option registered by a module rather than
by the resource it controls (llm.py does not register itself).
Pattern: any module can register options for shared resources it wants to
benchmark, without modifying the shared resource's code.


"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Callable, Dict, List, Optional

import streamlit as st

from shared.common import log


class DriverError(Exception):
    """Base class for driver errors."""


class DriverContextError(DriverError):
    """Raised when required context is missing."""


class DriverOptionError(DriverError):
    """Raised when option registration or switch fails."""


class DriverActionError(DriverError):
    """Raised when action registration or execution fails."""


@dataclass
class DriverContext:
    """Execution context for actions performed through the driver."""

    student_id: Optional[str] = None
    trainer_id: Optional[str] = None
    conversation_id: Optional[str] = None
    llm_id: Optional[str] = None


@dataclass
class ContextSwitchEvent:
    """Event emitted when the active context changes."""

    timestamp: str
    type: str = "context_switch"
    data: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Return a YAML-serializable dictionary representation."""
        return asdict(self)


@dataclass
class OptionSwitchEvent:
    """Event emitted when an option is switched."""

    timestamp: str
    group: str
    option: str
    previous: Optional[str] = None
    type: str = "option_switch"

    def to_dict(self) -> Dict:
        """Return a YAML-serializable dictionary representation."""
        return asdict(self)


@dataclass
class ActionEvent:
    """Event emitted when an action is executed."""

    timestamp: str
    name: str
    params: Dict = field(default_factory=dict)
    result: Dict = field(default_factory=dict)
    error: Optional[str] = None
    type: str = "action"

    def to_dict(self) -> Dict:
        """Return a YAML-serializable dictionary representation."""
        return asdict(self)


@dataclass
class PluginEvent:
    """Event emitted by plugins via record_plugin_event()."""

    timestamp: str
    plugin_id: str
    event: str
    data: Dict = field(default_factory=dict)
    type: str = "plugin_event"

    def to_dict(self) -> Dict:
        """Return a YAML-serializable dictionary representation."""
        return asdict(self)


@dataclass
class LLMCallEvent:
    """Event emitted when an LLM call happens."""

    timestamp: str
    llm_id: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    action_ref: Optional[str] = None
    type: str = "llm_call"

    def to_dict(self) -> Dict:
        """Return a YAML-serializable dictionary representation."""
        return asdict(self)


class AppDriver:
    """Programmatic driver for the Professor app."""

    def __init__(self):
        self._lock = RLock()
        self._context = DriverContext()
        self._options: Dict[str, Dict[str, Dict]] = {}
        self._active_options: Dict[str, str] = {}
        self._actions: Dict[str, Dict] = {}
        self._session_events: List[Dict] = []
        self._session_meta: Dict = {
            "scenario_name": "",
            "started_at": self._now_iso(),
            "ended_at": None,
        }

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def register_option(
        self,
        group: str,
        name: str,
        activate_fn: Callable[[], None],
        deactivate_fn: Callable[[], None],
        description: str = "",
    ) -> None:
        """Register a switchable option (plugin, engine, etc.)."""
        if not group or not name:
            raise DriverOptionError("Option registration requires non-empty group and name")

        with self._lock:
            group_options = self._options.setdefault(group, {})
            group_options[name] = {
                "activate_fn": activate_fn,
                "deactivate_fn": deactivate_fn,
                "description": description,
            }
            log("debug", f"Driver option registered: {group}.{name}")

    def register_action(
        self,
        name: str,
        handler_fn: Callable[..., Dict],
        description: str = "",
        required_context: Optional[List[str]] = None,
    ) -> None:
        """Register a driveable action."""
        if not name:
            raise DriverActionError("Action registration requires non-empty action name")

        with self._lock:
            self._actions[name] = {
                "handler_fn": handler_fn,
                "description": description,
                "required_context": list(required_context or []),
            }
            log("debug", f"Driver action registered: {name}")

    def set_context(self, **kwargs) -> None:
        """Set one or more context fields and record an event."""
        valid_fields = DriverContext.__dataclass_fields__.keys()
        with self._lock:
            for key, value in kwargs.items():
                if key not in valid_fields:
                    raise DriverContextError(f"Unknown context field: {key}")
                setattr(self._context, key, value)

            snapshot = asdict(self._context)
            self._session_events.append(ContextSwitchEvent(timestamp=self._now_iso(), data=snapshot).to_dict())

    def get_context(self) -> DriverContext:
        """Return a copy of the current context."""
        with self._lock:
            return DriverContext(**asdict(self._context))

    def clear_context(self) -> None:
        """Reset context to all-None and record an event."""
        with self._lock:
            self._context = DriverContext()
            self._session_events.append(
                ContextSwitchEvent(timestamp=self._now_iso(), data=asdict(self._context)).to_dict()
            )

    def switch_option(self, group: str, name: str) -> None:
        """Switch active option for a group and record an event."""
        with self._lock:
            group_options = self._options.get(group)
            if not group_options:
                raise DriverOptionError(f"Option group not registered: {group}")
            option = group_options.get(name)
            if not option:
                raise DriverOptionError(f"Option '{name}' is not registered in group '{group}'")

            previous = self._active_options.get(group)
            if previous == name:
                self._session_events.append(
                    OptionSwitchEvent(timestamp=self._now_iso(), group=group, option=name, previous=previous).to_dict()
                )
                return

            if previous and previous in group_options:
                try:
                    group_options[previous]["deactivate_fn"]()
                except Exception as e:
                    log("error", f"Error while deactivating option {group}.{previous}: {e}", exc_info=True)

            try:
                option["activate_fn"]()
            except Exception as e:
                log("error", f"Error while activating option {group}.{name}: {e}", exc_info=True)
                raise DriverOptionError(f"Failed to activate option '{name}' in group '{group}'") from e

            self._active_options[group] = name
            self._session_events.append(
                OptionSwitchEvent(timestamp=self._now_iso(), group=group, option=name, previous=previous).to_dict()
            )

    def get_active_option(self, group: str) -> Optional[str]:
        """Return the currently active option for a group."""
        with self._lock:
            return self._active_options.get(group)

    def list_options(self) -> Dict[str, List[Dict]]:
        """List all registered options grouped by group name."""
        with self._lock:
            output: Dict[str, List[Dict]] = {}
            for group, options in self._options.items():
                active = self._active_options.get(group)
                output[group] = [
                    {
                        "name": name,
                        "description": data.get("description", ""),
                        "active": active == name,
                    }
                    for name, data in options.items()
                ]
            return output

    def do_action(self, name: str, **params) -> Dict:
        """Execute a registered action in the current context."""
        with self._lock:
            action = self._actions.get(name)
            if not action:
                raise DriverActionError(f"Action not registered: {name}")

            context = DriverContext(**asdict(self._context))
            missing_fields = [
                field_name
                for field_name in action.get("required_context", [])
                if not getattr(context, field_name, None)
            ]
            if missing_fields:
                missing = ", ".join(missing_fields)
                raise DriverContextError(f"Missing required context field(s) for action '{name}': {missing}")

        action_event = ActionEvent(timestamp=self._now_iso(), name=name, params=params)

        try:
            result = action["handler_fn"](context=context, **params)
            action_event.result = result if isinstance(result, dict) else {"result": result}
            return action_event.result
        except Exception as e:
            action_event.error = str(e)
            log("error", f"Driver action failed: {name}: {e}", exc_info=True)
            raise
        finally:
            with self._lock:
                self._session_events.append(action_event.to_dict())

    def list_actions(self) -> List[Dict]:
        """List all registered actions."""
        with self._lock:
            return [
                {
                    "name": action_name,
                    "description": action_data.get("description", ""),
                    "required_context": action_data.get("required_context", []),
                }
                for action_name, action_data in self._actions.items()
            ]

    def start_session(self, scenario_name: str = "") -> None:
        """Start a new in-memory session log."""
        with self._lock:
            self._session_events = []
            self._session_meta = {
                "scenario_name": scenario_name,
                "started_at": self._now_iso(),
                "ended_at": None,
            }
            self._session_events.append(
                {
                    "timestamp": self._now_iso(),
                    "type": "session_start",
                    "data": {"scenario_name": scenario_name, "started_at": self._session_meta["started_at"]},
                }
            )

    def record_plugin_event(self, plugin_id: str, event: str, data: Dict = None) -> None:
        """Record a plugin event into the current session."""
        with self._lock:
            self._session_events.append(
                PluginEvent(
                    timestamp=self._now_iso(),
                    plugin_id=plugin_id,
                    event=event,
                    data=data or {},
                ).to_dict()
            )

    def record_llm_call(
        self,
        llm_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        action_ref: Optional[str] = None,
    ) -> None:
        """Record an LLM call into the current session."""
        with self._lock:
            self._session_events.append(
                LLMCallEvent(
                    timestamp=self._now_iso(),
                    llm_id=llm_id,
                    prompt_tokens=int(prompt_tokens or 0),
                    completion_tokens=int(completion_tokens or 0),
                    action_ref=action_ref,
                ).to_dict()
            )

    def get_session_events(self) -> List[Dict]:
        """Return all recorded session events as plain dictionaries."""
        with self._lock:
            return list(self._session_events)

    def get_session_summary(self) -> Dict:
        """Return aggregate session statistics."""
        with self._lock:
            now = datetime.now(timezone.utc)
            started = datetime.fromisoformat(self._session_meta["started_at"])
            total_actions = 0
            total_llm_calls = 0
            total_tokens = 0
            facts_created = 0
            facts_updated = 0

            for event in self._session_events:
                if event.get("type") == "action":
                    total_actions += 1
                elif event.get("type") == "llm_call":
                    total_llm_calls += 1
                    total_tokens += int(event.get("prompt_tokens", 0)) + int(event.get("completion_tokens", 0))
                elif event.get("type") == "plugin_event":
                    evt_name = str(event.get("event", "")).lower()
                    if evt_name == "fact_created":
                        facts_created += 1
                    elif evt_name == "fact_updated":
                        facts_updated += 1

            return {
                "scenario_name": self._session_meta.get("scenario_name", ""),
                "started_at": self._session_meta.get("started_at"),
                "duration_seconds": max((now - started).total_seconds(), 0.0),
                "total_actions": total_actions,
                "total_llm_calls": total_llm_calls,
                "total_tokens": total_tokens,
                "active_options": dict(self._active_options),
                "facts_created": facts_created,
                "facts_updated": facts_updated,
            }


@st.cache_resource
def get_driver() -> AppDriver:
    """Get or create the global AppDriver instance."""
    return AppDriver()
