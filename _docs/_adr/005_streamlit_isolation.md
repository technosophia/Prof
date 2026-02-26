Yes, absolutely! The migration guide needs to be updated to reflect the lessons learned from this migration. Here's an improved version of `005_streamlit_isolation.md` with more accurate guidance:

```markdown
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
│  - registers ALL shared services:                   │
│    • config (plain config object)                   │
│    • db_manager                                      │
│    • user_manager                                    │
│    • llm_manager          ← IMPORTANT!              │
│    • conversation_manager                            │
│    • prompt_manager                                  │
│    • any other shared services                       │
│  - calls module_handler.set_services(services)       │
│  - calls module_handler.initialize()                 │
│  - calls module_handler.activate_all()   ← NEW       │
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

## ServiceLocator - CRITICAL: Register ALL Services!

```python
# App startup registers services ONCE - THIS MUST INCLUDE ALL SHARED SERVICES!
from shared.module_handler import ServiceLocator, module_handler

services = ServiceLocator()
services.register("config", plain_config_object)      # NOT st_shared.cached
services.register("db_manager", db_manager)           # Database manager
services.register("user_manager", user_manager)       # User management
services.register("llm_manager", llm_manager)         # ← CRITICAL for LLM monitoring!
services.register("conversation_manager", conversation_manager)
services.register("prompt_manager", prompt_manager)
# ... any other shared services that modules might need

module_handler.set_services(services)
module_handler.initialize()
module_handler.activate_all()   # calls on_module_activated(services) for each active module
```

**IMPORTANT**: The ServiceLocator must contain **ALL** services that modules might need access to in their `on_module_activated()` hooks. The most commonly needed services are:
- `config` - Plain configuration object
- `db_manager` - Database access
- `user_manager` - User management
- `llm_manager` - LLM access (for monitoring callbacks, context injection)
- `conversation_manager` - Conversation management
- `prompt_manager` - Prompt management

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
- Monitor callbacks trying to access `st.session_state` for user_id (should come from LLM manager)

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

---

### Step 4 — Add module lifecycle hooks in `__init__.py`

Replace `inject_ui_initialize()` doing functional work with proper hooks.
**CRITICAL**: Store references to services you need for later use (like unregistration):

```python
# modules/your_module/__init__.py
# NO Streamlit import here

from .your_module import YourManager

_INITIALIZED = False
# Store references to services you'll need later
_LLM_MANAGER = None  # Example: store llm_manager for callback registration

def _get_manager(services=None):
    from modules.your_module.your_module_factory import get_your_manager, reset_your_manager
    
    if services is not None:
        config = services.get("config") if hasattr(services, "get") else None
        user_manager = services.get("user_manager") if hasattr(services, "get") else None
        if config and user_manager:
            reset_your_manager()
            return get_your_manager(config=config, user_manager=user_manager)
    
    return get_your_manager()


def _create_monitor_callback(manager):
    """Create a callback with proper module attribution."""
    def callback(data: dict):
        # The data should already contain user_id from the caller
        manager.do_something(data)
    
    # Important for debugging and unregistration
    callback.__name__ = "your_monitor_callback"
    callback.__module__ = "modules.your_module"
    return callback


def on_module_activated(services=None) -> None:
    """
    Called by ModuleHandler (no Streamlit).
    Register driver options, LLM callbacks, etc.
    """
    global _LLM_MANAGER
    
    # Initialize manager with injected services
    manager = _get_manager(services)
    
    # STORE REFERENCES TO SERVICES YOU NEED
    if services is not None:
        _LLM_MANAGER = services.get("llm_manager") if hasattr(services, "get") else None
    
    # Register with LLM manager if available
    if _LLM_MANAGER:
        callback = _create_monitor_callback(manager)
        _LLM_MANAGER.register_monitor_callback(callback)
        log("info", f"Registered monitor callback from {callback.__module__}")
    
    initialize()  # register driver options


def on_module_deactivated() -> None:
    """Called by ModuleHandler. Unregister callbacks."""
    global _INITIALIZED, _LLM_MANAGER
    
    # Use stored reference to unregister
    if _LLM_MANAGER:
        # Filter out callbacks from this module
        if hasattr(_LLM_MANAGER, '_monitor_callbacks'):
            _LLM_MANAGER._monitor_callbacks = [
                cb for cb in _LLM_MANAGER._monitor_callbacks
                if getattr(cb, '__module__', '') != 'modules.your_module'
            ]
    
    _unregister_all_callbacks()
    _INITIALIZED = False
    _LLM_MANAGER = None


def on_module_config_changed() -> None:
    """Called by ModuleHandler when config file changes."""
    from modules.your_module.your_module_factory import reset_your_manager
    reset_your_manager()
    _get_manager().refresh_config()
```

**Key points for LLM callbacks:**
1. Don't import `get_llm_manager()` from anywhere - get it from services
2. Store the reference for later unregistration
3. Set `__name__` and `__module__` on callbacks for debugging
4. The callback should receive data with `user_id` already populated by the caller

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
```

**Remove from `*_ui.py`:**
- Any callback registration (`register_llm_callback`, `register_option`, etc.)
- Any business logic
- Any attempt to access `user_id` from `st.session_state` for monitoring data (should come from LLM manager)

---

## What Changes in Application Startup

### BEFORE (incomplete service registration)
```python
services = ServiceLocator()
services.register("config", get_config())
services.register("user_manager", get_user_manager())
# Missing llm_manager, db_manager, etc.
module_handler.set_services(services)
```

### AFTER (complete service registration)
```python
services = ServiceLocator()
services.register("config", get_config())
services.register("db_manager", get_db_manager())
services.register("user_manager", get_user_manager())
services.register("llm_manager", get_llm_manager())          # ← CRITICAL!
services.register("conversation_manager", get_conversation_manager())
services.register("prompt_manager", get_prompt_manager())
# Add any other services modules might need
module_handler.set_services(services)
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

## Common Pitfalls

### 1. Missing services in ServiceLocator
```python
# WRONG - modules can't access llm_manager
services.register("config", config)
services.register("user_manager", user_manager)

# RIGHT - register ALL services modules might need
services.register("config", config)
services.register("user_manager", user_manager)
services.register("llm_manager", llm_manager)
services.register("db_manager", db_manager)
services.register("conversation_manager", conversation_manager)
services.register("prompt_manager", prompt_manager)
```

### 2. Importing get_llm_manager() in functional code
```python
# WRONG - imports from st_shared.cached
from st_shared.cached import get_llm_manager

# RIGHT - get from services in on_module_activated
def on_module_activated(services):
    llm_manager = services.get("llm_manager")
```

### 3. Trying to access st.session_state in monitor callbacks
```python
# WRONG - monitor callbacks run headless
def monitor_callback(data):
    user_id = st.session_state.current_user['id']  # Will crash headless!

# RIGHT - user_id should come from the caller
def monitor_callback(data):
    user_id = data.get('user_id')  # Already populated by LLM manager
```

### 4. Not storing service references for later use
```python
# WRONG - can't unregister on deactivation
def on_module_activated(services):
    llm_manager = services.get("llm_manager")
    llm_manager.register_monitor_callback(my_callback)

# RIGHT - store reference for later
_LLM_MANAGER = None

def on_module_activated(services):
    global _LLM_MANAGER
    _LLM_MANAGER = services.get("llm_manager")
    _LLM_MANAGER.register_monitor_callback(my_callback)

def on_module_deactivated():
    if _LLM_MANAGER:
        # Unregister callbacks
```

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

    manager = YourManager(config=config, user_manager=um)
    # Test functional logic without ANY Streamlit
    assert manager.do_something() == expected
```

### Callback registration test:

```python
def test_on_module_activated_registers_callbacks():
    from shared.module_handler import ServiceLocator
    import modules.your_module as mod
    
    # Create mock services
    services = ServiceLocator()
    mock_llm_manager = Mock()
    services.register("llm_manager", mock_llm_manager)
    services.register("config", Mock())
    services.register("user_manager", Mock())
    
    # Activate module
    mod.on_module_activated(services)
    
    # Verify callback was registered
    assert mock_llm_manager.register_monitor_callback.called
```

---

## Checklist

For each module migration:

- [ ] `your_module.py` (functional core) has NO `import streamlit` or `from st_shared`
- [ ] `your_module.py` accepts `config` and other deps as constructor params
- [ ] `your_module_factory.py` exists and is the ONLY file that imports `st_shared`
- [ ] `__init__.py` has `on_module_activated(services)` that stores needed service references
- [ ] `__init__.py` has `on_module_deactivated()` that uses stored references for cleanup
- [ ] `__init__.py` has `on_module_config_changed()` for config refresh
- [ ] `*_ui.py` `inject_ui_initialize()` ONLY touches `st.session_state`
- [ ] All `st.*` calls are in `*_ui.py` only
- [ ] Tests for the functional core run without Streamlit (no `st_shared` patching)
- [ ] `module.json` is unchanged (migration is transparent to module discovery)
- [ ] Application startup registers **ALL** services in ServiceLocator
- [ ] Conftest.py also registers **ALL** services for test environment

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

### `prof.py` (or equivalent app startup)
- Now registers ALL services in ServiceLocator including `llm_manager`
- Calls `module_handler.activate_all()` after service registration

### `conftest.py` (test setup)
- Now also registers ALL services in ServiceLocator for test environment
- Ensures modules work the same in tests as in production

### Module-specific files (as shown in examples)
```

The key additions to the guide are:
1. **Emphasis on registering ALL services** in the ServiceLocator
2. **Importance of storing service references** for later use (especially for unregistration)
3. **Proper callback creation** with `__name__` and `__module__` attributes
4. **Common pitfalls** section with specific examples
5. **Updated test examples** that verify callback registration
6. **Files changed** section now includes `prof.py` and `conftest.py`
