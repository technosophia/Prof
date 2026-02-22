"""Trainer UI injection points."""

import streamlit as st

from shared.common import log

from modules.trainer import initialize as initialize_trainer


def inject_ui_initialize():
    """Initialize trainer module driver registrations for UI runtime."""
    try:
        initialized = initialize_trainer()
        if initialized:
            log("info", "trainer_ui: trainer.initialize() executed")
        else:
            log("warning", "trainer_ui: trainer.initialize() returned False")
        return initialized
    except Exception as exc:
        log("error", f"trainer_ui: failed to initialize trainer module: {exc}", exc_info=True)
        return False


def inject_ui_main_footer():
    """Render trainer footer placeholder."""
    st.write("Trainer module content")
