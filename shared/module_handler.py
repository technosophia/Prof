"""Module Handler

[api]
The ModuleHandler is the core module management system. It handles:
- Discovering modules from the modules/ directory
- Managing module activation status via modules.json
- Loading module metadata and UI components
- Dependency tracking between modules
- Integration with the UI registry system

Key Features:
- Auto-discovers modules in the modules/ directory (cached for efficiency)
- Loads module configuration from module.json files
- Manages activation status in modules.json
- Provides toggle functionality for modules
- Integrates with UI registry for selective module loading
- Auto-discovery of translations and prompts
- Auto-discovery of injection points for UI integration with main App

NO STREAMLIT DEPENDENCY. This module must remain importable without Streamlit.
All Streamlit-specific logic belongs in ui_registry.py or *_ui.py files.

--- Module Lifecycle Hooks ---

ModuleHandler calls the following hooks on the module's Python *package*
(i.e. modules/<name>/__init__.py) when they exist and are callable.

FUNCTIONAL hooks (no Streamlit, called by ModuleHandler):
    on_module_activated(services: ServiceLocator)
        Called when a module is activated.
        Receives a ServiceLocator with injected dependencies (config, user_manager, etc.)
        Use this to register driver options, LLM callbacks, etc.

    on_module_deactivated()
        Called when a module is deactivated.
        Use this to unregister driver options, LLM callbacks, etc.

    on_module_config_changed()
        Called when the module's config file changes.
        Use this to refresh in-memory config state.

LEGACY hook (still supported for backward compatibility):
    inject_ui_initialize()
        Old-style hook called from UI layer (ui_registry / Streamlit startup).
        Kept for backward-compatible modules. New modules should use
        on_module_activated() instead for functional setup, and
        inject_ui_initialize() ONLY for st.session_state initialization.

--- Service Locator ---

on_module_activated(services) receives a ServiceLocator object:

    services.config          -> dict-like config object (NOT Streamlit-cached)
    services.get(name)       -> get any registered service by name
    services.register(name, obj) -> register a service (used by app startup)

The ServiceLocator is populated by the application startup code, not by
ModuleHandler itself. This keeps ModuleHandler dependency-free.

Module JSON Structure:
```json
{
    "name": "module_name",
    "version": "1.0.0",
    "description": "Module description",
    "author": "Author name",
    "enabled_by_default": true,
    "category": "category",
    "dependencies": []
}
```
"""

import os
import json
import importlib
import importlib.util
import sys
from typing import Dict, List, Optional, Set, Any
from pathlib import Path

from core.config import CONFIG_FILE
from core.logging import log


# ---------------------------------------------------------------------------
# Service Locator  (dependency injection container, no Streamlit)
# ---------------------------------------------------------------------------

class ServiceLocator:
    """
    Lightweight dependency injection container passed to on_module_activated().

    The application startup code registers services here before activating
    modules. Functional module hooks receive this object and use it to access
    config, managers, etc. without importing from st_shared.

    Example (app startup):
        services = ServiceLocator()
        services.register("config", get_plain_config())
        services.register("user_manager", user_manager)
        services.register("llm_manager", llm_manager)
        module_handler.set_services(services)

    Example (module on_module_activated):
        def on_module_activated(services):
            config = services.get("config")
            llm_manager = services.get("llm_manager")
            llm_manager.register_context_callback(my_callback)
    """

    def __init__(self):
        self._services: Dict[str, Any] = {}

    def register(self, name: str, obj: Any) -> None:
        """Register a service by name."""
        self._services[name] = obj

    def get(self, name: str, default: Any = None) -> Any:
        """Get a service by name. Returns default if not found."""
        return self._services.get(name, default)

    @property
    def config(self) -> Any:
        """Shortcut to the 'config' service."""
        return self._services.get("config")

    def __contains__(self, name: str) -> bool:
        return name in self._services


# ---------------------------------------------------------------------------
# Module discovery helpers (no Streamlit, pure filesystem)
# ---------------------------------------------------------------------------

def _compute_modules_signature() -> str:
    """Compute a signature based on module directories and key file mtimes."""
    modules_dir = Path("modules")
    if not modules_dir.exists():
        return "no_modules_dir"

    sig_parts = []
    for module_dir in sorted(modules_dir.iterdir()):
        if module_dir.is_dir():
            name = module_dir.name
            mj_path = module_dir / "module.json"
            mj_mtime = mj_path.stat().st_mtime if mj_path.exists() else 0.0

            ui_path = module_dir / f"{name}_ui.py"
            ui_mtime = ui_path.stat().st_mtime if ui_path.exists() else 0.0

            cfg_path = module_dir / CONFIG_FILE
            cfg_mtime = cfg_path.stat().st_mtime if cfg_path.exists() else 0.0

            sig_parts.append(f"{name}:{mj_mtime:.0f}:{ui_mtime:.0f}:{cfg_mtime:.0f}")

    return ";".join(sig_parts)


def _load_potential_modules(_signature: str) -> Dict[str, Dict]:
    """Cached discovery of all potential modules from disk."""
    modules_dir = Path("modules")
    if not modules_dir.exists():
        log("warning", f"Modules directory not found: {modules_dir}")
        return {}

    potential: Dict[str, Dict] = {}
    for module_dir in modules_dir.iterdir():
        if module_dir.is_dir():
            module_name = module_dir.name
            module_json_path = module_dir / "module.json"

            if module_json_path.exists():
                try:
                    with open(module_json_path, "r") as f:
                        module_config = json.load(f)
                except Exception as e:
                    log("error", f"Failed to load module.json for {module_name}: {str(e)}")
                    module_config = {}
            else:
                module_config = {}

            ui_file = module_dir / f"{module_name}_ui.py"
            has_ui = ui_file.exists()

            config_file = module_dir / CONFIG_FILE
            has_config = config_file.exists()

            # Detect which lifecycle hooks the module package exposes
            pkg_init = module_dir / "__init__.py"
            has_new_hooks = False
            if pkg_init.exists():
                try:
                    src = pkg_init.read_text(encoding="utf-8")
                    has_new_hooks = "on_module_activated" in src
                except Exception:
                    pass

            potential[module_name] = {
                'name': module_name,
                'path': str(module_dir),
                'description': module_config.get('description', ''),
                'version': module_config.get('version', '1.0.0'),
                'author': module_config.get('author', ''),
                'enabled_by_default': module_config.get('enabled_by_default', True),
                'has_ui': has_ui,
                'ui_file': str(ui_file) if has_ui else None,
                'config_file': str(config_file) if has_config else None,
                'dependencies': module_config.get('dependencies', []),
                'category': module_config.get('category', 'general'),
                # NEW: whether this module uses the new hook protocol
                'has_new_hooks': has_new_hooks,
            }

    log("info", f"Cached discovery completed: {len(potential)} potential modules found")
    return potential


# ---------------------------------------------------------------------------
# ModuleHandler
# ---------------------------------------------------------------------------

class ModuleHandler:
    """
    Handles module discovery, activation, and management.

    No Streamlit dependency. All UI concerns are delegated to ui_registry.py.
    """

    def __init__(self):
        self.modules: Dict[str, Dict] = {}
        self.active_modules: Set[str] = set()
        self.modules_file = "modules.json"
        self._initialized = False
        self._services: Optional[ServiceLocator] = None

    # ------------------------------------------------------------------
    # Service injection (called by app startup, not by Streamlit)
    # ------------------------------------------------------------------

    def set_services(self, services: ServiceLocator) -> None:
        """
        Inject the ServiceLocator that will be passed to on_module_activated().

        Call this from application startup before any module is activated.
        """
        self._services = services
        log("debug", "ModuleHandler: ServiceLocator registered")

    def get_services(self) -> Optional[ServiceLocator]:
        """Return the current ServiceLocator, or None if not set."""
        return self._services

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_modules_file(self):
        if os.path.exists(self.modules_file):
            try:
                with open(self.modules_file, 'r') as f:
                    data = json.load(f)
                    self.active_modules = set(data.get('active_modules', []))
                    log("debug", f"Loaded modules file: {len(self.active_modules)} active modules")
            except Exception as e:
                log("error", f"Failed to load {self.modules_file}: {str(e)}")
                self.active_modules = set()
        else:
            self.active_modules = set()

    def _save_modules_file(self):
        try:
            data = {
                'active_modules': sorted(self.active_modules),
                'total_modules': len(self.modules)
            }
            with open(self.modules_file, 'w') as f:
                json.dump(data, f, indent=2)
            log("debug", f"Saved modules file: {len(self.active_modules)} active modules")
        except Exception as e:
            log("error", f"Failed to save {self.modules_file}: {str(e)}")

    # ------------------------------------------------------------------
    # Discovery / sync
    # ------------------------------------------------------------------

    def _sync_with_disk(self):
        """Synchronize internal state with disk."""
        signature = _compute_modules_signature()
        potential_modules = _load_potential_modules(signature)

        updated = False

        for name, info in potential_modules.items():
            if name not in self.modules:
                self.modules[name] = info
                if info.get('enabled_by_default', True) and name not in self.active_modules:
                    self.active_modules.add(name)
                    log("info", f"Auto-activated new module '{name}' (enabled by default)")
                    updated = True
            else:
                self.modules[name].update(info)

        for name in list(self.modules.keys()):
            if name not in potential_modules:
                del self.modules[name]
                if name in self.active_modules:
                    self.active_modules.remove(name)
                    log("info", f"Deactivated and removed deleted module '{name}'")
                    updated = True

        if updated:
            self._save_modules_file()

        log("info", f"Module sync complete: {len(self.modules)} discovered, {len(self.active_modules)} active")

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def initialize(self):
        """
        Initialize the module handler.

        Must be called before using any other methods. Loads modules.json and
        synchronizes with the filesystem to discover all available modules.

        Does NOT call any module hooks. Call activate_all() separately when
        the ServiceLocator is ready.
        """
        if self._initialized:
            return

        self._load_modules_file()
        self._sync_with_disk()
        self._initialized = True
        log("info", "Module handler fully initialized")

    def activate_all(self) -> None:
        """
        Call on_module_activated() for every currently active module.

        Should be called once at application startup, after set_services() and
        after initialize(). This triggers functional setup (driver registration,
        LLM callback registration, etc.) for all active modules.

        Safe to call multiple times — modules that were already activated are
        skipped (tracked via _activated set).
        """
        if not self._initialized:
            self.initialize()

        for name in sorted(self.active_modules):
            self._call_module_hook(name, "on_module_activated", pass_services=True)

    def refresh(self):
        """Refresh module discovery from disk."""
        self._sync_with_disk()

    # ------------------------------------------------------------------
    # Module info
    # ------------------------------------------------------------------

    def get_all_modules(self) -> Dict[str, Dict]:
        if not self._initialized:
            self.initialize()
        return self.modules

    def get_active_modules(self) -> List[str]:
        if not self._initialized:
            self.initialize()
        return sorted(self.active_modules)

    def is_module_active(self, module_name: str) -> bool:
        if not self._initialized:
            self.initialize()
        return module_name in self.active_modules

    def get_module_info(self, module_name: str) -> Optional[Dict]:
        if not self._initialized:
            self.initialize()
        return self.modules.get(module_name)

    # ------------------------------------------------------------------
    # Import-cache helpers
    # ------------------------------------------------------------------

    def _refresh_module_cache(self, module_name: str):
        """Clear Python import cache entries for a module and its UI files."""
        keys_to_remove = [
            key for key in list(sys.modules.keys())
            if key == module_name
            or key == f"modules.{module_name}"
            or key.startswith(f"modules.{module_name}.")
            or key == f"{module_name}_ui"
            or key.startswith(f"{module_name}_")
        ]
        for key in keys_to_remove:
            sys.modules.pop(key, None)
        if keys_to_remove:
            log("debug", f"Refreshed cache for module '{module_name}' ({len(keys_to_remove)} entries)")

    # ------------------------------------------------------------------
    # Hook dispatch  (NO Streamlit dependency here)
    # ------------------------------------------------------------------

    def _call_module_hook(
        self,
        module_name: str,
        hook_name: str,
        pass_services: bool = False,
    ) -> None:
        """
        Import the module package and call a lifecycle hook if it exists.

        For on_module_activated, passes the ServiceLocator when pass_services=True.

        This method is deliberately Streamlit-free. UI hooks (inject_ui_xxx) are
        called exclusively by ui_registry.py in a Streamlit context.
        """
        module_path = f"modules.{module_name}"
        try:
            package = importlib.import_module(module_path)
        except Exception as e:
            log("debug", f"Module hook skipped for {module_name}: cannot import {module_path}: {e}")
            return

        hook = getattr(package, hook_name, None)
        if not callable(hook):
            return

        try:
            if pass_services and hook_name == "on_module_activated":
                # New protocol: pass ServiceLocator
                import inspect
                sig = inspect.signature(hook)
                if len(sig.parameters) > 0:
                    hook(self._services or ServiceLocator())
                else:
                    # Module declares on_module_activated() with no args → call without
                    hook()
            else:
                hook()
            log("info", f"Executed module hook {module_path}.{hook_name}()")
        except Exception as e:
            log("warning", f"Module hook failed {module_path}.{hook_name}(): {e}", exc_info=True)

    # ------------------------------------------------------------------
    # Config change notification
    # ------------------------------------------------------------------

    def notify_module_config_changed(self, module_name: str):
        """Refresh module cache and invoke on_module_config_changed hook."""
        if module_name not in self.modules:
            self.refresh()

        self._refresh_module_cache(module_name)
        self._call_module_hook(module_name, "on_module_config_changed")

    # ------------------------------------------------------------------
    # Toggle activation
    # ------------------------------------------------------------------

    def toggle_module(self, module_name: str, activate: bool) -> bool:
        """
        Activate or deactivate a module.

        When activating a new-style module, on_module_activated(services) is called.
        When activating a legacy module, only on_module_activated() (no args) is
        attempted for backward compatibility; the UI layer remains responsible for
        calling inject_ui_initialize() to set up Streamlit state.

        When deactivating, on_module_deactivated() is called regardless of style.
        """
        if not self._initialized:
            self.initialize()

        if module_name not in self.modules:
            self.refresh()
            if module_name not in self.modules:
                log("error", f"Cannot toggle module '{module_name}': not found")
                return False

        if activate:
            if module_name not in self.active_modules:
                self.active_modules.add(module_name)
                self._refresh_module_cache(module_name)
                self._call_module_hook(module_name, "on_module_activated", pass_services=True)
                log("info", f"Activated module: {module_name}")
                self._save_modules_file()
                return True
        else:
            if module_name in self.active_modules:
                self._call_module_hook(module_name, "on_module_deactivated")
                self.active_modules.remove(module_name)
                self._refresh_module_cache(module_name)
                log("info", f"Deactivated module: {module_name}")
                self._save_modules_file()
                return True

        return False

    # ------------------------------------------------------------------
    # Legacy: load UI module (kept for backward compatibility)
    # ------------------------------------------------------------------

    def load_module_ui(self, module_name: str) -> Optional[object]:
        """
        Load a module's UI module (*_ui.py).

        Used internally by ui_registry but can be called directly.
        Returns the imported module object, or None on failure.
        """
        if not self._initialized:
            self.initialize()

        if module_name not in self.modules:
            log("error", f"Cannot load UI for module '{module_name}': not found")
            return None

        module_info = self.modules[module_name]
        if not module_info['has_ui'] or not module_info['ui_file']:
            log("warning", f"Module '{module_name}' has no UI file")
            return None

        ui_file_path = module_info['ui_file']

        try:
            spec = importlib.util.spec_from_file_location(f"{module_name}_ui", ui_file_path)
            if spec is None or spec.loader is None:
                log("error", f"Could not load spec for module UI: {module_name}")
                return None

            module = importlib.util.module_from_spec(spec)
            sys.modules[f"{module_name}_ui"] = module
            spec.loader.exec_module(module)

            log("debug", f"Loaded UI module: {module_name}")
            return module

        except Exception as e:
            log("error", f"Failed to load UI module {module_name}: {str(e)}", exc_info=True)
            return None


# ---------------------------------------------------------------------------
# Global singleton instance
# ---------------------------------------------------------------------------

# Create the global module handler instance
module_handler = ModuleHandler()


# ---------------------------------------------------------------------------
# Convenience functions (using the global instance)
# ---------------------------------------------------------------------------

def get_active_modules() -> List[str]:
    """[api] Convenience function to get active modules without creating a handler."""
    module_handler.initialize()
    return module_handler.get_active_modules()


def toggle_module(module_name: str, activate: bool) -> bool:
    """Convenience function to toggle a module."""
    module_handler.initialize()
    return module_handler.toggle_module(module_name, activate)


def notify_module_config_changed(module_name: str) -> None:
    """Convenience function to notify that a module configuration changed."""
    module_handler.initialize()
    module_handler.notify_module_config_changed(module_name)


def get_services() -> Optional[ServiceLocator]:
    """[api] Get the ServiceLocator from the global module handler."""
    return module_handler.get_services()


def set_services(services: ServiceLocator) -> None:
    """[api] Set the ServiceLocator on the global module handler."""
    module_handler.set_services(services)
