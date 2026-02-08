# file name: shared/prompt_manager.py
"""
Prompt Manager - Centralized prompt management system.

Collects prompts from prompts.yaml files in modules directory.
Prompts are stored hierarchically and can be accessed using dot notation:
'<module_name>.<prompt_id>'

Key features:
- Automatic discovery of all prompts.yaml files
- Cached for performance
- Supports hierarchical organization
- Provides admin interface to view all prompts
- Integration with shared/common.py via get_prompt()
"""

import os
import sys
import yaml
from typing import Dict, Any, Optional, List
from pathlib import Path
from core.logging import log

class PromptManager:
    """Manages prompts across all modules."""

    def __init__(self):
        self._prompts: Dict[str, Any] = {}
        self._loaded = False
        self._source_files: Dict[str, str] = {}

    def _deep_merge(self, target: Dict, source: Dict):
        """Deep merge two dictionaries."""
        for key, value in source.items():
            if isinstance(value, dict) and key in target and isinstance(target[key], dict):
                self._deep_merge(target[key], value)
            else:
                target[key] = value

    def load_all_prompts(self, root_dir: str):
        """Load all prompts.yaml files from the project."""
        if self._loaded:
            return

        # Walk through all directories, skipping tests
        for dirpath, dirnames, filenames in os.walk(root_dir):
            # Skip tests directories
            if "tests" in dirnames:
                dirnames.remove("tests")

            # Check for prompts.yaml
            if "prompts.yaml" in filenames:
                file_path = os.path.join(dirpath, "prompts.yaml")

                # Calculate module prefix based on directory structure
                rel_path = os.path.relpath(dirpath, root_dir)
                if rel_path == ".":
                    prefix = ""
                else:
                    # Convert path to module-like prefix
                    parts = rel_path.split(os.sep)

                    # Handle shared directory specially
                    if parts[0] == "shared":
                        prefix = "shared"
                    # Handle modules directory
                    elif parts[0] == "modules" and len(parts) > 1:
                        prefix = parts[1]  # module name
                    else:
                        prefix = ".".join(parts)

                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        prompts = yaml.safe_load(f)

                    if prompts:
                        # If prefix is empty (root prompts), merge directly
                        if not prefix:
                            self._deep_merge(self._prompts, prompts)
                            self._source_files["root"] = file_path
                        else:
                            # Create nested structure for module
                            current = self._prompts
                            for part in prefix.split("."):
                                if part not in current:
                                    current[part] = {}
                                current = current[part]

                            self._deep_merge(current, prompts)
                            self._source_files[prefix] = file_path

                        print(f"Loaded prompts from {file_path} (prefix: '{prefix or 'root'}')")
                except Exception as e:
                    print(f"Error loading prompts from {file_path}: {e}")

        self._loaded = True

    def get_prompt(self, key: str, default: Any = None) -> Any:
        """
        Get a prompt by key using dot notation.

        Args:
            key: Dot-separated key (e.g., 'rag_manager.search_prompt')
            default: Default value if key not found

        Returns:
            Prompt value or default
        """
        keys = key.split(".")
        value = self._prompts

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def get_all_prompts(self) -> Dict[str, Any]:
        """Get all loaded prompts."""
        return self._prompts.copy()

    def get_module_prompts(self, module_prefix: str = "") -> Dict[str, Any]:
        """Get prompts for a specific module."""
        if not module_prefix:
            return self._prompts.copy()

        keys = module_prefix.split(".")
        value = self._prompts

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return {}

        return value.copy() if isinstance(value, dict) else value

    def get_source_file(self, module_prefix: str = "") -> Optional[str]:
        """Get the source file for a module's prompts."""
        return self._source_files.get(module_prefix)

    def list_modules(self) -> List[str]:
        """List all module prefixes with prompts."""
        modules = list(self._source_files.keys())
        modules.sort()
        return modules

    def search_prompts(self, search_text: str) -> Dict[str, Any]:
        """Search prompts containing the search text."""
        search_text = search_text.lower()
        results = {}

        def search_dict(d: Dict, path: str = ""):
            for key, value in d.items():
                current_path = f"{path}.{key}" if path else key

                if isinstance(value, dict):
                    search_dict(value, current_path)
                elif isinstance(value, str) and search_text in value.lower():
                    if path not in results:
                        results[path] = {}
                    results[path][key] = value
                elif isinstance(value, (list, int, float, bool)) and search_text in str(value).lower():
                    if path not in results:
                        results[path] = {}
                    results[path][key] = value

        search_dict(self._prompts)
        return results


# Global prompt manager instance
_prompt_manager = None

def get_prompt_manager() -> PromptManager:
    """Get the global prompt manager instance."""
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = PromptManager()
    return _prompt_manager

def load_all_prompts(root_dir: Optional[str] = None):
    """
    Load all prompts from the project.

    Args:
        root_dir: Project root directory (auto-detected if None)
    """
    if root_dir is None:
        # Determine project root (shared/prompt_manager.py → shared → root)
        shared_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.dirname(shared_dir)

    get_prompt_manager().load_all_prompts(root_dir)

def get_prompt(key: str, default: Any = None) -> Any:
    """
    Convenience function to get a prompt by key.

    Args:
        key: Dot-separated key (e.g., 'rag_manager.search_prompt')
        default: Default value if key not found

    Returns:
        Prompt value or default
    """
    return get_prompt_manager().get_prompt(key, default)

def get_all_prompts() -> Dict[str, Any]:
    """Get all loaded prompts."""
    return get_prompt_manager().get_all_prompts()

def get_module_prompts(module_prefix: str = "") -> Dict[str, Any]:
    """Get prompts for a specific module."""
    return get_prompt_manager().get_module_prompts(module_prefix)

def list_modules_with_prompts() -> List[str]:
    """List all module prefixes with prompts."""
    return get_prompt_manager().list_modules()
