import os
import json
from typing import Dict, Any

from core.logging import log

VALID_LANGUAGES = {'en', 'fr'}

def flatten_dict(d: Dict[str, Any], parent_key: str = '', sep: str = '.') -> Dict[str, str]:
    """
    Recursively flatten a nested dictionary using dot notation.

    Example:
        {
            "trainer_plugin_student_pad": {
                "name": "Student Pad",
                "notes": "Notes"
            }
        }

        Becomes:
        {
            "trainer_plugin_student_pad.name": "Student Pad",
            "trainer_plugin_student_pad.notes": "Notes"
        }
    """
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, str(v) if v is not None else ""))
    return dict(items)


def load_all_translations() -> Dict[str, Dict[str, str]]:
    """
    Search the entire project for 'translations' directories and load all JSON files.
    Returns a dict: {lang_code: {flat_key: translation, ...}, ...}

    Supports both flat JSON files and nested JSON files with dot notation.
    Later directories override earlier ones on key conflict (with warning).
    Loading order is deterministic: deeper paths first, root translations last.
    Only loads translations for languages in VALID_LANGUAGES.
    """
    translations: Dict[str, Dict[str, str]] = {}

    # Log starting point
    cwd = os.getcwd()
    log("debug", f"Starting translation loading from working directory: {cwd}")

    # Walk only from the project root – this covers everything recursively
    base_dir = "."

    translation_files: list[tuple[str, str]] = []
    directories_checked = 0
    translations_dirs_found = 0

    # Directories to skip completely
    SKIP_DIRS = {'.git', '__pycache__', 'node_modules', 'venv', 'env', '.venv', '.env',
                 '.pytest_cache', '.mypy_cache', '.idea', '.vscode', '.tox', 'dist', 'build'}

    if os.path.exists(base_dir):
        for root, dirs, files in os.walk(base_dir):
            directories_checked += 1

            # Modify dirs in-place to prevent walking into skipped directories
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

            # Check if current directory is named 'translations'
            if os.path.basename(root) == 'translations':
                translations_dirs_found += 1

                for file in files:
                    if file.endswith('.json'):
                        filepath = os.path.join(root, file)
                        rel_dir = os.path.relpath(root, os.getcwd())
                        translation_files.append((filepath, rel_dir))

    log("debug", f"Directory scan complete. Checked {directories_checked} directories")
    log("debug", f"Found {translations_dirs_found} directories named 'translations'")
    log("debug", f"Found {len(translation_files)} translation JSON files")

    if not translation_files:
        log("warning", "No translation files found in any 'translations' directories")
        return translations

    # Sort by path depth (deeper paths first) so root translations override plugin translations
    translation_files.sort(key=lambda x: x[1].count(os.sep), reverse=True)

    for filepath, rel_dir in translation_files:
        filename = os.path.basename(filepath)
        lang_code = os.path.splitext(filename)[0]

        # Skip if language is not in VALID_LANGUAGES
        if lang_code not in VALID_LANGUAGES:
            log("debug", f"Skipping {rel_dir}/{filename}: language '{lang_code}' is not in VALID_LANGUAGES")
            continue

        try:
            log("debug", f"Loading translation file: {filepath}")
            with open(filepath, "r", encoding="utf-8") as f:
                raw_data = json.load(f)

            # Flatten the JSON structure to support dot notation
            flat_data = flatten_dict(raw_data)

            log("debug", f"  Successfully parsed JSON with {len(raw_data)} top-level keys")
            log("debug", f"  Flattened to {len(flat_data)} translation keys")

            if lang_code not in translations:
                translations[lang_code] = {}

            # Warn on duplicates (keys already present from previously loaded files)
            duplicates = set(translations[lang_code].keys()) & set(flat_data.keys())
            if duplicates:
                log("warning", f"Duplicate translation keys in {lang_code} from {rel_dir}/{filename}: {sorted(duplicates)}")

            translations[lang_code].update(flat_data)
            log("debug", f"Loaded {len(flat_data)} translations for '{lang_code}' from {rel_dir}/{filename}")

        except json.JSONDecodeError as e:
            log("error", f"Invalid JSON in {filepath}: {e}")
        except Exception as e:
            log("error", f"Error loading {filepath}: {e}")
            import traceback
            log("debug", traceback.format_exc())

    total = sum(len(t) for t in translations.values())
    langs = list(translations.keys())
    log("info", f"Finished loading translations: {total} keys across {len(translations)} languages: {langs}")

    # Log sample keys for debugging
    for lang in langs:
        sample_keys = list(translations[lang].keys())[:10]
        log("debug", f"Sample keys for {lang}: {sample_keys}")

    return translations


def get_translation(key: str, lang: str, translations: Dict[str, Dict[str, str]]) -> str:
    """
    Get translation for a key in specified language.
    Supports dot notation (e.g., 'trainer_plugin_student_pad.my_learning_tools').
    Falls back to other languages if key not found.
    """
    # Primary lookup
    if lang in translations and key in translations[lang]:
        return translations[lang][key]

    # Fallback: search in any other loaded language
    for l, t in translations.items():
        if key in t:
            log("debug", f"Translation key '{key}' not in '{lang}', found in '{l}'")
            return t[key]

    # Missing key
    log("warning", f"Missing translation key: '{key}' (language: {lang})")
    return f"[{key}]"
