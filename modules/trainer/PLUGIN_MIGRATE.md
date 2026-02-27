# Trainer plugin migration (core/ui split)

## New plugin structure

Each plugin can now expose two entry points:

- `plugin_core`: class inheriting `TrainerPluginCore` in `core.py`
- `plugin_ui`: class inheriting `TrainerPluginUI` in `ui.py`

Legacy plugins that still expose a single class inheriting `TrainerPlugin` continue to work.

## Base classes

- `modules/trainer/plugin_base_core.py`
  - `TrainerPluginCore`
  - owns lifecycle/data methods (`initialize`, `on_activate`, `on_deactivate`, `get_context`, `export_history`)
  - no Streamlit import

- `modules/trainer/plugin_base_ui.py`
  - `TrainerPluginUI`
  - receives a core instance in `__init__(core)`
  - owns render hooks (`render_student_widgets`, `render_dashboard_widgets`, `render_student_header_widgets`, `render_get_admin_tabs`)

- `modules/trainer/plugin_base.py`
  - keeps backward compatibility with `TrainerPlugin(TrainerPluginCore, TrainerPluginUI)`
  - `PluginManager` supports both legacy and split plugins

## PluginManager behavior

- `self.plugins`: always contains core plugin instances
- `self.ui_plugins`: contains UI plugin instances when Streamlit is available
- `get_plugin(plugin_id)`: returns the core plugin
- `get_ui_plugin(plugin_id)`: returns the UI plugin
- `get_ui_plugins_by_hook(...)`: filter active UI plugins by render hook

## Migration checklist

1. Move data/lifecycle methods to `core.py`
2. Move render methods to `ui.py`
3. Make UI methods call core methods (`self._core.<method>()`) for data operations
4. Update plugin `__init__.py`:
   - `plugin_core = <Name>PluginCore`
   - `plugin_ui = <Name>PluginUI`
   - keep `plugin = <Name>PluginCore` for compatibility
5. Verify headless import/initialization still works without UI files
