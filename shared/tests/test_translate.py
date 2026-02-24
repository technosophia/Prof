import os
import sys
import json
import tempfile
import pytest

from core.translate import load_all_translations

from st_shared.cached import _load_translations


from st_shared.cached import _, get_available_languages
@pytest.fixture(autouse=True)
def clear_translation_cache():
    """Clear the Streamlit cache before each test to prevent leakage between tests"""
    _load_translations.clear()
    yield


@pytest.fixture(scope="function")
def project_structure():
    """Create a temporary project structure mimicking the real app layout"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        old_cwd = os.getcwd()
        os.chdir(tmp_dir)

        try:
            # Create base directories
            os.makedirs("translations", exist_ok=True)
            os.makedirs(os.path.join("shared", "translations"), exist_ok=True)
            os.makedirs(os.path.join("modules", "rag", "translations"), exist_ok=True)
            os.makedirs(os.path.join("modules", "admin", "deep", "translations"), exist_ok=True)

            # Root translations
            with open("translations/en.json", "w", encoding="utf-8") as f:
                json.dump({
                    "root_key": "Root English",
                    "overlap": "Final root override",
                    "common_key": "Root common"
                }, f, indent=2)
            with open("translations/fr.json", "w", encoding="utf-8") as f:
                json.dump({
                    "root_key": "Root Français",
                    "only_fr": "Seulement en français"
                }, f, indent=2)

            # Shared translations
            with open(os.path.join("shared", "translations", "en.json"), "w", encoding="utf-8") as f:
                json.dump({
                    "shared_key": "Shared English",
                    "overlap": "Shared override"
                }, f, indent=2)
            with open(os.path.join("shared", "translations", "fr.json"), "w", encoding="utf-8") as f:
                json.dump({
                    "shared_key": "Shared Français"
                }, f, indent=2)

            # Module: rag
            with open(os.path.join("modules", "rag", "translations", "en.json"), "w", encoding="utf-8") as f:
                json.dump({
                    "rag_key": "RAG English",
                    "overlap": "RAG override"
                }, f, indent=2)
            # No fr.json for rag → tests fallback

            # Module: admin (deeply nested)
            with open(os.path.join("modules", "admin", "deep", "translations", "en.json"), "w", encoding="utf-8") as f:
                json.dump({
                    "admin_key": "Admin English (deep)"
                }, f, indent=2)
            with open(os.path.join("modules", "admin", "deep", "translations", "fr.json"), "w", encoding="utf-8") as f:
                json.dump({
                    "admin_key": "Admin Français (deep)"
                }, f, indent=2)

            yield tmp_dir
        finally:
            os.chdir(old_cwd)


def test_load_all_translations_basic(project_structure):
    translations = load_all_translations()

    # Languages present
    assert set(translations.keys()) == {"en", "fr"}

    # Specific keys from different locations
    assert translations["en"]["root_key"] == "Root English"
    assert translations["en"]["shared_key"] == "Shared English"
    assert translations["en"]["rag_key"] == "RAG English"
    assert translations["en"]["admin_key"] == "Admin English (deep)"

    assert translations["fr"]["root_key"] == "Root Français"
    assert translations["fr"]["shared_key"] == "Shared Français"
    assert translations["fr"]["admin_key"] == "Admin Français (deep)"
    assert translations["fr"]["only_fr"] == "Seulement en français"

    # No rag_key in French (fallback test in next function)
    assert "rag_key" not in translations["fr"]


def test_translation_function(project_structure):
    # Primary language match
    assert _("root_key", lang="en") == "Root English"
    assert _("root_key", lang="fr") == "Root Français"

    # Fallback to other languages
    assert _("rag_key", lang="fr") == "RAG English"  # only exists in en
    assert _("only_fr", lang="en") == "Seulement en français"  # only exists in fr

    # Deep module key
    assert _("admin_key", lang="fr") == "Admin Français (deep)"

    # Missing key
    assert _("non_existent_key", lang="en") == "[non_existent_key]"


def test_key_overrides(project_structure):
    """
    Test that later-loaded files override earlier ones.
    Also indirectly tests duplicate key warnings (they are logged to console
    but not captured by caplog because the logger likely uses direct print).
    """
    translations = load_all_translations()

    # Final value comes from the last-loaded directory (root overrides all previous)
    assert translations["en"]["overlap"] == "Final root override"


def test_available_languages(project_structure):
    available = get_available_languages()
    assert available == ["en", "fr"]  # sorted


def test_no_translation_directories():
    with tempfile.TemporaryDirectory() as tmp_dir:
        old_cwd = os.getcwd()
        os.chdir(tmp_dir)
        try:
            translations = load_all_translations()
            assert translations == {}

            available = get_available_languages()
            assert available == []

            assert _("any_key", lang="en") == "[any_key]"
        finally:
            os.chdir(old_cwd)
