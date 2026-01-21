# Module Development Guide: Config, Logging & Translation System

## Overview

This application provides three core utilities that all modules can use: **configuration management**, **logging**, and **translation**. Each system is designed for simple one-line initialization and easy use throughout your modules.

## 1. Configuration System (`shared/config.py`)

### Purpose
Centralized configuration management with module injection support. Loads from JSON files and supports nested configurations with duplicate checking.

### Key Functions

#### Initialization (in your module)
```python
from shared.config import init_config, inject_module_config, get_config

# Initialize main config (usually done once in app.py)
config = init_config("config.json")

# Inject module-specific config (one line)
inject_module_config("your_module_name", "path/to/your/config.json")
```

#### Using Configuration
```python
from shared.config import get_config

config = get_config()

# Get values with dot notation
log_level = config.get("logging.level", "INFO")
app_name = config.get("app.name")

# Set values
config.set("your_module.some_key", "value")

# Check if key exists
if "your_module.enabled" in config:
    # Do something
```

### Module Configuration File Example
Create `your_module/config.json`:
```json
{
    "your_module": {
        "enabled": true,
        "api_key": "your_key_here",
        "endpoint": "https://api.example.com"
    },
    "logging": {
        "your_module_level": "DEBUG"
    }
}
```

## 2. Logging System (`shared/logging.py`)

### Purpose
Simple, configurable logging with multiple levels. All logs are in English (not translated). Integrates with configuration system.

### Key Functions

#### Simple Logging (main way to log)
```python
from shared.logging import log

# One-line logging
log("info", "Module initialized successfully")
log("debug", "Processing item %d", item_id)
log("warning", "Deprecated function called")
log("error", "Failed to connect: %s", error_msg)

# Or use convenience functions
from shared.logging import debug, info, warning, error
info("Module started")
debug("Detailed debug info: %s", data)
```

#### Connecting to Configuration
```python
from shared.config import get_config
from shared.logging import configure_from_dict

# Configure logging from config
config = get_config()
configure_from_dict(config.get("logging", {}))
```

### Log Levels (from most to least verbose)
- `debug` - Detailed information for debugging
- `info` - General information about program execution
- `warning` - Potential issues that don't stop execution
- `error` - Serious problems that affect functionality
- `critical` - Critical errors that may cause program termination

## 3. Translation System (`shared/translate.py`)

### Purpose
Multilingual support with module-specific translations. Uses simple `_()` function for translation lookups.

### Key Functions

#### For Regular Modules
```python
from shared.translate import _

# Simple translation
title = _("module_title")
description = _("module_description")

# Translation with parameters (use string formatting)
message = _("welcome_user").format(username=user_name)
```

#### For Streamlit Modules
```python
from shared.translate import _streamlit as _

# Works the same way but with Streamlit session support
st.title(_("module_title"))
st.write(_("description"))
```

#### Adding Module Translations
```python
from shared.translate import get_translator

translator = get_translator()

# Method 1: Direct dictionary injection
translator.add_module_translations("your_module", {
    "en": {
        "module_title": "Your Module",
        "welcome": "Welcome to the module"
    },
    "fr": {
        "module_title": "Votre Module",
        "welcome": "Bienvenue dans le module"
    }
})

# Method 2: Load from directory structure
translator.inject_module_translations("your_module", "translations/your_module/")
```

### Translation File Structure
```
translations/
├── your_module/
│   ├── en.json
│   └── fr.json
```

**`translations/your_module/en.json`:**
```json
{
    "module_title": "Your Module",
    "module_description": "This is your custom module",
    "button_text": "Click here"
}
```

**`translations/your_module/fr.json`:**
```json
{
    "module_title": "Votre Module",
    "module_description": "Ceci est votre module personnalisé",
    "button_text": "Cliquez ici"
}
```

## Complete Module Example

```python
"""
Example module demonstrating all three systems.
"""

# 1. IMPORTS
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from shared.config import inject_module_config, get_config
from shared.logging import log, configure_from_dict
from shared.translate import get_translator, _

# 2. INITIALIZATION FUNCTION
def init_module():
    """Initialize the module with config, logging, and translations."""
    
    # Inject module configuration
    inject_module_config("example", "modules/example/config.json")
    
    # Get updated config
    config = get_config()
    
    # Configure logging (optional - module-specific logging config)
    if config.get("example.logging"):
        configure_from_dict(config.get("example.logging"))
    
    # Load module translations
    translator = get_translator()
    translator.inject_module_translations("example", "translations/example/")
    
    # Log initialization
    log("info", "Example module initialized")
    log("debug", f"Config: enabled={config.get('example.enabled')}")
    
    return True

# 3. MODULE FUNCTIONS
def process_data(data):
    """Example function using all three systems."""
    config = get_config()
    
    # Check if module is enabled via config
    if not config.get("example.enabled", False):
        log("warning", "Module is disabled, skipping processing")
        return None
    
    log("info", "Starting data processing")
    
    try:
        # Use translations
        log("debug", _("processing_started"))
        
        # Do work
        result = len(data)
        log("debug", f"Processed {result} items")
        
        return result
        
    except Exception as e:
        log("error", f"Processing failed: {e}")
        return None

# 4. MAIN MODULE LOGIC (if any)
if __name__ == "__main__":
    # Test the module
    init_module()
    test_data = [1, 2, 3, 4, 5]
    result = process_data(test_data)
    print(f"Result: {result}")
```

## Best Practices

1. **Initialize early**: Call initialization functions at module import or startup
2. **Use simple logging**: Stick with `log("level", "message")` for consistency
3. **Keep translations separate**: Store all translations in JSON files, not in code
4. **Check config before actions**: Verify `config.get("module.enabled")` before expensive operations
5. **Handle errors gracefully**: Use try-except with proper logging
6. **Use English for logs**: All log messages should be in English (not translated)

## Quick Reference

```python
# Most common imports
from shared.config import get_config, inject_module_config
from shared.logging import log
from shared.translate import _

# Most common patterns
config = get_config()
log("info", "Message here")
translated_text = _("translation_key")
```

This system allows each module to be self-contained with its own configuration, translations, and logging while integrating seamlessly with the main application.
