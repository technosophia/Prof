"""Common shared resources (Streamlit-aware)"""

import streamlit as st
from shared.logging import log
from shared.translate import load_all_translations


@st.cache_resource
def _load_translations() -> dict[str, dict[str, str]]:
    """Load all translations once and cache them globally."""
    return load_all_translations()


def get_available_languages() -> list[str]:
    """Return sorted list of available language codes."""
    translations = _load_translations()
    return sorted(translations.keys())


def _(key: str, lang: str | None = None) -> str:
    """
    Central translation function.
    Uses per-session current language from st.session_state.
    """
    if lang is None:
        # Ensure a language is always set in session state
        if "current_language" not in st.session_state:
            st.session_state.current_language = "en"
        lang = st.session_state.current_language

    translations = _load_translations()

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
