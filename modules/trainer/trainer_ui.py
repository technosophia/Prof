"""Trainer UI injection points."""

import streamlit as st

from shared.common import log
from modules.trainer import initialize as initialize_trainer


def inject_ui_initialize():
    """Ensure trainer module core initialization runs once app UI initializes."""
    try:
        return initialize_trainer()
    except Exception as e:
        log("error", f"Failed to initialize trainer module from trainer_ui: {e}", exc_info=True)


def inject_ui_main_footer():
    """Render trainer module footer placeholder."""
    st.write("Trainer module content")
