## Context

We have a Trainer plugin system where each plugin currently lives in a single class (`TrainerPlugin`) in a single file (`modules/trainer/plugins/<id>/__init__.py`).

A previous migration (part 1) already established a clean data/UI seam inside that single class:
- **Data methods** (`get_context`, `export_history`, `import_history`, `on_activate`, `on_deactivate`, `export_config`, `import_config`, and all private helpers they call) use only `self.db`, `self.user_manager`, etc. — no `st.*`, no `st_shared.cached`
- **UI methods** (`render_student_widgets`, `render_dashboard_widgets`, `render_student_header_widgets`, `get_admin_tabs`) call only `self.<data_method>()` for data, then use `st.*` freely

The invariant to preserve: **if you delete all UI files, the system must continue to work headless.**

---

## Goal — Part 2: split into two classes, two files

For each plugin, produce:

**`plugins/<id>/core.py`** — `<Name>PluginCore(TrainerPluginCore)`
- Contains all data methods and private helpers
- Zero `import streamlit`
- Zero `st_shared.cached`
- Uses `self.db`, `self.user_manager`, etc. set by `initialize(services)`
- Inherits from `TrainerPluginCore` (new base, see below)

**`plugins/<id>/ui.py`** — `<Name>PluginUI(TrainerPluginUI)`
- Contains all render methods and admin tabs
- Imports and holds a reference to the core: `self._core = <Name>PluginCore`
- Every data call is `self._core.xxx()` — no direct db/service access
- `import streamlit as st` is fine here
- Inherits from `TrainerPluginUI` (new base, see below)

**`plugins/<id>/__init__.py`** — unchanged API surface
- Imports both, exposes `plugin_core` and `plugin_ui` entry points
- `PluginManager` discovers both via these entry points

---

## Base class split

**`plugin_base_core.py`** — `TrainerPluginCore(ABC)`
- All current data-layer abstract and concrete methods from `TrainerPlugin`
- `initialize(services=None)`, `_resolve_services(services)`, `on_activate`, `on_deactivate`, `get_context`, `export_config`, `import_config`, `export_history`, `import_history`
- No UI methods at all
- No streamlit import

**`plugin_base_ui.py`** — `TrainerPluginUI(ABC)`
- Constructor takes a core instance: `def __init__(self, core: TrainerPluginCore)`
- Stores it as `self._core`
- All current UI-layer methods from `TrainerPlugin`: `render_student_widgets`, `render_dashboard_widgets`, `render_student_header_widgets`, `get_admin_tabs`
- Default implementations return `[]`
- May import streamlit

**`plugin_base.py`** — keep for backward compatibility during transition
- `TrainerPlugin` now inherits from both: `class TrainerPlugin(TrainerPluginCore, TrainerPluginUI)`
- Old single-class plugins continue to work unchanged
- `PluginManager` updated to handle both old (single class) and new (core + ui pair) plugin styles

---

## PluginManager changes

`PluginManager` looks for either:
- **Legacy**: a single class inheriting `TrainerPlugin` (current behavior, keep working)
- **New style**: `plugin_core` and `plugin_ui` entry points in `__init__.py`

It stores:
- `self.plugins: Dict[str, TrainerPluginCore]` — core instances (always loaded)
- `self.ui_plugins: Dict[str, TrainerPluginUI]` — UI instances (loaded only when Streamlit available)

All existing calls to `plugin_manager.get_plugin(id)` return the core. UI rendering goes through `plugin_manager.get_ui_plugin(id)`.

---

## Files to produce

1. `modules/trainer/plugin_base_core.py` — `TrainerPluginCore`
2. `modules/trainer/plugin_base_ui.py` — `TrainerPluginUI`
3. `modules/trainer/plugin_base.py` — updated `TrainerPlugin` (backward compat) + updated `PluginManager`
4. `modules/trainer/plugins/memory/core.py` — `MemoryPluginCore`
5. `modules/trainer/plugins/memory/ui.py` — `MemoryPluginUI`
6. `modules/trainer/plugins/memory/__init__.py` — updated entry points
7. `modules/trainer/plugins/pedagogical_memory/core.py`
8. `modules/trainer/plugins/pedagogical_memory/ui.py`
9. `modules/trainer/plugins/pedagogical_memory/__init__.py`
10. `PLUGIN_MIGRATE.md` — updated to document the new two-file structure

---

## Constraints

- Deleting all `ui.py` files must leave a working headless system
- `trainer_admin_ui.py` calls `plugin.get_admin_tabs()` and `plugin.render_student_widgets()` — these must still work, routed through the UI instance
- The `memory` and `pedagogical_memory` plugins are the canonical examples — they were fully migrated in part 1 and have a clean seam already
- Do not touch `models.py`, `prompts.*.yaml`, `translations/`, `plugin.json`
- Keep `plugin_base.py` importing cleanly for any code that does `from modules.trainer.plugin_base import TrainerPlugin`

---

## Reference files available in context

Provide these files at the start of the session:
- `modules/trainer/plugin_base.py` (current, post part-1)
- `modules/trainer/plugins/memory/__init__.py` (migrated)
- `modules/trainer/plugins/pedagogical_memory/__init__.py` (migrated)
- `modules/trainer/manager.py`
- `modules/trainer/__init__.py`
- `modules/trainer/trainer_admin_ui.py`
