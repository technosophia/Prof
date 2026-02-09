"""
LLM Monitor Admin Interface
Provides comprehensive admin panel for monitoring LLM usage across all users.
"""
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

from shared.common import log
from shared.common import get_user_manager
from shared.common import get_llm_manager

from modules.llm_monitor.llm_monitor import get_llm_monitor
from modules.llm_monitor.display_utils import (
    render_llm_calls_table,
    render_user_stats,
    render_system_overview,
    render_llm_call_details
)
from modules.llm_monitor.models import LLMCallTable, UserLLMStatsTable


def show_llm_monitor_admin_content():
    """Main function to display the LLM Monitor Admin with tabs."""
    st.header("🤖 LLM Usage Monitor")

    monitor = get_llm_monitor()

    if not monitor.enabled:
        st.warning("LLM monitoring is disabled. Enable it in the configuration.")
        return

    # Create tabs
    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 Overview",
        "👤 User Statistics",
        "📝 Call Logs",
        "⚙️ Configuration"
    ])

    with tab1:
        show_overview_tab(monitor)

    with tab2:
        show_user_stats_tab(monitor)

    with tab3:
        show_call_logs_tab(monitor)

    with tab4:
        show_configuration_tab(monitor)


def show_overview_tab(monitor):
    """Render the overview tab."""
    st.subheader("System-wide LLM Usage")
    render_system_overview(monitor)


def show_user_stats_tab(monitor):
    """Render the user statistics tab."""
    st.subheader("User-level Statistics")

    # Get all users
    try:
        user_manager = get_user_manager()
        all_users = user_manager.get_all_users()

        if not all_users:
            st.info("No users found.")
            return

        # Create two columns: user selection and stats display
        col_selector, col_display = st.columns([1, 2])

        with col_selector:
            # User selection - all_users is a dict, not a list
            user_options = {user['name']: user['id'] for user in all_users.values()} if isinstance(all_users, dict) else {user['name']: user['id'] for user in all_users}
            selected_user_name = st.selectbox("Select User", list(user_options.keys()))
            selected_user_id = user_options[selected_user_name]

        with col_display:
            # Get filtered calls for the selected user
            date_range = st.selectbox(
                "Time period",
                ["Last 24h", "Last 7 days", "Last 30 days", "All time"],
                index=2,
                key="date_user_range"
            )
            calls = monitor.get_llm_calls(user_id=selected_user_id, limit=1000)

            if not calls:
                st.info("No LLM usage data for this user.")
                return

            # Filter by date range if needed
            if date_range != "All time":
                days_map = {
                    "Last 7 days": 7,
                    "Last 30 days": 30,
                    "Last 90 days": 90
                }
                days = days_map[date_range]
                cutoff_date = datetime.utcnow() - timedelta(days=days)

                filtered_calls = []
                for call in calls:
                    call_date = datetime.fromisoformat(call['timestamp'].replace('Z', '+00:00'))
                    if call_date >= cutoff_date:
                        filtered_calls.append(call)
                calls = filtered_calls

            # Calculate stats from filtered calls
            user_stats = {
                "by_llm_type": {},
                "overall": {
                    "total_input_tokens": 0,
                    "total_output_tokens": 0,
                    "total_calls": 0,
                    "total_cost": 0.0
                }
            }

            for call in calls:
                llm_type = call['llm_type']
                if llm_type not in user_stats["by_llm_type"]:
                    user_stats["by_llm_type"][llm_type] = {
                        "total_input_tokens": 0,
                        "total_output_tokens": 0,
                        "total_calls": 0,
                        "total_cost": 0.0
                    }

                # Update by type
                user_stats["by_llm_type"][llm_type]["total_input_tokens"] += call['input_tokens'] or 0
                user_stats["by_llm_type"][llm_type]["total_output_tokens"] += call['output_tokens'] or 0
                user_stats["by_llm_type"][llm_type]["total_calls"] += 1
                user_stats["by_llm_type"][llm_type]["total_cost"] += call['total_cost']

                # Update overall
                user_stats["overall"]["total_input_tokens"] += call['input_tokens'] or 0
                user_stats["overall"]["total_output_tokens"] += call['output_tokens'] or 0
                user_stats["overall"]["total_calls"] += 1
                user_stats["overall"]["total_cost"] += call['total_cost']

            # Render user stats
            render_user_stats(user_stats)

            # Show recent calls for this user
            st.subheader("Recent Calls")
            recent_calls = calls[:20]  # Show last 20 calls
            render_llm_calls_table(recent_calls)

    except Exception as e:
        st.error(f"Error loading user statistics: {str(e)}")
        log("error", f"User stats tab error: {e}", exc_info=True)


def show_call_logs_tab(monitor):
    """Render the call logs tab."""
    st.subheader("LLM Call Logs")

    # Filters in columns
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        # User filter
        try:
            user_manager = get_user_manager()
            all_users = user_manager.get_all_users()
            user_options = {user['name']: user['id'] for user in all_users.values()}
            user_options = {"All users": None, **user_options}
            selected_user_name = st.selectbox("User", list(user_options.keys()))
            user_filter = user_options[selected_user_name]
        except:
            user_filter = st.text_input("User ID", "")

    with col2:
        # LLM type filter
        llm_types = ["All types"] + list(monitor.cost_config.keys())
        llm_type_filter = st.selectbox("LLM Type", llm_types)
        llm_type_filter = None if llm_type_filter == "All types" else llm_type_filter

    with col3:
        # Date range
        date_filter = st.selectbox(
            "Time period",
            ["Last 24h", "Last 7 days", "Last 30 days", "All time"],
            index=2,
            key="date_filter_calls"
        )

    with col4:
        # Results limit
        limit = st.slider("Max results", 10, 500, 100)

    # Apply date filter
    calls = monitor.get_llm_calls(
        user_id=user_filter,
        llm_type=llm_type_filter,
        limit=limit * 2  # Get more initially to filter by date
    )

    if date_filter != "All time":
        days_map = {
            "Last 24h": 1,
            "Last 7 days": 7,
            "Last 30 days": 30
        }
        days = days_map[date_filter]
        cutoff_date = datetime.utcnow() - timedelta(days=days)

        filtered_calls = []
        for call in calls:
            call_date = datetime.fromisoformat(call['timestamp'].replace('Z', '+00:00'))
            if call_date >= cutoff_date:
                filtered_calls.append(call)
        calls = filtered_calls[:limit]  # Apply limit after date filtering

    # Apply final limit
    calls = calls[:limit]

    if not calls:
        st.info("No LLM calls found with the selected filters.")
        return

    # Display calls
    st.write(f"**Found {len(calls)} calls**")
    render_llm_calls_table(calls)

    # Export option
    if st.button("📥 Export to CSV"):
        if calls:
            # Create DataFrame
            export_data = []
            for call in calls:
                export_data.append({
                    "ID": call["id"],
                    "Timestamp": call["timestamp"],
                    "User ID": call["user_id"],
                    "LLM Type": call["llm_type"],
                    "Model": call["model"],
                    "Input Tokens": call["input_tokens"],
                    "Output Tokens": call["output_tokens"],
                    "Total Tokens": call["total_tokens"],
                    "Cost": call["total_cost"],
                    "Success": call["success"],
                    "Duration (ms)": call["duration_ms"]
                })

            df = pd.DataFrame(export_data)

            # Convert to CSV
            csv = df.to_csv(index=False)

            # Download button
            st.download_button(
                label="Download CSV",
                data=csv,
                file_name=f"llm_calls_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )


def show_configuration_tab(monitor):
    """Render the configuration tab."""
    st.subheader("Configuration")

    # Current configuration
    st.write("**Current Cost Configuration**")

    config_data = []
    for llm_type, costs in monitor.cost_config.items():
        config_data.append({
            "LLM Type": llm_type,
            "Input Cost per Million": costs.get("input_cost_per_million_tokens", 0),
            "Output Cost per Million": costs.get("output_cost_per_million_tokens", 0)
        })

    if config_data:
        df_config = pd.DataFrame(config_data)
        st.dataframe(
            df_config.style.format({
                "Input Cost per Million": "${:.4f}",
                "Output Cost per Million": "${:.4f}"
            }),
            width='stretch'
        )

    # Module status
    st.write("**Module Status**")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Monitoring Enabled", "✅" if monitor.enabled else "❌")

    with col2:
        st.metric("Auto Collect", "✅" if monitor.auto_collect else "❌")

    with col3:
        total_calls = monitor.get_total_calls_count()
        st.metric("Total Calls Logged", total_calls)

    # Token estimation info
    st.write("**Token Estimation**")
    st.write(f"Default estimator: {monitor.config.get('default_token_estimator', 'tiktoken')}")
    st.write("Note: Token counts are estimates. Actual API usage may vary.")

    # Configuration notes
    st.info("""
    **Note:** Cost configuration is loaded from `modules/llm_monitor/config.json`.
    To modify costs, edit the configuration file directly.

    Current cost sources (approximate):
    - **Groq:** ~$0.70/M input, ~$0.80/M output (varies by model)
    - **Gemini:** ~$0.35/M input, ~$1.05/M output
    - **Ollama:** Free (local)
    - **Mock:** Free (testing)
    """)

    # Database info
    with st.expander("🗄️ Database Information", expanded=False):
        try:
            with monitor.db.get_session() as session:
                # Get table sizes - use the actual table classes

                llm_calls_count = session.query(LLMCallTable).count()
                user_stats_count = session.query(UserLLMStatsTable).count()

                st.write(f"**LLM Calls table:** {llm_calls_count:,} records")
                st.write(f"**User Stats table:** {user_stats_count:,} records")

                # Get oldest and newest call
                oldest_call = session.query(
                    LLMCallTable.timestamp
                ).order_by(LLMCallTable.timestamp.asc()).first()

                newest_call = session.query(
                    LLMCallTable.timestamp
                ).order_by(LLMCallTable.timestamp.desc()).first()

                if oldest_call and newest_call:
                    st.write(f"**Date range:** {oldest_call[0]} to {newest_call[0]}")

        except Exception as e:
            st.error(f"Error getting database info: {str(e)}")


def inject_ui_admin_tab():
    """Register the LLM Monitor admin tab using the injection mechanism.
    Returns: (tab_name, render_function) tuple."""
    return ("LLM Monitor", show_llm_monitor_admin_content)


def inject_ui_initialize():
    """Initialize the LLM monitor admin UI module."""
    # Initialize any necessary session state variables
    def monitor_callback(data: dict):
        """Callback function to log LLM calls."""
        # Add user_id if available in session state
        if 'current_user' in st.session_state and st.session_state.current_user:
            data['user_id'] = st.session_state.current_user.get('id')

        # Add conversation_id if available in session state
        if 'current_conversation_id' in st.session_state:
            data['conversation_id'] = st.session_state.current_conversation_id

        # Log the call
        monitor = get_llm_monitor()
        monitor.log_llm_call(data)

    get_llm_manager().register_monitor_callback(monitor_callback)
    log("debug", "LLM monitor callback registered successfully")
    log("debug", "LLM monitor admin UI initialized")
    return True
