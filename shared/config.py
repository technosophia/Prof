# file name: shared/config.py
"""
New centralized configuration system.

Key changes:
- No Streamlit dependencies.
- Automatic discovery and hierarchical merge of ALL config.json files.
- Prefixes based on directory structure (e.g., modules/rag/config.json → prefix "modules.rag").
- Root config.json has no prefix (top-level keys).
- In TEST_MODE, all */tests/test_config.json files are automatically loaded as partial overrides on the corresponding section.
- Duplicate keys are impossible by design (hierarchical prefixes).
- Added get_section() and save_section() for module-specific read/write.
- Removed singleton, duplicate checking, reload.
"""

import json
import os
from typing import Any, Dict


class Config:
    def __init__(self):
        self._config: dict[str, Any] = {}
        self._source_files: dict[tuple[str, ...], str] = {}

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

    def load_file(self, file_path: str, prefix_parts: list[str]):
        """Load a single JSON file and merge it under the given prefix."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # === NEW: Optional auto-flattening for legacy wrapped module configs ===
            # If the config is wrapped under a single key matching the last prefix part
            # (e.g., {"rag_manager": { ... }} in modules/rag_manager/config.json),
            # flatten it so the settings end up directly under "modules.rag_manager"
            if prefix_parts:
                last_part = prefix_parts[-1]
                if len(data) == 1 and last_part in data and isinstance(data[last_part], dict):
                    print(f"Auto-flattening wrapped config: {file_path} (using inner '{last_part}')")
                    data = data[last_part]

            current = self._config
            for part in prefix_parts:
                current = current.setdefault(part, {})

            self._deep_merge(current, data)
            self._source_files[tuple(prefix_parts)] = file_path

            prefix_str = ".".join(prefix_parts) if prefix_parts else "root"
            print(f"Loaded config from {file_path} (prefix: {prefix_str})")
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


def load_all_configs(root_dir: str, test_mode: bool = False) -> Config:
    """Discover and load all configs automatically."""
    config = Config()

    # 1. Load normal config.json files (skip tests directories)
    for dirpath, dirnames, filenames in os.walk(root_dir):
        if "tests" in dirnames:
            dirnames.remove("tests")  # prevent recursion into tests/
        if "config.json" in filenames:
            rel_path = os.path.relpath(dirpath, root_dir)
            prefix_parts = rel_path.split(os.sep) if rel_path != "." else []
            file_path = os.path.join(dirpath, "config.json")
            config.load_file(file_path, prefix_parts)

    # 2. In TEST_MODE: load */tests/test_config.json as partial overrides
    if test_mode:
        for dirpath, dirnames, filenames in os.walk(root_dir):
            if os.path.basename(dirpath) == "tests" and "test_config.json" in filenames:
                parent_dir = os.path.dirname(dirpath)
                rel_path = os.path.relpath(parent_dir, root_dir)
                prefix_parts = rel_path.split(os.sep) if rel_path != "." else []
                file_path = os.path.join(dirpath, "test_config.json")
                config.load_file(file_path, prefix_parts)

    return config
