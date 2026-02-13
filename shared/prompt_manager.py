# file name: shared/prompt_manager.py
"""
Prompt Manager - Centralized prompt management system with multilingual support.

Collects prompts from prompts.yaml or prompts.xx.yaml files in modules directory.
Prompts can be accessed using dot notation: '<module_name>.<prompt_id>'

Key features:
- Automatic discovery of all prompts.yaml/prompts.xx.yaml files
- Multilingual support with language-specific prompt files
- Cached for performance
- Supports hierarchical organization
- Provides admin interface to view all prompts
- Integration with shared/common.py via get_prompt()
"""

import os
import sys
import yaml
import glob
from typing import Dict, Any, Optional, List, Set
from pathlib import Path
from core.logging import log
from core.translate import VALID_LANGUAGES


class PromptLoadError(Exception):
    """Exception raised for prompt loading errors."""
    pass


class PromptManager:
    """Manages prompts across all modules with multilingual support."""

    def __init__(self):
        self._prompts: Dict[str, Any] = {}  # Legacy single language prompts
        self._multilingual_prompts: Dict[str, Dict[str, Any]] = {}  # lang -> prompts
        self._loaded = False
        self._source_files: Dict[str, str] = {}  # module -> source file
        self._available_languages: Set[str] = set()
        self._default_language: str = 'en'
        self._is_multilingual: bool = False

    def _deep_merge(self, target: Dict, source: Dict):
        """Deep merge two dictionaries."""
        for key, value in source.items():
            if isinstance(value, dict) and key in target and isinstance(target[key], dict):
                self._deep_merge(target[key], value)
            else:
                target[key] = value

    def _detect_prompt_files(self, dirpath: str, recursive: bool = True) -> Dict[str, str]:
        """
        Detect prompt files in a directory recursively.
        Returns a dict: {language_code: file_path}
        Special key 'default' for prompts.yaml

        Args:
            dirpath: Directory to search
            recursive: Whether to search subdirectories recursively
        """
        prompt_files = {}

        # Check current directory
        # Check for legacy prompts.yaml
        legacy_file = os.path.join(dirpath, "prompts.yaml")
        if os.path.exists(legacy_file):
            prompt_files['default'] = legacy_file

        # Check for language-specific prompts.xx.yaml files
        pattern = os.path.join(dirpath, "prompts.*.yaml")
        for file_path in glob.glob(pattern):
            filename = os.path.basename(file_path)
            # Extract language code from prompts.xx.yaml
            if filename.startswith('prompts.') and filename.endswith('.yaml'):
                lang_code = filename.replace('prompts.', '').replace('.yaml', '')
                if lang_code in VALID_LANGUAGES:
                    prompt_files[lang_code] = file_path

        # Recursively search subdirectories if requested
        if recursive:
            try:
                for item in os.listdir(dirpath):
                    item_path = os.path.join(dirpath, item)
                    # Skip __pycache__ and tests directories
                    if os.path.isdir(item_path) and item not in ['__pycache__', 'tests']:
                        subdir_files = self._detect_prompt_files(item_path, recursive=True)
                        # Merge subdirectory files into the result
                        for lang_code, file_path in subdir_files.items():
                            if lang_code not in prompt_files:
                                prompt_files[lang_code] = file_path
                            else:
                                # If there are multiple files for same language, log warning
                                log("warning", f"Multiple prompt files for language '{lang_code}' found: "
                                            f"{prompt_files[lang_code]} and {file_path}")
            except PermissionError:
                log("debug", f"Permission denied accessing {dirpath}")

        return prompt_files

    def _validate_no_mixed_formats(self, prompt_files: Dict[str, str], dirpath: str):
        """
        Validate that directory doesn't mix legacy and multilingual prompt files.
        Raises PromptLoadError if mixed formats are found.
        """
        has_legacy = 'default' in prompt_files
        has_multilingual = any(lang != 'default' for lang in prompt_files.keys())

        if has_legacy and has_multilingual:
            legacy_file = prompt_files['default']
            lang_files = [f for lang, f in prompt_files.items() if lang != 'default']
            error_msg = (
                f"Mixed prompt formats detected in {dirpath}:\n"
                f"  Legacy format: {legacy_file}\n"
                f"  Multilingual formats: {lang_files}\n"
                f"Cannot mix prompts.yaml with language-specific prompts.xx.yaml files. "
                f"Please choose one format."
            )
            raise PromptLoadError(error_msg)

    def _detect_multilingual_mode(self):
        """Detect if we're in multilingual mode based on loaded prompts."""
        if self._multilingual_prompts and len(self._multilingual_prompts) > 0:
            self._is_multilingual = True
            self._available_languages = set(self._multilingual_prompts.keys())
            return True
        return False

    def load_all_prompts(self, root_dir: str):
        """Load all prompts.yaml or prompts.xx.yaml files from the project recursively."""
        if self._loaded:
            return

        multilingual_detected = False
        legacy_detected = False

        # Walk through all directories, skipping tests and __pycache__
        for dirpath, dirnames, filenames in os.walk(root_dir):
            # Skip tests directories
            if "tests" in dirnames:
                dirnames.remove("tests")
            # Skip __pycache__ directories
            if "__pycache__" in dirnames:
                dirnames.remove("__pycache__")

            # Detect prompt files in this directory (non-recursive here since os.walk handles recursion)
            prompt_files = self._detect_prompt_files(dirpath, recursive=False)

            if not prompt_files:
                continue

            # Validate no mixed formats
            self._validate_no_mixed_formats(prompt_files, dirpath)

            # Track format types
            if 'default' in prompt_files:
                legacy_detected = True
            else:
                multilingual_detected = True

            # Calculate module prefix based on full directory structure from root
            rel_path = os.path.relpath(dirpath, root_dir)
            if rel_path == ".":
                prefix = ""
            else:
                # Split the path and create a dot-separated prefix that includes subdirectories
                parts = rel_path.split(os.sep)

                # Handle special top-level directories
                if parts[0] == "shared":
                    # For shared directory, use full path
                    prefix = ".".join(parts)
                elif parts[0] == "modules" and len(parts) > 1:
                    # For modules, start from the module name (skip 'modules' directory)
                    prefix = ".".join(parts[1:])  # This preserves subdirectories
                else:
                    # For other directories, use full path
                    prefix = ".".join(parts)

            # Load prompt files
            for lang_code, file_path in prompt_files.items():
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        prompts = yaml.safe_load(f)

                    if not prompts:
                        continue

                    if lang_code == 'default':
                        # Legacy format - load into single prompts dict
                        if not prefix:
                            self._deep_merge(self._prompts, prompts)
                            self._source_files["root"] = file_path
                        else:
                            current = self._prompts
                            for part in prefix.split("."):
                                if part not in current:
                                    current[part] = {}
                                current = current[part]
                            self._deep_merge(current, prompts)
                            self._source_files[prefix] = file_path

                        log("debug", f"Loaded legacy prompts from {file_path} (prefix: '{prefix or 'root'}')")

                    else:
                        # Multilingual format - FORCE create the language entry
                        if lang_code not in self._multilingual_prompts:
                            self._multilingual_prompts[lang_code] = {}
                            self._available_languages.add(lang_code)

                        current = self._multilingual_prompts[lang_code]

                        if not prefix:
                            self._deep_merge(current, prompts)
                        else:
                            for part in prefix.split("."):
                                if part not in current:
                                    current[part] = {}
                                current = current[part]
                            self._deep_merge(current, prompts)

                        source_key = f"{prefix}:{lang_code}" if prefix else f"root:{lang_code}"
                        self._source_files[source_key] = file_path

                        log("debug", f"Loaded {lang_code} prompts from {file_path} (prefix: '{prefix or 'root'}')")

                except Exception as e:
                    log("error", f"Error loading prompts from {file_path}: {e}")
                    raise PromptLoadError(f"Failed to load {file_path}: {e}")

        # Validate that we don't have mixed formats across the project
        if legacy_detected and multilingual_detected:
            error_msg = (
                "Mixed prompt formats detected across the project:\n"
                "Some modules use legacy prompts.yaml while others use language-specific prompts.xx.yaml.\n"
                "All modules must use the same format. Please standardize on either:\n"
                "  - Legacy format: prompts.yaml only\n"
                "  - Multilingual format: prompts.en.yaml, prompts.fr.yaml, etc.\n"
                "Do not mix both formats in the project."
            )
            raise PromptLoadError(error_msg)

        # CRITICAL FIX: Force multilingual mode if we have any multilingual prompts
        if self._multilingual_prompts and len(self._multilingual_prompts) > 0:
            self._is_multilingual = True
            self._available_languages = set(self._multilingual_prompts.keys())
            multilingual_detected = True
            log("info", f"FORCE: Multilingual mode enabled. Available languages: {sorted(self._available_languages)}")
        else:
            self._is_multilingual = False

        self._loaded = True

        if self._is_multilingual:
            if self._default_language not in self._available_languages:
                log("warning", f"Default language '{self._default_language}' not found. Using '{next(iter(self._available_languages), 'en')}'")
                self._default_language = next(iter(self._available_languages), 'en')


    def get_prompt(self, key: str, default: Any = None, language: Optional[str] = None) -> Any:
        """
        Get a prompt by key using dot notation.

        Args:
            key: Dot-separated key (e.g., 'rag_manager.search_prompt')
            default: Default value if key not found
            language: Language code (e.g., 'en', 'fr').
                     If None, uses default language in multilingual mode,
                     or legacy prompts in single language mode.

        Returns:
            Prompt value or default
        """
        # Legacy mode - single language
        if not self._is_multilingual:
            return self._get_prompt_from_dict(self._prompts, key, default)

        # Multilingual mode
        lang = language or self._default_language

        # Try requested language
        if lang in self._multilingual_prompts:
            value = self._get_prompt_from_dict(self._multilingual_prompts[lang], key, None)
            if value is not None:
                return value

        # Fallback to default language
        if lang != self._default_language and self._default_language in self._multilingual_prompts:
            value = self._get_prompt_from_dict(self._multilingual_prompts[self._default_language], key, None)
            if value is not None:
                log("debug", f"Prompt '{key}' not in '{lang}', falling back to '{self._default_language}'")
                return value

        # Try any available language as last resort
        for available_lang in self._available_languages:
            if available_lang != lang and available_lang != self._default_language:
                value = self._get_prompt_from_dict(self._multilingual_prompts[available_lang], key, None)
                if value is not None:
                    log("debug", f"Prompt '{key}' not in '{lang}', found in '{available_lang}'")
                    return value

        return default

    def _get_prompt_from_dict(self, prompts_dict: Dict, key: str, default: Any) -> Any:
        """Get a prompt from a specific dictionary using dot notation."""
        keys = key.split(".")
        value = prompts_dict

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def get_all_prompts(self, language: Optional[str] = None) -> Dict[str, Any]:
        """
        Get all loaded prompts.

        Args:
            language: Language code for multilingual mode.
                     If None in multilingual mode, returns all languages.
        """
        if not self._is_multilingual:
            return self._prompts.copy()

        if language:
            return self._multilingual_prompts.get(language, {}).copy()

        return {lang: data.copy() for lang, data in self._multilingual_prompts.items()}

    def get_module_prompts(self, module_prefix: str = "", language: Optional[str] = None) -> Dict[str, Any]:
        """
        Get prompts for a specific module.

        Args:
            module_prefix: Module prefix (e.g., 'rag_manager')
            language: Language code for multilingual mode
        """
        if not self._is_multilingual:
            return self._get_module_prompts_from_dict(self._prompts, module_prefix)

        if language:
            prompts_dict = self._multilingual_prompts.get(language, {})
            return self._get_module_prompts_from_dict(prompts_dict, module_prefix)

        # Return all languages for the module
        result = {}
        for lang, prompts_dict in self._multilingual_prompts.items():
            module_data = self._get_module_prompts_from_dict(prompts_dict, module_prefix)
            if module_data:
                result[lang] = module_data
        return result

    def _get_module_prompts_from_dict(self, prompts_dict: Dict, module_prefix: str) -> Dict[str, Any]:
        """Get module prompts from a specific dictionary."""
        if not module_prefix:
            return prompts_dict.copy()

        keys = module_prefix.split(".")
        value = prompts_dict

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return {}

        return value.copy() if isinstance(value, dict) else value

    def get_available_languages(self) -> List[str]:
        """Get list of available languages in multilingual mode."""
        return sorted(self._available_languages)

    def is_multilingual(self) -> bool:
        """Check if the system is running in multilingual mode."""
        return self._is_multilingual

    def get_default_language(self) -> str:
        """Get the default language."""
        return self._default_language

    def set_default_language(self, language: str):
        """Set the default language for prompts."""
        if language in self._available_languages:
            self._default_language = language
            log("info", f"Default language set to '{language}'")
        else:
            log("warning", f"Cannot set default language to '{language}' - not available")

    def get_source_file(self, module_prefix: str = "", language: Optional[str] = None) -> Optional[str]:
        """Get the source file for a module's prompts."""
        if not self._is_multilingual or language is None:
            return self._source_files.get(module_prefix)

        source_key = f"{module_prefix}:{language}" if module_prefix else f"root:{language}"
        return self._source_files.get(source_key)

    def list_modules(self, language: Optional[str] = None) -> List[str]:
        """List all module prefixes with prompts."""
        if not self._is_multilingual or language is None:
            modules = [k for k in self._source_files.keys() if ':' not in k]
        else:
            modules = [k.split(':')[0] for k in self._source_files.keys()
                      if ':' in k and k.endswith(f":{language}")]

        modules = list(set(modules))  # Remove duplicates
        modules.sort()
        return modules

    def search_prompts(self, search_text: str, language: Optional[str] = None) -> Dict[str, Any]:
        """Search prompts containing the search text."""
        search_text = search_text.lower()
        results = {}

        def search_dict(d: Dict, path: str = "", lang: str = ""):
            for key, value in d.items():
                current_path = f"{path}.{key}" if path else key
                lang_prefix = f"[{lang}] " if lang else ""

                if isinstance(value, dict):
                    search_dict(value, current_path, lang)
                elif isinstance(value, str) and search_text in value.lower():
                    if lang_prefix + path not in results:
                        results[lang_prefix + path] = {}
                    results[lang_prefix + path][key] = value
                elif isinstance(value, (list, int, float, bool)) and search_text in str(value).lower():
                    if lang_prefix + path not in results:
                        results[lang_prefix + path] = {}
                    results[lang_prefix + path][key] = value

        if not self._is_multilingual:
            search_dict(self._prompts)
        elif language:
            if language in self._multilingual_prompts:
                search_dict(self._multilingual_prompts[language], lang=language)
        else:
            for lang, prompts_dict in self._multilingual_prompts.items():
                search_dict(prompts_dict, lang=lang)

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

    Raises:
        PromptLoadError: If mixed prompt formats are detected
    """
    if root_dir is None:
        # Determine project root (shared/prompt_manager.py → shared → root)
        shared_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.dirname(shared_dir)

    get_prompt_manager().load_all_prompts(root_dir)

def get_prompt(key: str, default: Any = None, language: Optional[str] = None) -> Any:
    """
    Convenience function to get a prompt by key.

    Args:
        key: Dot-separated key (e.g., 'rag_manager.search_prompt')
        default: Default value if key not found
        language: Language code for multilingual mode

    Returns:
        Prompt value or default
    """
    return get_prompt_manager().get_prompt(key, default, language)

def get_all_prompts(language: Optional[str] = None) -> Dict[str, Any]:
    """Get all loaded prompts."""
    return get_prompt_manager().get_all_prompts(language)

def get_module_prompts(module_prefix: str = "", language: Optional[str] = None) -> Dict[str, Any]:
    """Get prompts for a specific module."""
    return get_prompt_manager().get_module_prompts(module_prefix, language)

def list_modules_with_prompts(language: Optional[str] = None) -> List[str]:
    """List all module prefixes with prompts."""
    return get_prompt_manager().list_modules(language)

def get_available_languages() -> List[str]:
    """Get list of dynamic available languages."""
    return get_prompt_manager().get_available_languages()

def is_multilingual() -> bool:
    """Check if the system is running in multilingual mode."""
    return get_prompt_manager().is_multilingual()

def set_default_language(language: str):
    """Set the default language for prompts."""
    return get_prompt_manager().set_default_language(language)
