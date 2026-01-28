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
- Render functions must follow the pattern: inject_ui_injectionpoint()
  Example: inject_ui_sidebar(), inject_ui_main_header(), etc.

Injection Points:
- sidebar: Content injected into the sidebar
- main_header: Content injected into the main header area
- main_before_conversation: Content injected before conversation interface
- main_content: Content injected when no user is logged in
- main_after_conversation: Content injected after conversation interface
- main_footer: Content injected into the main footer area

Module Requirements:
1. Must be placed in shared/ or modules/*/ directories
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
            'main_content',
            'main_after_conversation',
            'main_footer',
        }
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

        active_modules = set(self.module_handler.get_active_modules())
        log("info", f"Active modules from handler: {active_modules} (total: {len(active_modules)})")

        # Log the actual modules discovered by handler
        log("info", f"Module handler has {len(self.module_handler.modules)} modules: {list(self.module_handler.modules.keys())}")

        # Always load shared modules (not in modules directory)
        log("info", f"Loading shared UI modules from: {current_dir}")
        # Get list of files in shared directory
        shared_files = os.listdir(current_dir) if os.path.exists(current_dir) else []
        log("info", f"Shared directory contains {len(shared_files)} files")

        for file_name in shared_files:
            if file_name.endswith('_ui.py') and file_name != 'ui_registry.py':
                module_path = os.path.join(current_dir, file_name)
                module_key = file_name[:-3]  # Remove _ui.py
                log("info", f"Found shared UI file: {file_name} -> {module_key}")
                self.register_module(module_key, module_path)

        # Load modules from modules directory
        modules_dir = os.path.join(project_root, "modules")
        if os.path.exists(modules_dir):
            log("info", f"Looking for UI modules in modules directory: {modules_dir}")
            modules_dir_contents = os.listdir(modules_dir)
            log("info", f"Modules directory contains: {modules_dir_contents}")

            # Walk through each item in modules directory
            for item in modules_dir_contents:
                item_path = os.path.join(modules_dir, item)

                # Check if it's a directory (a module)
                if os.path.isdir(item_path):
                    module_name = item
                    log("info", f"Found module directory: {module_name}")

                    # Check if module is active
                    if module_name in active_modules:
                        log("info", f"Module '{module_name}' is ACTIVE, searching for UI files")

                        # Look for _ui.py files in this module directory
                        try:
                            module_files = os.listdir(item_path)
                            log("info", f"Module '{module_name}' contains: {module_files}")

                            ui_files_found = []
                            for file_name in module_files:
                                if file_name.endswith('_ui.py'):
                                    ui_files_found.append(file_name)
                                    module_path = os.path.join(item_path, file_name)
                                    module_key = module_name  # Use directory name as key
                                    log("info", f"Found module UI file: {file_name} in {module_name} -> {module_key}")
                                    self.register_module(module_key, module_path)

                            if not ui_files_found:
                                log("warning", f"No _ui.py files found in module directory: {module_name}")
                        except Exception as e:
                            log("error", f"Error scanning module directory {module_name}: {str(e)}")
                    else:
                        log("info", f"Module '{module_name}' is INACTIVE, skipping")
                else:
                    log("debug", f"Skipping non-directory: {item}")
        else:
            log("warning", f"Modules directory not found: {modules_dir}")

        log("info", f"Total UI modules registered: {len(self.modules)}")
        log("info", f"Registered UI modules: {list(self.modules.keys())}")

    def _discover_modules_in_directory(self, directory: str, module_name: str = None, is_shared: bool = False):
        """Discover UI modules in a directory."""
        log("debug", f"Discovering UI modules in directory: {directory}")
        log("debug", f"Module name: {module_name}, Is shared: {is_shared}")

        if not os.path.exists(directory):
            log("debug", f"Directory not found: {directory}")
            return

        ui_files_found = []
        for file_name in os.listdir(directory):
            log("debug", f"Checking file: {file_name}")
            if file_name.endswith('_ui.py') and file_name != 'ui_registry.py':
                ui_files_found.append(file_name)
                module_path = os.path.join(directory, file_name)

                # Determine module key
                if is_shared:
                    # For shared modules, use filename without _ui
                    module_key = file_name[:-3]  # Remove _ui.py
                else:
                    # For module directories, use directory name as module key
                    module_key = module_name or os.path.basename(directory)

                log("info", f"Found UI file: {file_name} in {directory} -> module key: {module_key}")
                log("debug", f"Module path: {module_path}")
                self.register_module(module_key, module_path)

        if not ui_files_found:
            log("debug", f"No _ui.py files found in {directory}")

    def register_module(self, module_name: str, module_path: str):
        """Register a UI module from a file path."""
        log("info", f"Attempting to register module: {module_name} from {module_path}")

        try:
            # Check if file exists
            if not os.path.exists(module_path):
                log("error", f"Module file does not exist: {module_path}")
                return

            log("debug", f"File exists, loading module...")

            # Load the module
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            if spec is None:
                log("error", f"Could not load spec for module: {module_name}")
                return

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module

            # Execute the module
            log("debug", f"Executing module...")
            spec.loader.exec_module(module)

            # Log what's in the module
            import inspect
            module_contents = [name for name, obj in inspect.getmembers(module)
                              if not name.startswith('_') and callable(obj)]
            log("info", f"Module {module_name} contains callable functions: {module_contents}")

            # Find render functions using the new naming convention
            render_functions = {}
            PREFIX = "inject_ui_"

            for name, obj in inspect.getmembers(module):
                # Check if it's a callable function (not a class or module)
                if callable(obj) and not name.startswith('_') and not inspect.isclass(obj):
                    log("debug", f"Checking function: {name}")

                    # Check if function name follows the new pattern: inject_ui_injectionpoint
                    if name.startswith(PREFIX):
                        injection_point = name[len(PREFIX):]  # Remove "inject_ui_" prefix

                        if injection_point in self.injection_points:
                            render_functions[injection_point] = obj
                            log("info", f"Found render function: {module_name}.{name} -> {injection_point}")
                        else:
                            log("warning", f"Function {name} has correct prefix but unknown injection point: {injection_point}")
                    else:
                        log("debug", f"Function {name} doesn't match inject_ui_ pattern")

            if render_functions:
                self.modules[module_name] = {
                    'module': module,
                    'render_functions': render_functions,
                    'path': module_path
                }
                log("info", f"Successfully registered UI module: {module_name} with {len(render_functions)} render functions: {list(render_functions.keys())}")
            else:
                log("warning", f"No render functions found in module: {module_name}")
                log("debug", f"Available functions in module: {module_contents}")

        except Exception as e:
            log("error", f"Failed to register UI module {module_name}: {str(e)}", exc_info=True)

    def render_all(self, injection_point: str) -> List[Any]:
        """Call all render functions for a specific injection point."""
        if injection_point not in self.injection_points:
            log("error", f"Unknown injection point: {injection_point}")
            return []

        results = []

        # Get active modules from module handler
        active_modules = set()
        if self.module_handler:
            active_modules = set(self.module_handler.get_active_modules())
        else:
            # Fallback to imported module handler
            try:
                from shared.module_handler import module_handler
                active_modules = set(module_handler.get_active_modules())
            except:
                log("error", "Could not get active modules")

        log("debug", f"Rendering {injection_point} - Active modules: {active_modules}")
        log("debug", f"Available modules in registry: {list(self.modules.keys())}")

        for module_name, module_info in self.modules.items():
            # Check if module is active
            # For shared modules (user_ui, conservation_ui), always render them
            # For module directory modules (debug), only render if active
            is_shared = "shared" in module_info.get('path', '') or module_name in ['user_ui', 'conservation_ui']

            if not is_shared and module_name not in active_modules:
                log("debug", f"Skipping inactive module: {module_name}")
                continue

            render_func = module_info['render_functions'].get(injection_point)
            if render_func:
                try:
                    log("debug", f"Rendering {injection_point} from {module_name}")
                    # Call the render function
                    result = render_func()
                    results.append(result)
                except Exception as e:
                    log("error", f"Error rendering {injection_point} from {module_name}: {str(e)}", exc_info=True)
                    results.append(None)
            else:
                log("debug", f"No render function for {injection_point} in {module_name}")

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
