import os
import sys
import json
import tempfile
import shutil

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.translate import Translator, get_translator, init_translations

def test_direct_translation_addition():
    """Test adding translations directly via dictionary"""
    translator = Translator()

    translator.add_module_translations("test_module", {
        "en": {
            "test_key": "Test value in English",
            "another_key": "Another test value"
        },
        "fr": {
            "test_key": "Valeur de test en Français",
            "another_key": "Une autre valeur de test"
        }
    })

    translator.set_language("en")
    assert translator("test_key") == "Test value in English"
    assert translator("another_key") == "Another test value"

    translator.set_language("fr")
    assert translator("test_key") == "Valeur de test en Français"
    assert translator("another_key") == "Une autre valeur de test"

def test_file_based_translation():
    """Test loading translations from JSON files"""
    temp_dir = tempfile.mkdtemp()

    try:
        en_file = os.path.join(temp_dir, "en.json")
        fr_file = os.path.join(temp_dir, "fr.json")

        en_data = {"file_key": "Value from file in English"}
        fr_data = {"file_key": "Valeur du fichier en Français"}

        with open(en_file, "w", encoding="utf-8") as f:
            json.dump(en_data, f, ensure_ascii=False, indent=2)

        with open(fr_file, "w", encoding="utf-8") as f:
            json.dump(fr_data, f, ensure_ascii=False, indent=2)

        translator = Translator()

        assert translator.load_language_file("en", en_file)
        assert translator.load_language_file("fr", fr_file)

        translator.set_language("en")
        assert translator("file_key") == "Value from file in English"

        translator.set_language("fr")
        assert translator("file_key") == "Valeur du fichier en Français"

    finally:
        shutil.rmtree(temp_dir)

def test_load_app_translations():
    """Test the new one-line app translation loading"""
    temp_dir = tempfile.mkdtemp()

    try:
        # Create translation files
        en_file = os.path.join(temp_dir, "en.json")
        fr_file = os.path.join(temp_dir, "fr.json")

        en_data = {
            "app_title": "My Application",
            "app_description": "This is my app"
        }

        fr_data = {
            "app_title": "Mon Application",
            "app_description": "Ceci est mon application"
        }

        with open(en_file, "w", encoding="utf-8") as f:
            json.dump(en_data, f, ensure_ascii=False, indent=2)

        with open(fr_file, "w", encoding="utf-8") as f:
            json.dump(fr_data, f, ensure_ascii=False, indent=2)

        # Test load_app_translations method
        translator = Translator()
        translator.load_app_translations(temp_dir)

        translator.set_language("en")
        assert translator("app_title") == "My Application"
        assert translator("app_description") == "This is my app"

        translator.set_language("fr")
        assert translator("app_title") == "Mon Application"
        assert translator("app_description") == "Ceci est mon application"

    finally:
        shutil.rmtree(temp_dir)

def test_init_translations_one_line():
    """Test the ultimate one-line initialization"""
    temp_dir = tempfile.mkdtemp()

    try:
        # Create translation files
        en_file = os.path.join(temp_dir, "en.json")
        fr_file = os.path.join(temp_dir, "fr.json")

        en_data = {"test_init": "Initialization test in English"}
        fr_data = {"test_init": "Test d'initialisation en Français"}

        with open(en_file, "w", encoding="utf-8") as f:
            json.dump(en_data, f, ensure_ascii=False, indent=2)

        with open(fr_file, "w", encoding="utf-8") as f:
            json.dump(fr_data, f, ensure_ascii=False, indent=2)

        # Clear any existing instance
        import shared.translate
        shared.translate._translator_instance = None

        # One-line initialization
        translator = init_translations("fr", temp_dir)

        # Should be in French by default
        assert translator.get_current_language() == "fr"
        assert translator("test_init") == "Test d'initialisation en Français"

        # Switch to English
        translator.set_language("en")
        assert translator("test_init") == "Initialization test in English"

    finally:
        shutil.rmtree(temp_dir)

def test_singleton_pattern():
    """Test that get_translator returns the same instance"""
    import shared.translate
    shared.translate._translator_instance = None

    translator1 = get_translator()
    translator2 = get_translator()

    assert translator1 is translator2

    translator1.add_module_translations("singleton_test", {
        "en": {"test": "Singleton test"}
    })

    translator2.set_language("en")
    assert translator2("test") == "Singleton test"

def test_language_fallback():
    """Test fallback behavior when translation key is missing"""
    translator = Translator()

    translator.add_module_translations("fallback_test", {
        "en": {
            "common_key": "Common in English",
            "english_only": "Only in English"
        },
        "fr": {
            "common_key": "Commun en Français"
        }
    })

    translator.set_language("en")
    assert translator("common_key") == "Common in English"

    translator.set_language("fr")
    assert translator("common_key") == "Commun en Français"
    assert translator("english_only") == "Only in English"
    assert translator("non_existent_key") == "[non_existent_key]"

def test_multiple_modules():
    """Test that multiple modules can coexist without conflicts"""
    translator = Translator()

    translator.add_module_translations("auth", {
        "en": {"login": "Login", "logout": "Logout"},
        "fr": {"login": "Connexion", "logout": "Déconnexion"}
    })

    translator.add_module_translations("dashboard", {
        "en": {"welcome": "Welcome to Dashboard", "stats": "Statistics"},
        "fr": {"welcome": "Bienvenue au Tableau de Bord", "stats": "Statistiques"}
    })

    translator.set_language("en")
    assert translator("login") == "Login"
    assert translator("welcome") == "Welcome to Dashboard"

    translator.set_language("fr")
    assert translator("login") == "Connexion"
    assert translator("welcome") == "Bienvenue au Tableau de Bord"

def test_combined_approach():
    """Test combining multiple translation loading methods"""
    translator = Translator()

    # Method 1: Direct addition
    translator.add_module_translations("module1", {
        "en": {"key1": "Value 1"},
        "fr": {"key1": "Valeur 1"}
    })

    # Method 2: Load from files
    temp_dir = tempfile.mkdtemp()

    try:
        en_file = os.path.join(temp_dir, "en.json")
        fr_file = os.path.join(temp_dir, "fr.json")

        en_data = {"key2": "Value 2 from file"}
        fr_data = {"key2": "Valeur 2 du fichier"}

        with open(en_file, "w", encoding="utf-8") as f:
            json.dump(en_data, f, ensure_ascii=False, indent=2)

        with open(fr_file, "w", encoding="utf-8") as f:
            json.dump(fr_data, f, ensure_ascii=False, indent=2)

        translator.load_app_translations(temp_dir)

        # Test all translations work together
        translator.set_language("en")
        assert translator("key1") == "Value 1"
        assert translator("key2") == "Value 2 from file"

        translator.set_language("fr")
        assert translator("key1") == "Valeur 1"
        assert translator("key2") == "Valeur 2 du fichier"

    finally:
        shutil.rmtree(temp_dir)
