streamlit causes too much issues with pytest-bdd gherkin tests
streamlit will be kept for the backend, but not for the frontend

# Module Migration Guide: Functional Core / UI Separation

This document explains how to migrate existing modules to the new architecture
where functional logic is fully decoupled from Streamlit.

---

## Why this migration?

The goal is to allow any module's functional logic to run:
- **Headless** (no Streamlit process): CLI tools, benchmarkers, scheduled jobs
- **In tests** without Streamlit, without patching `st_shared.cached`
- **In future non-Streamlit interfaces** (REST API, etc.)

The Streamlit UI layer remains intentionally Streamlit-dependent — that is fine.
The problem was mixing the two in the same functions.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│  APPLICATION STARTUP  (app.py or equivalent)        │
│  - builds ServiceLocator                            │
│  - calls module_handler.set_services(services)      │
│  - calls module_handler.initialize()                │
│  - calls module_handler.activate_all()   ← NEW      │
│  - calls ui_registry.ensure_initialized() (Streamlit)│
└─────────────────────────────────────────────────────┘
           │                        │
           ▼                        ▼
┌─────────────────┐      ┌──────────────────────────┐
│  module_handler │      │  ui_registry              │
│  (NO Streamlit) │      │  (Streamlit context only) │
│                 │      │                           │
│  calls:         │      │  calls:                   │
│  on_module_     │      │  inject_ui_initialize()   │
│  activated()    │      │  inject_ui_sidebar()      │
│  on_module_     │      │  inject_ui_xxx()          │
│  deactivated()  │      └──────────────────────────┘
│  on_module_     │
│  config_changed()│
└─────────────────┘
```

---

## The 4 Callback Types

| Type | Streamlit? | Where registered | When called |
|------|-----------|-----------------|-------------|
| **Driver option/action** | No | `on_module_activated()` | By driver (headless OK) |
| **LLM monitor callback** | No | `on_module_activated()` | By llm_manager |
| **LLM context callback** | No | `on_module_activated()` | By llm_manager |
| **UI injection point** | Yes | `inject_ui_xxx()` | By ui_registry (Streamlit) |

---

## ServiceLocator

```python
# App startup registers services ONCE:
from shared.module_handler import ServiceLocator, module_handler

services = ServiceLocator()
services.register("config", plain_config_object)      # NOT st_shared.cached
services.register("user_manager", user_manager)
services.register("llm_manager", llm_manager)
services.register("driver", driver)
# ... any other shared services

module_handler.set_services(services)
module_handler.initialize()
module_handler.activate_all()   # calls on_module_activated(services) for each active module
```

---

## Step-by-Step Migration

### Step 1 — Audit your module

In your module directory, identify:

**Functional (should have NO Streamlit):**
- Business logic classes (managers, engines, etc.)
- Driver registration (`register_option`, `register_action`)
- LLM callbacks (monitor, context injection)
- Configuration loading

**UI (should ONLY be in `*_ui.py`):**
- `st.*` calls
- `st.session_state` access
- `st.sidebar.*`, `st.expander`, etc.
- `inject_ui_xxx` functions

**Mixed (the problem):**
- `inject_ui_initialize()` doing both `st.session_state` setup AND driver registration
- Functional classes calling `get_config()` from `st_shared.cached`
- `rag_context_callback` writing to `st.session_state`

---

### Step 2 — Create a factory (the Streamlit bridge)

For any module that has a singleton built with Streamlit-cached objects,
create `your_module_factory.py`:

```python
# modules/your_module/your_module_factory.py
"""
Bridge between Streamlit-cached singletons and the pure functional core.
This is the ONLY file in this module that may import from st_shared.
"""

from __future__ import annotations
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from modules.your_module.your_module import YourManager

_instance: Optional["YourManager"] = None


def get_your_manager(config=None, user_manager=None) -> "YourManager":
    global _instance
    if _instance is not None:
        return _instance

    if config is None or user_manager is None:
        from st_shared.cached import get_config, get_user_manager
        if config is None:
            config = get_config()
        if user_manager is None:
            user_manager = get_user_manager()

    from modules.your_module.your_module import YourManager
    _instance = YourManager(config=config, user_manager=user_manager)
    return _instance


def reset_your_manager() -> None:
    """Reset the singleton (for tests)."""
    global _instance
    _instance = None
```

---

### Step 3 — Refactor the functional core

Remove ALL `st_shared.cached` imports from your business logic class.
Accept dependencies as constructor parameters:

```python
# modules/your_module/your_module.py
# NO import from st_shared here

class YourManager:
    def __init__(self, config, user_manager):
        self._config = config
        self._user_manager = user_manager
        rag_cfg = config.get("modules.your_module", {})
        # ... rest of init
```

For **sub-components** (engines, helpers) that previously called `get_config()`:

```python
# Before (bad):
class YourEngine:
    def __init__(self):
        from st_shared.cached import get_config
        config = get_config().get("modules.your_module.engines.your_engine", {})

# After (good):
class YourEngine:
    def __init__(self, config: dict = None):
        if config is None:
            # Backward compat fallback — remove once all callers are migrated
            from st_shared.cached import get_config as _gc
            config = _gc().get("modules.your_module", {}).get("engines", {}).get("your_engine", {})
        self.some_setting = config.get("some_setting", "default")
```

---

### Step 4 — Add module lifecycle hooks in `__init__.py`

Replace `inject_ui_initialize()` doing functional work with proper hooks:

```python
# modules/your_module/__init__.py
# NO Streamlit import here

from .your_module import YourManager

_INITIALIZED = False

def _get_manager():
    from modules.your_module.your_module_factory import get_your_manager
    return get_your_manager()


def on_module_activated(services=None) -> None:
    """
    Called by ModuleHandler (no Streamlit).
    Register driver options, LLM callbacks, etc.
    """
    # Optionally build the manager with injected deps if services provided
    if services is not None:
        cfg = services.get("config")
        um = services.get("user_manager")
        if cfg and um:
            from modules.your_module.your_module_factory import get_your_manager, _instance
            if _instance is None:
                get_your_manager(config=cfg, user_manager=um)

    initialize()  # register driver options


def on_module_deactivated() -> None:
    """Called by ModuleHandler. Unregister callbacks."""
    global _INITIALIZED
    _unregister_all_callbacks()
    _INITIALIZED = False


def on_module_config_changed() -> None:
    """Called by ModuleHandler when config file changes."""
    _get_manager().refresh_config()


def initialize() -> bool:
    """Register driver options. Safe to call headless."""
    global _INITIALIZED
    try:
        from shared.common import register_option
        register_option(
            group="your_group",
            name="your_option",
            activate_fn=lambda: _activate_something(),
            deactivate_fn=lambda: _deactivate_something(),
            description="Your option description",
        )
        _INITIALIZED = True
        return True
    except Exception as exc:
        return False
```

---

### Step 5 — Clean up `*_ui.py`

The UI file should ONLY contain:

```python
# modules/your_module/your_module_ui.py
# Streamlit is EXPECTED here — this file is always Streamlit-context

import streamlit as st
from core.logging import log


def _get_manager():
    from modules.your_module.your_module_factory import get_your_manager
    return get_your_manager()


def inject_ui_initialize() -> bool:
    """
    Session state initialization ONLY.
    Functional setup was done by on_module_activated() already.
    """
    if 'your_module_enabled' not in st.session_state:
        st.session_state.your_module_enabled = True
    # etc.
    return True


def inject_ui_sidebar():
    """Pure Streamlit rendering."""
    manager = _get_manager()
    st.sidebar.write(f"Status: {manager.get_status()}")


def inject_ui_admin_tab():
    def render():
        st.header("Your Module Admin")
        # ...
    return ("Your Module", render)
```

**Remove from `*_ui.py`:**
- Any callback registration (`register_llm_callback`, `register_option`, etc.)
- Any business logic
- Any writing to external state that isn't `st.session_state`

---

### Step 6 — Move LLM context callbacks to `__init__.py`

If you had a callback that wrote to `st.session_state` (for debug display),
split it:

```python
# In __init__.py (functional part — no st.session_state writes):
def _make_context_callback(name):
    def _callback(user_id, messages):
        # Pure logic — no st.session_state
        query = messages[-1].get("content", "")
        context = _get_manager().get_context(user_id, query)
        return context, "system", "bottom"
    return _callback


# In *_ui.py (UI part — handles st.session_state for debug display):
def inject_ui_inside_conversation():
    """Show last context in debug expander."""
    if not st.session_state.get('debug_enabled', False):
        return
    context = st.session_state.get('last_context', '')
    if context:
        with st.expander("Debug Context"):
            st.text(context)
```

---

## What Changes in `module_handler`

### Before
```
module_handler.toggle_module("x", True)
  → calls inject_ui_initialize()  ← WRONG: Streamlit in functional layer
```

### After
```
module_handler.toggle_module("x", True)
  → calls on_module_activated(services)  ← functional only

ui_registry.ensure_initialized()
  → calls inject_ui_initialize()  ← Streamlit context only
```

The key invariant: **`module_handler` never calls any `inject_ui_xxx` function.**

---

## Backward Compatibility

Modules NOT yet migrated continue to work:

1. `module_handler.toggle_module()` tries `on_module_activated()` — if not found, silently skips.
2. `ui_registry.ensure_initialized()` calls `inject_ui_initialize()` — for legacy modules this still does everything (functional + UI setup).
3. Old-style `inject_ui_initialize()` calling `register_llm_callback()` will still work — it just runs in a Streamlit context instead of functional context.

**Migration is non-breaking.** Migrate one module, test, then the next.

---

## Testing After Migration

### Headless test (no Streamlit):

```python
# tests/test_your_module.py
from modules.your_module.your_module import YourManager

def make_config(data_dir):
    class Cfg:
        def get(self, key, default=None):
            # Return test config values
            ...
    return Cfg()

def test_something():
    config = make_config(tmp_path)
    um = Mock()
    um.get_user.return_value = {"id": "u1", "role": "admin"}
    um.register_before_delete_callback = Mock()

    manager = YourManager(config=config, user_manager=um)
    # Test functional logic without ANY Streamlit
    assert manager.do_something() == expected
```

### Driver registration test:

```python
def test_on_module_activated_registers_driver_options():
    from shared.module_handler import ServiceLocator
    import modules.your_module as mod

    services = ServiceLocator()
    mod.on_module_activated(services)

    from shared.common import get_driver
    options = get_driver().list_options()
    assert "your_group" in options
```

---

## Checklist

For each module migration:

- [ ] `your_module.py` (functional core) has NO `import streamlit` or `from st_shared`
- [ ] `your_module.py` accepts `config` and other deps as constructor params
- [ ] `your_module_factory.py` exists and is the ONLY file that imports `st_shared`
- [ ] `__init__.py` has `on_module_activated(services)` for driver/callback registration
- [ ] `__init__.py` has `on_module_deactivated()` for cleanup
- [ ] `__init__.py` has `on_module_config_changed()` for config refresh
- [ ] `*_ui.py` `inject_ui_initialize()` ONLY touches `st.session_state`
- [ ] All `st.*` calls are in `*_ui.py` only
- [ ] Tests for the functional core run without Streamlit (no `st_shared` patching)
- [ ] `module.json` is unchanged (migration is transparent to module discovery)

---

## Files Changed in This Migration

### `shared/module_handler.py`
- Added `ServiceLocator` class
- Added `set_services()` / `get_services()` methods
- Added `activate_all()` method
- `_call_module_hook()` passes `ServiceLocator` to `on_module_activated()`
- `toggle_module()` calls `on_module_activated(services)` not `inject_ui_initialize()`
- Zero Streamlit dependency (was already true, now enforced)

### `shared/ui_registry.py`
- `_run_initialize_hooks()` calls `inject_ui_initialize()` for ALL modules
- `ensure_initialized()` is now the ONLY place `inject_ui_initialize` is auto-called
- module_handler hooks (`on_module_activated` etc.) are explicitly NOT called here

### `modules/rag_manager/rag_manager.py`
- `RAGManager(config, user_manager)` — injected deps, NO `st_shared` imports

### `modules/rag_manager/rag_factory.py` ← NEW
- Bridges `st_shared.cached` to pure `RAGManager`

### `modules/rag_manager/__init__.py`
- `on_module_activated(services)` does all functional setup
- `_ManagerProxy` for backward-compat `from modules.rag_manager import rag_manager`

### `modules/rag_manager/rag_manager_ui.py`
- `inject_ui_initialize()` ONLY touches `st.session_state`
- All `register_llm_callback` / `register_option` calls removed
- Lazy `_get_rag_manager()` accessor

### `modules/rag_manager/rag_simple.py`
### `modules/rag_manager/rag_engines/rag_classic.py`
### `modules/rag_manager/rag_engines/rag_hierarchical.py`
- Accept optional `config` dict at construction
- Backward-compat fallback to `st_shared.cached` when `config=None`
