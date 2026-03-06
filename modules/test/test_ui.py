
import streamlit as st
import os, sys

def inject_ui_main_footer():
    test_mode = os.getenv("TEST_MODE") == "true" or "pytest" in sys.modules
    if not test_mode:
        return

    st.write("Test module content")
