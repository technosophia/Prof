
import streamlit as st
import os
from shared.translate import _
from shared.logging import log
from shared.config import get_config
from shared.database import db_manager
from shared.llm import get_available_llms, get_current_llm_info
from shared.users import user_manager
from shared.conversation import conversation_manager
from shared.module_handler import get_active_modules, module_handler
from shared.ui_registry import ui_registry

def inject_ui_main_footer():
    st.write("Test module active")
