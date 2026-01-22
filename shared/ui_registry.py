"""UI Registry System

[agent]

Provides a modular UI injection system for Streamlit applications. UI modules
can register render functions that are automatically discovered and injected
into predefined injection points.

Module Discovery:
- Discovers UI modules from shared/*_ui.py files
- Discovers UI modules from modules/*/*_ui.py files (subdirectories within modules)

Naming Conventions:
- Module files must end with _ui.py
- Render functions can use either pattern:
  1. Direct injection point names: sidebar(), main_header(), etc.
  2. Namespaced pattern: modulename_render_injectionpoint()

Injection Points:
- sidebar: Content injected into the sidebar
- main_header: Content injected into the main header area
- main_before_conversation: Content injected before conversation interface
- main_no_user: Content injected when no user is logged in
- main_after_conversation: Content injected after conversation interface

Module Requirements:
1. Must be placed in shared/ or modules/*/ directories
2. Must have filename ending with _ui.py
3. Must define at least one render function matching an injection point
4. Render functions must be callable and return a value

Registry Initialization:
Automatically initialized and cached in Streamlit session state.
No manual initialization required in modules.
"""

import os
import sys
import importlib.util
import inspect
from typing import Dict, List, Callable, Any
import streamlit as st
from shared.logging import log

class UIRegistry:
    """Registry for UI modules and their render functions."""

    def __init__(self):
        self.modules: Dict[str, Dict] = {}
        self.injection_points = {
            'sidebar',
            'main_header',
            'main_before_conversation',
            'main_no_user',
            'main_after_conversation'
        }
        self._initialized = False

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

        # Search paths for UI modules
        search_paths = [
            current_dir,  # shared directory
            os.path.join(project_root, "modules")  # modules directory
        ]

        for base_path in search_paths:
            if not os.path.exists(base_path):
                log("debug", f"Search path not found: {base_path}")
                continue

            self._discover_modules_in_directory(base_path)

    def _discover_modules_in_directory(self, base_path: str):
        """Discover UI modules in a directory and its subdirectories."""
        log("debug", f"Discovering UI modules in: {base_path}")

        # Walk through directory and subdirectories
        for root, dirs, files in os.walk(base_path):
            for file_name in files:
                if file_name.endswith('_ui.py') and file_name != 'ui_registry.py':
                    module_name = file_name[:-3]  # Remove .py
                    module_path = os.path.join(root, file_name)

                    # Create a unique module key based on relative path
                    rel_path = os.path.relpath(root, base_path)
                    if rel_path == '.':
                        module_key = module_name
                    else:
                        # Convert path to valid module identifier
                        path_parts = rel_path.replace(os.sep, '_')
                        module_key = f"{path_parts}_{module_name}"

                    log("debug", f"Found UI module: {file_name} at {module_path} (key: {module_key})")
                    self.register_module(module_key, module_path)

    def register_module(self, module_name: str, module_path: str):
        """Register a UI module from a file path."""
        try:
            # Load the module
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            if spec is None:
                log("error", f"Could not load spec for module: {module_name}")
                return

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module

            # Execute the module
            spec.loader.exec_module(module)

            # Find render functions
            render_functions = {}
            for name, obj in inspect.getmembers(module):
                # Check if it's a callable function (not a class or module)
                if callable(obj) and not name.startswith('_') and not inspect.isclass(obj):
                    # Check if function name matches an injection point
                    if name in self.injection_points:
                        render_functions[name] = obj
                        log("debug", f"Found render function: {module_name}.{name}")
                    elif name.startswith(f"{module_name}_render_"):
                        # Extract injection point from name
                        injection_point = name[len(f"{module_name}_render_"):]
                        if injection_point in self.injection_points:
                            render_functions[injection_point] = obj
                            log("debug", f"Found render function: {module_name}.{name} -> {injection_point}")
                    else:
                        # Check if function follows modulename_render_injectionpoint pattern
                        # where modulename might be different from module_name
                        for ip in self.injection_points:
                            if name.endswith(f"_render_{ip}"):
                                # Extract base module name from function name
                                base_name = name[:-len(f"_render_{ip}")]
                                if base_name:
                                    render_functions[ip] = obj
                                    log("debug", f"Found render function: {module_name}.{name} -> {ip}")
                                    break

            if render_functions:
                self.modules[module_name] = {
                    'module': module,
                    'render_functions': render_functions,
                    'path': module_path
                }
                log("info", f"Registered UI module: {module_name} with {len(render_functions)} render functions: {list(render_functions.keys())}")
            else:
                log("warning", f"No render functions found in module: {module_name}")

        except Exception as e:
            log("error", f"Failed to register UI module {module_name}: {str(e)}", exc_info=True)

    def render_all(self, injection_point: str) -> List[Any]:
        """Call all render functions for a specific injection point."""
        if injection_point not in self.injection_points:
            log("error", f"Unknown injection point: {injection_point}")
            return []

        results = []

        for module_name, module_info in self.modules.items():
            render_func = module_info['render_functions'].get(injection_point)
            if render_func:
                try:
                    # Call the render function
                    result = render_func()
                    results.append(result)
                except Exception as e:
                    log("error", f"Error rendering {injection_point} from {module_name}: {str(e)}", exc_info=True)
                    results.append(None)

        return results

    def get_module(self, module_name: str) -> Dict:
        """Get information about a registered module."""
        return self.modules.get(module_name)

    def has_module(self, module_name: str) -> bool:
        """Check if a module is registered."""
        return module_name in self.modules

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
        'path': None
    }
    log("info", f"Directly registered UI module: {module_name}")
