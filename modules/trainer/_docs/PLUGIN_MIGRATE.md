# PLUGIN_MIGRATE.md — Trainer Plugin Migration Guide

This document is the complete reference for migrating a Trainer plugin from the
legacy architecture (uses `st_shared.cached` directly) to the new architecture
(uses injected services, clear data/UI seam).

Read this once before starting. The migration is mechanical and should not
require any logic rewrite.

---

## Why migrate?

The new architecture lets data methods (DB, LLM calls, export/import) run
**headless** — no Streamlit process, no `st_shared.cached`, testable in isolation.
Render methods stay in the same class and continue using `st.*` freely.

---

## Architecture summary

Every plugin has two conceptual layers in one class:

```
┌─────────────────────────────────────────────────────────┐
│  UI LAYER  (render_* and get_admin_tabs)                │
│  • May use st.* freely                                  │
│  • Must call self.<data_method>() for all data access   │
│  • Must NOT touch self.db, self.user_manager, etc.      │
│    directly — delegate to a data method instead         │
└─────────────────────────────────────────────────────────┘
           calls ↓  self.xxx()
┌─────────────────────────────────────────────────────────┐
│  DATA LAYER  (everything else)                          │
│  • Uses self.db, self.user_manager, self.llm_manager,   │
│    self.conversation_manager, self.config               │
│  • Must NOT import st_shared.cached                     │
│  • Must NOT import streamlit                            │
│  • Callable headless                                    │
└─────────────────────────────────────────────────────────┘
```

**Future split into two classes** will be trivial: move data methods to
`PluginLogic`, keep render methods in `PluginUI`, and replace every
`self.xxx()` call in render methods with `self._logic.xxx()`. No logic rewrite.

---

## Step-by-step migration

### Step 1 — Read the existing plugin

Open `modules/trainer/plugins/<plugin_id>/__init__.py`.

Identify:
- What services it uses (db_manager, user_manager, conversation_manager, llm_manager)
- Where it calls `st_shared.cached` (usually in `__init__` or top of methods)
- Which methods are data methods vs render methods

### Step 2 — Update `initialize()`

Change the signature from:
```python
def initialize(self) -> bool:
```
to:
```python
def initialize(self, services=None) -> bool:
    self._resolve_services(services)
    # ... rest of initialization unchanged
```

`_resolve_services` is defined on `TrainerPlugin` base class. It sets:
- `self.db`
- `self.user_manager`
- `self.conversation_manager`
- `self.llm_manager`
- `self.config`

If `services` is `None` (legacy fallback), it calls `st_shared.cached`
automatically. So the plugin continues to work in Streamlit even before
the application startup is updated to pass a real `ServiceLocator`.

### Step 3 — Remove `st_shared.cached` imports from data methods

Replace every inline call like:
```python
# BEFORE
from st_shared.cached import get_db_manager
db = get_db_manager()
```
with:
```python
# AFTER
self.db  # already set in initialize()
```

Common replacements:
| Old call | New attribute |
|---|---|
| `get_db_manager()` | `self.db` |
| `get_user_manager()` | `self.user_manager` |
| `get_conversation_manager()` | `self.conversation_manager` |
| `get_llm_manager()` | `self.llm_manager` |
| `get_config()` | `self.config` |

Remove the `from st_shared.cached import ...` lines from data methods.
If the import is at the top of the file, move it to the render methods that
still need it, or remove it entirely if no render method uses it.

### Step 4 — Check render methods

In each render method (`render_student_widgets`, `render_dashboard_widgets`,
`render_student_header_widgets`, `get_admin_tabs`):

- Verify every piece of data access goes through `self.<data_method>()`.
- If you find inline DB/cache calls, extract a new private data method and call that.
- `st.*` calls are fine here — that's expected.

**Bad pattern** (render method doing data work inline):
```python
def render_student_widgets(self, trainer_id, student):
    def render():
        db = get_db_manager()               # ❌ data work inline
        with db.get_session() as session:   # ❌
            row = session.query(...).first()
        st.write(row.value)
    return [render]
```

**Good pattern** (render method delegates to data method):
```python
# Data method (below the line)
def _get_value(self, student_id: str) -> str:
    with self.db.get_session() as session:   # ✅ uses self.db
        row = session.query(...).first()
    return row.value if row else ""

# Render method (above the line)
def render_student_widgets(self, trainer_id, student):
    def render():
        value = self._get_value(student['id'])  # ✅ delegates
        st.write(value)
    return [render]
```

### Step 5 — Remove top-level `st_shared.cached` file import

If the plugin file has at the top:
```python
from st_shared.cached import get_db_manager, get_user_manager, ...
```
remove those lines. The file should have zero imports from `st_shared.cached`.

The `_resolve_services` fallback handles the Streamlit-cached lookup internally
when `services=None`, so nothing breaks.

### Step 6 — Verify the seam comment

Add a migration status block at the top of the plugin class (after the class
docstring) so future developers know where things stand:

```python
"""
Migration status: COMPLETE
  - initialize() calls self._resolve_services(services)
  - All data methods use self.db, self.user_manager, etc. — no st_shared.cached
  - All render methods call self.<data_method>() only — no db/cache access inline
  - Future split: replace self.xxx() with self._logic.xxx() in render methods.
    No logic rewrite needed.
"""
```

### Step 7 — Smoke test

Run the Streamlit app and verify:
1. The plugin loads (check logs for `Loaded plugin: <id>`)
2. The plugin's admin tab renders without errors
3. The plugin's student widgets render without errors
4. Any data operations (save, export, import) work correctly

---

## Checklist

Copy this per-plugin:

```
Plugin: <plugin_id>
Date: <date>
Migrated by: <name>

[ ] initialize(self, services=None) signature updated
[ ] self._resolve_services(services) called first in initialize()
[ ] All data methods use self.db / self.user_manager / etc.
[ ] No st_shared.cached imports in data methods
[ ] No st_shared.cached imports at file top level
[ ] All render methods delegate data access to self.<data_method>()
[ ] No inline DB/cache calls inside render closures
[ ] Migration status comment added to class docstring
[ ] Smoke tested in Streamlit — plugin loads and renders correctly
[ ] Data operations verified (save, export, import if applicable)
```

---

## Reference: migrated plugin structure

Use `modules/trainer/plugins/memory/__init__.py` as the canonical example.

Key things to look for in that file:
- `initialize(self, services=None)` calls `self._resolve_services(services)` first
- `_get_student_trainer_id()` is a data helper extracted so render methods don't
  need to touch `self.user_manager` directly — they call `self._get_student_trainer_id()`
- `get_memory_context()` (LLM callback, runs headless) uses `self.user_manager`
  and `self.db` — no `st_shared.cached`
- Every render closure only calls `self._get_xxx()` or `self.refresh_memory()` —
  never `self.db` or `self.user_manager` directly

---

## What NOT to change

- `plugin.json` — untouched
- `prompts.*.yaml` — untouched
- `translations/*.json` — untouched
- `models.py` (if plugin has one) — untouched
- Render method logic — untouched (only extract data calls if needed)
- Export/import data format — untouched

---

## When is a plugin "fully migrated"?

A plugin is fully migrated when:
1. It can be instantiated and its data methods called with no Streamlit process running.
2. `grep -n "st_shared.cached" modules/trainer/plugins/<id>/__init__.py` returns nothing.
3. The checklist above is fully checked.
