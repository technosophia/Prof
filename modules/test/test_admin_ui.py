import streamlit as st
import asyncio

from shared.cached import get_config

from core.logging import log, set_module_level
from shared.cached import _
def show_test_admin_content():
    """Display the Debug Admin content."""
    st.header("Test")
    st.write("Test module active")

def inject_ui_admin_tab():
    """Register the Debug admin tab using the new injection mechanism.
    Returns: (tab_name, render_function) tuple."""
    return ("Test", show_test_admin_content)
