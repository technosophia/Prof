"""
LLM Monitor User Interface
Provides sidebar switch and footer display for LLM monitoring.
"""
import streamlit as st
from shared.common import log
from shared.common import _

from modules.llm_monitor.llm_monitor import get_llm_monitor
from modules.llm_monitor.display_utils import render_llm_call_details


def inject_ui_initialize():
    """Initialize the LLM monitor UI module."""
    # Initialize session state variables
    if "show_llm_monitor" not in st.session_state:
        st.session_state.show_llm_monitor = False

    if "last_llm_call_refresh" not in st.session_state:
        st.session_state.last_llm_call_refresh = None

    log("debug", "LLM monitor UI initialized")
    return True


def inject_ui_sidebar():
    """Render LLM monitor toggle in sidebar."""
    # Only show if user is logged in
    if not st.session_state.get('current_user'):
        return None

    monitor = get_llm_monitor()
    if not monitor.enabled:
        return None

    # Only show on chat page
    if st.session_state.get("current_page") == "chat":
        st.divider()
        col1, col2 = st.columns([3, 1])
        with col1:
            st.write("**LLM Monitor**")
        with col2:
            current_state = st.session_state.get("show_llm_monitor", False)
            new_state = st.toggle(label="LM", value=current_state, key="llm_monitor_toggle")
            if new_state != current_state:
                st.session_state.show_llm_monitor = new_state
                st.rerun()

    return None


def inject_ui_main_footer():
    """Render LLM monitor information in the main footer."""
    # Only show if user is logged in and monitor is enabled
    if not st.session_state.get('current_user'):
        return None

    monitor = get_llm_monitor()
    if not monitor.enabled:
        return None

    # Only show if toggle is ON
    if not st.session_state.get("show_llm_monitor", False):
        return None

    # Get current user
    user_id = st.session_state.current_user['id']

    # Get user stats
    user_stats = monitor.get_user_stats(user_id)

    # Get last LLM call for this user
    last_call = monitor.get_last_user_call(user_id)

    # Display expandable section
    with st.expander("🤖 LLM Monitor", expanded=False):
        # Quick stats
        if user_stats["overall"]["total_calls"] > 0:
            col1, col2, col3 = st.columns(3)

            with col1:
                st.metric("Your Calls", user_stats["overall"]["total_calls"])

            with col2:
                total_tokens = user_stats["overall"]["total_input_tokens"] + user_stats["overall"]["total_output_tokens"]
                st.metric("Your Tokens", f"{total_tokens:,}")

            with col3:
                if user_stats["overall"]["total_cost"] > 0:
                    st.metric("Your Cost", f"${user_stats['overall']['total_cost']:.4f}")
                else:
                    st.metric("Your Cost", "Free")

        # Show last call details if available
        if last_call:
            st.divider()
            st.subheader("📝 Last LLM Call")

            # Basic info in a compact format
            col1, col2, col3 = st.columns(3)

            with col1:
                st.write(f"**Model:** {last_call['model']}")
                st.write(f"**Type:** {last_call['llm_type']}")

            with col2:
                st.write(f"**Tokens:** {last_call['total_tokens'] or 'N/A'}")
                st.write(f"**Cost:** ${last_call['total_cost']:.6f}")

            with col3:
                status = "✅" if last_call['success'] else "❌"
                st.write(f"**Status:** {status}")
                if last_call['duration_ms']:
                    st.write(f"**Time:** {last_call['duration_ms']}ms")

            # Show detailed view in an expandable section
            with st.expander("View Details", expanded=False):
                render_llm_call_details(last_call)

        # Refresh button
        if st.button("🔄 Refresh", key="refresh_llm_monitor"):
            st.rerun()

        # Hide button
        if st.button("❌ Hide Monitor", key="hide_llm_monitor"):
            st.session_state.show_llm_monitor = False
            st.rerun()

    return None
