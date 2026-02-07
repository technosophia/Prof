"""Debug UI Module

[agent]
Debug module that displays system information and debugging tools.
This module provides the debug section that was previously in app.py.
"""

import streamlit as st
import os
from shared.common import _, log, get_config, get_user_manager, get_conversation_manager
from shared.llm import get_available_llms, get_current_llm_info
from shared.module_handler import get_active_modules, module_handler
from shared.ui_registry import ui_registry

def inject_ui_main_footer():
    """Render debug information in the main footer."""
    log("debug", "debug_render_main_footer called")
    if not st.session_state.get("show_debug", False):
        return None

    with st.expander("🔧 " + _("debug_info")):
        config = get_config()
        current_llm_info = get_current_llm_info()
        available_llms_list = get_available_llms()

        st.write("**DEBUGER**")

        st.write(f"**Current language:** {st.session_state.get('current_language', 'en')}")
        st.write(f"**Log level from config:** {config.get('logging.level', 'INFO')}")
        st.write(f"**App name:** {config.get('app.name')}")
        st.write(f"**App version:** {config.get('app.version')}")

        # User info
        st.write("**User Info:**")
        if st.session_state.current_user:
            st.write(f"- Current User: {st.session_state.current_user['name']} ({st.session_state.current_user['id']})")
            st.write(f"- Email: {st.session_state.current_user['email']}")
            st.write(f"- Created: {st.session_state.current_user['created_at']}")
            st.write(f"- Active: {st.session_state.current_user['is_active']}")

            # Conversation info
            if st.session_state.current_conversation_id:
                st.write("**Current Conversation:**")
                st.write(f"- ID: {st.session_state.current_conversation_id}")
                st.write(f"- Message count: {len(st.session_state.conversation_messages)}")

                # Get conversation from DB for more info
                conv = get_conversation_manager().get_conversation(
                    st.session_state.current_conversation_id,
                    include_messages=False
                )
                if conv:
                    st.write(f"- Title: {conv.title}")
                    st.write(f"- Created: {conv.created_at}")
                    st.write(f"- Updated: {conv.updated_at}")
        else:
            st.write("- No user logged in")

        st.write(f"**Total Users:** {get_user_manager().get_user_count()}")

        # Current LLM info
        if current_llm_info:
            st.write("**Current LLM:**")
            st.write(f"- ID: {current_llm_info['id']}")
            st.write(f"- Name: {current_llm_info['name']}")
            st.write(f"- Type: {current_llm_info['type']}")
            st.write(f"- Model: {current_llm_info['model']}")
            st.write(f"- Available: {current_llm_info['available']}")
        else:
            st.write("- No LLM info")

        # All LLMs info
        st.write("**All LLMs:**")
        for llm_item in available_llms_list:
            status = "🟢" if llm_item["available"] else "🔴"
            st.write(f"- {status} {llm_item['name']} ({llm_item['type']}): {llm_item['description']}")

        # Environment info
        st.write("**Environment Info:**")
        st.write(f"- GEMINI_API_KEY present: {'Yes' if os.getenv('GEMINI_API_KEY') else 'No'}")
        st.write(f"- GROQ_API_KEY present: {'Yes' if os.getenv('GROQ_API_KEY') else 'No'}")
        st.write(f"- OLLAMA_BASE_URL: {os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')}")

        # Database info
        db_path = os.path.join("data", "app.db") if os.path.exists("data") else None
        st.write("**Database Info:**")
        st.write(f"- Database path: {db_path}")
        st.write(f"- Data directory exists: {os.path.exists('data')}")

        # Module info
        st.write("**Module Info:**")
        active_modules = get_active_modules()
        all_modules = module_handler.get_all_modules()
        st.write(f"- Active modules: {len(active_modules)}/{len(all_modules)}")
        st.write(f"- Total discovered: {len(all_modules)}")

        # UI Modules info
        st.write("**UI Modules Info:**")
        for module_name, module_info in ui_registry.modules.items():
            st.write(f"- {module_name}: {len(module_info['render_functions'])} render functions")

        # Test logging buttons
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
                log("error", "Error test message from Streamlit", exc_info=False)
                st.success("Error message logged")

        # Test error with traceback
        if st.button("Test Error with Traceback"):
            try:
                # Create a test error
                raise ValueError("This is a test error for traceback")
            except Exception as e:
                log("error", "Test error with traceback", exc_info=True)
                st.success("Error with traceback logged")

        # Toggle debug
        if st.button("Hide Debug"):
            st.session_state.show_debug = False
            st.rerun()

    return None

def inject_ui_sidebar():
    """Render debug toggle in sidebar."""
    log("debug", "debug_render_sidebar called")
    if st.session_state.get("current_page") == "chat":
        st.divider()
        col1, col2 = st.columns([3, 1])
        with col1:
            st.write("**Debug**")
        with col2:
            current_state = st.session_state.get("show_debug", False)
            new_state = st.toggle(label="DT", value=current_state, key="debug_toggle")
            if new_state != current_state:
                st.session_state.show_debug = new_state
                st.rerun()

    return None
