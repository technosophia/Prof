"""Module Handler

[agent]
Provides module discovery, activation, and management for the application.
Scans ./modules directory to detect modules and allows loading them or not,
depending on the configuration. Module activation status is stored in modules.json.

Key Features:
- Auto-discovers modules in the modules/ directory (cached for efficiency)
- Loads module configuration from module.json files
- Manages activation status in modules.json
- Provides toggle functionality for modules
- Integrates with UI registry for selective module loading
- Auto-discovery of translations and prompts
- Auto-discovery of injection points for UI integration with main App

Module Requirements:
1. Must be placed in modules/ directory as a subdirectory
2. Must contain a module.json file with metadata
3. UI modules should follow *_ui.py naming convention and inject_ui_xxx for UI integration with main App
4. Can include config.json for module-specific configuration
5. Can include translation/xx.json for language-specific translations
6. Can include prompts.xx.json for language-specific prompts
7. Can include tests in the test/ directory for pytest automatic testing

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
import importlib.util
import sys
from typing import Dict, List, Optional, Set
from pathlib import Path
import streamlit as st
from shared.common import log

def _compute_modules_signature() -> str:
    """Compute a signature based on module directories and key file modification times."""
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

            cfg_path = module_dir / "config.json"
            cfg_mtime = cfg_path.stat().st_mtime if cfg_path.exists() else 0.0

            sig_parts.append(f"{name}:{mj_mtime:.0f}:{ui_mtime:.0f}:{cfg_mtime:.0f}")

    return ";".join(sig_parts)


@st.cache_resource
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

            config_file = module_dir / "config.json"
            has_config = config_file.exists()

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
                'category': module_config.get('category', 'general')
            }

    log("info", f"Cached discovery completed: {len(potential)} potential modules found")
    return potential


class ModuleHandler:
    """Handles module discovery, activation, and management."""

    def __init__(self):
        self.modules: Dict[str, Dict] = {}
        self.active_modules: Set[str] = set()
        self.modules_file = "modules.json"
        self._initialized = False

    def _load_modules_file(self):
        """Load modules.json file or initialize empty."""
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
        """Save modules.json file."""
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

    def _sync_with_disk(self):
        """Synchronize internal state with disk (used in init and refresh)."""
        signature = _compute_modules_signature()
        potential_modules = _load_potential_modules(signature)

        updated = False

        # Add new modules and update existing ones
        for name, info in potential_modules.items():
            if name not in self.modules:
                # New module discovered
                self.modules[name] = info
                if info.get('enabled_by_default', True) and name not in self.active_modules:
                    self.active_modules.add(name)
                    log("info", f"Auto-activated new module '{name}' (enabled by default)")
                    updated = True
            else:
                # Update existing module metadata (e.g., if module.json changed)
                self.modules[name].update(info)

        # Remove deleted modules
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

    def initialize(self):
        """Initialize the module handler."""
        if self._initialized:
            return

        self._load_modules_file()
        self._sync_with_disk()
        self._initialized = True
        log("info", "Module handler fully initialized")

    def refresh(self):
        """Refresh module discovery from disk (useful if modules added/removed during dev)."""
        self._sync_with_disk()

    def get_all_modules(self) -> Dict[str, Dict]:
        """Get all discovered modules."""
        if not self._initialized:
            self.initialize()
        return self.modules

    def get_active_modules(self) -> List[str]:
        """Get list of active module names."""
        if not self._initialized:
            self.initialize()
        return sorted(self.active_modules)

    def is_module_active(self, module_name: str) -> bool:
        """Check if a module is active."""
        if not self._initialized:
            self.initialize()
        return module_name in self.active_modules

    def toggle_module(self, module_name: str, activate: bool) -> bool:
        """Activate or deactivate a module."""
        if not self._initialized:
            self.initialize()

        # If module not known, attempt refresh in case it was added
        if module_name not in self.modules:
            self.refresh()
            if module_name not in self.modules:
                log("error", f"Cannot toggle module '{module_name}': not found")
                return False

        if activate:
            if module_name not in self.active_modules:
                self.active_modules.add(module_name)
                log("info", f"Activated module: {module_name}")
                self._save_modules_file()
                return True
        else:
            if module_name in self.active_modules:
                self.active_modules.remove(module_name)
                log("info", f"Deactivated module: {module_name}")
                self._save_modules_file()
                return True

        return False

    def load_module_ui(self, module_name: str) -> Optional[object]:
        """Load a module's UI module (kept for backward compatibility)."""
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

    def get_module_info(self, module_name: str) -> Optional[Dict]:
        """Get detailed information about a module."""
        if not self._initialized:
            self.initialize()
        return self.modules.get(module_name)


# Backward-compatible convenience functions (initialize internally)
def get_active_modules() -> List[str]:
    handler = ModuleHandler()
    handler.initialize()
    return handler.get_active_modules()

def toggle_module(module_name: str, activate: bool) -> bool:
    handler = ModuleHandler()
    handler.initialize()
    return handler.toggle_module(module_name, activate)


# Singleton instance (used in prof.py via session_state)
module_handler = ModuleHandler()
