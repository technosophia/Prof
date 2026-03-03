"""
LLM Monitor Admin Interface
Provides comprehensive admin panel for monitoring LLM usage, costs, and rate limits.
"""
import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
from core.logging import log


def _get_monitor():
    """Get monitor instance via factory (Streamlit context)."""
    from modules.llm_monitor.llm_monitor_factory import get_llm_monitor
    return get_llm_monitor()


def _get_llm_manager():
    """Get LLM manager from session state or services."""
    from st_shared.cached import get_llm_manager
    return get_llm_manager()


def _get_user_manager():
    """Get user manager from session state or services."""
    from st_shared.cached import get_user_manager
    return get_user_manager()


def show_llm_monitor_admin_content():
    """Main function to display the LLM Monitor Admin with tabs."""
    st.header("🤖 LLM Usage Monitor")

    monitor = _get_monitor()

    if not monitor.enabled:
        st.warning("LLM monitoring is disabled. Enable it in the configuration.")
        return

    # Create tabs
    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "📊 Overview",
        "👤 User Statistics",
        "📝 Call Logs",
        "⏱️ Rate Limits",
        "⚙️ Configuration",
        "🔍 Diagnostics",
        "🧪 Test",
    ])

    with tab1:
        show_overview_tab(monitor)

    with tab2:
        show_user_stats_tab(monitor)

    with tab3:
        show_call_logs_tab(monitor)

    with tab4:
        show_rate_limits_tab(monitor)

    with tab5:
        show_configuration_tab(monitor)

    with tab6:
        show_diagnostics_tab(monitor)

    with tab7:
        test_rate_limit_tracking(monitor)


def show_overview_tab(monitor):
    """Render the overview tab."""
    st.subheader("System-wide LLM Usage")
    from modules.llm_monitor.display_utils import render_system_overview
    render_system_overview(monitor)

    st.subheader("💰 Cost Summary")

    col1, col2, col3 = st.columns(3)

    with col1:
        today_cost = sum(c['total_cost'] for c in monitor.get_daily_costs(days=1))
        st.metric("Today's Cost", f"${today_cost:.4f}")

    with col2:
        month_cost = monitor.get_monthly_cost()
        st.metric("This Month", f"${month_cost:.4f}")

    with col3:
        today = datetime.utcnow()
        days_in_month = 30
        days_passed = today.day
        if days_passed > 0 and month_cost > 0:
            projected = (month_cost / days_passed) * days_in_month
            st.metric("Projected Monthly", f"${projected:.4f}")


def show_user_stats_tab(monitor):
    """Render the user statistics tab."""
    st.subheader("User-level Statistics")

    try:
        user_manager = _get_user_manager()
        all_users = user_manager.get_all_users()

        if not all_users:
            st.info("No users found.")
            return

        col_selector, col_display = st.columns([1, 2])

        with col_selector:
            # Handle both dictionary and list return types
            if isinstance(all_users, dict):
                user_options = {user['name']: user['id'] for user in all_users.values()}
            else:
                # Assume it's a list
                user_options = {user['name']: user['id'] for user in all_users}

            selected_user_name = st.selectbox("Select User", list(user_options.keys()))
            selected_user_id = user_options[selected_user_name]

        with col_display:
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

            # Filter by date range
            if date_range != "All time":
                days_map = {"Last 24h": 1, "Last 7 days": 7, "Last 30 days": 30}
                days = days_map.get(date_range, 7)
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

                user_stats["by_llm_type"][llm_type]["total_input_tokens"] += call['input_tokens'] or 0
                user_stats["by_llm_type"][llm_type]["total_output_tokens"] += call['output_tokens'] or 0
                user_stats["by_llm_type"][llm_type]["total_calls"] += 1
                user_stats["by_llm_type"][llm_type]["total_cost"] += call['total_cost']

                user_stats["overall"]["total_input_tokens"] += call['input_tokens'] or 0
                user_stats["overall"]["total_output_tokens"] += call['output_tokens'] or 0
                user_stats["overall"]["total_calls"] += 1
                user_stats["overall"]["total_cost"] += call['total_cost']

            from modules.llm_monitor.display_utils import render_user_stats
            render_user_stats(user_stats)

            # Show user's rate limit usage
            if monitor.rate_limit_tracking.get("enabled", True) and monitor.rate_limit_tracking.get("track_per_user", False):
                st.write("---")
                st.subheader("⏱️ User Rate Limit Usage")

                providers_with_limits = []
                for provider, config in monitor.llm_configs.items():
                    if any(config.get(k, 0) > 0 for k in ["rpm", "rpd", "tpm", "tpd"]):
                        providers_with_limits.append(provider)

                if providers_with_limits:
                    for provider in providers_with_limits:
                        usage = monitor.get_rate_limit_usage(provider, provider, user_id=selected_user_id)

                        if usage and usage.get("limits"):
                            st.write(f"**{provider}**")
                            from modules.llm_monitor.display_utils import render_rate_limit_gauge
                            render_rate_limit_gauge(usage)

            # Clear user logs
            st.write("---")
            st.write("### ⚠️ Clear User Logs")

            col_clear1, col_clear2 = st.columns([2, 1])

            with col_clear1:
                st.warning(f"This will permanently delete **ALL** LLM usage logs for {selected_user_name}. This action cannot be undone.")

            with col_clear2:
                if st.button("🗑️ Clear User Logs", key="clear_user_logs"):
                    with st.spinner(f"Clearing logs for {selected_user_name}..."):
                        deleted_count = monitor.clear_user_logs(selected_user_id)
                        if deleted_count > 0:
                            st.success(f"✅ Cleared {deleted_count} LLM call records for {selected_user_name}")
                            st.rerun()
                        else:
                            st.info("No logs found to clear for this user")

            # Show recent calls
            st.subheader("Recent Calls")
            recent_calls = calls[:20]
            from modules.llm_monitor.display_utils import render_llm_calls_table
            render_llm_calls_table(recent_calls)

    except Exception as e:
        st.error(f"Error loading user statistics: {str(e)}")
        log("error", f"User stats tab error: {e}", stacktrace=True)


def show_call_logs_tab(monitor):
    """Render the call logs tab."""
    st.subheader("LLM Call Logs")

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        try:
            user_manager = _get_user_manager()
            all_users = user_manager.get_all_users()

            # Handle both dictionary and list return types
            if isinstance(all_users, dict):
                user_options = {user['name']: user['id'] for user in all_users.values()}
            else:
                # Assume it's a list
                user_options = {user['name']: user['id'] for user in all_users}

            user_options = {"All users": None, **user_options}
            selected_user_name = st.selectbox("User", list(user_options.keys()))
            user_filter = user_options[selected_user_name]
        except Exception as e:
            log("error", f"Error loading users: {e}")
            user_filter = st.text_input("User ID", "")

    with col2:
        llm_types = ["All types"] + list(monitor.llm_configs.keys())
        llm_type_filter = st.selectbox("LLM Type", llm_types)
        llm_type_filter = None if llm_type_filter == "All types" else llm_type_filter

    with col3:
        if llm_type_filter:
            try:
                with monitor.db.get_session() as session:
                    from modules.llm_monitor.models import LLMCallTable
                    models = session.query(LLMCallTable.model).filter_by(
                        llm_type=llm_type_filter
                    ).distinct().all()
                    model_options = ["All models"] + [m[0] for m in models]
                    model_filter = st.selectbox("Model", model_options)
                    model_filter = None if model_filter == "All models" else model_filter
            except Exception as e:
                log("error", f"Error loading models: {e}")
                model_filter = st.text_input("Model", "")
        else:
            model_filter = st.selectbox("Model", ["All models"], disabled=True)
            model_filter = None

    with col4:
        date_filter = st.selectbox(
            "Time period",
            ["Last 24h", "Last 7 days", "Last 30 days", "All time"],
            index=2,
            key="date_filter_calls"
        )

    with col5:
        limit = st.slider("Max results", 10, 500, 100)

    start_date = None
    if date_filter != "All time":
        days_map = {"Last 24h": 1, "Last 7 days": 7, "Last 30 days": 30}
        days = days_map[date_filter]
        start_date = datetime.utcnow() - timedelta(days=days)

    calls = monitor.get_llm_calls(
        user_id=user_filter,
        llm_type=llm_type_filter,
        model=model_filter,
        start_date=start_date,
        limit=limit
    )

    if not calls:
        st.info("No LLM calls found with the selected filters.")
        return

    st.write(f"**Found {len(calls)} calls**")
    from modules.llm_monitor.display_utils import render_llm_calls_table
    render_llm_calls_table(calls)

    # Export option
    if st.button("📥 Export to CSV"):
        if calls:
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
                    "Duration (ms)": call["duration_ms"],
                    "Free Provider": monitor.is_free_provider(call['llm_type'])
                })

            df = pd.DataFrame(export_data)
            csv = df.to_csv(index=False)

            st.download_button(
                label="Download CSV",
                data=csv,
                file_name=f"llm_calls_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )


def show_rate_limits_tab(monitor):
    """Render the rate limits tab."""
    st.subheader("⏱️ Rate Limit Tracking")

    if not monitor.rate_limit_tracking.get("enabled", True):
        st.warning("Rate limit tracking is disabled. Enable it in the configuration.")
        return

    providers_with_limits = []
    for provider, config in monitor.llm_configs.items():
        if any(config.get(k, 0) > 0 for k in ["rpm", "rpd", "tpm", "tpd"]):
            providers_with_limits.append(provider)

    if not providers_with_limits:
        st.info("No providers with rate limits configured")
        return

    selected_provider = st.selectbox(
        "Select Provider",
        providers_with_limits
    )

    if selected_provider:
        st.write(f"**{selected_provider.title()} Rate Limits**")

        provider_config = monitor.get_llm_config(selected_provider)

        limits_data = [{
            "Provider": selected_provider,
            "RPM": provider_config.get("rpm", 0),
            "RPD": provider_config.get("rpd", 0),
            "TPM": provider_config.get("tpm", 0),
            "TPD": provider_config.get("tpd", 0)
        }]

        df_limits = pd.DataFrame(limits_data)
        st.write("**Rate Limits Configuration:**")
        st.dataframe(df_limits, width='stretch')

        st.subheader("Current Usage")

        usage = monitor.get_rate_limit_usage(selected_provider, selected_provider)

        if usage and usage.get("limits"):
            col1, col2 = st.columns(2)

            with col1:
                daily_req = usage["daily"]["requests"]
                daily_req_limit = usage["daily"]["requests_limit"]
                if daily_req_limit and daily_req_limit > 0:
                    st.metric("Daily Requests", f"{daily_req} / {daily_req_limit}")
                    st.progress(min(daily_req / daily_req_limit, 1.0))
                else:
                    st.metric("Daily Requests", f"{daily_req} / Unlimited")

                hourly_req = usage["hourly"]["requests"]
                hourly_req_limit = usage["hourly"]["requests_limit"]
                if hourly_req_limit and hourly_req_limit > 0:
                    st.metric("Hourly Requests", f"{hourly_req} / {hourly_req_limit}")
                    st.progress(min(hourly_req / hourly_req_limit, 1.0))
                else:
                    st.metric("Hourly Requests", f"{hourly_req} / Unlimited")

            with col2:
                daily_tokens = usage["daily"]["tokens"]
                daily_tokens_limit = usage["daily"]["tokens_limit"]
                if daily_tokens_limit and daily_tokens_limit > 0:
                    st.metric("Daily Tokens", f"{daily_tokens:,} / {daily_tokens_limit:,}")
                    st.progress(min(daily_tokens / daily_tokens_limit, 1.0))
                else:
                    st.metric("Daily Tokens", f"{daily_tokens:,} / Unlimited")

                hourly_tokens = usage["hourly"]["tokens"]
                hourly_tokens_limit = usage["hourly"]["tokens_limit"]
                if hourly_tokens_limit and hourly_tokens_limit > 0:
                    st.metric("Hourly Tokens", f"{hourly_tokens:,} / {hourly_tokens_limit:,}")
                    st.progress(min(hourly_tokens / hourly_tokens_limit, 1.0))
                else:
                    st.metric("Hourly Tokens", f"{hourly_tokens:,} / Unlimited")


def show_configuration_tab(monitor):
    """Render the configuration tab."""
    st.subheader("Configuration")

    st.write("**Current Cost Configuration (per million tokens)**")

    config_data = []
    for llm_type, config in monitor.llm_configs.items():
        is_free = config.get("input_cost_per_million_tokens", 0) == 0 and config.get("output_cost_per_million_tokens", 0) == 0
        config_data.append({
            "LLM Type": llm_type,
            "Type": "Free" if is_free else "Paid",
            "Input Cost per Million": config.get("input_cost_per_million_tokens", 0),
            "Output Cost per Million": config.get("output_cost_per_million_tokens", 0)
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

    st.write("**Rate Limits Configuration**")

    rate_limit_data = []
    for llm_type, config in monitor.llm_configs.items():
        rate_limit_data.append({
            "LLM Type": llm_type,
            "RPM": config.get("rpm", 0),
            "RPD": config.get("rpd", 0),
            "TPM": config.get("tpm", 0),
            "TPD": config.get("tpd", 0)
        })

    if rate_limit_data:
        df_rate_limits = pd.DataFrame(rate_limit_data)
        st.dataframe(df_rate_limits, width='stretch')

    st.write("**Module Status**")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Monitoring Enabled", "✅" if monitor.enabled else "❌")

    with col2:
        st.metric("Auto Collect", "✅" if monitor.auto_collect else "❌")

    with col3:
        st.metric("Rate Limit Tracking", "✅" if monitor.rate_limit_tracking.get("enabled", True) else "❌")

    with col4:
        total_calls = monitor.get_total_calls_count()
        st.metric("Total Calls Logged", total_calls)

    st.info("""
    **Note:** Cost and rate limit configuration is loaded from `modules/llm_monitor/config.json`.
    To modify costs or rate limits, edit the configuration file directly.
    """)


def show_diagnostics_tab(monitor):
    """Render the diagnostics tab showing registered callbacks and system information."""
    st.subheader("🔍 System Diagnostics")

    llm_manager = _get_llm_manager()

    st.write("### 📞 Registered Callbacks")

    col1, col2 = st.columns(2)

    with col1:
        st.write("**Legacy Callbacks**")
        if hasattr(llm_manager, 'llm_callbacks') and llm_manager.llm_callbacks:
            for i, callback in enumerate(llm_manager.llm_callbacks, 1):
                callback_name = getattr(callback, '__name__', str(callback))
                module_name = getattr(callback, '__module__', 'unknown')
                st.write(f"{i}. `{callback_name}` (module: `{module_name}`)")
        else:
            st.info("No legacy callbacks registered")

    with col2:
        st.write("**Enhanced Context Callbacks**")
        if hasattr(llm_manager, 'context_callbacks') and llm_manager.context_callbacks:
            for i, callback in enumerate(llm_manager.context_callbacks, 1):
                callback_name = getattr(callback, '__name__', str(callback))
                module_name = getattr(callback, '__module__', 'unknown')
                st.write(f"{i}. `{callback_name}` (module: `{module_name}`)")
        else:
            st.info("No enhanced context callbacks registered")

    st.write("**Monitor Callbacks**")
    if hasattr(llm_manager, '_monitor_callbacks') and llm_manager._monitor_callbacks:
        for i, callback in enumerate(llm_manager._monitor_callbacks, 1):
            callback_name = getattr(callback, '__name__', str(callback))
            module_name = getattr(callback, '__module__', 'unknown')
            st.write(f"{i}. `{callback_name}` (module: `{module_name}`)")
    else:
        st.info("No monitor callbacks registered")

    st.divider()

    st.write("### 🖥️ System Information")

    st.write("**LLM Manager Status**")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Current LLM ID", llm_manager.current_llm or "None")

    with col2:
        st.metric("Available Engines", len(llm_manager.engines))

    with col3:
        st.metric("Total Callbacks",
                 len(getattr(llm_manager, 'llm_callbacks', [])) +
                 len(getattr(llm_manager, 'context_callbacks', [])) +
                 len(getattr(llm_manager, '_monitor_callbacks', [])))

    st.write("### ✅ Configuration Validation")

    llms_config = monitor.llm_configs
    valid_configs = 0
    invalid_configs = []

    for llm_id, config in llms_config.items():
        issues = []
        if not isinstance(config, dict):
            issues.append("Not a dictionary")
        else:
            if "type" not in config:
                issues.append("Missing 'type'")
            if "model" not in config:
                issues.append("Missing 'model'")

        if issues:
            invalid_configs.append({"LLM ID": llm_id, "Issues": ", ".join(issues)})
        else:
            valid_configs += 1

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Valid Configurations", valid_configs)
    with col2:
        st.metric("Total Configurations", len(llms_config))

    if invalid_configs:
        st.write("**Configuration Issues Found:**")
        st.dataframe(pd.DataFrame(invalid_configs), width='stretch')
    else:
        st.success("All LLM configurations appear valid!")

    st.divider()

    st.write("### 🗄️ Database Statistics")

    try:
        with monitor.db.get_session() as session:
            from modules.llm_monitor.models import (
                LLMCallTable,
                UserLLMStatsTable,
                RateLimitUsageTable,
                DailyCostSummaryTable
            )

            llm_calls_count = session.query(LLMCallTable).count()
            user_stats_count = session.query(UserLLMStatsTable).count()
            rate_limit_count = session.query(RateLimitUsageTable).count()
            daily_summary_count = session.query(DailyCostSummaryTable).count()

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("LLM Calls", f"{llm_calls_count:,}")
            with col2:
                st.metric("User Stats", f"{user_stats_count:,}")
            with col3:
                st.metric("Rate Limit Records", f"{rate_limit_count:,}")
            with col4:
                st.metric("Daily Summaries", f"{daily_summary_count:,}")

            if llm_calls_count > 0:
                oldest_call = session.query(LLMCallTable.timestamp).order_by(LLMCallTable.timestamp.asc()).first()
                newest_call = session.query(LLMCallTable.timestamp).order_by(LLMCallTable.timestamp.desc()).first()

                if oldest_call and newest_call:
                    st.write(f"**Date range:** {oldest_call[0]} to {newest_call[0]}")

    except Exception as e:
        st.error(f"Error getting database info: {str(e)}")
        log("error", f"Database error in diagnostics tab: {e}", stacktrace=True)

    st.divider()

    st.write("### 🗑️ Clear All Logs")

    col_clear_all1, col_clear_all2 = st.columns([2, 1])

    with col_clear_all1:
        st.error("""
        **Danger Zone:** This will permanently delete **ALL** LLM usage logs from the entire system.

        **Impact:**
        - All LLM call records will be deleted
        - All user statistics will be reset
        - All rate limit usage history will be lost
        - Daily cost summaries will be deleted
        - This action cannot be undone!
        """)

    with col_clear_all2:
        confirm_clear = st.checkbox(
            "I understand this action is irreversible",
            key="confirm_clear_all_diag"
        )

        if confirm_clear:
            if st.button("🔥 Clear ALL Logs", type="secondary", key="clear_all_logs_diag_button"):
                with st.spinner("Clearing all logs..."):
                    result = monitor.clear_all_logs()
                    if result["llm_calls"] > 0 or result["user_stats"] > 0:
                        st.success(f"✅ Cleared {result['llm_calls']} LLM call records, {result['user_stats']} user statistics, {result['rate_limit_usage']} rate limit records, and {result['daily_summary']} daily summaries")
                        st.rerun()
                    else:
                        st.info("No logs found to clear")
        else:
            st.button("🔥 Clear ALL Logs", disabled=True, help="Check the confirmation box first", key="clear_all_logs_diag_disabled")


def test_rate_limit_tracking(monitor):
    """Test function to manually verify rate limit tracking."""
    st.subheader("🧪 Verify Rate Limit Tracking")

    st.write("This will show the current rate limit usage from the database.")

    if st.button("Refresh Usage Data"):
        st.rerun()

    try:
        with monitor.db.get_session() as session:
            today = datetime.utcnow().strftime("%Y-%m-%d")
            from modules.llm_monitor.models import RateLimitUsageTable

            usage_records = session.query(RateLimitUsageTable).filter_by(
                period_date=today
            ).order_by(RateLimitUsageTable.provider, RateLimitUsageTable.model).all()

            if usage_records:
                data = []
                for record in usage_records:
                    row = {
                        "Provider": str(record.provider) if record.provider else "",
                        "Model": str(record.model) if record.model else "",
                        "Period": "Hourly" if record.period_hour is not None else "Daily",
                        "Hour": record.period_hour,
                        "Requests": record.requests_count,
                        "Tokens": record.tokens_count,
                        "Last Updated": record.last_updated
                    }
                    data.append(row)

                df = pd.DataFrame(data)

                for col in ['Hour', 'Requests', 'Tokens']:
                    if col in df.columns:
                        df[col] = df[col].fillna(0).astype(int)

                st.write("**Raw Rate Limit Data:**")
                st.dataframe(df, width='stretch')

                total_requests = df['Requests'].sum() if 'Requests' in df else 0
                total_tokens = df['Tokens'].sum() if 'Tokens' in df else 0

                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Total Requests Today", f"{total_requests:,}")
                with col2:
                    st.metric("Total Tokens Today", f"{total_tokens:,}")

                st.success(f"Found {len(usage_records)} rate limit tracking records for today")
            else:
                st.warning("No rate limit tracking records found for today. Make some LLM calls with free providers first!")

    except Exception as e:
        st.error(f"Error querying rate limit data: {str(e)}")
        log("error", f"Test rate limit error: {e}", stacktrace=True)


def inject_ui_admin_tab():
    """Register the LLM Monitor admin tab."""
    return ("LLM Monitor", show_llm_monitor_admin_content)
