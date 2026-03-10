## UI Injection System

UI modules are `*_ui.py` files that expose functions following the pattern: `inject_ui_[injection_point]()`.

### File Requirements
- Location: `shared/` or `modules/[module_name]/`
- Naming: Must end with `_ui.py` (e.g., `analytics_ui.py`)
- Functions: Must be named exactly `inject_ui_[injection_point]()`
- Content: Use Streamlit commands (`st.*`) to render UI

### Injection Points

| Injection Point | Location | Return Format |
|----------------|----------|---------------|
| `initialize` | App startup | None (setup only) |
| `sidebar` | Main sidebar | None (use `st.*`) |
| `main_header` | Top of chat page | None (use `st.*`) |
| `main_before_conversation` | Before chat messages | None (use `st.*`) |
| `main_content` | Fallback (no user) | None (use `st.*`) |
| `main_after_conversation` | After chat messages | None (use `st.*`) |
| `main_footer` | Bottom of main area | None (use `st.*`) |
| `settings_content` | User settings page | None (use `st.*`) |
| `admin_tab` | Admin interface | `(tab_name: str, render_func: callable)` |
| `settings_tab` | Admin interface | `(tab_name: str, render_func: callable)` |


### Examples

#### Basic Sidebar Module
```python
# modules/analytics/analytics_ui.py
def inject_ui_sidebar():
    if st.checkbox("Show analytics"):
        st.line_chart(data)
```

#### Admin Tab Module
```python
# modules/user_manager/user_manager_ui.py
def inject_ui_admin_tab():
    def render():
        st.header("User Management")
        users = get_users()
        for user in users:
            st.write(f"- {user.name}")
    return ("User Manager", render)
```

#### Settings Module
```python
# modules/notifications/notifications_ui.py
def inject_ui_settings_content():
    st.subheader("Notification Settings")
    email = st.text_input("Email address")
```

### Registry Usage
```python
from shared.ui_registry import ui_registry

# Get all injection points
points = ui_registry.get_all_injection_points()

# Render a specific injection point
ui_registry.render("sidebar")  # Calls all matching functions

# Get admin tabs (returns list of (name, render_func))
admin_tabs = ui_registry.render_admin_tabs()
```

## Important Notes

- Multiple modules can implement the same injection point (execution order not guaranteed)
- Shared modules (`shared/`) are always active; feature modules respect activation status
- UI modules should focus on presentation logic only
- Access module status with: `module_handler.is_module_active("module_name")`

## Quick Troubleshooting

| Issue | Check |
|-------|-------|
| Module not appearing | `module_handler.get_active_modules()` |
| UI not rendering | Function name matches pattern exactly? |
| Injection point not found | File ends with `_ui.py`? In correct location? |
| Module loading errors | Validate `module.json` format and dependencies |
