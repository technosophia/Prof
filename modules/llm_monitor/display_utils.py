"""
Common display utilities for LLM monitor UI components.
"""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Callable, Tuple

from core.logging import log


def render_rate_limit_gauge(usage: Dict[str, Any], title: str = "Rate Limit Usage"):
    """Render a gauge chart for rate limit usage."""
    if not usage or not usage.get("limits"):
        return

    limits = usage.get("limits", {})

    # Daily gauges
    if limits.get("rpd"):
        col1, col2 = st.columns(2)

        with col1:
            daily_requests = usage.get("daily", {}).get("requests", 0)
            daily_requests_limit = limits.get("rpd", 1000)
            if daily_requests_limit > 0:
                daily_requests_percentage = (daily_requests / daily_requests_limit) * 100

                fig = go.Figure(go.Indicator(
                    mode="gauge+number+delta",
                    value=daily_requests,
                    number={"suffix": f" / {daily_requests_limit}"},
                    title={"text": "Daily Requests"},
                    delta={"reference": daily_requests_limit},
                    gauge={
                        "axis": {"range": [0, daily_requests_limit]},
                        "bar": {"color": "darkblue"},
                        "steps": [
                            {"range": [0, daily_requests_limit * 0.7], "color": "lightgreen"},
                            {"range": [daily_requests_limit * 0.7, daily_requests_limit * 0.9], "color": "yellow"},
                            {"range": [daily_requests_limit * 0.9, daily_requests_limit], "color": "red"}
                        ],
                        "threshold": {
                            "line": {"color": "red", "width": 4},
                            "thickness": 0.75,
                            "value": daily_requests_limit
                        }
                    }
                ))
                fig.update_layout(height=250)
                st.plotly_chart(fig, width='stretch')

        with col2:
            if limits.get("tpd") and limits.get("tpd", 0) > 0:
                daily_tokens = usage.get("daily", {}).get("tokens", 0)
                daily_tokens_limit = limits.get("tpd", 100000)
                daily_tokens_percentage = (daily_tokens / daily_tokens_limit) * 100

                fig = go.Figure(go.Indicator(
                    mode="gauge+number+delta",
                    value=daily_tokens,
                    number={"suffix": f" / {daily_tokens_limit}", "format": ",.0f"},
                    title={"text": "Daily Tokens"},
                    delta={"reference": daily_tokens_limit},
                    gauge={
                        "axis": {"range": [0, daily_tokens_limit]},
                        "bar": {"color": "darkblue"},
                        "steps": [
                            {"range": [0, daily_tokens_limit * 0.7], "color": "lightgreen"},
                            {"range": [daily_tokens_limit * 0.7, daily_tokens_limit * 0.9], "color": "yellow"},
                            {"range": [daily_tokens_limit * 0.9, daily_tokens_limit], "color": "red"}
                        ],
                        "threshold": {
                            "line": {"color": "red", "width": 4},
                            "thickness": 0.75,
                            "value": daily_tokens_limit
                        }
                    }
                ))
                fig.update_layout(height=250)
                st.plotly_chart(fig, width='stretch')

    # Hourly gauges
    if limits.get("rpm"):
        col1, col2 = st.columns(2)

        with col1:
            hourly_requests = usage.get("hourly", {}).get("requests", 0)
            hourly_requests_limit = limits.get("rpm", 30)
            if hourly_requests_limit > 0:
                hourly_requests_percentage = (hourly_requests / hourly_requests_limit) * 100

                fig = go.Figure(go.Indicator(
                    mode="gauge+number+delta",
                    value=hourly_requests,
                    number={"suffix": f" / {hourly_requests_limit}"},
                    title={"text": "Hourly Requests"},
                    delta={"reference": hourly_requests_limit},
                    gauge={
                        "axis": {"range": [0, hourly_requests_limit]},
                        "bar": {"color": "darkblue"},
                        "steps": [
                            {"range": [0, hourly_requests_limit * 0.7], "color": "lightgreen"},
                            {"range": [hourly_requests_limit * 0.7, hourly_requests_limit * 0.9], "color": "yellow"},
                            {"range": [hourly_requests_limit * 0.9, hourly_requests_limit], "color": "red"}
                        ],
                        "threshold": {
                            "line": {"color": "red", "width": 4},
                            "thickness": 0.75,
                            "value": hourly_requests_limit
                        }
                    }
                ))
                fig.update_layout(height=250)
                st.plotly_chart(fig, width='stretch')

        with col2:
            if limits.get("tpm") and limits.get("tpm", 0) > 0:
                hourly_tokens = usage.get("hourly", {}).get("tokens", 0)
                hourly_tokens_limit = limits.get("tpm", 12000)
                hourly_tokens_percentage = (hourly_tokens / hourly_tokens_limit) * 100

                fig = go.Figure(go.Indicator(
                    mode="gauge+number+delta",
                    value=hourly_tokens,
                    number={"suffix": f" / {hourly_tokens_limit}", "format": ",.0f"},
                    title={"text": "Hourly Tokens"},
                    delta={"reference": hourly_tokens_limit},
                    gauge={
                        "axis": {"range": [0, hourly_tokens_limit]},
                        "bar": {"color": "darkblue"},
                        "steps": [
                            {"range": [0, hourly_tokens_limit * 0.7], "color": "lightgreen"},
                            {"range": [hourly_tokens_limit * 0.7, hourly_tokens_limit * 0.9], "color": "yellow"},
                            {"range": [hourly_tokens_limit * 0.9, hourly_tokens_limit], "color": "red"}
                        ],
                        "threshold": {
                            "line": {"color": "red", "width": 4},
                            "thickness": 0.75,
                            "value": hourly_tokens_limit
                        }
                    }
                ))
                fig.update_layout(height=250)
                st.plotly_chart(fig, width='stretch')


def render_rate_limit_summary(monitor, provider: str = "groq"):
    """Render a summary of rate limit usage for a provider."""
    if not monitor.rate_limit_tracking.get("enabled", True):
        st.info("Rate limit tracking is disabled")
        return

    provider_config = monitor.get_llm_config(provider)

    if not provider_config:
        st.info(f"No configuration found for {provider}")
        return

    limits = {
        "rpm": provider_config.get("rpm", 0),
        "rpd": provider_config.get("rpd", 0),
        "tpm": provider_config.get("tpm", 0),
        "tpd": provider_config.get("tpd", 0)
    }

    has_limits = any(limits.get(k, 0) > 0 for k in ["rpm", "rpd", "tpm", "tpd"])

    if not has_limits:
        st.info(f"No rate limits configured for {provider}")
        return

    usage = monitor.get_rate_limit_usage(provider, provider)

    if usage and usage.get("limits"):
        st.subheader(f"Provider: {provider}")

        col1, col2, col3 = st.columns(3)

        with col1:
            if usage["daily"].get("requests_limit"):
                daily_req = usage["daily"]["requests"]
                daily_req_limit = usage["daily"]["requests_limit"]
                if daily_req_limit > 0:
                    daily_req_pct = (daily_req / daily_req_limit) * 100

                    st.metric(
                        "Daily Requests",
                        f"{daily_req} / {daily_req_limit}",
                        delta=f"{daily_req_pct:.1f}% used",
                        delta_color="inverse"
                    )

        with col2:
            if usage["hourly"].get("requests_limit"):
                hourly_req = usage["hourly"]["requests"]
                hourly_req_limit = usage["hourly"]["requests_limit"]
                if hourly_req_limit > 0:
                    hourly_req_pct = (hourly_req / hourly_req_limit) * 100

                    st.metric(
                        "Hourly Requests",
                        f"{hourly_req} / {hourly_req_limit}",
                        delta=f"{hourly_req_pct:.1f}% used",
                        delta_color="inverse"
                    )

        with col3:
            if usage["daily"].get("tokens_limit"):
                daily_tokens = usage["daily"]["tokens"]
                daily_tokens_limit = usage["daily"]["tokens_limit"]
                if daily_tokens_limit > 0:
                    daily_tokens_pct = (daily_tokens / daily_tokens_limit) * 100

                    st.metric(
                        "Daily Tokens",
                        f"{daily_tokens:,} / {daily_tokens_limit:,}",
                        delta=f"{daily_tokens_pct:.1f}% used",
                        delta_color="inverse"
                    )

        if usage["daily"].get("requests_limit") and usage["daily"]["requests_limit"] > 0:
            progress_value = min(usage["daily"]["requests"] / usage["daily"]["requests_limit"], 1.0)
            st.progress(
                progress_value,
                text=f"Daily Requests: {(usage['daily']['requests'] / usage['daily']['requests_limit'] * 100):.1f}%"
            )

        if usage["hourly"].get("requests_limit") and usage["hourly"]["requests_limit"] > 0:
            progress_value = min(usage["hourly"]["requests"] / usage["hourly"]["requests_limit"], 1.0)
            st.progress(
                progress_value,
                text=f"Hourly Requests: {(usage['hourly']['requests'] / usage['hourly']['requests_limit'] * 100):.1f}%"
            )

        if usage["daily"].get("tokens_limit") and usage["daily"]["tokens_limit"] > 0:
            progress_value = min(usage["daily"]["tokens"] / usage["daily"]["tokens_limit"], 1.0)
            st.progress(
                progress_value,
                text=f"Daily Tokens: {(usage['daily']['tokens'] / usage['daily']['tokens_limit'] * 100):.1f}%"
            )

        st.divider()


def render_llm_call_details(call: dict):
    """Render detailed information about an LLM call."""
    if not call:
        st.info("No LLM call data available")
        return

    col1, col2 = st.columns(2)

    with col1:
        st.write("**Basic Info**")
        st.write(f"**Timestamp:** {call['timestamp']}")
        st.write(f"**LLM Type:** {call['llm_type']}")
        st.write(f"**Model:** {call['model']}")
        st.write(f"**Status:** {'✅ Success' if call['success'] else '❌ Failed'}")

        if call['error_message']:
            st.error(f"**Error:** {call['error_message']}")

    with col2:
        st.write("**Usage & Cost**")
        st.write(f"**Input Tokens:** {call['input_tokens'] or 'N/A'}")
        st.write(f"**Output Tokens:** {call['output_tokens'] or 'N/A'}")
        st.write(f"**Total Tokens:** {call['total_tokens'] or 'N/A'}")

        if call['total_cost'] > 0:
            st.write(f"**Cost:** ${call['total_cost']:.6f}")
        else:
            st.write(f"**Cost:** Free")

        if call['duration_ms']:
            st.write(f"**Duration:** {call['duration_ms']}ms")

    if call.get('rate_limit_info'):
        with st.expander("⏱️ Rate Limit Info", expanded=False):
            st.json(call['rate_limit_info'])

    if call['messages']:
        with st.expander(f"💬 Messages ({len(call['messages'])} messages)", expanded=False):
            for i, msg in enumerate(call['messages']):
                role = msg.get('role', 'unknown').upper()
                content_preview = msg.get('content', '')[:50] + "..." if len(msg.get('content', '')) > 50 else msg.get('content', '')
                with st.expander(f"{role}: {content_preview}", expanded=False):
                    st.write(f"**Role:** {msg.get('role', 'unknown')}")
                    st.write("**Content:**")
                    st.text(msg.get("content", ""))

    if call['context_messages']:
        with st.expander(f"🔧 Context ({len(call['context_messages'])} items)", expanded=False):
            for i, msg in enumerate(call['context_messages']):
                role = msg.get('role', 'system').upper()
                source = msg.get('source', f'context_{i+1}')
                content_preview = msg.get('content', '')[:50] + "..." if len(msg.get('content', '')) > 50 else msg.get('content', '')
                with st.expander(f"🔧 Context {i+1} [{source}] ({role}): {content_preview}", expanded=False):
                    st.write(f"**Role:** {msg.get('role', 'system')}")
                    st.write(f"**Source:** {source}")
                    st.write("**Content:**")
                    st.text(msg.get("content", ""))

    with st.expander(f"🤖 Response ({len(call['response'])} chars)", expanded=False):
        st.text(call["response"])

    with st.expander("📊 Raw Data", expanded=False):
        call_copy = call.copy()
        if 'response' in call_copy and len(call_copy['response']) > 1000:
            call_copy['response'] = call_copy['response'][:1000] + "... [truncated]"
        st.json(call_copy, expanded=False)


def render_llm_calls_table(calls: list):
    """Render a table of LLM calls with expandable details."""
    if not calls:
        st.info("No LLM calls found")
        return

    summary_data = []
    for call in calls:
        summary_data.append({
            "ID": call["id"][:8],
            "Timestamp": call["timestamp"],
            "User": call["user_id"][:8] if call["user_id"] else "N/A",
            "LLM": f"{call['llm_type']}/{call['model']}",
            "Tokens": call["total_tokens"] if call["total_tokens"] is not None else None,
            "Cost": "Free" if call['total_cost'] == 0 else f"${call['total_cost']:.6f}",
            "Success": "✅" if call["success"] else "❌"
        })

    df_summary = pd.DataFrame(summary_data)
    st.dataframe(df_summary, width='stretch')

    for i, call in enumerate(calls):
        with st.expander(f"Call {i+1}: {call['timestamp']} - {call['llm_type']}/{call['model']}", expanded=False):
            render_llm_call_details(call)


def render_user_stats(user_stats: dict):
    """Render user statistics."""
    if not user_stats or not user_stats["by_llm_type"]:
        st.info("No LLM usage data available")
        return

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Calls", user_stats["overall"]["total_calls"])

    with col2:
        st.metric("Input Tokens", f"{user_stats['overall']['total_input_tokens']:,}")

    with col3:
        st.metric("Output Tokens", f"{user_stats['overall']['total_output_tokens']:,}")

    with col4:
        if user_stats["overall"]["total_cost"] > 0:
            st.metric("Total Cost", f"${user_stats['overall']['total_cost']:.4f}")
        else:
            st.metric("Total Cost", "Free")

    if user_stats["by_llm_type"]:
        st.subheader("Breakdown by LLM Type")

        breakdown_data = []
        for llm_type, stats in user_stats["by_llm_type"].items():
            breakdown_data.append({
                "LLM Type": llm_type,
                "Calls": stats["total_calls"],
                "Input Tokens": stats["total_input_tokens"],
                "Output Tokens": stats["total_output_tokens"],
                "Total Tokens": stats["total_input_tokens"] + stats["total_output_tokens"],
                "Cost": stats["total_cost"] if stats["total_cost"] > 0 else 0
            })

        df_breakdown = pd.DataFrame(breakdown_data)

        formatters = {
            "Calls": "{:,}",
            "Input Tokens": "{:,}",
            "Output Tokens": "{:,}",
            "Total Tokens": "{:,}"
        }

        if any(d["Cost"] > 0 for d in breakdown_data):
            formatters["Cost"] = lambda x: "${:.4f}".format(x) if x > 0 else "Free"

        st.dataframe(
            df_breakdown.style.format(formatters),
            width='stretch'
        )

        if len(breakdown_data) > 1:
            col1, col2 = st.columns(2)

            with col1:
                fig_calls = px.bar(
                    df_breakdown,
                    x="LLM Type",
                    y="Calls",
                    title="Calls by LLM Type",
                    color="LLM Type"
                )
                st.plotly_chart(fig_calls, width='stretch')

            with col2:
                paid_costs = [d for d in breakdown_data if d["Cost"] > 0]
                if paid_costs:
                    fig_cost = px.pie(
                        df_breakdown,
                        values="Cost",
                        names="LLM Type",
                        title="Cost Distribution"
                    )
                    st.plotly_chart(fig_cost, width='stretch')


def render_system_overview(monitor):
    """Render system-wide overview."""
    try:
        with monitor.db.get_session() as session:
            from modules.llm_monitor.models import LLMCallTable

            total_calls = session.query(LLMCallTable).count()

            calls_by_type = session.query(
                LLMCallTable.llm_type,
                LLMCallTable.total_cost
            ).all()

            thirty_days_ago = datetime.utcnow() - timedelta(days=30)
            recent_calls = session.query(
                LLMCallTable.timestamp,
                LLMCallTable.llm_type,
                LLMCallTable.total_tokens,
                LLMCallTable.total_cost
            ).filter(
                LLMCallTable.timestamp >= thirty_days_ago
            ).all()

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("Total Calls", total_calls)

        with col2:
            total_tokens = sum(call[2] for call in recent_calls if call[2])
            st.metric("Total Tokens", f"{total_tokens:,}")

        with col3:
            total_cost = sum(call[3] for call in recent_calls if call[3])
            st.metric("Total Cost", f"${total_cost:.4f}")

        with col4:
            with monitor.db.get_session() as session:
                unique_users = session.query(LLMCallTable.user_id).distinct().count()
            st.metric("Active Users", unique_users)

        if monitor.rate_limit_tracking.get("enabled", True):
            st.subheader("⏱️ Rate Limit Status")

            providers_with_limits = []
            for provider, config in monitor.llm_configs.items():
                has_limits = any(config.get(k, 0) > 0 for k in ["rpm", "rpd", "tpm", "tpd"])
                if has_limits:
                    providers_with_limits.append(provider)

            if providers_with_limits:
                tabs = st.tabs([p.title() for p in providers_with_limits])

                for i, provider in enumerate(providers_with_limits):
                    with tabs[i]:
                        render_rate_limit_summary(monitor, provider)
            else:
                st.info("No providers with rate limits configured")

        if recent_calls:
            df = pd.DataFrame(recent_calls, columns=['timestamp', 'llm_type', 'total_tokens', 'total_cost'])
            df['date'] = pd.to_datetime(df['timestamp']).dt.date

            daily_usage = df.groupby(['date', 'llm_type']).agg({
                'total_tokens': 'sum',
                'total_cost': 'sum'
            }).reset_index()

            fig = make_subplots(
                rows=2, cols=1,
                subplot_titles=('Daily Token Usage', 'Daily Cost'),
                vertical_spacing=0.15
            )

            for llm_type in daily_usage['llm_type'].unique():
                llm_data = daily_usage[daily_usage['llm_type'] == llm_type]
                fig.add_trace(
                    go.Scatter(
                        x=llm_data['date'],
                        y=llm_data['total_tokens'],
                        name=f"{llm_type} - Tokens",
                        mode='lines+markers'
                    ),
                    row=1, col=1
                )

            paid_llm_types = [t for t in daily_usage['llm_type'].unique()
                            if not monitor.is_free_provider(t)]

            for llm_type in paid_llm_types:
                llm_data = daily_usage[daily_usage['llm_type'] == llm_type]
                fig.add_trace(
                    go.Scatter(
                        x=llm_data['date'],
                        y=llm_data['total_cost'],
                        name=f"{llm_type} - Cost",
                        mode='lines+markers'
                    ),
                    row=2, col=1
                )

            fig.update_layout(height=600, showlegend=True)
            st.plotly_chart(fig, width='stretch')

            st.subheader("LLM Type Distribution")
            col1, col2 = st.columns(2)

            with col1:
                type_counts = df['llm_type'].value_counts()
                fig_pie = px.pie(
                    values=type_counts.values,
                    names=type_counts.index,
                    title="Calls by LLM Type"
                )
                st.plotly_chart(fig_pie, width='stretch')

            with col2:
                paid_df = df[df['llm_type'].isin(paid_llm_types)]
                if not paid_df.empty:
                    cost_by_type = paid_df.groupby('llm_type')['total_cost'].sum()
                    fig_bar = px.bar(
                        x=cost_by_type.index,
                        y=cost_by_type.values,
                        title="Cost by LLM Type",
                        labels={'x': 'LLM Type', 'y': 'Total Cost ($)'}
                    )
                    st.plotly_chart(fig_bar, width='stretch')
                else:
                    st.info("No paid provider usage to display")

    except Exception as e:
        st.error(f"Error loading system overview: {str(e)}")
        log("error", f"System overview error: {e}", exc_info=True)
