"""
Module Development Guide: Config, Logging, Translation & LLM Systems

[agent]

## Overview

This application provides four core utilities that all modules can use: **configuration management**, **logging**, **translation**, and **LLM integration**. Each system is designed for simple one-line initialization and easy use throughout your modules.

## Important Initialization Order

**CRITICAL**: Always load configuration **BEFORE** importing other modules that depend on it:

```python
# CORRECT ORDER:
from shared.config import init_config, get_config
config = init_config("config.json")  # MUST BE FIRST

# Then import other modules
from shared.logging import log, configure_logging_from_dict
from shared.translate import init_translations_streamlit, _streamlit as _
from shared.llm import llm_generate, set_current_llm, get_available_llms

# Configure other systems
configure_logging_from_dict(config.get("logging", {}))
```

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
Simple, configurable logging with multiple levels and stack trace support. All logs are in English (not translated). Integrates with configuration system.

### Key Functions

#### Simple Logging (main way to log)
```python
from shared.logging import log

# One-line logging
log("info", "Module initialized successfully")
log("debug", "Processing item %d", item_id)
log("warning", "Deprecated function called")
log("error", "Failed to connect: %s", error_msg)

# With stack trace for errors
try:
    risky_operation()
except Exception as e:
    log("error", "Operation failed: %s", str(e), exc_info=True)

# Or use convenience functions
from shared.logging import debug, info, warning, error
info("Module started")
debug("Detailed debug info: %s", data)
```

#### Connecting to Configuration
```python
from shared.config import get_config
from shared.logging import configure_logging_from_dict

# Configure logging from config
config = get_config()
configure_logging_from_dict(config.get("logging", {}))
```

### Log Levels (from most to least verbose)
- `debug` - Detailed information for debugging
- `info` - General information about program execution
- `warning` - Potential issues that don't stop execution
- `error` - Serious problems that affect functionality
- `critical` - Critical errors that may cause program termination

### Configuration Example
```json
{
  "logging": {
    "level": "INFO",
    "format": "[{level}] {timestamp} - {message}",
    "include_traceback": true
  }
}
```

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
from shared.translate import init_translations_streamlit, _streamlit as _

# Initialize with Streamlit session support
translator = init_translations_streamlit("en", "translations")

# Use in Streamlit components
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
├── en.json
├── fr.json
└── your_module/
    ├── en.json
    └── fr.json
```

**`translations/en.json`:**
```json
{
    "hello_world": "Hello World!",
    "description": "Welcome to the application",
    "button_text": "Click here"
}
```

**`translations/fr.json`:**
```json
{
    "hello_world": "Bonjour le monde!",
    "description": "Bienvenue dans l'application",
    "button_text": "Cliquez ici"
}
```

## 4. LLM System (`shared/llm.py`)

### Purpose
Unified interface for multiple Large Language Models (Ollama, Gemini, Groq) with streaming support and configuration-based management.

### Key Functions

#### Initialization and Setup
```python
from shared.llm import llm_generate, set_current_llm, get_available_llms, get_current_llm_info

# LLM manager is automatically initialized with app config
# No manual initialization needed
```

#### Generating Responses
```python
import asyncio

# Simple text generation
response = await llm_generate("Hello, how are you?")
print(response)

# With streaming (real-time response)
def stream_callback(chunk):
    print(chunk, end="", flush=True)

response = await llm_generate("Tell me a story", stream_callback)
```

#### Managing LLMs
```python
# Get available LLMs
available_llms = get_available_llms()
for llm_info in available_llms:
    print(f"{llm_info['name']}: {llm_info['description']}")

# Switch LLM
success = set_current_llm("ollama_qwen")
if success:
    print("LLM switched successfully")

# Get current LLM info
current_llm = get_current_llm_info()
if current_llm:
    print(f"Current LLM: {current_llm['name']}")
```

### Configuration Example (`config.json`)
```json
{
  "app": {
    "name": "My App",
    "default_llm": "Qwen 3 4B",
    "version": "1.0.0"
  },
  "llms": {
    "ollama_qwen": {
      "type": "ollama",
      "model": "qwen3:4b",
      "name": "Qwen 3 4B",
      "enabled": true,
      "description": "Local Qwen model via Ollama",
      "requires_api_key": false
    },
    "gemini": {
      "type": "gemini",
      "model": "gemini-2.5-flash",
      "name": "Google Gemini",
      "enabled": true,
      "description": "Google's fast multimodal model",
      "requires_api_key": true
    },
    "groq": {
      "type": "groq",
      "model": "llama-3.3-70b-versatile",
      "name": "Groq Llama 3",
      "enabled": true,
      "description": "Fast inference via Groq",
      "requires_api_key": true
    }
  }
}
```

### Environment Variables
Create a `.env` file in your project root:
```bash
# Required for Gemini
GEMINI_API_KEY=your_gemini_api_key_here

# Required for Groq
GROQ_API_KEY=your_groq_api_key_here

# Optional: Custom Ollama URL
OLLAMA_BASE_URL=http://localhost:11434
```

## Best Practices

1. **Initialize in correct order**: Always load config first, then other systems
2. **Use async for LLM calls**: Always use `asyncio.run()` or async context for LLM operations
3. **Handle streaming properly**: Use callbacks for real-time response display
4. **Log errors with tracebacks**: Use `exc_info=True` for error logs to get stack traces
5. **Check LLM availability**: Verify `llm_info["available"]` before trying to use an LLM
6. **Use environment variables**: Keep API keys in `.env` file, not in code
7. **Validate configurations**: Ensure your `config.json` has all required fields
8. **Graceful error handling**: Always wrap LLM calls in try-except blocks

## Quick Reference

```python
# Most common imports
from shared.config import get_config
from shared.logging import log
from shared.translate import _
from shared.llm import llm_generate, set_current_llm

# Most common patterns
config = get_config()
log("info", "Message here")
translated_text = _("translation_key")
response = await llm_generate("Your prompt")
```

## Troubleshooting

### Common Issues

1. **"No available LLMs found"**: Check your `.env` file for missing API keys
2. **"cannot access local variable 'llm'"**: Avoid using `llm` as variable name in loops
3. **Configuration errors**: Ensure config is loaded before importing other modules
4. **Streaming not working**: Verify the LLM supports streaming and callback is defined
5. **Translation errors**: Check that translation files exist and keys match

### Debug Tips

1. Enable traceback in logging config: `"include_traceback": true`
2. Check LLM availability: `get_available_llms()` returns detailed status
3. Verify environment variables: Use debug section in Streamlit app
4. Monitor logs: All system operations are logged with appropriate levels

This integrated system allows each module to be self-contained with its own configuration, translations, logging, and LLM capabilities while seamlessly integrating with the main application.

"""
