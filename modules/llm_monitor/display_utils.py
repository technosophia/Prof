"""
Common display utilities for LLM monitor UI components.
"""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
from shared.common import Base
from shared.common import log
from modules.llm_monitor.llm_monitor import get_llm_monitor
from modules.llm_monitor.models import LLMCallTable, UserLLMStatsTable

def render_llm_call_details(call: dict):
    """Render detailed information about an LLM call."""
    if not call:
        st.info("No LLM call data available")
        return

    # Basic info in columns
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
        st.write(f"**Cost:** ${call['total_cost']:.6f}")
        if call['duration_ms']:
            st.write(f"**Duration:** {call['duration_ms']}ms")

    # Messages sent to LLM (user/assistant only)
    if call['messages']:
        with st.expander(f"💬 Messages ({len(call['messages'])} messages)", expanded=False):
            for i, msg in enumerate(call['messages']):
                with st.expander(f"{msg['role'].upper()}: {msg['content'][:50]}...", expanded=False):
                    st.write(f"**Role:** {msg['role']}")
                    st.write("**Content:**")
                    st.text(msg["content"])

    # Context messages (system messages, etc.)
    if call['context_messages']:
        with st.expander(f"🔧 Context ({len(call['context_messages'])} items)", expanded=False):
            for i, msg in enumerate(call['context_messages']):
                with st.expander(f"Context {i+1} ({msg['role']})", expanded=False):
                    st.write(f"**Role:** {msg['role']}")
                    st.write("**Content:**")
                    st.text(msg["content"])

    # LLM Response
    with st.expander(f"🤖 Response ({len(call['response'])} chars)", expanded=False):
        st.text(call["response"])

    # Raw data (for debugging)
    with st.expander("📊 Raw Data", expanded=False):
        # Create a copy without the full response to avoid huge display
        call_copy = call.copy()
        if 'response' in call_copy and len(call_copy['response']) > 1000:
            call_copy['response'] = call_copy['response'][:1000] + "... [truncated]"
        st.json(call_copy, expanded=False)


def render_llm_calls_table(calls: list):
    """Render a table of LLM calls with expandable details."""
    if not calls:
        st.info("No LLM calls found")
        return

    # Create a DataFrame for the summary table
    summary_data = []
    for call in calls:
        summary_data.append({
            "ID": call["id"][:8],  # Short ID for display
            "Timestamp": call["timestamp"],
            "User": call["user_id"][:8] if call["user_id"] else "N/A",
            "LLM": f"{call['llm_type']}/{call['model']}",
            "Tokens": call["total_tokens"] or "N/A",
            "Cost": f"${call['total_cost']:.6f}",
            "Success": "✅" if call["success"] else "❌"
        })

    df_summary = pd.DataFrame(summary_data)
    st.dataframe(df_summary, width='stretch')

    # Detailed view for each call
    for i, call in enumerate(calls):
        with st.expander(f"Call {i+1}: {call['timestamp']} - {call['llm_type']}/{call['model']}", expanded=False):
            render_llm_call_details(call)


def render_user_stats(user_stats: dict):
    """Render user statistics."""
    if not user_stats or not user_stats["by_llm_type"]:
        st.info("No LLM usage data available")
        return

    # Overall metrics
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Calls", user_stats["overall"]["total_calls"])

    with col2:
        st.metric("Input Tokens", f"{user_stats['overall']['total_input_tokens']:,}")

    with col3:
        st.metric("Output Tokens", f"{user_stats['overall']['total_output_tokens']:,}")

    with col4:
        st.metric("Total Cost", f"${user_stats['overall']['total_cost']:.4f}")

    # Breakdown by LLM type
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
                "Cost": stats["total_cost"]
            })

        df_breakdown = pd.DataFrame(breakdown_data)
        st.dataframe(
            df_breakdown.style.format({
                "Calls": "{:,}",
                "Input Tokens": "{:,}",
                "Output Tokens": "{:,}",
                "Total Tokens": "{:,}",
                "Cost": "${:.4f}"
            }),
            width='stretch'
        )

        # Visualizations
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
            # Get total calls
            total_calls = session.query(LLMCallTable).count()

            # Get calls by LLM type
            calls_by_type = session.query(
                LLMCallTable.llm_type,
                LLMCallTable.total_cost
            ).all()

            # Get recent calls for time series (last 30 days)
            thirty_days_ago = datetime.utcnow() - timedelta(days=30)
            recent_calls = session.query(
                LLMCallTable.timestamp,
                LLMCallTable.llm_type,
                LLMCallTable.total_tokens,
                LLMCallTable.total_cost
            ).filter(
                LLMCallTable.timestamp >= thirty_days_ago
            ).all()

        # Display metrics
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
            # Count unique users with calls
            with monitor.db.get_session() as session:
                unique_users = session.query(
                    LLMCallTable.user_id
                ).distinct().count()
            st.metric("Active Users", unique_users)


        # Create DataFrame for visualization
        if recent_calls:
            df = pd.DataFrame(recent_calls, columns=['timestamp', 'llm_type', 'total_tokens', 'total_cost'])
            df['date'] = pd.to_datetime(df['timestamp']).dt.date

            # Daily usage chart
            daily_usage = df.groupby(['date', 'llm_type']).agg({
                'total_tokens': 'sum',
                'total_cost': 'sum'
            }).reset_index()

            # Create subplots
            fig = make_subplots(
                rows=2, cols=1,
                subplot_titles=('Daily Token Usage', 'Daily Cost'),
                vertical_spacing=0.15
            )

            # Token usage by LLM type
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

            # Cost by LLM type
            for llm_type in daily_usage['llm_type'].unique():
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

            # LLM type distribution
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
                cost_by_type = df.groupby('llm_type')['total_cost'].sum()
                fig_bar = px.bar(
                    x=cost_by_type.index,
                    y=cost_by_type.values,
                    title="Cost by LLM Type",
                    labels={'x': 'LLM Type', 'y': 'Total Cost ($)'}
                )
                st.plotly_chart(fig_bar, width='stretch')

    except Exception as e:
        st.error(f"Error loading system overview: {str(e)}")
        log("error", f"System overview error: {e}", exc_info=True)
