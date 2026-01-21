import streamlit as st
import os
import sys

# Add shared directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), "shared"))

# Import everything needed
from shared.translate import init_translations_streamlit, _streamlit as _
from shared.config import init_config, inject_module_config
from shared.logging import log, configure_logging_from_dict  # Simple log function + config helper

# Initialize configuration (one line)
config = init_config("config.json")

# Configure logging from config (one line)
configure_logging_from_dict(config.get("logging", {}))

# Log app startup using the simple log() function
log("info", "Starting multilingual Streamlit application")
log("debug", f"Configuration loaded: {config.get('app.name')} v{config.get('app.version')}")

# Initialize translator with Streamlit session support
translator = init_translations_streamlit("en", "translations")
log("debug", f"Translator initialized with {len(translator.translations)} languages")

# Page configuration
st.set_page_config(
    page_title="Multilingual App",
    page_icon="🌍",
    layout="centered"
)

def main():
    # Log main function entry
    log("debug", "Entering main function")

    # Sidebar for language selection
    with st.sidebar:
        st.title("🌍 " + _("language_select"))

        # Show available languages
        available_langs = list(translator.translations.keys())

        # Log available languages
        log("debug", f"Available languages: {available_langs}")

        # Language selector
        lang_option = st.selectbox(
            _("language_select"),
            options=available_langs,
            format_func=lambda x: "English" if x == "en" else "Français",
            index=0 if st.session_state.current_language == "en" else 1,
            key="language_selector"
        )

        # Check if language changed
        if lang_option != st.session_state.current_language:
            old_lang = st.session_state.current_language
            st.session_state.current_language = lang_option
            translator.set_language(lang_option)
            log("info", f"Language changed from '{old_lang}' to '{lang_option}'")
            st.rerun()

        st.divider()
        st.caption(_("current_language"))



    # Main content
    st.title(_("hello_world"))
    st.write(_("description"))

    # Log that we're displaying main content
    log("debug", "Displaying main content")

    # Example button with logging
    if st.button(_("button_text"), type="primary"):
        log("info", "Main button clicked")
        st.success(_("button_clicked"))

    # Log configuration information
    translation_count = sum(len(t) for t in translator.translations.values())
    log("debug", f"Translation keys loaded: {translation_count}")

    # Debug section in sidebar
    with st.expander("Debug Info"):
        st.write(f"**Current language:** {translator.get_current_language()}")
        st.write(f"**Available languages:** {', '.join(available_langs)}")
        st.write(f"**Log level from config:** {config.get('logging.level', 'INFO')}")
        st.write(f"**App name:** {config.get('app.name')}")
        st.write(f"**App version:** {config.get('app.version')}")

        # Test logging buttons - using only the simple log() function
        st.subheader("Test Logging")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            if st.button("Debug", key="debug_btn"):
                log("debug", "Debug test message from Streamlit")
                st.success("Debug message logged")
        with col2:
            if st.button("Info", key="info_btn"):
                log("info", "Info test message from Streamlit")
                st.success("Info message logged")
        with col3:
            if st.button("Warning", key="warning_btn"):
                log("warning", "Warning test message from Streamlit")
                st.success("Warning message logged")
        with col4:
            if st.button("Error", key="error_btn"):
                log("error", "Error test message from Streamlit")
                st.success("Error message logged")

if __name__ == "__main__":
    main()
