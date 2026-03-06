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
- Supports local_modules.json override for development/testing

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
from core.service import ServiceLocator


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOCAL_MODULES_FILE = "local_modules.json"  # Local override file


# ---------------------------------------------------------------------------
# Module discovery helpers (no Streamlit, pure filesystem)
# ---------------------------------------------------------------------------

def _compute_modules_signature() -> str:
    """Compute a signature based on module directories and key file mtimes."""
    modules_dir = Path("modules")
    if not modules_dir.exists():
        return "no_modules_dir"

    sig_parts = []
    for root, dirs, files in os.walk(modules_dir):
        dirs.sort()
        files.sort()

        root_path = Path(root)
        if "module.json" not in files:
            continue

        rel_dir = root_path.relative_to(modules_dir)
        name = root_path.name
        mj_path = root_path / "module.json"
        mj_mtime = mj_path.stat().st_mtime if mj_path.exists() else 0.0

        ui_path = root_path / f"{name}_ui.py"
        ui_mtime = ui_path.stat().st_mtime if ui_path.exists() else 0.0

        cfg_path = root_path / CONFIG_FILE
        cfg_mtime = cfg_path.stat().st_mtime if cfg_path.exists() else 0.0

        sig_parts.append(f"{rel_dir}:{mj_mtime:.0f}:{ui_mtime:.0f}:{cfg_mtime:.0f}")

    return ";".join(sorted(sig_parts))


def _load_potential_modules(_signature: str, filter_modules: Optional[Set[str]] = None) -> Dict[str, Dict]:
    """
    Cached discovery of all potential modules from disk.

    If filter_modules is provided, only modules whose names are in the set
    will be included. This is used when local_modules.json overrides are active
    to limit which modules are considered available.
    """
    modules_dir = Path("modules")
    if not modules_dir.exists():
        log("warning", f"Modules directory not found: {modules_dir}")
        return {}

    potential: Dict[str, Dict] = {}
    for root, dirs, files in os.walk(modules_dir):
        dirs.sort()
        files.sort()

        if "module.json" not in files:
            continue

        module_dir = Path(root)
        module_name = module_dir.name

        # Skip if filter is active and module not in filter set
        if filter_modules is not None and module_name not in filter_modules:
            log("debug", f"Skipping module '{module_name}' (not in local override filter)")
            continue

        if module_name in potential:
            log("warning", f"Duplicate module basename '{module_name}' detected at {module_dir}; keeping first occurrence at {potential[module_name]['path']}")
            continue

        module_json_path = module_dir / "module.json"
        try:
            with open(module_json_path, "r") as f:
                module_config = json.load(f)
        except Exception as e:
            log("error", f"Failed to load module.json for {module_name}: {str(e)}")
            module_config = {}

        rel_path = module_dir.relative_to(modules_dir)
        import_path = "modules." + ".".join(rel_path.parts)

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
            'import_path': import_path,
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

    log("info", f"Cached discovery completed: {len(potential)} potential modules found" +
                (f" (filtered by local override)" if filter_modules is not None else ""))
    return potential


def _load_override_module_list(override_file: str) -> Optional[Set[str]]:
    """
    Load the list of module names from a local override file.

    Returns a set of module names that should be considered available,
    or None if the override file doesn't exist or is invalid.
    """
    if not os.path.exists(override_file):
        return None

    try:
        with open(override_file, 'r') as f:
            data = json.load(f)

        # Get active_modules list from the override file
        active_modules = data.get('active_modules', [])

        # Also include any modules that might be mentioned elsewhere?
        # For now, we'll just use the active_modules list as the definitive
        # list of modules that should exist when override is active.
        # This means if you remove a module from active_modules in the override,
        # it completely disappears from the system.

        module_set = set(active_modules)
        log("info", f"Loaded override module list: {len(module_set)} modules will be available")
        return module_set
    except Exception as e:
        log("error", f"Failed to parse override file {override_file}: {str(e)}")
        return None


# ---------------------------------------------------------------------------
# ModuleHandler
# ---------------------------------------------------------------------------

class ModuleHandler:
    """
    Handles module discovery, activation, and management.

    No Streamlit dependency. All UI concerns are delegated to ui_registry.py.

    Supports local_modules.json override for development/testing purposes.
    If local_modules.json exists alongside modules.json, it will be used
    instead of modules.json for module activation status AND to filter
    which modules are considered available in the system.
    """

    def __init__(self):
        self.modules: Dict[str, Dict] = {}
        self.active_modules: Set[str] = set()
        self.modules_file = "modules.json"
        self.local_modules_file = LOCAL_MODULES_FILE
        self._using_local_override = False
        self._override_module_filter: Optional[Set[str]] = None
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

    def _get_modules_file_path(self) -> str:
        """
        Determine which modules file to use.

        Returns the path to local_modules.json if it exists and should override,
        otherwise returns the path to modules.json.
        """
        # Check if local override exists
        if os.path.exists(self.local_modules_file):
            log("info", f"Using local override: {self.local_modules_file}")
            self._using_local_override = True
            return self.local_modules_file

        self._using_local_override = False
        self._override_module_filter = None
        return self.modules_file

    def _load_modules_file(self):
        """Load modules from either modules.json or local_modules.json."""
        modules_file_path = self._get_modules_file_path()

        if os.path.exists(modules_file_path):
            try:
                with open(modules_file_path, 'r') as f:
                    data = json.load(f)
                    self.active_modules = set(data.get('active_modules', []))

                    # If using local override, also capture the module filter
                    if self._using_local_override:
                        # The active_modules list becomes our filter for which modules exist
                        self._override_module_filter = set(self.active_modules)
                        log("info", f"Local override active: module list filtered to {len(self._override_module_filter)} modules")

                    log("debug", f"Loaded modules file: {len(self.active_modules)} active modules from {os.path.basename(modules_file_path)}")
            except Exception as e:
                log("error", f"Failed to load {modules_file_path}: {str(e)}")
                self.active_modules = set()
                if self._using_local_override:
                    self._override_module_filter = set()
        else:
            self.active_modules = set()
            if self._using_local_override:
                self._override_module_filter = set()

    def _save_modules_file(self):
        """
        Save modules to the appropriate file.

        If using local override, save to local_modules.json to preserve the override.
        Otherwise, save to modules.json.
        """
        # If we're currently using local override, save to local file
        # This ensures that toggles made during development stay in the local file
        target_file = self.local_modules_file if self._using_local_override else self.modules_file

        try:
            data = {
                'active_modules': sorted(self.active_modules),
                'total_modules': len(self.modules),
                '_note': "This file overrides modules.json for development/testing" if target_file == self.local_modules_file else None
            }
            # Remove None values
            data = {k: v for k, v in data.items() if v is not None}

            with open(target_file, 'w') as f:
                json.dump(data, f, indent=2)

            log("debug", f"Saved modules file: {len(self.active_modules)} active modules to {os.path.basename(target_file)}")

            # If we just saved to local override, update the filter
            if self._using_local_override:
                self._override_module_filter = set(self.active_modules)
                log("info", f"Updated local override filter: {len(self._override_module_filter)} modules now available")

        except Exception as e:
            log("error", f"Failed to save {target_file}: {str(e)}")

    def is_using_local_override(self) -> bool:
        """Return whether local_modules.json is currently being used as override."""
        return self._using_local_override

    def get_available_modules_count(self) -> int:
        """Return the number of modules available in the current configuration."""
        if not self._initialized:
            self.initialize()
        return len(self.modules)

    # ------------------------------------------------------------------
    # Discovery / sync
    # ------------------------------------------------------------------

    def _sync_with_disk(self):
        """Synchronize internal state with disk, respecting local override filter."""
        signature = _compute_modules_signature()

        # Pass the override filter to module discovery
        potential_modules = _load_potential_modules(signature, self._override_module_filter)

        updated = False

        # Add or update modules
        for name, info in potential_modules.items():
            if name not in self.modules:
                self.modules[name] = info
                # Only auto-activate if the module is in our active set or enabled by default
                if name in self.active_modules:
                    # Already active, nothing to do
                    pass
                elif info.get('enabled_by_default', True) and name not in self.active_modules:
                    # Only auto-activate if not using override filter or if in override filter
                    if self._override_module_filter is None or name in self._override_module_filter:
                        self.active_modules.add(name)
                        log("info", f"Auto-activated new module '{name}' (enabled by default)")
                        updated = True
            else:
                self.modules[name].update(info)

        # Remove modules that no longer exist on disk OR are filtered out by override
        for name in list(self.modules.keys()):
            if name not in potential_modules:
                del self.modules[name]
                if name in self.active_modules:
                    self.active_modules.remove(name)
                    log("info", f"Deactivated and removed module '{name}' (no longer available)")
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

        Must be called before using any other methods. Loads modules.json (or
        local_modules.json if it exists) and synchronizes with the filesystem
        to discover all available modules.

        Does NOT call any module hooks. Call activate_all() separately when
        the ServiceLocator is ready.
        """
        if self._initialized:
            return

        self._load_modules_file()
        self._sync_with_disk()
        self._initialized = True
        log("info", f"Module handler fully initialized (using local override: {self._using_local_override})")

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

    def module_exists(self, module_name: str) -> bool:
        """Check if a module exists in the current configuration."""
        if not self._initialized:
            self.initialize()
        return module_name in self.modules

    # ------------------------------------------------------------------
    # Import-cache helpers
    # ------------------------------------------------------------------

    def _refresh_module_cache(self, module_name: str):
        """Clear Python import cache entries for a module and its UI files."""
        module_info = self.modules.get(module_name, {})
        import_path = module_info.get('import_path', f"modules.{module_name}")
        keys_to_remove = [
            key for key in list(sys.modules.keys())
            if key == module_name
            or key == import_path
            or key.startswith(f"{import_path}.")
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
        module_info = self.modules.get(module_name, {})
        if not module_info:
            log("debug", f"Module hook skipped for {module_name}: module not found")
            return

        module_path = module_info.get("import_path", f"modules.{module_name}")
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
            log("warning", f"Module hook failed {module_path}.{hook_name}(): {e}", stacktrace=True)

    # ------------------------------------------------------------------
    # Config change notification
    # ------------------------------------------------------------------

    def notify_module_config_changed(self, module_name: str):
        """Refresh module cache and invoke on_module_config_changed hook."""
        if module_name not in self.modules:
            self.refresh()
            if module_name not in self.modules:
                log("warning", f"Cannot notify config change for module '{module_name}': not found")
                return

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

        Changes are saved to the appropriate modules file (modules.json or
        local_modules.json if override is active).
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
            log("error", f"Cannot load module '{module_name}': not found")
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
            log("error", f"Failed to load UI module {module_name}: {str(e)}", stacktrace=True)
            return None

    # ------------------------------------------------------------------
    # Local override management
    # ------------------------------------------------------------------

    def create_local_override(self) -> bool:
        """
        Create a local_modules.json file based on current modules.json.

        This allows developers to "fork" the module configuration for local
        development without affecting the main modules.json file.

        Returns True if successful, False otherwise.
        """
        if not os.path.exists(self.modules_file):
            log("error", f"Cannot create local override: {self.modules_file} does not exist")
            return False

        try:
            # Load current modules.json
            with open(self.modules_file, 'r') as f:
                data = json.load(f)

            # Add a note about it being a local override
            data['_note'] = "This file overrides modules.json for development/testing"

            # Save as local_modules.json
            with open(self.local_modules_file, 'w') as f:
                json.dump(data, f, indent=2)

            log("info", f"Created local override file: {self.local_modules_file}")

            # Refresh to start using the local override
            if self._initialized:
                self._load_modules_file()
                self._sync_with_disk()

            return True
        except Exception as e:
            log("error", f"Failed to create local override: {str(e)}")
            return False

    def remove_local_override(self) -> bool:
        """
        Remove the local_modules.json override file.

        Returns True if successful or file didn't exist, False on error.
        """
        if not os.path.exists(self.local_modules_file):
            log("info", "No local override file to remove")
            return True

        try:
            os.remove(self.local_modules_file)
            log("info", f"Removed local override file: {self.local_modules_file}")

            # Refresh to revert to modules.json
            if self._initialized:
                self._load_modules_file()
                self._sync_with_disk()

            return True
        except Exception as e:
            log("error", f"Failed to remove local override: {str(e)}")
            return False


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


def is_using_local_override() -> bool:
    """Convenience function to check if local_modules.json override is active."""
    return module_handler.is_using_local_override()


def create_local_override() -> bool:
    """Convenience function to create a local_modules.json override file."""
    return module_handler.create_local_override()


def remove_local_override() -> bool:
    """Convenience function to remove the local_modules.json override file."""
    return module_handler.remove_local_override()


def load_module_ui(module_name: str) -> Optional[object]:
    """[api] Convenience function to load a module's UI component."""
    module_handler.initialize()
    return module_handler.load_module_ui(module_name)


def module_exists(module_name: str) -> bool:
    """[api] Convenience function to check if a module exists."""
    module_handler.initialize()
    return module_handler.module_exists(module_name)


def get_available_modules_count() -> int:
    """[api] Convenience function to get the number of available modules."""
    module_handler.initialize()
    return module_handler.get_available_modules_count()
