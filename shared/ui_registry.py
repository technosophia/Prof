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
from typing import Dict, List, Callable, Any, Set
import streamlit as st
from shared.logging import log

class UIRegistry:
    """Registry for UI modules and their render functions."""

    def __init__(self):
        self.modules: Dict[str, Dict] = {}
        # Use a set to track all injection points discovered (dynamic)
        self.injection_points: Set[str] = set()
        self._initialized = False
        self.module_handler = None  # Will be set externally

    def set_module_handler(self, handler):
        """Set the module handler instance."""
        self.module_handler = handler
        log("info", f"Module handler set in UI registry")

    def initialize(self):
        """Initialize the registry (discover modules)."""
        if not self._initialized:
            self.discover_and_register_modules()
            self._initialized = True

    def discover_and_register_modules(self):
        """Discover and register all UI modules in shared and modules directories."""
        # Get the directory where this file is located
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_dir)

        # Clear existing modules
        self.modules.clear()

        # Check if module handler is set
        if not self.module_handler:
            log("error", "Module handler not set in UI registry!")
            # Try to import it as fallback
            from shared.module_handler import module_handler
            self.module_handler = module_handler
            log("info", "Falling back to imported module handler")

        # Ensure module handler is initialized
        if not self.module_handler._initialized:
            log("info", "Module handler not initialized, initializing now")
            self.module_handler.initialize()

        # Get active modules
        active_modules = set(self.module_handler.get_active_modules())
        log("info", f"Active modules from handler: {active_modules}")

        # Discover UI modules in shared directory (including subdirectories)
        shared_dir = current_dir
        self._discover_ui_files_recursive(
            directory=shared_dir,
            is_shared=True,
            base_name="shared"
        )

        # Discover UI modules in modules directory
        modules_dir = os.path.join(project_root, "modules")
        if os.path.exists(modules_dir):
            # For each directory in modules, check if it's an active module
            for module_name in os.listdir(modules_dir):
                module_path = os.path.join(modules_dir, module_name)

                if os.path.isdir(module_path):
                    # Check if this module is active
                    if module_name in active_modules:
                        log("info", f"Module '{module_name}' is ACTIVE, discovering UI files")
                        self._discover_ui_files_recursive(
                            directory=module_path,
                            is_shared=False,
                            base_name=module_name
                        )
                    else:
                        log("info", f"Module '{module_name}' is INACTIVE, skipping")
        else:
            log("warning", f"Modules directory not found: {modules_dir}")

        log("info", f"Total UI modules registered: {len(self.modules)}")
        log("info", f"Registered UI modules: {list(self.modules.keys())}")

        # Log all discovered injection points
        log("debug", f"Discovered injection points: {sorted(self.get_all_injection_points())}")

    def _discover_ui_files_recursive(self, directory: str, is_shared: bool, base_name: str):
        """Recursively discover _ui.py files in a directory and its subdirectories."""
        log("debug", f"Discovering UI files in {directory} (base: {base_name}, shared: {is_shared})")

        if not os.path.exists(directory):
            return

        for root, dirs, files in os.walk(directory):
            # Skip __pycache__ directories
            dirs[:] = [d for d in dirs if d != '__pycache__']

            for file_name in files:
                if file_name.endswith('_ui.py') and file_name != 'ui_registry.py':
                    file_path = os.path.join(root, file_name)

                    # Generate a unique module key
                    if is_shared:
                        # For shared directory, use relative path from shared directory
                        rel_path = os.path.relpath(file_path, directory)
                        # Remove .py extension and replace path separators with _
                        module_key = rel_path.replace('.py', '').replace(os.path.sep, '_')
                    else:
                        # For module directories, include module name in the key
                        rel_path = os.path.relpath(file_path, directory)
                        # Remove .py extension and replace path separators with _
                        path_part = rel_path.replace('.py', '').replace(os.path.sep, '_')
                        module_key = f"{base_name}_{path_part}" if path_part else base_name

                    # Register the module
                    self.register_module(module_key, file_path, is_shared, base_name)

    def register_module(self, module_key: str, module_path: str, is_shared: bool = False, base_name: str = None):
        """Register a UI module from a file path."""
        log("info", f"Attempting to register module: {module_key} from {module_path}")

        # Check if module is already registered
        if module_key in self.modules:
            log("debug", f"Module {module_key} already registered, skipping")
            return

        try:
            # Check if file exists
            if not os.path.exists(module_path):
                log("error", f"Module file does not exist: {module_path}")
                return

            # Load the module
            spec = importlib.util.spec_from_file_location(module_key, module_path)
            if spec is None:
                log("error", f"Could not load spec for module: {module_key}")
                return

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_key] = module

            # Execute the module
            spec.loader.exec_module(module)

            # Find render functions using the new naming convention
            render_functions = {}
            PREFIX = "inject_ui_"

            for name, obj in inspect.getmembers(module):
                # Check if it's a callable function (not a class or module)
                if callable(obj) and not name.startswith('_') and not inspect.isclass(obj):
                    # Check if function name follows the new pattern: inject_ui_injectionpoint
                    if name.startswith(PREFIX):
                        injection_point = name[len(PREFIX):]  # Remove "inject_ui_" prefix

                        # Automatically register new injection points
                        self.injection_points.add(injection_point)

                        render_functions[injection_point] = obj
                        log("info", f"Found render function: {module_key}.{name} -> {injection_point}")

            if render_functions:
                self.modules[module_key] = {
                    'module': module,
                    'render_functions': render_functions,
                    'path': module_path,
                    'is_shared': is_shared,
                    'base_name': base_name
                }
                log("info", f"Successfully registered UI module: {module_key} with {len(render_functions)} render functions: {list(render_functions.keys())}")
            else:
                log("warning", f"No render functions found in module: {module_key}")

        except Exception as e:
            log("error", f"Failed to register UI module {module_key}: {str(e)}", exc_info=True)

    def render_all(self, injection_point: str) -> List[Any]:
        """Call all render functions for a specific injection point."""
        # No verification if injection point exists - just render if there are functions for it
        # New injection points are automatically registered when modules are discovered

        results = []

        # Get active modules from module handler
        active_modules = set()
        if self.module_handler:
            active_modules = set(self.module_handler.get_active_modules())

        for module_key, module_info in self.modules.items():
            # Shared modules are always rendered
            # Module directory modules are only rendered if the base module is active
            is_shared = module_info.get('is_shared', False)
            base_name = module_info.get('base_name')

            if not is_shared:
                # Check if the base module is active
                if base_name not in active_modules:
                    log("debug", f"Skipping module {module_key} because base module {base_name} is not active")
                    continue

            render_func = module_info['render_functions'].get(injection_point)
            if render_func:
                try:
                    log("debug", f"Rendering {injection_point} from {module_key}")
                    result = render_func()
                    results.append(result)
                except Exception as e:
                    log("error", f"Error rendering {injection_point} from {module_key}: {str(e)}", exc_info=True)
                    results.append(None)
            else:
                log("debug", f"No render function for {injection_point} in {module_key}")

        return results

    def render_admin_tabs(self) -> Dict[str, Any]:
        """Render all admin tabs from registered modules."""
        log("debug", "=== START COLLECTING ADMIN TABS ===")
        admin_tabs = {}
        active_modules = set(self.module_handler.get_active_modules() if self.module_handler else [])

        for module_key, module_info in self.modules.items():
            is_shared = module_info.get('is_shared', False)
            base_name = module_info.get('base_name')
            should_render = is_shared or (base_name in active_modules)

            log("debug", f"Processing module {module_key} | shared: {is_shared} | base: {base_name} | render: {should_render}")

            render_func = module_info['render_functions'].get('admin_tab')
            if render_func and should_render:
                try:
                    result = render_func()
                    log("debug", f"admin_tab result from {module_key}: {result}")
                    if result and isinstance(result, tuple) and len(result) == 2:
                        tab_name, content_func = result
                        admin_tabs[tab_name] = content_func
                        log("debug", f"ADDED TAB '{tab_name}' from {module_key}")
                except Exception as e:
                    log("error", f"Error getting admin_tab from {module_key}: {e}", exc_info=True)

        log("debug", f"=== FINAL ADMIN TABS: {list(admin_tabs.keys())} ===")
        return admin_tabs

    def get_all_injection_points(self) -> List[str]:
        """Get all registered injection points, sorted alphabetically."""
        return sorted(self.injection_points)

    def get_injection_point_stats(self) -> Dict[str, int]:
        """Get statistics about injection point usage across all modules."""
        stats = {}
        for injection_point in self.injection_points:
            count = 0
            for module_info in self.modules.values():
                if injection_point in module_info['render_functions']:
                    count += 1
            stats[injection_point] = count
        return stats

    def get_module(self, module_key: str) -> Dict:
        """Get information about a registered module."""
        return self.modules.get(module_key)

    def has_module(self, module_key: str) -> bool:
        """Check if a module is registered."""
        return module_key in self.modules

# Create a singleton instance
ui_registry = UIRegistry()

# Helper function for modules to register themselves
def register_ui_module(module_name: str, render_functions: Dict[str, Callable]):
    """Register a UI module directly with render functions."""
    if module_name in ui_registry.modules:
        log("warning", f"UI module {module_name} already registered, updating")

    ui_registry.modules[module_name] = {
        'module': None,
        'render_functions': render_functions,
        'path': None,
        'is_shared': False,
        'base_name': module_name.split('_')[0] if '_' in module_name else module_name
    }

    # Register any new injection points from the render functions
    for injection_point in render_functions.keys():
        ui_registry.injection_points.add(injection_point)

    log("info", f"Directly registered UI module: {module_name}")
