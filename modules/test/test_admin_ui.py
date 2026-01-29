import streamlit as st
import asyncio
from shared.logging import log
from shared.translate import _
from shared.llm import llm_generate, get_current_llm_info
from shared.users import user_manager

def show_test_admin_content():
    """Display the Debug Admin content."""
    st.header("Test")
    st.write("Test module active")

def inject_ui_admin_tab():
    """Register the Debug admin tab using the new injection mechanism.
    Returns: (tab_name, render_function) tuple."""
    return ("Test", show_test_admin_content)
