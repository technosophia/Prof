"""
Debug Admin UI Module
====================

Provides a simple debug/testing interface in the admin panel for:
- Text input and display
- LLM testing with current LLM
- Display current user info

This module adds a "Debug" tab to the admin interface.
"""

import streamlit as st
import asyncio
from shared.logging import log
from shared.translate import _
from shared.llm import llm_generate, get_current_llm_info
from shared.users import user_manager

def show_debug_admin_content():
    """Display the Debug Admin content."""
    st.header("🔧 Debug and Testing")
    st.write("Debug moduel is active")

    # Section 1: Current User Info
    st.subheader("👤 Current User")
    if st.session_state.get('current_user'):
        user = st.session_state.current_user
        st.write(f"**Name:** {user.get('name', 'N/A')}")
        st.write(f"**ID:** {user.get('id', 'N/A')}")
        st.write(f"**Email:** {user.get('email', 'N/A')}")
        st.write(f"**Active:** {'Yes' if user.get('is_active', True) else 'No'}")

        if user.get('profile'):
            st.write("**Profile:**")
            profile = user['profile']
            st.write(f"  - Role: {profile.get('role', 'N/A')}")
            st.write(f"  - Rights: {', '.join(profile.get('rights', []))}")
    else:
        st.warning("No user currently logged in")

    st.divider()

    # Section 2: Text Input Test
    st.subheader("📝 Text Input Test")

    # Initialize session state for debug text
    if 'debug_test_text' not in st.session_state:
        st.session_state.debug_test_text = ""

    if 'debug_test_result' not in st.session_state:
        st.session_state.debug_test_result = ""

    if 'debug_llm_response' not in st.session_state:
        st.session_state.debug_llm_response = ""

    if 'debug_llm_loading' not in st.session_state:
        st.session_state.debug_llm_loading = False

    # Text input
    test_text = st.text_area(
        "Enter some text for testing:",
        value=st.session_state.debug_test_text,
        height=100,
        key="debug_text_input",
        help="Enter any text you want to test with"
    )

    # Update session state
    st.session_state.debug_test_text = test_text

    col1, col2 = st.columns(2)

    with col1:
        # Button to display text
        if st.button("📤 Display Text", use_container_width=True):
            if test_text.strip():
                st.session_state.debug_test_result = test_text
                st.success("Text captured! Check the result section below.")
                log("debug", f"Debug text captured: {test_text[:50]}...")
            else:
                st.warning("Please enter some text first")

    with col2:
        # Button to clear text
        if st.button("🗑️ Clear Text", use_container_width=True, type="secondary"):
            st.session_state.debug_test_text = ""
            st.session_state.debug_test_result = ""
            st.session_state.debug_llm_response = ""
            st.rerun()

    # Display result section
    if st.session_state.debug_test_result:
        st.divider()
        st.subheader("📋 Text Result")
        st.info(st.session_state.debug_test_result)

        # Additional info
        st.caption(f"Character count: {len(st.session_state.debug_test_result)}")
        st.caption(f"Word count: {len(st.session_state.debug_test_result.split())}")

    st.divider()

    # Section 3: LLM Test
    st.subheader("🤖 LLM Test")

    # Get current LLM info
    current_llm_info = get_current_llm_info()

    if current_llm_info:
        st.write(f"**Current LLM:** {current_llm_info.get('name', 'Unknown')}")
        st.write(f"**Type:** {current_llm_info.get('type', 'Unknown')}")
        st.write(f"**Model:** {current_llm_info.get('model', 'Unknown')}")
        st.write(f"**Status:** {'🟢 Available' if current_llm_info.get('available') else '🔴 Unavailable'}")

        # LLM question input
        llm_question = st.text_input(
            "Question for LLM:",
            value="What is 2+2?",
            key="debug_llm_question",
            help="Enter a question to ask the current LLM"
        )

        col3, col4 = st.columns(2)

        with col3:
            # Button to ask LLM
            if st.button("💭 Ask LLM", use_container_width=True, type="primary"):
                if llm_question.strip():
                    st.session_state.debug_llm_loading = True
                    st.rerun()
                else:
                    st.warning("Please enter a question")

        with col4:
            # Button to clear LLM response
            if st.button("🗑️ Clear Response", use_container_width=True, type="secondary"):
                st.session_state.debug_llm_response = ""
                st.rerun()

        # Handle LLM query
        if st.session_state.debug_llm_loading:
            try:
                # Create a placeholder for streaming
                response_placeholder = st.empty()
                stream_buffer = ""

                # Define streaming callback
                def stream_callback(chunk):
                    nonlocal stream_buffer
                    stream_buffer += chunk
                    response_placeholder.markdown(stream_buffer)

                # Call the LLM
                with st.spinner(f"Asking {current_llm_info.get('name')}..."):
                    response = asyncio.run(
                        llm_generate(
                            llm_question.strip(),
                            stream_callback
                        )
                    )

                st.session_state.debug_llm_response = response
                st.session_state.debug_llm_loading = False
                log("info", f"Debug LLM query completed: {llm_question[:50]}...")
                st.rerun()

            except Exception as e:
                error_msg = f"Error calling LLM: {str(e)}"
                st.error(error_msg)
                log("error", error_msg, exc_info=True)
                st.session_state.debug_llm_loading = False
                st.session_state.debug_llm_response = f"Error: {str(e)}"
                st.rerun()

        # Display LLM response
        if st.session_state.debug_llm_response:
            st.divider()
            st.subheader("🤖 LLM Response")

            # Check if it's an error message
            if st.session_state.debug_llm_response.startswith("Error:"):
                st.error(st.session_state.debug_llm_response)
            else:
                st.info(st.session_state.debug_llm_response)

            # Response info
            st.caption(f"Response length: {len(st.session_state.debug_llm_response)} characters")

            # Copy button
            if st.button("📋 Copy Response", key="copy_debug_response"):
                st.write("Response copied to clipboard! (In a real app, you'd use clipboard API)")
    else:
        st.warning("No LLM available. Please configure an LLM in the settings.")

    st.divider()

    # Section 4: Quick Tests
    st.subheader("⚡ Quick Tests")

    col5, col6, col7 = st.columns(3)

    with col5:
        if st.button("Test User Count", use_container_width=True):
            try:
                user_count = user_manager.get_user_count()
                st.session_state.debug_test_result = f"Total users in system: {user_count}"
                st.rerun()
            except Exception as e:
                st.error(f"Error: {str(e)}")

    with col6:
        if st.button("Test Logging", use_container_width=True):
            log("info", "Test log message from debug admin panel")
            st.session_state.debug_test_result = "Test log message sent. Check logs."
            st.rerun()

    with col7:
        if st.button("Session Info", use_container_width=True):
            session_keys = list(st.session_state.keys())
            session_info = f"Session has {len(session_keys)} keys:\n"
            for key in sorted(session_keys):
                if not key.startswith('_'):
                    value = st.session_state.get(key)
                    value_type = type(value).__name__
                    session_info += f"- {key}: {value_type}\n"

            st.session_state.debug_test_result = session_info
            st.rerun()

    st.divider()

    # Section 5: Reset All
    st.subheader("🔄 Reset")

    if st.button("Reset All Debug Data", type="secondary", use_container_width=True):
        st.session_state.debug_test_text = ""
        st.session_state.debug_test_result = ""
        st.session_state.debug_llm_response = ""
        st.session_state.debug_llm_loading = False
        st.success("All debug data cleared!")
        st.rerun()

def inject_ui_admin_tab():
    """Register the Debug admin tab using the new injection mechanism.
    Returns: (tab_name, render_function) tuple."""
    return ("Debug", show_debug_admin_content)


def inject_ui_initialize():
    """Initialize the debug admin UI module."""
    # Initialize session state variables
    if "debug_test_text" not in st.session_state:
        st.session_state.debug_test_text = ""
    if "debug_test_result" not in st.session_state:
        st.session_state.debug_test_result = ""
    if "debug_llm_response" not in st.session_state:
        st.session_state.debug_llm_response = ""
    if "debug_llm_loading" not in st.session_state:
        st.session_state.debug_llm_loading = False

    log("debug", "Debug admin UI initialized")
