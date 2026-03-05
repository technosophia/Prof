"""Streamlit UI for mem_bench module."""

from __future__ import annotations

import os
from typing import Dict, List

import streamlit as st

from modules.mem_bench.exporter import build_export_dict, to_yaml_str
from modules.mem_bench.runner import MemBenchResult, MemBenchRunner
from modules.mem_bench.rubric_loader import find_rubrics, load_rubric
from st_shared.cached import _
from shared.common import get_driver
from core.logging import log

def _get_formation_name_from_scenario(scenario_path: str) -> str:
    """
    Extract the formation name from a scenario file path.
    Expected path format: .../data/mem_bench/scenarios/<formation_name>/<file>.yaml
    Returns the <formation_name>.
    """
    # Normalize path separators
    path = os.path.normpath(scenario_path)
    parts = path.split(os.sep)

    # Find the 'scenarios' directory and take the next part
    try:
        scenarios_idx = parts.index("scenarios")
        if scenarios_idx + 1 < len(parts):
            return parts[scenarios_idx + 1]
    except ValueError:
        pass

    # Fallback: use the immediate parent directory name
    return os.path.basename(os.path.dirname(scenario_path))

def _t(key: str) -> str:
    return _(f"mem_bench.{key}")


def _load_scenario(path: str) -> Dict:
    return MemBenchRunner._load_scenario(path)


def _scenario_label(runner: MemBenchRunner, path: str) -> str:
    data = _load_scenario(path)
    meta = data.get("meta", {}) or data.get("yamlmeta", {})
    name = str(meta.get("name") or "").strip()
    rel_path = runner.get_relative_scenario_path(path)
    return f"{name} ({rel_path})" if name else f"{os.path.basename(path)} ({rel_path})"


def _embedding_score(result: MemBenchResult) -> float:
    emb = result.eval_results.get("embedding")
    return float(emb.score) if emb else 0.0


def _rubric_overall(result: MemBenchResult) -> str:
    rub = result.eval_results.get("rubric")
    if not rub or rub.details.get("status") == "skipped":
        return "-"
    return f"{rub.score * 4:.1f}/4"


def _render_rubric_summary(rubric_path: str | None) -> None:
    if not rubric_path:
        return
    rubric = load_rubric(rubric_path)
    if not rubric:
        st.warning("Selected rubric could not be loaded.")
        return
    dimensions = rubric.get("dimensions") or []
    weights = [float(dim.get("weight", 1.0)) for dim in dimensions]
    st.caption(
        f"Rubric: {rubric.get('name', os.path.basename(rubric_path))} — "
        f"{len(dimensions)} dimensions, total weight={sum(weights):.1f}. "
        f"{str(rubric.get('description') or '').strip()[:180]}"
    )


def _render_run_tab(runner: MemBenchRunner, scenario_files: List[str], options: List[Dict]) -> None:
    if not scenario_files:
        st.warning("No valid scenario files found in the scenarios directory.")
        return

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

        if selected_data.get("rounds"):
            st.markdown("**Rounds**")
            for round_item in selected_data.get("rounds", []):
                st.markdown(f"- Round {round_item.get('round', '?')}: {round_item.get('description', '-')}")
        else:
            st.markdown("**Conversation**")
            for turn in selected_data.get("conversation", []):
                role = str(turn.get("role") or "")
                prefix = "👤" if role == "user" else "🤖" if role == "assistant" else "⚙️"
                st.markdown(f"{prefix} **{role}**: {turn.get('content', '')}")

    option_labels = [item["name"] for item in options]
    active_idx = next((i for i, item in enumerate(options) if item.get("active")), 0)
    selected_memory_backend = st.selectbox(_t("memory_backend"), option_labels, index=active_idx, key="mem_bench_memory_backend")

    rubrics = find_rubrics(runner.scenarios_directory)
    rubric_labels = ["None (skip rubric eval)"] + list(rubrics.keys())
    rubric_choice = st.selectbox("Rubric", rubric_labels, key="mem_bench_rubric_select")
    rubric_path = rubrics.get(rubric_choice)

    # NEW: Get the formation directory from the rubric's parent directory
    formation_dir = None
    if rubric_path:
        formation_dir = os.path.dirname(rubric_path)
        st.caption(f"📁 Using formation from: `{formation_dir}`")

    _render_rubric_summary(rubric_path)

    trace_enabled = st.checkbox("Capture trace logs", value=False, key="mem_bench_trace_single")

    if st.button(_t("run_button"), key="mem_bench_run"):
        with st.spinner(_t("running")):
            # Extract JUST the formation name (e.g., "attention", not "material/attention")
            formation_name = _get_formation_name_from_scenario(selected_scenario)

            result = runner.run(
                scenario_path=selected_scenario,
                memory_backend_option=selected_memory_backend,
                rubric_path=rubric_path,
                formation_dir=formation_name,  # Pass JUST the name
                capture_trace=trace_enabled,
            )
            st.session_state["mem_bench_last_result"] = result
            st.session_state.setdefault("mem_bench_history", []).insert(0, result)

    result: MemBenchResult = st.session_state.get("mem_bench_last_result")
    if result is None:
        return

    st.subheader("Memory output")
    st.text_area("Memory", value=result.memory_content or "", height=220, disabled=True, key="mem_bench_memory_output")

    st.subheader("Basic checks")
    emb = result.eval_results.get("embedding")
    emb_scores = {c.term: c.score for c in (emb.checks if emb else [])}
    for check in result.checks:
        icon = "✅" if check.found else "❌"
        st.write(f"{icon} [{check.check_type}] {check.term} — score: {emb_scores.get(check.term, check.score):.2f}")

    rub = result.eval_results.get("rubric")
    if rub and rub.details.get("status") != "skipped":
        st.subheader("Rubric scores")
        table_rows = []
        for dim_id, data in (rub.details.get("rubric_scores") or {}).items():
            score = float(data.get("score", 0))
            weight = float(data.get("weight", 1))
            table_rows.append({"dimension": dim_id, "score": f"{score:.0f}/4", "weighted": f"{(score/4.0)*weight:.2f}"})
        if table_rows:
            st.table(table_rows)
            for dim_id, data in (rub.details.get("rubric_scores") or {}).items():
                with st.expander(f"Reasoning — {dim_id}"):
                    st.write(data.get("reasoning") or "")

    st.subheader("Export")
    export_dict = build_export_dict(result, selected_data)
    export_yaml = to_yaml_str(export_dict)
    st.download_button("Download YAML", data=export_yaml, file_name=f"mem_bench_{result.scenario_name}_{result.memory_backend}.yaml", mime="text/yaml")
    st.code(export_yaml, language="yaml")



def _render_compare_tab(runner: MemBenchRunner, scenario_files: List[str], options: List[Dict]) -> None:
    scenario_labels = [_scenario_label(runner, path) for path in scenario_files]
    selected_scenarios = st.multiselect("Scenarios", options=scenario_labels, default=scenario_labels[: min(3, len(scenario_labels))])
    label_to_path = dict(zip(scenario_labels, scenario_files))
    selected_paths = [label_to_path[label] for label in selected_scenarios]

    backend_names = [item["name"] for item in options]
    selected_backends = st.multiselect("Memory backends", options=backend_names, default=backend_names[: min(2, len(backend_names))])

    rubrics = find_rubrics(runner.scenarios_directory)
    rubric_labels = ["None (skip rubric eval)"] + list(rubrics.keys())
    rubric_choice = st.selectbox("Rubric (compare)", rubric_labels, key="mem_bench_rubric_compare")
    rubric_path = rubrics.get(rubric_choice)
    _render_rubric_summary(rubric_path)

    trace_enabled = st.checkbox("Capture trace logs for comparison runs", value=False, key="mem_bench_trace_compare")

    if st.button("▶ Run comparison", key="mem_bench_compare_run"):
        if not selected_paths or not selected_backends:
            st.warning("Select at least one scenario and one backend.")
        else:
            total = len(selected_paths) * len(selected_backends)
            progress = st.progress(0, text=f"Running 0/{total}")
            runs: List[MemBenchResult] = []
            done = 0

            # For each selected scenario
            for scenario_path in selected_paths:
                # Extract JUST the formation name (e.g., "attention", not "material/attention")
                formation_name = _get_formation_name_from_scenario(scenario_path)

                # For each selected backend
                for backend in selected_backends:
                    # Run matrix for this single scenario and backend
                    runs.extend(
                        runner.run_matrix(
                            [scenario_path],  # Single scenario
                            [backend],        # Single backend
                            rubric_path=rubric_path,
                            formation_dir=formation_name,  # Pass JUST the name
                            capture_trace=trace_enabled,
                        )
                    )
                    done += 1
                    progress.progress(done / total, text=f"Running {done}/{total}")

            progress.empty()
            st.session_state["mem_bench_matrix"] = runs

    matrix_runs: List[MemBenchResult] = st.session_state.get("mem_bench_matrix", [])
    if not matrix_runs:
        return

    # Rest of the function remains exactly the same
    st.subheader("Quick comparison view")
    scenario_order = list(dict.fromkeys(run.scenario_path for run in matrix_runs))
    backend_order = list(dict.fromkeys(run.memory_backend for run in matrix_runs))
    header = "| Scenario | " + " | ".join(backend_order) + " |"
    sep = "|---" * (len(backend_order) + 1) + "|"
    lines = [header, sep]
    for scenario_path in scenario_order:
        row = [os.path.basename(scenario_path)]
        for backend in backend_order:
            match = next((r for r in matrix_runs if r.scenario_path == scenario_path and r.memory_backend == backend), None)
            row.append("-" if not match else f"{'✅' if match.success else '❌'} emb={_embedding_score(match):.2f} rub={_rubric_overall(match)}")
        lines.append("| " + " | ".join(row) + " |")
    st.markdown("\n".join(lines))


def _render_results_tab() -> None:
    matrix_runs: List[MemBenchResult] = st.session_state.get("mem_bench_matrix", [])
    if not matrix_runs:
        st.info("No comparison results yet. Run a comparison first.")
        return

    st.subheader("Results matrix")
    scenario_order = list(dict.fromkeys(run.scenario_path for run in matrix_runs))
    backend_order = list(dict.fromkeys(run.memory_backend for run in matrix_runs))

    cols = st.columns([1] + [3] * len(backend_order))
    cols[0].markdown("**Scenario**")
    for idx, backend in enumerate(backend_order, start=1):
        cols[idx].markdown(f"**{backend}**")

    row_layout = [2] + [3] * len(backend_order)

    evaluator_ids = sorted({ev_id for run in matrix_runs for ev_id in run.eval_results.keys()})
    summary_row = st.columns(row_layout)
    summary_row[0].markdown("**Overall (mean)**")
    for col_idx, backend in enumerate(backend_order, start=1):
        backend_runs = [run for run in matrix_runs if run.memory_backend == backend]
        if not backend_runs or not evaluator_ids:
            summary_row[col_idx].write("-")
            continue

        summary_lines = []
        for evaluator_id in evaluator_ids:
            scores = [
                run.eval_results[evaluator_id].score
                for run in backend_runs
                if evaluator_id in run.eval_results
            ]
            if not scores:
                continue
            avg_score = round(sum(scores) / len(scores), 2)
            indicator = "🟢" if avg_score >= 0.8 else ("🟠" if avg_score >= 0.5 else "🔴")
            summary_lines.append(f"{indicator} {evaluator_id}={avg_score:.2f}")

        summary_row[col_idx].markdown("<br>".join(summary_lines) if summary_lines else "-", unsafe_allow_html=True)

    st.divider()

    for row_idx, scenario_path in enumerate(scenario_order):
        row = st.columns(row_layout)
        row[0].markdown(f"`{os.path.basename(scenario_path)}`")

        row_results: List[MemBenchResult] = []
        for col_idx, backend in enumerate(backend_order, start=1):
            match = next((r for r in matrix_runs if r.scenario_path == scenario_path and r.memory_backend == backend), None)
            if not match:
                row[col_idx].write("-")
                continue
            row_results.append(match)
            row[col_idx].write(f"score={_embedding_score(match):.2f} | rub={_rubric_overall(match)}")
            with row[col_idx].expander("Details"):
                st.write(match.memory_content or "_")
                for check in match.checks:
                    st.write(f"{'✅' if check.found else '❌'} {check.term}")
                scenario_data = _load_scenario(match.scenario_path)
                one_export = to_yaml_str(build_export_dict(match, scenario_data))
                st.download_button(
                    "Export cell",
                    data=one_export,
                    file_name=f"mem_bench_cell_{row_idx}_{col_idx}.yaml",
                    mime="text/yaml",
                    key=f"mem_bench_export_cell_{row_idx}_{col_idx}",
                )
                with st.expander("Export cell YAML"):
                    st.code(one_export, language="yaml")

        row_export = {
            "scenario_path": scenario_path,
            "results": [build_export_dict(item, _load_scenario(item.scenario_path)) for item in row_results],
        }
        row_yaml = to_yaml_str(row_export)
        st.download_button(
            label=f"Export full row: {os.path.basename(scenario_path)}",
            data=row_yaml,
            file_name=f"mem_bench_row_{row_idx}.yaml",
            mime="text/yaml",
            key=f"mem_bench_row_export_{row_idx}",
        )
        with st.expander(f"Copy export row: {os.path.basename(scenario_path)}", expanded=False):
            st.code(row_yaml, language="yaml")


def render() -> None:
    st.header(_t("title"))
    runner = MemBenchRunner()
    runner.ensure_default_scenarios()
    scenario_files = runner.list_scenario_files()
    if not scenario_files:
        st.info("No valid scenario files found.")
        return

    options = get_driver().list_options().get("memory_backend", [])
    if not options:
        st.warning(_t("no_memory_options"))
        return

    tab_run, tab_compare, tab_results = st.tabs(["▶ Run", "⚡ Compare", "📊 Results"])
    with tab_run:
        _render_run_tab(runner, scenario_files, options)
    with tab_compare:
        _render_compare_tab(runner, scenario_files, options)
    with tab_results:
        _render_results_tab()
