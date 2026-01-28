"""
Configuration manager with module injection support.

[agent]
## Configuration System (`shared/config.py`)

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
"""

import json
import os
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class Config:
    """Configuration manager with module injection support."""

    # Default configuration
    defaults: Dict[str, Any] = field(default_factory=lambda: {
        "logging": {
            "level": "INFO",
            "format": "[{level}] {timestamp} - {message}",
            "file": None,
            "console": True
        },
        "app": {
            "name": "Default App",
            "version": "1.0.0",
            "debug": False
        }
    })

    def __init__(self):
        self._config: Dict[str, Any] = {}
        self._modules: Dict[str, Dict[str, Any]] = {}
        self._loaded_files: Dict[str, datetime] = {}

    def load_config_file(self, filepath: str) -> bool:
        """
        Load configuration from a JSON file.

        Args:
            filepath: Path to JSON configuration file

        Returns:
            bool: True if loaded successfully, False otherwise
        """
        try:
            if os.path.exists(filepath):
                with open(filepath, "r", encoding="utf-8") as f:
                    config_data = json.load(f)

                # Track when this file was loaded
                self._loaded_files[filepath] = datetime.now()

                # Deep merge configuration
                self._deep_merge(self._config, config_data)
                return True
        except Exception as e:
            print(f"Error loading config file {filepath}: {e}")

        return False

    def _deep_merge(self, target: Dict[str, Any], source: Dict[str, Any]):
        """
        Deep merge source dictionary into target dictionary.

        Args:
            target: Target dictionary to merge into
            source: Source dictionary to merge from
        """
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                self._deep_merge(target[key], value)
            else:
                target[key] = value

    def inject_module_config(self, module_name: str, config_path: Optional[str] = None):
        """
        Inject module configuration.

        Args:
            module_name: Name of the module
            config_path: Path to module's config.json (default: module_name/config.json)
        """
        if config_path is None:
            config_path = f"{module_name}/config.json"

        if not os.path.exists(config_path):
            print(f"Warning: Config file not found for module '{module_name}': {config_path}")
            return

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                module_config = json.load(f)

            # Check for duplicates
            self._check_duplicates(module_name, module_config)

            # Store module configuration
            self._modules[module_name] = module_config

            # Merge into global config
            self._deep_merge(self._config, module_config)

            self._loaded_files[config_path] = datetime.now()
            print(f"Loaded config for module '{module_name}' from {config_path}")

        except Exception as e:
            print(f"Error loading config for module '{module_name}': {e}")

    def _check_duplicates(self, module_name: str, module_config: Dict[str, Any]):
        """
        Check for duplicate configuration keys.

        Args:
            module_name: Name of the module
            module_config: Module configuration dictionary
        """
        duplicates = []

        def find_duplicates(base_dict: Dict[str, Any], new_dict: Dict[str, Any], path: str = ""):
            for key, value in new_dict.items():
                full_path = f"{path}.{key}" if path else key

                if key in base_dict:
                    if isinstance(value, dict) and isinstance(base_dict[key], dict):
                        find_duplicates(base_dict[key], value, full_path)
                    else:
                        duplicates.append(full_path)

        find_duplicates(self._config, module_config)

        if duplicates:
            print(f"Warning: Module '{module_name}' has duplicate configuration keys: {', '.join(duplicates)}")

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value by dot notation key.

        Args:
            key: Dot notation key (e.g., "logging.level")
            default: Default value if key not found

        Returns:
            Any: Configuration value
        """
        keys = key.split(".")
        value = self._config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key: str, value: Any):
        """
        Set configuration value by dot notation key.

        Args:
            key: Dot notation key (e.g., "logging.level")
            value: Value to set
        """
        keys = key.split(".")
        config = self._config

        for i, k in enumerate(keys[:-1]):
            if k not in config:
                config[k] = {}
            config = config[k]

        config[keys[-1]] = value

    def get_module_config(self, module_name: str) -> Dict[str, Any]:
        """
        Get configuration for a specific module.

        Args:
            module_name: Name of the module

        Returns:
            Dict[str, Any]: Module configuration
        """
        return self._modules.get(module_name, {}).copy()

    def reload(self, filepath: str) -> bool:
        """
        Reload configuration from a file.

        Args:
            filepath: Path to configuration file

        Returns:
            bool: True if reloaded successfully
        """
        if filepath in self._loaded_files:
            # Clear the file from loaded files
            del self._loaded_files[filepath]

            # Reload the file
            return self.load_config_file(filepath)

        return False

    def __getitem__(self, key: str) -> Any:
        """Allow dictionary-like access."""
        return self.get(key)

    def __setitem__(self, key: str, value: Any):
        """Allow dictionary-like assignment."""
        self.set(key, value)

    def __contains__(self, key: str) -> bool:
        """Check if key exists in configuration."""
        return self.get(key) is not None

# Global configuration instance
_config_instance = None

def get_config() -> Config:
    """Get the singleton configuration instance."""
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    return _config_instance

def init_config(config_file: str = "config.json") -> Config:
    """
    Initialize configuration from a file.

    Args:
        config_file: Path to configuration file

    Returns:
        Config: Initialized configuration instance
    """
    config = get_config()
    config.load_config_file(config_file)
    return config

def inject_module_config(module_name: str, config_path: Optional[str] = None):
    """
    Inject module configuration (one-line solution).

    Args:
        module_name: Name of the module
        config_path: Path to module's config.json
    """
    config = get_config()
    config.inject_module_config(module_name, config_path)
