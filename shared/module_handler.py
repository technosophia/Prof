import os
import json
import importlib
import importlib.util
import sys
from typing import Dict, List, Optional, Set, Any
from pathlib import Path

from core.config import CONFIG_FILE
from core.logging import log
from core.service import ServiceLocator, get_global_services, set_global_services


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOCAL_MODULES_FILE = "local_modules.json"  # Local override file


# ---------------------------------------------------------------------------
# Cache helper
# ---------------------------------------------------------------------------

def _get_cache_decorator():
    """
    Return the application cache decorator from the global ServiceLocator.

    Falls back to a transparent no-op when the ServiceLocator is not yet
    available (headless / test bootstrap, early imports).  This keeps
    module_handler.py Streamlit-free while still benefiting from
    st.cache_resource in production.
    """
    services = get_global_services()
    if services is not None:
        cache = services.get("cache")
        if callable(cache):
            return cache
    # No-op fallback: behaves like the function was never decorated
    return lambda f: f


# ---------------------------------------------------------------------------
# Module discovery helpers (no UX dependency, pure filesystem)
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


# NOTE: _load_potential_modules is NOT decorated here at definition time
# because the cache service may not be available yet.  ModuleHandler wraps
# calls to it via _cached_load_potential_modules() which resolves the cache
# decorator lazily on first use.  See ModuleHandler._cached_load_potential_modules.

def _load_potential_modules(_signature: str, filter_modules: Optional[Set[str]] = None) -> Dict[str, Dict]:
    """
    Discovery of all potential modules from disk.

    ``_signature`` is used as a cache key by the wrapping layer so that the
    expensive filesystem walk is skipped when nothing has changed on disk.

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

        active_modules = data.get('active_modules', [])
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

    No UX dependency. All UI concerns are delegated to ui_registry.py.

    Supports local_modules.json override for development/testing purposes.
    If local_modules.json exists alongside modules.json, it will be used
    instead of modules.json for module activation status AND to filter
    which modules are considered available in the system.

    Performance notes
    -----------------
    * ``_activated`` tracks which modules have already had
      ``on_module_activated()`` called.  ``activate_all()`` is therefore O(1)
      on every Streamlit rerun after the first.
    * ``_load_potential_modules`` is wrapped with the application cache
      decorator (``st.cache_resource`` in production, no-op in tests) so the
      filesystem walk only runs when the on-disk signature changes.
    """

    def __init__(self):
        self.modules: Dict[str, Dict] = {}
        self.active_modules: Set[str] = set()
        self.modules_file = "modules.json"
        self.local_modules_file = LOCAL_MODULES_FILE
        self._using_local_override = False
        self._override_module_filter: Optional[Set[str]] = None
        self._initialized = False
        # Tracks modules whose on_module_activated() hook has been called.
        # Cleared per-module on deactivation so re-enabling works correctly.
        self._activated: Set[str] = set()
        # Lazily-built cached wrapper around _load_potential_modules.
        self._cached_discover = None

    # ------------------------------------------------------------------
    # Cached discovery
    # ------------------------------------------------------------------

    def _get_cached_discover(self):
        """
        Return a cached wrapper for _load_potential_modules.

        The wrapper is built once and stored on the instance.  We resolve the
        cache decorator lazily (not at import time) so that the ServiceLocator
        is already populated when we first call it.
        """
        if self._cached_discover is None:
            cache = _get_cache_decorator()
            self._cached_discover = cache(_load_potential_modules)
            log("debug", "Built cached discovery wrapper for _load_potential_modules")
        return self._cached_discover

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _get_modules_file_path(self) -> str:
        if os.path.exists(self.local_modules_file):
            log("info", f"Using local override: {self.local_modules_file}")
            self._using_local_override = True
            return self.local_modules_file

        self._using_local_override = False
        self._override_module_filter = None
        return self.modules_file

    def _load_modules_file(self):
        modules_file_path = self._get_modules_file_path()

        if os.path.exists(modules_file_path):
            try:
                with open(modules_file_path, 'r') as f:
                    data = json.load(f)
                    self.active_modules = set(data.get('active_modules', []))

                    if self._using_local_override:
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
        target_file = self.local_modules_file if self._using_local_override else self.modules_file

        try:
            data = {
                'active_modules': sorted(self.active_modules),
                'total_modules': len(self.modules),
                '_note': "This file overrides modules.json for development/testing" if target_file == self.local_modules_file else None
            }
            data = {k: v for k, v in data.items() if v is not None}

            with open(target_file, 'w') as f:
                json.dump(data, f, indent=2)

            log("debug", f"Saved modules file: {len(self.active_modules)} active modules to {os.path.basename(target_file)}")

            if self._using_local_override:
                self._override_module_filter = set(self.active_modules)
                log("info", f"Updated local override filter: {len(self._override_module_filter)} modules now available")

        except Exception as e:
            log("error", f"Failed to save {target_file}: {str(e)}")

    def is_using_local_override(self) -> bool:
        return self._using_local_override

    def get_available_modules_count(self) -> int:
        if not self._initialized:
            self.initialize()
        return len(self.modules)

    # ------------------------------------------------------------------
    # Discovery / sync
    # ------------------------------------------------------------------

    def _sync_with_disk(self):
        """Synchronize internal state with disk, respecting local override filter."""
        signature = _compute_modules_signature()

        # Use cached wrapper — filesystem walk is skipped when signature matches
        potential_modules = self._get_cached_discover()(signature, self._override_module_filter)

        updated = False

        # Add or update modules
        for name, info in potential_modules.items():
            if name not in self.modules:
                self.modules[name] = info
                if name in self.active_modules:
                    pass
                elif info.get('enabled_by_default', True) and name not in self.active_modules:
                    if self._override_module_filter is None or name in self._override_module_filter:
                        self.active_modules.add(name)
                        log("info", f"Auto-activated new module '{name}' (enabled by default)")
                        updated = True
            else:
                self.modules[name].update(info)

        # Remove modules that no longer exist on disk OR are filtered out
        for name in list(self.modules.keys()):
            if name not in potential_modules:
                del self.modules[name]
                if name in self.active_modules:
                    self.active_modules.remove(name)
                    self._activated.discard(name)
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

        Should be called once at application startup, after initialize().
        This triggers functional setup (driver registration, LLM callback
        registration, etc.) for all active modules.

        Safe to call multiple times — modules already in ``_activated`` are
        skipped, making repeated calls (e.g. on every Streamlit rerun) O(1).
        """
        if not self._initialized:
            self.initialize()

        for name in sorted(self.active_modules):
            if name in self._activated:
                continue  # already activated — skip the expensive import
            self._call_module_hook(name, "on_module_activated", pass_services=True)
            self._activated.add(name)

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
    # Hook dispatch  (NO UX dependency here)
    # ------------------------------------------------------------------

    def _call_module_hook(
        self,
        module_name: str,
        hook_name: str,
        pass_services: bool = False,
    ) -> None:
        """
        Import the module package and call a lifecycle hook if it exists.

        For on_module_activated, passes the global ServiceLocator when pass_services=True.

        This method is deliberately UX-free. UI hooks (inject_ui_xxx) are
        called exclusively by ui_registry.py in a UX context.
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
                import inspect
                sig = inspect.signature(hook)
                if len(sig.parameters) > 0:
                    hook(get_global_services() or ServiceLocator())
                else:
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

        When activating, on_module_activated(services) is called and the
        module is added to ``_activated``.
        When deactivating, on_module_deactivated() is called and the module
        is removed from ``_activated`` so it can be re-activated cleanly later.
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
                self._activated.add(module_name)
                log("info", f"Activated module: {module_name}")
                self._save_modules_file()
                return True
        else:
            if module_name in self.active_modules:
                self._call_module_hook(module_name, "on_module_deactivated")
                self.active_modules.remove(module_name)
                self._activated.discard(module_name)
                self._refresh_module_cache(module_name)
                log("info", f"Deactivated module: {module_name}")
                self._save_modules_file()
                return True

        return False

    # ------------------------------------------------------------------
    # Hot-reload
    # ------------------------------------------------------------------

    def reload_module(self, module_name: str) -> bool:
        """
        Hot-reload a single active module without a full app restart.

        Steps:
          1. Call on_module_deactivated() hook (best-effort).
          2. Clear all Python import cache entries for the module.
          3. Remove from ``_activated`` so activate_all() will re-run the hook.
          4. Re-import the package and call on_module_activated() immediately.
          5. Mark as activated again.

        The module must already be in ``active_modules``; this method does not
        change activation status, only refreshes the imported code.

        Returns True on success, False if the module is unknown or inactive.
        """
        if not self._initialized:
            self.initialize()

        if module_name not in self.modules:
            log("error", f"Cannot reload module '{module_name}': not found")
            return False

        if module_name not in self.active_modules:
            log("warning", f"Cannot reload module '{module_name}': not active")
            return False

        log("info", f"Hot-reloading module: {module_name}")

        # Step 1 — graceful teardown
        self._call_module_hook(module_name, "on_module_deactivated")

        # Step 2 & 3 — wipe import cache and activation record
        self._refresh_module_cache(module_name)
        self._activated.discard(module_name)

        # Step 4 & 5 — fresh import + hook
        self._call_module_hook(module_name, "on_module_activated", pass_services=True)
        self._activated.add(module_name)

        log("info", f"Hot-reload complete: {module_name}")
        return True

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

        Returns True if successful, False otherwise.
        """
        if not os.path.exists(self.modules_file):
            log("error", f"Cannot create local override: {self.modules_file} does not exist")
            return False

        try:
            with open(self.modules_file, 'r') as f:
                data = json.load(f)

            data['_note'] = "This file overrides modules.json for development/testing"

            with open(self.local_modules_file, 'w') as f:
                json.dump(data, f, indent=2)

            log("info", f"Created local override file: {self.local_modules_file}")

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


def reload_module(module_name: str) -> bool:
    """[api] Hot-reload a single active module without a full app restart."""
    module_handler.initialize()
    return module_handler.reload_module(module_name)


def notify_module_config_changed(module_name: str) -> None:
    """Convenience function to notify that a module configuration changed."""
    module_handler.initialize()
    module_handler.notify_module_config_changed(module_name)


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
