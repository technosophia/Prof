<!-- modules/trainer/_docs/API_PLUGIN_BASE.md -->

<!-- GENERATED FILE - do not edit manually -->
<!-- Source: modules/trainer/plugin_base.py -->

# API — plugin_base

Trainer Plugin Base Module

This module provides the foundation for creating Trainer plugins.
Plugins extend the functionality of the Trainer module by adding custom
features, UI components, and data processing capabilities.

Goal: Enable developers to create modular, disposable features that can be
quickly implemented and tested with users.

Principles:
- Keep plugins focused on a single responsibility
- Minimize coupling between plugins
- Use provided hooks instead of modifying core code
- Store only essential data in history exports
- Follow bio-coding: make plugins easy to create and discard

Architecture — two-layer design (enforced by convention, future: two classes):
─────────────────────────────────────────────────────────────────────────────
  DATA LAYER  (below the line)
    Methods: get_context(), export_history(), import_history(), on_activate(),
             on_deactivate(), export_config(), import_config(), and any private
             helpers they call.
    Rules:
      - MUST use self.<service> attributes set in initialize(services)
      - MUST NOT import from st_shared.cached
      - MUST NOT import streamlit
      - MUST be callable headless (no Streamlit process)

  UI LAYER  (above the line)
    Methods: render_student_widgets(), render_dashboard_widgets(),
             render_student_header_widgets(), get_admin_tabs()
    Rules:
      - MUST only call self.<data_method>() for all data access
      - MAY import and use streamlit freely
      - MUST NOT call st_shared.cached or database code directly

  Future split: when two-class separation is needed, data methods move to
  PluginLogic and render methods move to PluginUI. The only change in render
  methods will be: self.xxx() → self._logic.xxx(). No logic rewrite needed.
─────────────────────────────────────────────────────────────────────────────

How to create a new plugin:
1. Create a directory in /modules/trainer/plugins/ with your plugin ID
2. Add plugin.json manifest (see example below)
3. Create __init__.py with your plugin class inheriting from TrainerPlugin
4. Implement required abstract methods
5. Call super().__init__(manifest) and set service attributes in initialize()
6. Override hooks as needed, respecting the data/UI layer rules above

Plugin manifest example (plugin.json):
{
    "id": "my_plugin",
    "name": "My Plugin",
    "version": "1.0.0",
    "description": "Does something useful",
    "author": "Your Name",
    "enabled_by_default": true,
    "category": "analytics"
}

See PLUGIN_MIGRATE.md for step-by-step migration of existing plugins.

---

### Class `TrainerPlugin`

```python
class TrainerPlugin(ABC):
```

Base class for all Trainer plugins.

    All plugins must inherit from this class and implement the abstract methods.
    Override the optional methods to add functionality at specific hooks.

    Lifecycle:
    1. Plugin is discovered — initialize(services) called once at startup.
       services is a ServiceLocator or None (legacy / Streamlit-cached fallback).
    2. For each trainer, on_activate() called when plugin is enabled.
    3. Plugin hooks are called when relevant UI is rendered.
    4. When trainer disables plugin, on_deactivate() called for cleanup.
    5. On export/import, history methods are called.

    Service attributes (set in initialize, used by data methods):
        self.db              — db_manager
        self.user_manager    — user_manager
        self.conversation_manager — conversation_manager
        self.llm_manager     — llm_manager (if needed)
        self.config          — config (if needed)

    Plugins that have not yet been migrated may still use st_shared.cached
    inside initialize() as a fallback when services is None. See PLUGIN_MIGRATE.md.

#### `initialize`

```python
def initialize(self, services=None) -> bool:
```

Initialize the plugin. Called once at module startup.

        Pattern for migrated plugins:
            def initialize(self, services=None) -> bool:
                self._resolve_services(services)
                # one-time setup: create DB tables, register callbacks, etc.
                return True

        Args:
            services: ServiceLocator passed by PluginManager, or None (legacy).

        Returns:
            bool: True if initialization successful, False otherwise.

#### `on_activate`

```python
def on_activate(self, trainer_id: str) -> None:
```

Called when the plugin is activated for a specific trainer.

        DATA LAYER — no st.* calls allowed here.

        Args:
            trainer_id: The trainer's ID

#### `on_deactivate`

```python
def on_deactivate(self, trainer_id: str) -> None:
```

Called when the plugin is deactivated for a specific trainer.

        DATA LAYER — no st.* calls allowed here.

        Args:
            trainer_id: The trainer's ID

#### `get_context`

```python
def get_context(self, student_id: str) -> Dict[str, str]:
```

Get plugin-specific context information for a student.

        DATA LAYER — use self.<service> attributes only.

        Returns:
            Dictionary of context strings (key: label, value: context data)

#### `export_config`

```python
def export_config(self, trainer_id: str) -> Optional[Dict]:
```

Export plugin configuration for YAML export.

        DATA LAYER — use self.<service> attributes only.

        Returns:
            Dictionary of configuration data or None

#### `import_config`

```python
def import_config(self, trainer_id: str, config: Dict) -> bool:
```

Import plugin configuration from YAML.

        DATA LAYER — use self.<service> attributes only.

#### `export_history`

```python
def export_history(self, trainer_id: str, student_id: Optional[str] = None) -> List[Dict[str, Any]]:
```

Export plugin-specific history events in minimal format.

        DATA LAYER — use self.<service> attributes only.

        Each event must contain at minimum:
        - timestamp: ISO format datetime
        - type: event type (e.g., 'plugin.score_update')
        - plugin_id: this plugin's ID

        Returns:
            List of minimal event dictionaries

#### `import_history`

```python
def import_history(self, trainer_id: str, events: List[Dict[str, Any]], student_info: Dict = None) -> bool:
```

Import plugin-specific history events.

        DATA LAYER — use self.<service> attributes only.

        Returns:
            True if import successful, False otherwise

#### `get_admin_tabs`

```python
def get_admin_tabs(self, trainer_id: str) -> List[tuple]:
```

Return list of admin UI tabs for this plugin.

        UI LAYER — may use st.*; must call self.<data_method>() for data.

        Returns:
            List of (tab_name, render_function) tuples

#### `render_dashboard_widgets`

```python
def render_dashboard_widgets(self, trainer_id: str, students: List[Dict]) -> List[Callable]:
```

Return list of render functions for dashboard widgets.

        UI LAYER — may use st.*; must call self.<data_method>() for data.

        Returns:
            List of callable render functions

#### `render_student_widgets`

```python
def render_student_widgets(self, trainer_id: str, student: Dict) -> List[Callable]:
```

Return list of render functions for student-specific widgets.

        UI LAYER — may use st.*; must call self.<data_method>() for data.

        Returns:
            List of callable render functions

#### `render_student_header_widgets`

```python
def render_student_header_widgets(self, student_id: str, trainer_id: str) -> List[Callable]:
```

Return list of render functions for student header area.

        UI LAYER — may use st.*; must call self.<data_method>() for data.

        Returns:
            List of callable render functions

