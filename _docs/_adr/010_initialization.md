# Trigger
Lazy admin tab loading revealed that some tests failed strangely => 
It was the initialization process that had technical debt

# Solution 
Refactor the initialization of modules. HUGE cleanup of code.

Claude gave me that refactoring prompt. Except for RAG engine initialization that did not get correct config it worked immediately.

This patch corrected the problem in rag engine __init__ but I factorized it outside of the Plugin.
        if config is None:
            # Backward-compat: fetch from Streamlit-cached config
            from shared.common import get_module_handler
            services = get_module_handler().get_services()
            config = services.get("config")
            rag_config = config.get("modules.rag_manager", {})
            config = rag_config.get("engines", {}).get("classic", {})

---
# REFACTORING PROMPT

**CONTEXT — read carefully before touching any file**

You are refactoring a Python module in a Streamlit application. The application has a clean two-layer architecture that must be enforced:

**Layer 1 — Functional core (`__init__.py`):** No Streamlit. No `st_shared` imports. Receives all dependencies via a `ServiceLocator` passed to `on_module_activated(services)`. This is the _only_ place functional initialization happens.

**Layer 2 — UI (`*_ui.py` files):** Streamlit only. Discovered automatically by `ui_registry.py` via `inject_ui_` naming convention. `inject_ui_initialize()` must contain _only_ `st.session_state` assignments — nothing else.

**The ServiceLocator** (`core/service.py`) is a dict-like container. Access services with `services.get("name")`. Available services registered at startup: `config`, `user_manager`, `db_manager`, `conversation_manager`, `prompt_manager`, `llm_manager`, `user_settings_manager`, `driver`, `language_service`, `semantic_eval`, `cache`.

**`shared/common.py`** provides `@require_services`-decorated functions (e.g. `get_driver()`, `get_llm_manager()`). These are for use in functional code _after_ initialization. Do not use them _inside_ `on_module_activated` itself — use `services.get(...)` directly there, since that's exactly when services are being wired up.

**`shared/driver.py` (`AppDriver`)** is the runtime bus. Modules register options, actions, and assertions on it during `on_module_activated`. Access it via `services.get("driver")`.

---

**THE MODULE TO REFACTOR: `modules/<MODULE_NAME>/`**

**Step 1 — Audit: find every file that does initialization**

Search the entire module directory for:

- Any function named `initialize()` or `init()` — in `__init__.py` or anywhere else
- Any `inject_ui_initialize()` function in any `*_ui.py` file
- Any `from st_shared` or `import st_shared` or `import streamlit` in `__init__.py`
- Any `from st_shared` or `import st_shared` in non-`*_ui.py` files
- Any module-level code in `__init__.py` that calls external services (i.e., not just `import` statements and constant definitions)
- Any `_INITIALIZED`, `_ACTIONS_REGISTERED`, `_OPTIONS_REGISTERED` or similar guard flags

List every file found and what initialization logic it contains. Do not proceed until this audit is complete.

**Step 2 — Identify what the initialization actually does**

For each piece of initialization logic found, classify it into one of:

- **A** — Register driver options (`register_option(...)`)
- **B** — Register driver actions (`register_action(...)`)
- **C** — Register driver assertions (`register_assertion(...)`)
- **D** — Register LLM callbacks (`register_llm_context_callback(...)`, etc.)
- **E** — Ensure DB tables exist
- **F** — Create filesystem directories
- **G** — Set `st.session_state` values
- **H** — Load config values for later use
- **I** — Other (describe)

Classes A–F belong in `on_module_activated(services)` in `__init__.py`. Class G belongs in `inject_ui_initialize()` in the `*_ui.py` file. Class H: if config is needed at activation time, read it from `services.get("config")`. If it's needed at render time, read it from `st_shared.cached.get_section()` in the UI file.

**Step 3 — Rewrite `__init__.py`**

The file must have exactly this structure and nothing else:

python

```python
"""
<Module name> — one line description.
"""

from core.logging import log

# Module-level state for registered callbacks only
# (keep these if deactivation needs to unregister specific callbacks)
# _my_callback = None  ← only if needed for unregister

def on_module_activated(services) -> None:
    """
    Called by module_handler at startup. Receives a ServiceLocator.
    No Streamlit. No st_shared. Raises on misconfiguration — no silent fallbacks.
    """
    driver = services.get("driver")
    config = services.get("config")
    db_manager = services.get("db_manager")
    # ... get only what you actually use

    if driver is None:
        raise RuntimeError("<module>: 'driver' service not available in ServiceLocator")

    # E — DB tables
    # Call ensure_tables_exist() or equivalent directly here
    # Import from the module's own submodules (not from st_shared)

    # A — Register driver options
    driver.register_option(...)

    # B — Register driver actions  
    driver.register_action(...)

    # C — Register driver assertions
    driver.register_assertion(...)

    # D — Register LLM callbacks
    llm_manager = services.get("llm_manager")
    llm_manager.register_context_callback(...)

    log("info", "<module>: activated")


def on_module_deactivated() -> None:
    """
    Called by module_handler when module is deactivated.
    Unregister anything registered in on_module_activated.
    """
    # Unregister LLM callbacks, etc.
    log("info", "<module>: deactivated")


def on_module_config_changed() -> None:
    """
    Called when config changes. Refresh any cached config state.
    """
    pass
```

**Rules for `__init__.py`:**

- No `from st_shared` anywhere
- No `import streamlit` anywhere
- No `initialize()` function
- No `_INITIALIZED` flags (they don't survive module cache clears anyway)
- No `_ACTIONS_REGISTERED` flags (driver registration is idempotent — registering twice is fine, the driver overwrites)
- No calls to `shared.common.get_driver()` etc. — use `services.get("driver")` directly
- DB table creation: import the table-creation function from the module's own persistence file (e.g. `from .models import ensure_tables_exist`) — that file must itself not import from `st_shared`

**Step 4 — Rewrite `inject_ui_initialize()` in `*_ui.py`**

Find the `inject_ui_initialize()` function. Remove everything from it except `st.session_state` assignments. If it is now empty, delete the function entirely.

python

```python
def inject_ui_initialize() -> bool:
    """Initialize Streamlit session state only. No functional setup."""
    if "some_key" not in st.session_state:
        st.session_state.some_key = default_value
    return True
```

If the original `inject_ui_initialize()` contained logic from classes A–F, that logic must already have been moved to `on_module_activated` in Step 3. Do not duplicate it.

**Step 5 — Check all other files in the module for `st_shared` imports**

Every non-`*_ui.py` file in the module (e.g. `manager.py`, `runner.py`, `models.py`, `scoring_pipeline.py`, etc.) must be checked. For each `from st_shared.cached import X` found:

- If `X` is a manager singleton (e.g. `get_db_manager`, `get_llm_manager`): replace with constructor injection. The manager should receive the dependency via `__init__` parameter, not fetch it itself. The `*_ui.py` or `on_module_activated` passes it in.
- If `X` is `get_section` (config): replace with the config object passed in, or accept a config dict in the constructor.
- If `X` is `_` (translation): this is UI-only, it belongs only in `*_ui.py` files. Remove from non-UI files.

Exception: `*_admin_ui.py` and `*_ui.py` files may freely import from `st_shared`.

**Step 6 — Delete the old `initialize()` function**

Once Steps 3–5 are done, the old `initialize()` function (wherever it lived) should be unreferenced. Delete it. Also delete any `_INITIALIZED`, `_ACTIONS_REGISTERED`, `_OPTIONS_REGISTERED` module-level flags.

**Step 7 — Verify**

Confirm the following by reading the code (no execution needed):

1. `grep -r "st_shared" modules/<MODULE_NAME>/` returns results **only** in `*_ui.py` files
2. `grep -r "import streamlit" modules/<MODULE_NAME>/` returns results **only** in `*_ui.py` files
3. `__init__.py` contains `on_module_activated`, `on_module_deactivated`, `on_module_config_changed` and nothing else functional
4. No `initialize()` function exists anywhere in the module
5. `inject_ui_initialize()` contains only `st.session_state` assignments (or is deleted)
6. Every manager/runner/pipeline class in the module receives its dependencies via constructor or method parameter — it does not call `st_shared.cached` itself

**Output required:**

For each step, output:

1. What you found (the audit)
2. What you changed and why
3. The complete new content of every modified file

Do not output partial files. Do not skip files. If a file is unchanged, say so explicitly.

---

**Files to look at** (give this list to the agent for the specific module):

For `modules/<MODULE_NAME>/`, the agent must read:

- `modules/<MODULE_NAME>/__init__.py` — primary target
- `modules/<MODULE_NAME>/<MODULE_NAME>_ui.py` — UI layer
- `modules/<MODULE_NAME>/<MODULE_NAME>_admin_ui.py` — if it exists
- Every `.py` file in the module that is not a `*_ui.py` — check for `st_shared` imports
- `shared/common.py` — read-only reference, do not modify
- `core/service.py` — read-only reference, understand the ServiceLocator API
- `shared/driver.py` — read-only reference, understand `register_option`, `register_action`, `register_assertion`
- `shared/module_handler.py` — read-only reference, understand the hook protocol
