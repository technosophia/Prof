"""UI Registry System

Provides a modular UI injection system for Streamlit applications. UI modules
can register render functions that are automatically discovered and injected
into predefined injection points.

Module Discovery:
- Discovers UI modules from shared/**/*_ui.py files (including subdirectories)
- Discovers UI modules from modules/**/*_ui.py files (all subdirectories within modules)

Naming Conventions:
- Module files must end with _ui.py
- Render functions must follow the pattern: inject_ui_injectionpoint()
  Example: inject_ui_sidebar(), inject_ui_main_header(), etc.

Injection Points:
- initialize: Content injected at the beginning of app initialization
- sidebar: Content injected into the sidebar
- main_header: Content injected into the main header area
- main_before_conversation: Content injected before conversation interface
- main_content: Content injected when no user is logged in
- main_after_conversation: Content injected after conversation interface
- main_footer: Content injected into the main footer area
- admin_tab: NEW: Content injected as admin tabs in the admin interface

Module Requirements:
1. Must be placed in shared/ or modules/*/ directories (or subdirectories)
2. Must have filename ending with _ui.py
3. Must define at least one render function matching the inject_ui_injectionpoint pattern
4. Render functions must be callable and return a value

Registry Initialization:
Automatically initialized and cached in Streamlit session state.
No manual initialization required in modules.
"""

import os
import sys
import importlib.util
import inspect
from typing import Dict, List, Callable, Any, Set, Tuple
import streamlit as st
from shared.common import _, log, get_config

@st.cache_resource
def _discover_ui_modules(active_modules_tuple: Tuple[str, ...]) -> Tuple[Dict[str, Dict], Set[str]]:
    """Cached discovery of all UI modules and their render functions."""
    active_modules = set(active_modules_tuple)
    modules: Dict[str, Dict] = {}
    injection_points: Set[str] = set()

    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    shared_dir = current_dir

    def _recursive_discover(directory: str, is_shared: bool, base_name: str):
        if not os.path.exists(directory):
            return

        for root, dirs, files in os.walk(directory):
            # Skip __pycache__ directories
            dirs[:] = [d for d in dirs if d != '__pycache__']

            for file_name in files:
                if file_name.endswith('_ui.py') and file_name != 'ui_registry.py':
                    file_path = os.path.join(root, file_name)

                    # Generate unique module key
                    if is_shared:
                        rel_path = os.path.relpath(file_path, directory)
                        module_key = rel_path[:-3].replace(os.path.sep, '_')
                    else:
                        rel_path = os.path.relpath(file_path, directory)
                        path_part = rel_path[:-3].replace(os.path.sep, '_')
                        module_key = f"{base_name}_{path_part}" if path_part else base_name

                    try:
                        spec = importlib.util.spec_from_file_location(module_key, file_path)
                        if spec is None or spec.loader is None:
                            log("error", f"Could not create spec for {module_key}")
                            continue

                        module = importlib.util.module_from_spec(spec)
                        sys.modules[module_key] = module
                        spec.loader.exec_module(module)

                        render_functions: Dict[str, Callable] = {}
                        PREFIX = "inject_ui_"

                        for name, obj in inspect.getmembers(module):
                            if (inspect.isfunction(obj) and
                                not name.startswith('_') and
                                not inspect.isclass(obj) and
                                name.startswith(PREFIX)):
                                injection_point = name[len(PREFIX):]
                                injection_points.add(injection_point)
                                render_functions[injection_point] = obj
                                log("info", f"Found render function: {module_key}.{name} -> {injection_point}")

                        if render_functions:
                            modules[module_key] = {
                                'render_functions': render_functions,
                                'path': file_path,
                                'is_shared': is_shared,
                                'base_name': base_name
                            }
                            log("info", f"Successfully registered UI module: {module_key} with {len(render_functions)} render functions: {list(render_functions.keys())}")
                        else:
                            log("warning", f"No render functions found in module: {module_key}")

                    except Exception as e:
                        log("error", f"Failed to register UI module {module_key}: {str(e)}", exc_info=True)

    # Discover shared UI modules (always included)
    _recursive_discover(shared_dir, is_shared=True, base_name="shared")

    # Discover module UI modules (only active ones)
    modules_dir = os.path.join(project_root, "modules")
    if os.path.exists(modules_dir):
        for module_name in os.listdir(modules_dir):
            module_path = os.path.join(modules_dir, module_name)
            if os.path.isdir(module_path):
                if module_name in active_modules:
                    log("info", f"Module '{module_name}' is ACTIVE, discovering UI files")
                    _recursive_discover(module_path, is_shared=False, base_name=module_name)
                else:
                    log("info", f"Module '{module_name}' is INACTIVE, skipping")
    else:
        log("warning", f"Modules directory not found: {modules_dir}")

    return modules, injection_points


class UIRegistry:
    """Registry for UI modules and their render functions."""

    def __init__(self):
        self.modules: Dict[str, Dict] = {}
        self.injection_points: Set[str] = set()
        self.render_callbacks: List[Callable[[str, str, Any], Any]] = []
        self.last_active_hash: Tuple[str, ...] | None = None
        self.module_handler = None

    def set_module_handler(self, handler):
        """Set the module handler instance."""
        self.module_handler = handler

    def ensure_initialized(self):
        """Ensure the registry is initialized and refreshed if active modules changed."""
        if not self.module_handler:
            log("error", "Module handler not set in UI registry!")
            from shared.module_handler import module_handler
            self.module_handler = module_handler
            log("info", "Falling back to imported module handler")

        # Ensure module handler itself is initialized
        if hasattr(self.module_handler, '_initialized') and not self.module_handler._initialized:
            self.module_handler.initialize()

        active_modules = self.module_handler.get_active_modules()
        current_hash = tuple(sorted(active_modules))

        if current_hash != self.last_active_hash:
            self.modules, self.injection_points = _discover_ui_modules(current_hash)
            self.last_active_hash = current_hash
            log("info", f"UI Registry refreshed: {len(self.modules)} modules registered")
            log("info", f"Registered UI modules: {list(self.modules.keys())}")
            log("debug", f"Discovered injection points: {sorted(self.injection_points)}")

    def register_render_callback(self, callback: Callable[[str, str, Any], Any]):
        """Register a callback to process render results (for debugging/alteration)."""
        if callable(callback):
            self.render_callbacks.append(callback)
            log("debug", f"Registered render callback: {callback.__name__ if hasattr(callback, '__name__') else 'anonymous'}")
        else:
            log("warning", "Attempted to register non-callable as render callback")

    def _execute_render(self, injection_point: str, module_key: str, render_func: Callable) -> Any:
        """Execute a single render function and apply post-render callbacks."""
        try:
            log("debug", f"Rendering {injection_point} from {module_key}")
            result = render_func()
            for cb in self.render_callbacks:
                new_result = cb(injection_point, module_key, result)
                if new_result is not None:
                    result = new_result
            return result
        except Exception as e:
            log("error", f"Error rendering injection point - {injection_point} from {module_key}: {str(e)}", exc_info=True)
            return None

    def render(self, injection_point: str) -> Dict[str, Any]:
        """Render all functions for a specific injection point.

        Returns a dictionary where:
        - For admin_tab: keys are tab names, values are content functions
        - For other injection points: keys are module keys, values are results (usually None)
        """
        self.ensure_initialized()

        results = {}
        active_modules = set(self.module_handler.get_active_modules())

        for module_key, module_info in self.modules.items():
            is_shared = module_info['is_shared']
            base_name = module_info['base_name']

            if not is_shared and base_name not in active_modules:
                log("debug", f"Skipping module {module_key} because base module {base_name} is not active")
                continue

            render_func = module_info['render_functions'].get(injection_point)
            if render_func:
                result = self._execute_render(injection_point, module_key, render_func)

                if result is not None:
                    if injection_point == 'admin_tab':
                        # For admin tabs, expect (tab_name, content_func) tuple
                        if isinstance(result, tuple) and len(result) == 2:
                            tab_name, content_func = result
                            results[tab_name] = content_func
                            log("debug", f"ADDED TAB '{tab_name}' from {module_key}")
                        else:
                            log("warning", f"Module {module_key} returned invalid format for admin_tab. Expected (tab_name, content_func) tuple.")
                    else:
                        # For other injection points, store by module key
                        results[module_key] = result

        return results

    def render_all(self, injection_point: str) -> List[Any]:
        """Legacy method: Call all render functions for a specific injection point.

        Returns a list of results (for backward compatibility).
        """
        results_dict = self.render(injection_point)
        return list(results_dict.values())

    def render_admin_tabs(self) -> Dict[str, Any]:
        """Render all admin tabs from registered modules.

        Returns a dictionary of {tab_name: content_function}
        """
        admin_tabs = self.render("admin_tab")
        return admin_tabs

    def get_all_injection_points(self) -> List[str]:
        """Get all registered injection points, sorted alphabetically."""
        self.ensure_initialized()
        return sorted(self.injection_points)

    def get_injection_point_stats(self) -> Dict[str, int]:
        """Get statistics about injection point usage across all modules."""
        self.ensure_initialized()
        stats = {}
        for injection_point in self.injection_points:
            count = sum(1 for info in self.modules.values() if injection_point in info['render_functions'])
            stats[injection_point] = count
        return stats

    def get_module(self, module_key: str) -> Dict:
        """Get information about a registered module."""
        self.ensure_initialized()
        return self.modules.get(module_key)

    def has_module(self, module_key: str) -> bool:
        """Check if a module is registered."""
        self.ensure_initialized()
        return module_key in self.modules


# Create a singleton instance
ui_registry = UIRegistry()
