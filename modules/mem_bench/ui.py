"""Streamlit UI for mem_bench module."""

from __future__ import annotations

import os

import streamlit as st

from modules.mem_bench.runner import MemBenchRunner
from st_shared.cached import _
from shared.common import get_driver


def _t(key: str) -> str:
    return _(f"mem_bench.{key}")


def render() -> None:
    """Render memory benchmark admin UI."""
    st.header(_t("title"))
    runner = MemBenchRunner()
    runner.ensure_default_scenarios()

    scenario_files = runner.list_scenario_files()
    if not scenario_files:
        st.info(_t("no_scenarios"))
        return

    options = get_driver().list_options().get("memory_backend", [])
    if not options:
        st.warning(_t("no_memory_options"))
        return

    scenario_labels = [os.path.basename(path) for path in scenario_files]
    selected_label = st.selectbox(_t("scenario"), scenario_labels, key="mem_bench_scenario")
    selected_scenario = scenario_files[scenario_labels.index(selected_label)]

    option_labels = [item["name"] for item in options]
    active_idx = next((i for i, item in enumerate(options) if item.get("active")), 0)
    selected_memory_backend = st.selectbox(
        _t("memory_backend"),
        option_labels,
        index=active_idx,
        key="mem_bench_memory_backend",
    )

    st.warning(
        "MemBench will wipe all conversations for this dedicated benchmark student before each run. "
        "Use only a special bench_mem_ user for tests."
    )
    trace_enabled = st.checkbox("Enable trace monitoring", value=False, key="mem_bench_trace_enabled")

    if st.button(_t("run_button"), key="mem_bench_run"):
        with st.spinner(_t("running")):
            st.session_state["mem_bench_last_result"] = runner.run(
                scenario_path=selected_scenario,
                memory_backend_option=selected_memory_backend,
            )
            st.session_state["mem_bench_trace_requested"] = trace_enabled
            history = st.session_state.setdefault("mem_bench_history", [])
            history.insert(0, st.session_state["mem_bench_last_result"])

    result = st.session_state.get("mem_bench_last_result")
    if result is None:
        return

    st.subheader(_t("result_status"))
    if result.success:
        st.success(_t("result_success"))
    else:
        st.error(f"{_t('result_error')}: {result.error or 'Unknown error'}")
    st.caption(f"Cleared conversations before run: {result.cleared_conversation_count}")

    st.subheader(_t("memory_output"))
    st.text_area("", value=result.memory_content, height=220, key="mem_bench_memory_output")

    st.subheader(_t("expected_checks"))
    for check in result.checks:
        icon = "✅" if check.found else "❌"
        st.write(f"{icon} {check.term}")

    history = st.session_state.get("mem_bench_history", [])
    if history:
        st.subheader(_t("history"))
        st.caption(" | ".join(f"{item.scenario_name}@{item.memory_backend}" for item in history[:5]))

    if st.session_state.get("mem_bench_trace_requested"):
        with st.expander(f"Trace logs ({len(result.trace_logs)} lines)", expanded=False):
            st.text("\n".join(result.trace_logs[-500:]) if result.trace_logs else "No logs captured")
