"""
UI Registry System
==================

This module provides a registry system for UI modules to inject content into
the main application. UI modules can register render functions for specific
injection points.

Injection Points:
- sidebar: Content injected into the sidebar
- main_header: Content injected into the main header area
- main_before_conversation: Content injected before conversation interface
- main_no_user: Content injected when no user is logged in
- main_after_conversation: Content injected after conversation interface

UI modules should be placed in the shared directory and named with _ui.py suffix.
They should define functions with names that match the injection points.
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
        """Discover and register all UI modules in the shared directory."""
        # Get the directory where this file is located
        current_dir = os.path.dirname(os.path.abspath(__file__))
        shared_dir = current_dir

        log("debug", f"Looking for UI modules in: {shared_dir}")

        if not os.path.exists(shared_dir):
            log("warning", f"Shared directory not found: {shared_dir}")
            return

        # Look for files ending with _ui.py
        for file_name in os.listdir(shared_dir):
            if file_name.endswith('_ui.py') and file_name != 'ui_registry.py':
                module_name = file_name[:-3]  # Remove .py
                module_path = os.path.join(shared_dir, file_name)
                log("debug", f"Found UI module file: {file_name} at {module_path}")
                self.register_module(module_name, module_path)

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
        log("info", f"Rendering all modules for injection point: {injection_point}")
        log("info", f"Available modules: {list(self.modules.keys())}")

        if injection_point not in self.injection_points:
            log("error", f"Unknown injection point: {injection_point}")
            return []

        results = []

        for module_name, module_info in self.modules.items():
            render_func = module_info['render_functions'].get(injection_point)
            if render_func:
                try:
                    log("debug", f"Calling render function for {module_name}.{injection_point}")
                    # Call the render function
                    result = render_func()
                    log("debug", f"Render function {module_name}.{injection_point} returned: {result}")
                    results.append(result)
                except Exception as e:
                    log("error", f"Error rendering {injection_point} from {module_name}: {str(e)}", exc_info=True)
                    results.append(None)
            else:
                log("debug", f"No render function for {injection_point} in module {module_name}")

        log("debug", f"Render results for {injection_point}: {len(results)} results")
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
