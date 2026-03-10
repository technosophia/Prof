<!-- /shared/_docs/MODULE.md -->

# Module System & UI Injection API

## Overview

The application uses a modular architecture where features can be dynamically enabled/disabled. Modules are managed by `ModuleHandler` (module_handler.py) and can inject UI components via `UIRegistry` (ui_registry.py).

## Module Structure

### Directory Layout
```
modules/[module_name]/
├── module.json              # Required: Metadata
├── [module_name]_ui.py      # Optional: UI injection points
├── config.json              # Optional: Configuration
├── translations/            # Optional: i18n files
├── prompts/                 # Optional: LLM prompts
└── tests/                   # Optional: Pytest tests
```

### module.json
```json
{
    "name": "module_name",           // Must match directory name
    "version": "1.0.0",
    "description": "Module description",
    "author": "Author name",
    "enabled_by_default": true,      // Auto-activate on discovery
    "category": "general",           // For UI grouping
    "dependencies": []                // Required module names
}
```

### Module Discovery & Activation
- **Discovery locations**: `modules/` (feature modules) and `shared/` (always active)
- **Activation status**: Stored in `modules.json` (project root)
- **Runtime control**: `module_handler.toggle_module(module_name, activate)`
- **Caching**: Active modules cached in session state
