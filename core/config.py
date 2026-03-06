# file name: shared/config.py
"""
New centralized configuration system.

Key changes:
- No Streamlit dependencies.
- Automatic discovery and hierarchical merge of config files with different prefixes.
- Prefixes based on directory structure (e.g., modules/rag/CONFIG_FILE → prefix "modules.rag").
- Root config.json has no prefix (top-level keys).
- Additional prefix-based config files (e.g., local_config.json, test_config.json) are loaded as overrides.
- Added get_section() and save_section() for module-specific read/write.
- Removed singleton, duplicate checking, reload.
"""

import json
import sys
import os
from typing import Any, Dict, List, Optional, Set
from .logging import log

# Constants for config file suffixes
CONFIG_FILE = "config.json"

class Config:
    def __init__(self):
        self._config: dict[str, Any] = {}
        self._source_files: dict[tuple[str, ...], str] = {}
        self._missing_keys_warned: set[str] = set()
        self._key_source_files: dict[str, str] = {}
        self._file_to_keys: dict[str, set[str]] = {}
        self._loaded_files: Set[str] = set()

        # Optional built-in defaults (kept from your original code)
        defaults = {
            "logging": {
                "level": "INFO",
                "format": "[{level}] {timestamp} - {message}",
                "include_traceback": True,
                "file": None,
                "console": True
            },
            "app": {
                "name": "Default App",
                "version": "1.0.0",
                "debug": False
            }
        }
        self._deep_merge(self._config, defaults)

    def _deep_merge(self, target: dict, source: dict):
        """Deep merge that always overrides leaf values."""
        for key, value in source.items():
            if isinstance(value, dict) and key in target and isinstance(target[key], dict):
                self._deep_merge(target[key], value)
            else:
                target[key] = value

    def _flatten_leaf_keys(self, data: Any, prefix: str = "") -> list[str]:
        """Return dot-notation leaf keys for a nested dictionary."""
        if isinstance(data, dict):
            keys: list[str] = []
            for key, value in data.items():
                current = f"{prefix}.{key}" if prefix else key
                keys.extend(self._flatten_leaf_keys(value, current))
            return keys
        return [prefix] if prefix else []

    def _is_override_file(self, file_path: str) -> bool:
        """Whether this file is an explicit override config file."""
        normalized = file_path.replace("\\", "/")
        return (
            normalized.endswith("/local_config.json")
            or normalized.endswith("/test_config.json")
            or normalized.endswith("/tests/test_config.json")
        )

    def load_file(self, file_path: str):
        """Load a single JSON file and merge directly at root level."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Keep file-content namespaces as-is (no path-derived prefixing).
            # Wrapped module keys are preserved because they are part of file content.
            self._deep_merge(self._config, data)

            self._loaded_files.add(file_path)
            is_override = self._is_override_file(file_path)

            for top_level_key in data.keys():
                self._source_files[(top_level_key,)] = file_path

            for leaf_key in self._flatten_leaf_keys(data):
                previous_file = self._key_source_files.get(leaf_key)
                if previous_file and previous_file != file_path and not is_override:
                    log("warning", f"Duplicate config key '{leaf_key}' loaded from {file_path}; previous source: {previous_file}")
                self._key_source_files[leaf_key] = file_path
                self._file_to_keys.setdefault(file_path, set()).add(leaf_key)

            log("debug", f"Loaded config from {file_path} (flat merge)")
        except Exception as e:
            print(f"Error loading config file {file_path}: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """Dot-notation access (e.g., 'database.path' or 'modules.rag.enabled')."""
        keys = key.split(".")
        value = self._config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                if key not in self._missing_keys_warned:
                    self._missing_keys_warned.add(key)
                    log("warning", f"Config key not found: '{key}' (returning default={default!r})")
                return default
        return value

    def set(self, key: str, value: Any):
        """Dot-notation set."""
        keys = key.split(".")
        config = self._config
        for k in keys[:-1]:
            config = config.setdefault(k, {})
        config[keys[-1]] = value

    def __contains__(self, key: str) -> bool:
        """Support: if "some.nested.key" in config"""
        return self.get(key) is not None

    def __getitem__(self, key: str) -> Any:
        """Support: config["some.nested.key"]  (returns None if missing, like original)"""
        return self.get(key)

    def __setitem__(self, key: str, value: Any) -> None:
        """Support: config["some.nested.key"] = value"""
        self.set(key, value)

    def __iter__(self):
        """Support: for key in config:  (iterates over top-level keys only)"""
        return iter(self._config)

    def __len__(self) -> int:
        """Support: len(config)  (top-level keys count)"""
        return len(self._config)

    # Optional but recommended for full dict-like feel
    def keys(self):
        """config.keys() → top-level keys"""
        return self._config.keys()

    def items(self):
        """config.items() → top-level items"""
        return self._config.items()

    def values(self):
        """config.values() → top-level values"""
        return self._config.values()

    def get_key_source_file(self, key: str) -> Optional[str]:
        """Get the source file path for a specific dot-notation config key."""
        return self._key_source_files.get(key)

    def list_source_files(self) -> list[str]:
        """List all loaded config file paths."""
        return sorted(self._loaded_files)

    def list_keys_by_source_file(self) -> dict[str, list[str]]:
        """Map each source config file path to sorted leaf keys loaded from it."""
        return {file_path: sorted(keys) for file_path, keys in sorted(self._file_to_keys.items())}

    def get_section(self, prefix: str = "") -> dict:
        """Return a copy of an entire section (e.g., prefix='modules.rag')."""
        parts = prefix.split(".") if prefix else []
        current = self._config
        for p in parts:
            if isinstance(current, dict) and p in current and isinstance(current[p], dict):
                current = current[p]
            else:
                return {}
        return current.copy()

    def save_section(self, prefix: str, data: dict) -> bool:
        """Save a full section back to its original config.json file and update runtime config."""
        parts = prefix.split(".") if prefix else []
        tuple_parts = tuple(parts)

        if tuple_parts not in self._source_files:
            print(f"No source file mapped for prefix '{prefix}' – cannot save.")
            return False

        file_path = self._source_files[tuple_parts]
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, sort_keys=True)

            # Update in-memory config
            current = self._config
            for p in parts[:-1]:
                current = current[p]
            if parts:
                current[parts[-1]] = data.copy()
            else:
                self._config = data.copy()

            print(f"Saved config section '{prefix or 'root'}' to {file_path}")
            return True
        except Exception as e:
            print(f"Error saving config to {file_path}: {e}")
            return False


def load_all_configs(root_dir: str, additional_prefixes: Optional[List[str]] = None) -> Config:
    """
    Discover and load all configs automatically.

    Args:
        root_dir: Root directory to start discovery from
        additional_prefixes: List of config file suffixes to load (e.g., ['local', 'test'])
                           The actual filenames will be {prefix}_config.json
    """
    config = Config()
    additional_prefixes = additional_prefixes or []

    # First pass: find all directories containing base config.json
    base_config_dirs = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        if "tests" in dirnames:
            dirnames.remove("tests")  # prevent recursion into tests/
        if CONFIG_FILE in filenames:
            base_config_dirs.append(dirpath)

            # Load base config first
            file_path = os.path.join(dirpath, CONFIG_FILE)
            config.load_file(file_path)

    # Second pass: load additional prefixed config files where base config exists
    for prefix in additional_prefixes:
        config_file = f"{prefix}_{CONFIG_FILE}"
        for dirpath in base_config_dirs:
            file_path = os.path.join(dirpath, config_file)
            if os.path.exists(file_path):
                config.load_file(file_path)

    return config


def _load_config() -> Config:
    """Cached loading of the full configuration."""
    try:
        # Determine project root (shared/common.py → shared → root)
        shared_dir = os.path.dirname(os.path.abspath(__file__))

        # Debug logging
        log("debug", f"_load_config: __file__ = {__file__}")
        log("debug", f"_load_config: shared_dir = {shared_dir}")

        if not shared_dir:
            raise ValueError("shared_dir is None or empty")

        root_dir = os.path.dirname(shared_dir)
        log("debug", f"_load_config: root_dir = {root_dir}")

        if not root_dir or not os.path.exists(root_dir):
            raise ValueError(f"Invalid root_dir: {root_dir}")

        # Determine additional prefixes to load
        additional_prefixes = ['local']  # Always load local configs

        test_mode = os.getenv("TEST_MODE") == "true" or "pytest" in sys.modules
        if test_mode:
            additional_prefixes.append('tests/test')

        log("debug", f"_load_config: test_mode = {test_mode}")
        log("debug", f"_load_config: additional_prefixes = {additional_prefixes}")

        config = load_all_configs(root_dir, additional_prefixes)
        log("debug", f"_load_config: config loaded successfully, has {len(config)} top-level sections")

        return config

    except Exception as e:
        log("error", f"_load_config failed: {e}", stacktrace=True)

        # Return a minimal default config as fallback
        from core.config import Config
        fallback_config = Config()

        # Try to load root config directly
        root_config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), CONFIG_FILE)
        if os.path.exists(root_config_path):
            fallback_config.load_file(root_config_path)

        log("warning", f"Using fallback configuration due to error: {e}")
        return fallback_config
