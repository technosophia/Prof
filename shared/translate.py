import os
import json
from typing import Dict

from shared.logging import log


def load_all_translations() -> Dict[str, Dict[str, str]]:
    """
    Search the entire project for 'translations' directories and load all JSON files.
    Returns a dict: {lang_code: {key: translation, ...}, ...}
    Later directories override earlier ones on key conflict (with warning).
    Loading order is deterministic: modules → shared → root (root has highest priority).
    """
    translations: Dict[str, Dict[str, str]] = {}

    # Walk only from the project root – this covers everything recursively
    base_dir = "."

    translation_dirs: set[str] = set()

    if os.path.exists(base_dir):
        for root, dirs, _ in os.walk(base_dir):
            if "translations" in dirs:
                trans_path = os.path.join(root, "translations")
                abs_path = os.path.abspath(trans_path)
                if os.path.exists(abs_path):
                    translation_dirs.add(abs_path)

    if not translation_dirs:
        log("warning", "No translation directories found")
        return translations

    # Nice relative paths for logging
    rel_dirs = [os.path.relpath(p, os.getcwd()) for p in translation_dirs]
    log("info", f"Found translation directories: {sorted(rel_dirs)}")

    # Load in sorted order by relative path → modules first, shared, then root last
    # This ensures root translations have the highest priority (override everything)
    load_order = sorted(
        translation_dirs,
        key=lambda p: os.path.relpath(p, os.getcwd())
    )

    for abs_dir in load_order:
        rel_dir = os.path.relpath(abs_dir, os.getcwd())
        log("info", f"Loading translations from: {rel_dir}")

        if not os.path.exists(abs_dir):
            continue

        for filename in os.listdir(abs_dir):
            if filename.endswith(".json"):
                lang_code = os.path.splitext(filename)[0]
                filepath = os.path.join(abs_dir, filename)

                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data: Dict[str, str] = json.load(f)

                    if lang_code not in translations:
                        translations[lang_code] = {}

                    # Warn on duplicates (keys already present from previous directories)
                    duplicates = set(translations[lang_code].keys()) & set(data.keys())
                    if duplicates:
                        log("warning", f"Duplicate translation keys in {lang_code} from {rel_dir}/{filename}: {duplicates}")

                    translations[lang_code].update(data)
                    log("info", f"Loaded {len(data)} translations for '{lang_code}' from {rel_dir}/{filename}")

                except json.JSONDecodeError as e:
                    log("error", f"Invalid JSON in {filepath}: {e}")
                except Exception as e:
                    log("error", f"Error loading {filepath}: {e}")

    total = sum(len(t) for t in translations.values())
    log("info", f"Finished loading translations: {total} keys across {len(translations)} languages")
    return translations
