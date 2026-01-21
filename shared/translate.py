""" Translate helper function

[agent]
Streamlit-safe translation function.
Works with the translator in session state.
Must be imported like this : from shared.translate import _streamlit as _
"""


import json
import os
from typing import Dict, Optional

# Import the simple log function (no config dependency)
from shared.logging import log

class Translator:
    def __init__(self):
        self.translations: Dict[str, Dict[str, str]] = {}
        self.current_lang = "en"
        self._modules: Dict[str, Dict[str, Dict[str, str]]] = {}

    def load_language_file(self, lang_code: str, filepath: str) -> bool:
        """
        Load a translation file for a specific language.

        Args:
            lang_code: Language code (e.g., 'fr', 'en')
            filepath: Path to JSON file

        Returns:
            bool: True if loaded successfully, False otherwise
        """
        try:
            if os.path.exists(filepath):
                with open(filepath, "r", encoding="utf-8") as f:
                    translations = json.load(f)

                if lang_code not in self.translations:
                    self.translations[lang_code] = {}

                self.translations[lang_code].update(translations)
                log("debug", f"Loaded {len(translations)} translations for language '{lang_code}' from {filepath}")
                return True
        except Exception as e:
            log("error", f"Error loading translation file {filepath}: {e}")

        return False

    def add_module_translations(self, module_name: str, translations_dict: Dict[str, Dict[str, str]]):
        """
        Add translations for a specific module.

        Args:
            module_name: Module name (e.g., 'app', 'dashboard', 'auth')
            translations_dict: Dictionary with language codes as keys
                              and translation dictionaries as values
                              Example: {'en': {'key': 'value'}, 'fr': {'key': 'valeur'}}
        """
        if module_name not in self._modules:
            self._modules[module_name] = {}

        total_translations = 0
        for lang_code, translations in translations_dict.items():
            if lang_code not in self._modules[module_name]:
                self._modules[module_name][lang_code] = {}

            # Check for duplicates
            existing_keys = set(self._modules[module_name][lang_code].keys())
            new_keys = set(translations.keys())
            duplicates = existing_keys.intersection(new_keys)

            if duplicates:
                log("warning", f"Module '{module_name}' has duplicate translation keys in language '{lang_code}': {', '.join(duplicates)}")

            self._modules[module_name][lang_code].update(translations)
            total_translations += len(translations)

            # Update global translations
            if lang_code not in self.translations:
                self.translations[lang_code] = {}
            self.translations[lang_code].update(translations)

        log("info", f"Added module '{module_name}' with {total_translations} total translations")

    def inject_module_translations(self, module_name: str, base_path: str):
        """
        Automatically inject module translations from JSON files.

        Args:
            module_name: Module name
            base_path: Base path to look for translation files
                      (e.g., 'translations/app' for translations/app/fr.json)
        """
        translations_dict = {}

        # Look for all language files in the directory
        if os.path.exists(base_path):
            for filename in os.listdir(base_path):
                if filename.endswith(".json"):
                    lang_code = filename.split(".")[0]
                    filepath = os.path.join(base_path, filename)

                    try:
                        with open(filepath, "r", encoding="utf-8") as f:
                            translations = json.load(f)

                        if lang_code not in translations_dict:
                            translations_dict[lang_code] = {}

                        translations_dict[lang_code].update(translations)
                    except Exception as e:
                        log("error", f"Error loading {filepath}: {e}")

        if translations_dict:
            self.add_module_translations(module_name, translations_dict)

    def load_app_translations(self, translations_dir: str = "translations"):
        """
        Load application translations from a directory.
        This is the one-line solution for loading app translations.

        Args:
            translations_dir: Directory containing translation JSON files
        """
        if os.path.exists(translations_dir):
            for filename in os.listdir(translations_dir):
                if filename.endswith(".json"):
                    lang_code = filename.split(".")[0]
                    filepath = os.path.join(translations_dir, filename)
                    self.load_language_file(lang_code, filepath)

    def set_language(self, lang: str):
        """Change current language"""
        if lang in self.translations:
            self.current_lang = lang
            log("debug", f"Language set to '{lang}'")
        else:
            # Fallback to first available language
            available_langs = list(self.translations.keys())
            if available_langs:
                self.current_lang = available_langs[0]
                log("warning", f"Language '{lang}' not available, falling back to '{self.current_lang}'")
            else:
                self.current_lang = "en"
                log("warning", f"No translations loaded, defaulting to '{self.current_lang}'")

    def get_current_language(self) -> str:
        """Return current language code"""
        return self.current_lang

    def get_module_translations(self, module_name: str, lang_code: Optional[str] = None) -> Dict[str, str]:
        """
        Retrieve all translations for a specific module.

        Args:
            module_name: Module name
            lang_code: Language code (None for current language)

        Returns:
            Dict[str, str]: Module translations dictionary
        """
        lang = lang_code or self.current_lang

        if module_name in self._modules and lang in self._modules[module_name]:
            return self._modules[module_name][lang].copy()

        return {}

    def __call__(self, key: str) -> str:
        """Function _() to get a translation"""
        try:
            return self.translations[self.current_lang][key]
        except KeyError:
            # Search in all available languages
            for lang_code in self.translations:
                if key in self.translations[lang_code]:
                    log("debug", f"Translation key '{key}' not found in '{self.current_lang}', found in '{lang_code}'")
                    return self.translations[lang_code][key]

            # If no translation found
            log("warning", f"Translation key '{key}' not found in any language")
            return f"[{key}]"

# Global translator instance
_translator_instance = None

def get_translator() -> Translator:
    """Return the singleton translator instance"""
    global _translator_instance
    if _translator_instance is None:
        _translator_instance = Translator()
    return _translator_instance

def _(key: str) -> str:
    """Helper function to access translations"""
    return get_translator()(key)

def init_translations(lang: str = "en", translations_dir: str = "translations"):
    """
    Initialize translator with default language and load translations.
    This is the ultimate one-line initialization.

    Args:
        lang: Default language code
        translations_dir: Directory containing translation JSON files

    Returns:
        Translator: Initialized translator instance
    """
    translator = get_translator()
    translator.load_app_translations(translations_dir)
    translator.set_language(lang)
    return translator

# Streamlit-specific helper functions
def init_translations_streamlit(lang: str = "en", translations_dir: str = "translations"):
    """
    Initialize translations for Streamlit with session state support.
    Use this in Streamlit apps for proper state management.

    Args:
        lang: Default language code
        translations_dir: Directory containing translation JSON files

    Returns:
        Translator: Initialized translator instance
    """
    import streamlit as st

    # Use Streamlit's session state to persist the translator
    if "translator" not in st.session_state:
        translator = Translator()
        translator.load_app_translations(translations_dir)
        translator.set_language(lang)
        st.session_state.translator = translator
        st.session_state.current_language = lang
        log("info", f"Translator initialized with language '{lang}' from '{translations_dir}'")

    return st.session_state.translator

def get_translator_streamlit():
    """
    Get translator from Streamlit session state.
    Raises an error if translator hasn't been initialized.
    """
    import streamlit as st

    if "translator" not in st.session_state:
        raise RuntimeError("Translator not initialized. Call init_translations_streamlit() first.")

    return st.session_state.translator

def _streamlit(key: str) -> str:
    import streamlit as st

    if "translator" not in st.session_state:
        # Fallback to global translator if available
        try:
            return _(key)
        except:
            log("error", f"Translator not available for key '{key}'")
            return f"[{key}]"

    return st.session_state.translator(key)
