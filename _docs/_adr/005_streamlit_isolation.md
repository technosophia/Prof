# Module Migration Guide: Functional Core / UI Separation

This document explains how to migrate existing modules to the new architecture
where functional logic is fully decoupled from Streamlit.

---

## Why this migration?

The goal is to allow any module's functional logic to run:
- **Headless** (no Streamlit process): CLI tools, benchmarkers, scheduled jobs
- **In tests** without Streamlit, without patching `st_shared.cached`
- **In future non-Streamlit interfaces** (REST API, etc.)

**CRITICAL:** The key architectural violation we're fixing is the use of `st_shared.cached` in business logic. 
This module provided convenient access to singletons, but it **binds your code to Streamlit's runtime**.
After migration, **NO business logic file should import from `st_shared.cached`** - all dependencies come from the ServiceLocator.

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────┐
│  APPLICATION STARTUP  (app.py or equivalent)         │
│  - builds ServiceLocator                             │
│  - registers ALL shared services:                    │
│    • config (plain config object)                    │
│    • db_manager                                      │
│    • user_manager                                    │
│    • llm_manager                                     │
│    • conversation_manager                            │
│    • prompt_manager                                  │
│    • any other shared services                       │
│  - calls module_handler.set_services(services)       │
│  - calls module_handler.initialize()                 │
│  - calls module_handler.activate_all()               │
│  - calls ui_registry.ensure_initialized() (Streamlit)│
└──────────────────────────────────────────────────────┘
           │                        │
           ▼                        ▼
┌──────────────────┐      ┌───────────────────────────┐
│  module_handler  │      │  ui_registry              │
│  (NO Streamlit)  │      │  (Streamlit context only) │
│                  │      │                           │
│  calls:          │      │  calls:                   │
│  on_module_      │      │  inject_ui_initialize()   │
│  activated()     │      │  inject_ui_sidebar()      │
│  on_module_      │      │  inject_ui_xxx()          │
│  deactivated()   │      └───────────────────────────┘
│  on_module_      │
│  config_changed()│
└──────────────────┘
```

**Key Invariant:** The left side (functional core) has ZERO knowledge of Streamlit. The right side (UI) is the ONLY place where `st.*` calls exist.

---

## The Golden Rule: NO `st_shared.cached` in Business Logic

```python
# ❌ WRONG - This binds your module to Streamlit
from st_shared.cached import get_config, get_user_manager, get_llm_manager

class YourManager:
    def __init__(self):
        self.config = get_config()  # Can only run in Streamlit!
        self.user_manager = get_user_manager()  # Will crash headless!

# ✅ RIGHT - Dependencies are injected
class YourManager:
    def __init__(self, config, user_manager):
        self.config = config  # Plain object, works anywhere
        self.user_manager = user_manager  # Works in any context
```

---

## ServiceLocator - CRITICAL: Register ALL Services!

```python
# App startup registers services ONCE - THIS MUST INCLUDE ALL SHARED SERVICES!
from shared.module_handler import ServiceLocator, module_handler

services = ServiceLocator()
services.register("config", plain_config_object)      # NOT st_shared.cached!
services.register("db_manager", db_manager)           # Database manager
services.register("user_manager", user_manager)       # User management
services.register("llm_manager", llm_manager)         # For LLM callbacks
services.register("conversation_manager", conversation_manager)
services.register("prompt_manager", prompt_manager)
# ... any other shared services that modules might need

module_handler.set_services(services)
module_handler.initialize()
module_handler.activate_all()   # calls on_module_activated(services) for each active module
```

**IMPORTANT**: The ServiceLocator must contain **ALL** services that modules might need. 
The old pattern of importing from `st_shared.cached` is replaced by receiving these services 
in `on_module_activated()`.

---

## Step-by-Step Migration

### Step 1 — Audit your module for `st_shared.cached` imports

Search your module for:
```bash
grep -r "st_shared.cached" modules/your_module/
```

Every file that imports from `st_shared.cached` needs to be refactored. The ONLY exception
is the factory file (`your_module_factory.py`), which serves as the bridge between
Streamlit-cached singletons and the functional core.

### Step 2 — Create a factory (the Streamlit bridge)

For any module that has a singleton built with Streamlit-cached objects,
create `your_module_factory.py`. This is the **ONLY** file in your module
that may import from `st_shared.cached`:

```python
# modules/your_module/your_module_factory.py
"""
Bridge between Streamlit-cached singletons and the pure functional core.
This is the ONLY file in this module that may import from st_shared.cached.
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

    # This is the ONLY place where st_shared.cached is allowed!
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

### Step 3 — Refactor the functional core

Remove ALL `st_shared.cached` imports from your business logic class.
Accept dependencies as constructor parameters:

```python
# modules/your_module/your_module.py
# NO import from st_shared here - this file must be pure!

class YourManager:
    def __init__(self, config, user_manager):
        self._config = config  # Injected, not imported
        self._user_manager = user_manager  # Injected, not imported
        rag_cfg = config.get("modules.your_module", {})
        # ... rest of init
    
    def do_something(self, user_id):
        # user_id should come from caller, not from st.session_state!
        user = self._user_manager.get_user(user_id)
        # ... business logic
```

### Step 4 — Add module lifecycle hooks in `__init__.py`

Replace `inject_ui_initialize()` doing functional work with proper hooks.
**CRITICAL**: Store references to services you need for later use:

```python
# modules/your_module/__init__.py
# NO Streamlit import here - NO st_shared.cached!

from .your_module import YourManager

_INITIALIZED = False
# Store references to services you'll need later
_LLM_MANAGER = None  # Store for callback unregistration
_SERVICES = None     # Store for later use

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
        # NEVER try to get user_id from st.session_state here!
        manager.do_something(data)
    
    # Important for debugging and unregistration
    callback.__name__ = "your_monitor_callback"
    callback.__module__ = "modules.your_module"
    return callback


def on_module_activated(services=None) -> None:
    """
    Called by ModuleHandler (no Streamlit).
    
    This is the ONLY place where services are injected. All dependencies
    come from the ServiceLocator, NOT from st_shared.cached.
    
    Register driver options, LLM callbacks, etc.
    """
    global _LLM_MANAGER, _SERVICES
    
    # Store services for later use
    _SERVICES = services
    
    # Initialize manager with injected services
    manager = _get_manager(services)
    
    # Get service references - these come from ServiceLocator, not st_shared.cached!
    if services is not None:
        _LLM_MANAGER = services.get("llm_manager") if hasattr(services, "get") else None
    
    # Register with LLM manager if available
    if _LLM_MANAGER:
        callback = _create_monitor_callback(manager)
        _LLM_MANAGER.register_monitor_callback(callback)
        log("info", f"Registered monitor callback from {callback.__module__}")
    
    initialize()  # register driver options


def on_module_deactivated() -> None:
    """Called by ModuleHandler. Unregister callbacks using stored references."""
    global _INITIALIZED, _LLM_MANAGER, _SERVICES
    
    # Use stored reference to unregister - no need to import from st_shared!
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
    _SERVICES = None
```

### Step 5 — Clean up `*_ui.py`

The UI file should ONLY contain Streamlit rendering code. 
**NO business logic, NO service registration, NO callbacks:**

```python
# modules/your_module/your_module_ui.py
# Streamlit is EXPECTED here — this file is always Streamlit-context

import streamlit as st
from core.logging import log


def _get_manager():
    # This is fine - the factory handles the Streamlit-cached singleton
    from modules.your_module.your_module_factory import get_your_manager
    return get_your_manager()


def inject_ui_initialize() -> bool:
    """
    Session state initialization ONLY.
    Functional setup was done by on_module_activated() already.
    """
    if 'your_module_enabled' not in st.session_state:
        st.session_state.your_module_enabled = True
    return True


def inject_ui_sidebar():
    """Pure Streamlit rendering."""
    manager = _get_manager()
    st.sidebar.write(f"Status: {manager.get_status()}")
```

**Remove from `*_ui.py`:**
- ❌ Any callback registration (`register_llm_callback`, `register_option`, etc.)
- ❌ Any business logic
- ❌ Any attempt to access `user_id` from `st.session_state` for monitoring data
- ❌ Any imports from `st_shared.cached` (the factory handles this)

---

## Common Pitfalls with `st_shared.cached`

### 1. Importing `get_llm_manager()` in functional code
```python
# ❌ WRONG - imports from st_shared.cached, binds to Streamlit
from st_shared.cached import get_llm_manager

def my_function():
    llm_manager = get_llm_manager()  # Will crash headless!

# ✅ RIGHT - get from services in on_module_activated
def on_module_activated(services):
    llm_manager = services.get("llm_manager")  # Injected, works anywhere
```

### 2. Using `st_shared.cached` in business logic classes
```python
# ❌ WRONG - class depends on Streamlit at import time
class MyManager:
    def __init__(self):
        self.config = get_config()  # Imported at module top-level
    
    def do_something(self):
        user = get_user_manager().get_current_user()  # Hidden dependency!

# ✅ RIGHT - dependencies are explicit
class MyManager:
    def __init__(self, config, user_manager):
        self.config = config  # Explicit dependency
        self.user_manager = user_manager  # Explicit dependency
    
    def do_something(self, user_id):
        user = self.user_manager.get_user(user_id)  # Clear data flow
```

### 3. Trying to access Streamlit state in callbacks
```python
# ❌ WRONG - monitor callbacks run headless
def monitor_callback(data):
    user_id = st.session_state.current_user['id']  # Will crash headless!

# ✅ RIGHT - user_id should come from the caller
def monitor_callback(data):
    user_id = data.get('user_id')  # Already populated by LLM manager
```

### 4. Not storing service references
```python
# ❌ WRONG - can't unregister on deactivation
def on_module_activated(services):
    llm_manager = services.get("llm_manager")
    llm_manager.register_monitor_callback(my_callback)
    # llm_manager reference lost!

# ✅ RIGHT - store reference for later
_LLM_MANAGER = None

def on_module_activated(services):
    global _LLM_MANAGER
    _LLM_MANAGER = services.get("llm_manager")
    _LLM_MANAGER.register_monitor_callback(my_callback)

def on_module_deactivated():
    if _LLM_MANAGER:
        # Can unregister without importing from st_shared!
        _LLM_MANAGER.unregister_callback(...)
```

---

## Testing Without `st_shared.cached`

The beauty of this architecture is that you can test without Streamlit,
without patching, without any magic:

```python
# tests/test_your_module.py
# NO Streamlit imports, NO patching of st_shared.cached!

from modules.your_module.your_module import YourManager

def make_config():
    """Create a plain config object for testing."""
    class TestConfig:
        def get(self, key, default=None):
            if key == "modules.your_module":
                return {"some_setting": "test_value"}
            return default
    return TestConfig()

def test_something():
    # Create real objects, no mocks needed if possible
    config = make_config()
    user_manager = FakeUserManager()  # Your test double
    
    # Inject dependencies directly
    manager = YourManager(config=config, user_manager=user_manager)
    
    # Test business logic - no Streamlit anywhere!
    result = manager.do_something(user_id="test-user")
    assert result == expected
```

---

## Migration Checklist

For each module migration:

- [ ] **NO `import streamlit`** in any `.py` file except `*_ui.py`
- [ ] **NO `from st_shared.cached`** in any business logic file
- [ ] `your_module.py` accepts all dependencies as constructor params
- [ ] `your_module_factory.py` is the **ONLY** file that imports `st_shared.cached`
- [ ] `__init__.py` has `on_module_activated(services)` that stores service references
- [ ] `__init__.py` has `on_module_deactivated()` that uses stored references
- [ ] Callbacks never access `st.session_state`
- [ ] All `st.*` calls are in `*_ui.py` only
- [ ] Tests run without Streamlit, without patching `st_shared.cached`
- [ ] Application startup registers **ALL** services in ServiceLocator

---

## Summary: The Three Golden Rules

1. **NO `st_shared.cached` in business logic** - All dependencies are injected
2. **ONLY factories import `st_shared.cached`** - They bridge Streamlit to functional core
3. **ALWAYS store service references** - For proper cleanup in `on_module_deactivated()`

This architecture ensures your code can run anywhere - Streamlit UI, CLI tools, batch jobs, or REST APIs - without modification.
```

The key enhancements in this documentation:

1. **"The Golden Rule"** section explicitly stating "NO `st_shared.cached` in Business Logic"
2. **Clear examples** showing wrong vs right patterns with `st_shared.cached`
3. **Emphasis that factories are the ONLY exception** for importing `st_shared.cached`
4. **Common pitfalls section** focused specifically on `st_shared.cached` misuse
5. **Testing section** showing how tests no longer need to patch `st_shared.cached`
6. **Three Golden Rules** summary at the end reinforcing the core principle

This makes it crystal clear that `st_shared.cached` is banned from business logic and the ServiceLocator is the proper way to inject dependencies.
