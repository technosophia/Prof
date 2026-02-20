<!-- modules/trainer/plugin_base.py -->

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

How to create a new plugin:
1. Create a directory in /modules/trainer/plugins/ with your plugin ID
2. Add plugin.json manifest (see example below)
3. Create __init__.py with your plugin class inheriting from TrainerPlugin
4. Implement required abstract methods
5. Override hooks as needed

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

See AGENTS.md in the trainer module for more context on plugin architecture.

---

### Class `TrainerPlugin`

```python
class TrainerPlugin(ABC):
```

Base class for all Trainer plugins.

    All plugins must inherit from this class and implement the abstract methods.
    Override the optional methods to add functionality at specific hooks.

    Lifecycle:
    1. Plugin is discovered and initialized (initialize() called once)
    2. For each trainer, on_activate() called when plugin is enabled
    3. Plugin hooks are called when relevant UI is rendered
    4. When trainer disables plugin, on_deactivate() called for cleanup
    5. On export/import, history methods are called

    Best practices:
    - Keep initialization lightweight in __init__
    - Use initialize() for heavy setup (DB connections, file creation)
    - Clean up resources in on_deactivate()
    - Return empty lists from hook methods when no content
    - Keep exported history minimal and reconstructable

#### `initialize`

```python
def initialize(self) -> bool:
```

Initialize the plugin. Called once at module startup.

        Use this for one-time setup like creating database tables,
        registering event handlers, or loading resources.

        Returns:
            bool: True if initialization successful, False otherwise

#### `on_activate`

```python
def on_activate(self, trainer_id: str) -> None:
```

Called when the plugin is activated for a specific trainer.

        Override to perform per-trainer setup when plugin is turned on.
        This is where you might create trainer-specific data structures
        or initialize per-trainer state.

        Args:
            trainer_id: The trainer's ID

#### `on_deactivate`

```python
def on_deactivate(self, trainer_id: str) -> None:
```

Called when the plugin is deactivated for a specific trainer.

        Override to perform per-trainer cleanup when plugin is turned off.
        Release resources, close connections, or archive data.

        Args:
            trainer_id: The trainer's ID

#### `get_admin_tabs`

```python
def get_admin_tabs(self, trainer_id: str) -> List[tuple]:
```

Return list of admin UI tabs for this plugin.

        Each tab is a tuple of (tab_name: str, render_function: callable).
        The render function will be called with the request context and
        should return HTML content.

        Args:
            trainer_id: The trainer's ID

        Returns:
            List of (tab_name, render_function) tuples

#### `render_dashboard_widgets`

```python
def render_dashboard_widgets(self, trainer_id: str, students: List[Dict]) -> List[Callable]:
```

Return list of render functions for dashboard widgets.

        Widgets appear on the trainer's main dashboard. Each render function
        should accept the request context and return HTML.

        Args:
            trainer_id: The trainer's ID
            students: List of student data dictionaries

        Returns:
            List of callable render functions

#### `render_student_widgets`

```python
def render_student_widgets(self, trainer_id: str, student: Dict) -> List[Callable]:
```

Return list of render functions for student-specific widgets.

        Widgets appear on individual student pages when viewed by trainer.

        Args:
            trainer_id: The trainer's ID
            student: Student data dictionary

        Returns:
            List of callable render functions

#### `render_student_header_widgets`

```python
def render_student_header_widgets(self, student_id: str, trainer_id: str) -> List[Callable]:
```

Return list of render functions for student header area.

        Called when a student views their own page. Use this to show
        student-facing information or controls.

        Args:
            student_id: The student's ID
            trainer_id: The trainer's ID

        Returns:
            List of callable render functions

#### `get_context`

```python
def get_context(self, student_id: str) -> Dict[str, str]:
```

Get plugin-specific context information for a student.

        This provides key-value pairs for student context display.
        All values must be strings for consistent UI rendering.

        Args:
            student_id: The student's ID

        Returns:
            Dictionary of context strings (key: description, value: context data)

#### `export_config`

```python
def export_config(self, trainer_id: str) -> Optional[Dict]:
```

Export plugin configuration for YAML export.

        Return None if no configuration to export.

        Args:
            trainer_id: The trainer's ID

        Returns:
            Dictionary of configuration data or None

#### `import_config`

```python
def import_config(self, trainer_id: str, config: Dict) -> bool:
```

Import plugin configuration from YAML.

        Args:
            trainer_id: The trainer's ID
            config: Dictionary of configuration data

        Returns:
            True if import successful, False otherwise

#### `export_history`

```python
def export_history(self, trainer_id: str, student_id: Optional[str] = None) -> List[Dict[str, Any]]:
```

Export plugin-specific history events in minimal format.

        Each event must contain at minimum:
        - timestamp: ISO format datetime
        - type: event type (e.g., 'plugin.score_update')
        - plugin_id: this plugin's ID

        Additional fields must be kept minimal. Do not include data that
        can be inferred from configuration (like student names). The goal
        is to export only what's necessary for reconstructing history.

        Args:
            trainer_id: The trainer's ID
            student_id: Optional student ID to filter history for a specific student

        Returns:
            List of minimal event dictionaries

#### `import_history`

```python
def import_history(self, trainer_id: str, events: List[Dict[str, Any]], student_info: Dict = None) -> bool:
```

Import plugin-specific history events.

        Reconstruct plugin state from minimal event data. Use student_info
        to map IDs to names or other context when needed.

        Args:
            trainer_id: The trainer's ID
            events: List of minimal event dictionaries to import
            student_info: Optional dictionary with student information for reconstruction

        Returns:
            True if import successful, False otherwise

