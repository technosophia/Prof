"""Module Handler

[agent]
Provides module discovery, activation, and management for the application.
Scans ./modules directory to detect modules and allows loading them or not,
depending on the configuration. Module activation status is stored in modules.json.

Key Features:
- Auto-discovers modules in the modules/ directory
- Loads module configuration from module.json files
- Manages activation status in modules.json
- Provides toggle functionality for modules
- Integrates with UI registry for selective module loading

Module Requirements:
1. Must be placed in modules/ directory as a subdirectory
2. Must contain a module.json file with metadata
3. UI modules should follow *_ui.py naming convention
4. Can include config.json for module-specific configuration

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
from shared.logging import log
from shared.common import get_config

class ModuleHandler:
    """Handles module discovery, activation, and management."""

    def __init__(self):
        self.modules: Dict[str, Dict] = {}
        self.modules_file = "modules.json"
        self.active_modules: Set[str] = set()
        self._initialized = False

    def initialize(self):
        """Initialize the module handler."""
        if not self._initialized:
            self._load_modules_file()
            self.discover_modules()
            self._initialized = True
            log("info", f"Module handler initialized with {len(self.modules)} modules, {len(self.active_modules)} active")

    def _load_modules_file(self):
        """Load modules.json file or create default."""
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
            # Create default modules.json
            self._save_modules_file()

    def _save_modules_file(self):
        """Save modules.json file."""
        try:
            data = {
                'active_modules': list(self.active_modules),
                'total_modules': len(self.modules)
            }
            with open(self.modules_file, 'w') as f:
                json.dump(data, f, indent=2)
            log("debug", f"Saved modules file: {len(self.active_modules)} active modules")
        except Exception as e:
            log("error", f"Failed to save {self.modules_file}: {str(e)}")

    def discover_modules(self):
        """Discover all modules in the modules directory."""
        modules_dir = Path("modules")

        if not modules_dir.exists():
            log("warning", f"Modules directory not found: {modules_dir}")
            return

        log("info", f"Discovering modules in: {modules_dir}")

        for module_dir in modules_dir.iterdir():
            if module_dir.is_dir():
                module_name = module_dir.name

                # Check for module.json configuration
                module_json = module_dir / "module.json"
                if module_json.exists():
                    try:
                        with open(module_json, 'r') as f:
                            module_config = json.load(f)
                    except Exception as e:
                        log("error", f"Failed to load module.json for {module_name}: {str(e)}")
                        module_config = {}
                else:
                    module_config = {}

                # Check for _ui.py file
                ui_file = module_dir / f"{module_name}_ui.py"
                has_ui = ui_file.exists()

                # Get module info
                self.modules[module_name] = {
                    'name': module_name,
                    'path': str(module_dir),
                    'description': module_config.get('description', ''),
                    'version': module_config.get('version', '1.0.0'),
                    'author': module_config.get('author', ''),
                    'enabled_by_default': module_config.get('enabled_by_default', True),
                    'has_ui': has_ui,
                    'ui_file': str(ui_file) if has_ui else None,
                    'config_file': str(module_dir / "config.json") if (module_dir / "config.json").exists() else None,
                    'dependencies': module_config.get('dependencies', []),
                    'category': module_config.get('category', 'general')
                }

                # If module is new and enabled by default, activate it
                # BUT ONLY IF IT'S NOT ALREADY IN THE ACTIVE/INACTIVE STATE
                # Don't auto-activate if user has explicitly disabled it
                if (module_name not in self.modules and  # Only for new modules
                    module_name not in self.active_modules and  # Not already active
                    module_config.get('enabled_by_default', True)):
                    self.active_modules.add(module_name)
                    log("info", f"Auto-activated module '{module_name}' (enabled by default)")
                elif module_name in self.modules:
                    # Module already exists, preserve its activation state
                    log("debug", f"Module '{module_name}' already discovered, preserving state")

        # Save after discovery
        log("info", f"Discovered {len(self.modules)} modules")

    def refresh_modules(self):
        """Refresh module discovery."""
        self.discover_modules()
        return self.modules

    def get_all_modules(self) -> Dict[str, Dict]:
        """Get all discovered modules."""
        return self.modules

    def get_active_modules(self) -> List[str]:
        """Get list of active module names."""
        return list(self.active_modules)

    def is_module_active(self, module_name: str) -> bool:
        """Check if a module is active."""
        return module_name in self.active_modules

    def toggle_module(self, module_name: str, activate: bool) -> bool:
        """Activate or deactivate a module."""
        # Try to refresh modules first if not found
        if module_name not in self.modules:
            self.discover_modules()

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
        """Load a module's UI module."""
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
            if spec is None:
                log("error", f"Could not load spec for module: {module_name}")
                return None

            module = importlib.util.module_from_spec(spec)
            sys.modules[f"{module_name}_ui"] = module

            # Execute the module
            spec.loader.exec_module(module)

            log("debug", f"Loaded UI module: {module_name}")
            return module

        except Exception as e:
            log("error", f"Failed to load UI module {module_name}: {str(e)}", exc_info=True)
            return None

    def get_module_info(self, module_name: str) -> Optional[Dict]:
        """Get detailed information about a module."""
        return self.modules.get(module_name)

def get_active_modules() -> List[str]:
    """Convenience function to get active modules."""
    handler = ModuleHandler()
    return handler.get_active_modules()

def toggle_module(module_name: str, activate: bool) -> bool:
    """Convenience function to toggle module activation."""
    handler = ModuleHandler()
    return handler.toggle_module(module_name, activate)

# Create a singleton instance
module_handler = ModuleHandler()
