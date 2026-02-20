<!-- shared/module_handler.py -->

<!-- GENERATED FILE - do not edit manually -->
<!-- Source: shared/module_handler.py -->

# API — module_handler

Module Handler


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

Module Requirements:
1. Must be placed in modules/ directory as a subdirectory
2. Must contain a module.json file with metadata
3. UI modules should follow *_ui.py naming convention and inject_ui_xxx for UI integration
4. Can include CONFIG_FILE for module-specific configuration
5. Can include translation/xx.json for language-specific translations
6. Can include prompts.xx.json for language-specific prompts
7. Can include tests in the test/ directory for pytest automatic testing

Module JSON Structure:
```json
{
    "name": "module_name",           // Must match directory name
    "version": "1.0.0",              // Semantic version
    "description": "Module description",
    "author": "Author name",
    "enabled_by_default": true,      // Auto-activate on first discovery
    "category": "category",           // For grouping in UI
    "dependencies": []                // Other module names required
}
```

Class: ModuleHandler
Description: Main handler for module discovery, activation, and management.
Usage:
    handler = ModuleHandler()
    handler.initialize()
    active_modules = handler.get_active_modules()

---

### `get_active_modules`

```python
def get_active_modules() -> List[str]:
```

Convenience function to get active modules without creating a handler.

    Returns:
        Sorted list of active module names

    Example:
        if "analytics" in get_active_modules():
            show_analytics()
