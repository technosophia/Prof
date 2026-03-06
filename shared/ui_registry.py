"""UI Registry System

Provides a modular UI injection system for Streamlit applications. UI modules
can register render functions that are automatically discovered and injected
into predefined injection points.

STREAMLIT DEPENDENCY IS INTENTIONAL HERE. This module runs only in a Streamlit
context and is responsible for:
  1. Discovering *_ui.py files
  2. Calling inject_ui_xxx() functions (Streamlit rendering)
  3. Calling inject_ui_initialize() for LEGACY modules (backward compatibility)
     New modules use on_module_activated() via module_handler instead.

ui_registry NEVER calls on_module_activated / on_module_deactivated — those are
the responsibility of module_handler (no Streamlit).
"""

import os
import sys
import importlib.util
import inspect
from typing import Dict, List, Callable, Any, Set, Tuple, Optional
from core.logging import log


def _discover_ui_modules(
    active_modules_tuple: Tuple[str, ...],
    module_entries: Tuple[Tuple[str, str, str], ...],
    shared_ui_dir: str | None = None,
) -> Tuple[Dict[str, Dict], Set[str]]:
    """Cached discovery of all UI modules and their render functions."""
    active_modules = set(active_modules_tuple)
    modules: Dict[str, Dict] = {}
    injection_points: Set[str] = set()

    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    shared_dir = shared_ui_dir or current_dir

    def _recursive_discover(directory: str, is_shared: bool, base_name: str, import_path: str):
        if not os.path.exists(directory):
            return

        base_dir = os.path.abspath(directory)

        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if d != '__pycache__']

            # Do not recurse into nested modules from parent module traversal.
            if os.path.abspath(root) != base_dir and os.path.exists(os.path.join(root, 'module.json')):
                dirs[:] = []
                continue

            for file_name in files:
                if file_name.endswith('_ui.py') and file_name != 'ui_registry.py':
                    file_path = os.path.join(root, file_name)

                    rel_path = os.path.relpath(file_path, project_root)
                    module_key = rel_path[:-3].replace(os.path.sep, '_')

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
                                log("debug", f"Found render function: {module_key}.{name} -> {injection_point}")

                        if render_functions:
                            modules[module_key] = {
                                'render_functions': render_functions,
                                'path': file_path,
                                'is_shared': is_shared,
                                'base_name': base_name,
                                'import_path': import_path,
                                'module': module,
                            }
                            log("info", f"Registered UI module: {module_key} with {len(render_functions)} functions: {list(render_functions.keys())}")
                        else:
                            log("warning", f"No render functions found in module: {module_key}")

                    except Exception as e:
                        log("error", f"Failed to register UI module {module_key}: {str(e)}", stacktrace=True)

    _recursive_discover(shared_dir, is_shared=True, base_name="shared", import_path="shared")

    for module_name, module_path, module_import_path in module_entries:
        if module_name in active_modules:
            log("info", f"Module '{module_name}' is ACTIVE, discovering UI files")
            _recursive_discover(module_path, is_shared=False, base_name=module_name, import_path=module_import_path)
        else:
            log("info", f"Module '{module_name}' is INACTIVE, skipping")

    return modules, injection_points



class UIRegistry:
    """
    Registry for UI modules and their render functions.

    Responsible ONLY for Streamlit UI injection points (inject_ui_xxx).
    Functional module lifecycle (on_module_activated etc.) is handled by
    module_handler, not here.

    Backward compatibility:
    - inject_ui_initialize() is still called for ALL modules (legacy + new)
      because it is the only safe place to set up st.session_state.
    - on_module_activated() is called by module_handler (no Streamlit).
    """

    def __init__(self, shared_ui_dir: str | None = None):
        self.modules: Dict[str, Dict] = {}
        self.injection_points: Set[str] = set()
        self.render_callbacks: List[Callable[[str, str, Any], Any]] = []
        self.last_active_hash: Tuple[str, ...] | None = None
        self.module_handler = None
        self.shared_ui_dir = shared_ui_dir
        # Track which modules have had inject_ui_initialize called
        self._initialized_modules: Set[str] = set()
        # Cache for lazy-loaded render results
        self._tab_cache: Dict[str, Tuple[str, Callable]] = {}

    def set_module_handler(self, handler, shared_ui_dir: str | None = None):
        """Set the module handler instance."""
        self.module_handler = handler
        if shared_ui_dir is not None:
            self.shared_ui_dir = shared_ui_dir

    def ensure_initialized(self):
        """Ensure the registry is initialized and refreshed if active modules changed."""
        if not self.module_handler:
            log("error", "Module handler not set in UI registry!")
            from shared.module_handler import module_handler
            self.module_handler = module_handler
            log("info", "Falling back to imported module handler")

        if hasattr(self.module_handler, '_initialized') and not self.module_handler._initialized:
            self.module_handler.initialize()

        active_modules = self.module_handler.get_active_modules()
        current_hash = tuple(sorted(active_modules))
        module_entries = tuple(
            sorted(
                (
                    module_name,
                    module_info.get('path', ''),
                    module_info.get('import_path', f"modules.{module_name}"),
                )
                for module_name, module_info in self.module_handler.get_all_modules().items()
                if module_info.get('path')
            )
        )

        if current_hash != self.last_active_hash:
            self.modules, self.injection_points = _discover_ui_modules(
                current_hash,
                module_entries,
                self.shared_ui_dir,
            )
            self.last_active_hash = current_hash
            # Clear tab cache when modules change
            self._tab_cache.clear()
            log("info", f"UI Registry refreshed: {len(self.modules)} modules registered")
            log("debug", f"Discovered injection points: {sorted(self.injection_points)}")

            # Call inject_ui_initialize for newly discovered modules
            # This is the ONLY place inject_ui_initialize is called automatically.
            # It is intentionally Streamlit-aware: it sets up st.session_state.
            self._run_initialize_hooks(current_hash)

    def _run_initialize_hooks(self, active_modules_tuple: Tuple[str, ...]) -> None:
        """
        Call inject_ui_initialize() for any module that hasn't been initialized yet.

        This covers:
        - Legacy modules that use inject_ui_initialize for ALL setup
        - New-style modules that use inject_ui_initialize ONLY for st.session_state setup

        Functional setup (driver registration, LLM callbacks) must have already been
        done via on_module_activated() by the time this runs.
        """
        for module_key, module_info in self.modules.items():
            base_name = module_info['base_name']
            if base_name in self._initialized_modules:
                continue

            init_fn = module_info['render_functions'].get('initialize')
            if init_fn is not None:
                try:
                    init_fn()
                    log("info", f"Called inject_ui_initialize for module: {base_name}")
                except Exception as e:
                    log("error", f"inject_ui_initialize failed for {base_name}: {e}", stacktrace=True)

            self._initialized_modules.add(base_name)

    def register_render_callback(self, callback: Callable[[str, str, Any], Any]):
        """Register a callback to process render results."""
        if callable(callback):
            self.render_callbacks.append(callback)
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
            log("error", f"Error rendering {injection_point} from {module_key}: {str(e)}", stacktrace=True)
            return None

    def render(self, injection_point: str) -> Dict[str, Any]:
        """
        Render all functions for a specific injection point.

        Returns a dict:
        - For admin_tab: keys are tab names, values are content functions
        - For other injection points: keys are module keys, values are results
        """
        self.ensure_initialized()

        results = {}
        active_modules = set(self.module_handler.get_active_modules())

        for module_key, module_info in self.modules.items():
            is_shared = module_info['is_shared']
            base_name = module_info['base_name']

            if not is_shared and base_name not in active_modules:
                log("debug", f"Skipping {module_key}: base module {base_name} is not active")
                continue

            render_func = module_info['render_functions'].get(injection_point)
            if render_func:
                result = self._execute_render(injection_point, module_key, render_func)

                if result is not None:
                    if injection_point == 'admin_tab':
                        if isinstance(result, tuple) and len(result) == 2:
                            tab_name, content_func = result
                            results[tab_name] = content_func
                            #log("debug", f"ADDED TAB '{tab_name}' from {module_key}")
                        else:
                            log("warning", f"Module {module_key} returned invalid format for admin_tab.")
                    else:
                        results[module_key] = result

        return results

    def render_all(self, injection_point: str) -> List[Any]:
        """Legacy: returns list of results."""
        return list(self.render(injection_point).values())

    def get_admin_tabs(self) -> Dict[str, Tuple[str, Callable]]:
        """
        Get all admin tabs without rendering them.
        Returns {tab_name: (module_key, render_function)} for lazy loading.
        """
        self.ensure_initialized()

        tabs = {}
        active_modules = set(self.module_handler.get_active_modules())

        for module_key, module_info in self.modules.items():
            is_shared = module_info['is_shared']
            base_name = module_info['base_name']

            if not is_shared and base_name not in active_modules:
                continue

            render_func = module_info['render_functions'].get('admin_tab')
            if render_func:
                try:
                    # Call the function to get tab info without rendering content
                    result = render_func()
                    if isinstance(result, tuple) and len(result) == 2:
                        tab_name, content_func = result
                        tabs[tab_name] = (module_key, content_func)
                        log("debug", f"Found tab '{tab_name}' from {module_key}")
                except Exception as e:
                    log("error", f"Error getting tab info from {module_key}: {e}")

        return tabs

    def render_admin_tab(self, tab_name: str, module_key: str, content_func: Callable) -> Any:
        """
        Render a specific admin tab by name.
        This is called only when the tab is actually selected.
        """
        log("debug", f"Lazy rendering tab '{tab_name}' from {module_key}")

        # Check cache
        cache_key = f"{module_key}:{tab_name}"
        if cache_key in self._tab_cache:
            log("debug", f"Using cached render for tab '{tab_name}'")
            return self._tab_cache[cache_key][1]()

        # Render the content
        try:
            result = content_func()

            # Optionally cache for this session
            import streamlit as st
            if 'tab_cache_enabled' in st.session_state and st.session_state.tab_cache_enabled:
                self._tab_cache[cache_key] = (time.time(), lambda: result)

            return result
        except Exception as e:
            log("error", f"Error rendering tab '{tab_name}': {e}", stacktrace=True)
            import streamlit as st
            st.error(f"Error loading tab '{tab_name}': {e}")
            return None

    def render_admin_tabs(self) -> Dict[str, Any]:
        """
        LEGACY: Render all admin tabs immediately.
        Use get_admin_tabs() + render_admin_tab() for lazy loading instead.
        """
        return self.render("admin_tab")

    def get_all_injection_points(self) -> List[str]:
        self.ensure_initialized()
        return sorted(self.injection_points)

    def get_injection_point_stats(self) -> Dict[str, int]:
        self.ensure_initialized()
        stats = {}
        for injection_point in self.injection_points:
            count = sum(1 for info in self.modules.values() if injection_point in info['render_functions'])
            stats[injection_point] = count
        return stats

    def get_module(self, module_key: str) -> Dict:
        self.ensure_initialized()
        return self.modules.get(module_key)

    def has_module(self, module_key: str) -> bool:
        self.ensure_initialized()
        return module_key in self.modules


# Singleton instance
ui_registry = UIRegistry()
