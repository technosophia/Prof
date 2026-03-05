"""Streamlit UI for mem_bench module."""

from __future__ import annotations

import os
from typing import Dict, List

import streamlit as st

from modules.mem_bench.runner import MemBenchResult, MemBenchRunner
from st_shared.cached import _
from shared.common import get_driver


def _t(key: str) -> str:
    return _(f"mem_bench.{key}")


def _load_scenario(path: str) -> Dict:
    return MemBenchRunner._load_scenario(path)


def _scenario_label(runner: MemBenchRunner, path: str) -> str:
    """
    Generate a human-readable label for a scenario file using the runner's
    scenarios directory for relative path calculation.
    """
    data = _load_scenario(path)
    meta = data.get("meta", {}) or data.get("yamlmeta", {})
    name = str(meta.get("name") or "").strip()

    # Use the runner's method to get relative path
    rel_path = runner.get_relative_scenario_path(path)

    if name:
        return f"{name} ({rel_path})"
    return f"{os.path.basename(path)} ({rel_path})"


def _ratio_style(passed: int, total: int) -> str:
    if total <= 0:
        return "⚪ 0/0"
    ratio = passed / total
    icon = "✅" if ratio >= 0.75 else "⚠️" if ratio >= 0.5 else "❌"
    return f"{passed}/{total} {icon}"


def _render_run_tab(runner: MemBenchRunner, scenario_files: List[str], options: List[Dict]) -> None:
    """Render the single run tab."""
    if not scenario_files:
        st.warning("No valid scenario files found in the scenarios directory.")
        return

    # Pass runner to _scenario_label to use its scenarios_dir
    scenario_labels = [_scenario_label(runner, path) for path in scenario_files]
    selected_label = st.selectbox(_t("scenario"), scenario_labels, key="mem_bench_scenario")
    selected_scenario = scenario_files[scenario_labels.index(selected_label)]
    selected_data = _load_scenario(selected_scenario)

    with st.expander("📋 Scenario details", expanded=False):
        meta = selected_data.get("meta", {}) or selected_data.get("yamlmeta", {})
        setup = selected_data.get("setup", {}) or {}
        st.markdown(f"**Name:** {meta.get('name', '-')}")
        st.markdown(f"**Description:** {meta.get('description', '-')}")
        st.markdown(f"**File:** `{selected_scenario}`")
        st.markdown(f"**Relative path:** `{runner.get_relative_scenario_path(selected_scenario)}`")
        st.markdown("**Setup**")
        st.markdown(f"- student_id: `{setup.get('student_id', '-')}`")
        st.markdown(f"- trainer_id: `{setup.get('trainer_id', '-')}`")
        if setup.get("training_program"):
            st.markdown("- training_program:")
            st.code(str(setup.get("training_program")), language="text")

        st.markdown("**Conversation**")
        for turn in selected_data.get("conversation", []):
            role = str(turn.get("role") or "")
            prefix = "👤" if role == "user" else "🤖" if role == "assistant" else "⚙️"
            st.markdown(f"{prefix} **{role}**: {turn.get('content', '')}")

        st.markdown("**Expected memory contains**")
        for term in selected_data.get("expected_memory_contains", []):
            st.markdown(f"- [ ] {term}")

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
    st.markdown(result.memory_content or "_")

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


def _render_compare_tab(runner: MemBenchRunner, scenario_files: List[str], options: List[Dict]) -> None:
    """Render the comparison matrix tab."""
    if not scenario_files:
        st.warning("No valid scenario files found in the scenarios directory.")
        return

    # Pass runner to _scenario_label to use its scenarios_dir
    scenario_labels = [_scenario_label(runner, path) for path in scenario_files]
    selected_scenarios = st.multiselect(
        "Scenarios",
        options=scenario_labels,
        default=scenario_labels[: min(3, len(scenario_labels))],
        key="mem_bench_compare_scenarios",
    )
    label_to_path = dict(zip(scenario_labels, scenario_files))
    selected_paths = [label_to_path[label] for label in selected_scenarios]

    backend_names = [item["name"] for item in options]
    selected_backends = st.multiselect(
        "Memory backends",
        options=backend_names,
        default=backend_names[: min(2, len(backend_names))],
        key="mem_bench_compare_backends",
    )

    run_button = st.button("▶ Run comparison", key="mem_bench_compare_run")
    if run_button:
        if not selected_paths or not selected_backends:
            st.warning("Select at least one scenario and one backend.")
        else:
            total = len(selected_paths) * len(selected_backends)
            progress = st.progress(0, text=f"Running 0/{total}")
            runs: List[MemBenchResult] = []
            completed = 0
            for scenario_path in selected_paths:
                for backend in selected_backends:
                    one = runner.run_matrix([scenario_path], [backend])
                    runs.extend(one)
                    completed += 1
                    progress.progress(completed / total, text=f"Running {completed}/{total}")
            st.session_state["mem_bench_matrix"] = runs
            progress.empty()

    matrix_runs: List[MemBenchResult] = st.session_state.get("mem_bench_matrix", [])
    if not matrix_runs:
        return

    st.subheader("Comparison matrix")

    path_to_name = {}
    for run in matrix_runs:
        if run.scenario_path not in path_to_name:
            data = _load_scenario(run.scenario_path)
            meta = data.get("meta", {}) or data.get("yamlmeta", {})
            path_to_name[run.scenario_path] = str(meta.get("name") or os.path.basename(run.scenario_path))

    scenario_order = list(dict.fromkeys(run.scenario_path for run in matrix_runs))
    backend_order = list(dict.fromkeys(run.memory_backend for run in matrix_runs))

    header = "| Scenario | " + " | ".join(backend_order) + " |"
    sep = "|---" * (len(backend_order) + 1) + "|"
    lines = [header, sep]

    for scenario_path in scenario_order:
        cells = []
        for backend in backend_order:
            match = next(
                (
                    run for run in matrix_runs
                    if run.scenario_path == scenario_path and run.memory_backend == backend
                ),
                None,
            )
            if match is None:
                cells.append("-")
                continue
            total = len(match.checks)
            passed = sum(1 for item in match.checks if item.found)
            cells.append(_ratio_style(passed, total))
        lines.append(f"| {path_to_name[scenario_path]} | " + " | ".join(cells) + " |")

    st.markdown("\n".join(lines))

    for run in matrix_runs:
        total = len(run.checks)
        passed = sum(1 for item in run.checks if item.found)
        title = f"{path_to_name.get(run.scenario_path, run.scenario_path)} × {run.memory_backend} — {_ratio_style(passed, total)}"
        with st.expander(title, expanded=False):
            if run.success:
                st.success("Run succeeded")
            else:
                st.error(run.error or "Run failed")
            st.markdown("**Memory output**")
            st.markdown(run.memory_content or "_")
            st.markdown("**Checks**")
            for check in run.checks:
                icon = "✅" if check.found else "❌"
                st.write(f"{icon} {check.term}")


def render() -> None:
    """Render memory benchmark admin UI."""
    st.header(_t("title"))
    runner = MemBenchRunner()
    runner.ensure_default_scenarios()

    with st.spinner("Scanning for valid scenario files..."):
        scenario_files = runner.list_scenario_files()

    if not scenario_files:
        st.info(
            f"No valid scenario files found in {runner.scenarios_directory} or its subdirectories.\n\n"
            "Valid scenarios must be YAML files containing:\n"
            "- 'setup' section with student_id and trainer_id\n"
            "- 'conversation' section with at least one message\n"
            "- 'expected_memory_contains' list with at least one term"
        )
        return

    options = get_driver().list_options().get("memory_backend", [])
    if not options:
        st.warning(_t("no_memory_options"))
        return

    st.caption(f"Found {len(scenario_files)} valid scenario file(s) in recursive scan of {runner.scenarios_directory}")

    tab_run, tab_compare = st.tabs(["▶ Run", "⚡ Compare"])
    with tab_run:
        _render_run_tab(runner, scenario_files, options)
    with tab_compare:
        _render_compare_tab(runner, scenario_files, options)
