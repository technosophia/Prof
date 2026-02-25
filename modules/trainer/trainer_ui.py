"""Trainer UI injection points."""

import streamlit as st


from modules.trainer import initialize as initialize_trainer


from core.logging import log, set_log_module_level
def inject_ui_initialize():
    """Ensure trainer module core initialization runs once app UI initializes."""
    try:
        return initialize_trainer()
    except Exception as e:
        log("error", f"Failed to initialize trainer module from trainer_ui: {e}", exc_info=True)


def inject_ui_main_footer():
    """Render trainer module footer placeholder."""
    st.write("Trainer module content")
