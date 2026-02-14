"""
LLM Monitor User Interface
Provides sidebar switch and footer display for LLM monitoring with rate limit tracking.
"""
import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
from shared.common import log
from shared.common import _
from typing import Dict, List, Any, Optional, Callable, Tuple
from modules.llm_monitor.llm_monitor import get_llm_monitor
from modules.llm_monitor.display_utils import render_llm_call_details, render_rate_limit_summary


def inject_ui_initialize():
    """Initialize the LLM monitor UI module."""
    # Initialize session state variables
    if "show_llm_monitor" not in st.session_state:
        st.session_state.show_llm_monitor = False

    if "last_llm_call_refresh" not in st.session_state:
        st.session_state.last_llm_call_refresh = None

    if "show_rate_limits" not in st.session_state:
        st.session_state.show_rate_limits = True

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

        # LLM Monitor toggle
        col1, col2 = st.columns([3, 1])
        with col1:
            st.write("**LLM Monitor**")
        with col2:
            current_state = st.session_state.get("show_llm_monitor", False)
            new_state = st.toggle(label="LM", value=current_state, key="llm_monitor_toggle")
            if new_state != current_state:
                st.session_state.show_llm_monitor = new_state
                st.rerun()

        # Quick cost/usage summary (always show mini version)
        user_id = st.session_state.current_user['id']
        user_stats = monitor.get_user_stats(user_id)

        if user_stats["overall"]["total_calls"] > 0:
            # Create a mini summary
            with st.container():
                st.caption("📊 Your Usage")

                col1, col2 = st.columns(2)
                with col1:
                    st.caption(f"Calls: {user_stats['overall']['total_calls']}")

                with col2:
                    total_tokens = user_stats['overall']['total_input_tokens'] + user_stats['overall']['total_output_tokens']
                    st.caption(f"Tokens: {total_tokens:,}")

                # Show cost if any
                if user_stats['overall']['total_cost'] > 0:
                    st.caption(f"💰 Cost: ${user_stats['overall']['total_cost']:.4f}")
                else:
                    st.caption("💰 Cost: Free")

        # Rate limit summary (show for providers with rate limits configured)
        if monitor.rate_limit_tracking.get("enabled", True):
            # Get all providers that have any rate limits configured
            providers_with_limits = []
            for provider, config in monitor.llm_configs.items():
                has_limits = any(config.get(k, 0) > 0 for k in ["rpm", "rpd", "tpm", "tpd"])
                if has_limits:
                    providers_with_limits.append(provider)

            if providers_with_limits:
                with st.expander("⏱️ Rate Limits", expanded=False):
                    for provider in providers_with_limits:
                        st.write(f"**{provider.title()}**")

                        # Get rate limit usage for this provider
                        usage = monitor.get_rate_limit_usage(provider, provider)

                        if usage and usage.get("limits"):
                            # Compact display
                            limits = usage.get("limits", {})

                            if limits.get("rpm", 0) > 0:
                                hourly_requests = usage.get("hourly", {}).get("requests", 0)
                                hourly_limit = limits.get("rpm", 30)
                                pct = (hourly_requests / hourly_limit) * 100

                                # Color-coded progress bar
                                if pct < 70:
                                    bar_color = "green"
                                elif pct < 90:
                                    bar_color = "orange"
                                else:
                                    bar_color = "red"

                                st.caption(f"**{provider}**")
                                st.progress(
                                    pct / 100,
                                    text=f"Requests: {hourly_requests}/{hourly_limit} ({pct:.0f}%)"
                                )

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
            col1, col2, col3, col4 = st.columns(4)

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

            with col4:
                # Daily cost (today)
                today = datetime.utcnow().strftime("%Y-%m-%d")
                daily_calls = [c for c in monitor.get_llm_calls(user_id=user_id, limit=1000)
                             if c['timestamp'].startswith(today)]
                st.metric("Today's Calls", len(daily_calls))

        st.divider()

        # Two tabs: Last Call and Rate Limits
        tab1, tab2 = st.tabs(["📝 Last Call", "⏱️ Rate Limits"])

        with tab1:
            # Show last call details if available
            if last_call:
                render_llm_call_details(last_call)
            else:
                st.info("No LLM calls yet")

        with tab2:
            # Show rate limits for providers with limits configured
            if monitor.rate_limit_tracking.get("enabled", True):
                # Get all providers that have any rate limits configured
                providers_with_limits = []
                for provider, config in monitor.llm_configs.items():
                    has_limits = any(config.get(k, 0) > 0 for k in ["rpm", "rpd", "tpm", "tpd"])
                    if has_limits:
                        providers_with_limits.append(provider)

                if providers_with_limits:
                    for provider in providers_with_limits:
                        with st.expander(f"📊 {provider.title()} Rate Limits", expanded=True):
                            # Use the updated render_rate_limit_summary function
                            # Note: render_rate_limit_summary should also be updated to use the new structure
                            from modules.llm_monitor.display_utils import render_rate_limit_summary
                            render_rate_limit_summary(monitor, provider)
                else:
                    st.info("No providers with rate limits configured")
            else:
                st.info("Rate limit tracking is disabled")

        # Monthly cost summary (for paid providers)
        paid_providers = [p for p, config in monitor.llm_configs.items()
                         if config.get("input_cost_per_million_tokens", 0) > 0 or
                            config.get("output_cost_per_million_tokens", 0) > 0]

        if paid_providers:
            st.divider()
            st.subheader("💰 Monthly Cost Summary")

            monthly_total = monitor.get_monthly_cost()
            if monthly_total > 0:
                st.metric("Current Month Total", f"${monthly_total:.4f}")

                # Daily costs for the month
                daily_costs = monitor.get_daily_costs(days=30)
                if daily_costs:
                    df = pd.DataFrame(daily_costs)
                    df = df[df['total_cost'] > 0]  # Only show paid calls
                    if not df.empty:
                        df['date'] = pd.to_datetime(df['date'])
                        df = df.sort_values('date')

                        fig = px.line(
                            df,
                            x='date',
                            y='total_cost',
                            color='provider',
                            title='Daily Costs (Last 30 Days)'
                        )
                        st.plotly_chart(fig, width='stretch')
            else:
                st.info("No paid LLM usage this month")

        # Refresh button
        col1, col2 = st.columns([1, 5])
        with col1:
            if st.button("🔄 Refresh", key="refresh_llm_monitor"):
                st.rerun()

        with col2:
            # Hide button
            if st.button("❌ Hide Monitor", key="hide_llm_monitor"):
                st.session_state.show_llm_monitor = False
                st.rerun()

    return None


def inject_ui_metrics():
    """Inject metrics into the sidebar or dashboard."""
    if not st.session_state.get('current_user'):
        return None

    monitor = get_llm_monitor()
    if not monitor.enabled:
        return None

    # Get daily and monthly costs for admin users
    if st.session_state.current_user.get('role') == 'admin':
        daily_total = sum(c['total_cost'] for c in monitor.get_daily_costs(days=1))
        monthly_total = monitor.get_monthly_cost()

        return {
            "daily_cost": daily_total,
            "monthly_cost": monthly_total,
            "rate_limits_enabled": monitor.rate_limit_tracking.get("enabled", True)
        }

    return None


def initialize():
    """Initialize the LLM monitor UI module."""
    inject_ui_initialize()
    log("debug", "LLM monitor UI module registered")
    return True

initialize()
