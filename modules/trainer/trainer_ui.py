"""Trainer UI injection points."""

import streamlit as st


def inject_ui_initialize():
    """Streamlit session state setup only."""
    if "trainer_ui_ready" not in st.session_state:
        st.session_state.trainer_ui_ready = True
    return True


def inject_ui_main_footer():
    """Render trainer module footer placeholder."""
    st.write("Trainer module content")
