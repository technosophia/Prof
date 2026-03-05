"""Streamlit UI for mem_bench module."""

from __future__ import annotations

import os
from typing import Dict, List

import streamlit as st

from modules.mem_bench.exporter import build_export_dict, to_yaml_str
from modules.mem_bench.runner import MemBenchResult, MemBenchRunner
from modules.mem_bench.rubric_loader import find_rubrics
from st_shared.cached import _
from shared.common import get_driver


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

        st.markdown("**Expected memory contains**")
        expected_contains = selected_data.get("expected_memory_contains", [])
        if not expected_contains and selected_data.get("rounds"):
            expected_contains = (selected_data.get("rounds")[-1] or {}).get("expected_memory_contains", [])
        for term in expected_contains:
            st.markdown(f"- [ ] {term}")

    option_labels = [item["name"] for item in options]
    active_idx = next((i for i, item in enumerate(options) if item.get("active")), 0)
    selected_memory_backend = st.selectbox(_t("memory_backend"), option_labels, index=active_idx, key="mem_bench_memory_backend")

    rubrics = find_rubrics(runner.scenarios_directory)
    rubric_labels = ["None (skip rubric eval)"] + list(rubrics.keys())
    rubric_choice = st.selectbox("Rubric", rubric_labels, key="mem_bench_rubric_select")
    rubric_path = rubrics.get(rubric_choice)

    if st.button(_t("run_button"), key="mem_bench_run"):
        with st.spinner(_t("running")):
            result = runner.run(
                scenario_path=selected_scenario,
                memory_backend_option=selected_memory_backend,
                rubric_path=rubric_path,
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
            table_rows.append(
                {
                    "dimension": dim_id,
                    "score": f"{score:.0f}/4",
                    "weighted": f"{(score/4.0)*weight:.2f}",
                }
            )
        if table_rows:
            st.table(table_rows)
            for dim_id, data in (rub.details.get("rubric_scores") or {}).items():
                with st.expander(f"Reasoning — {dim_id}"):
                    st.write(data.get("reasoning") or "")

    st.subheader("Export")
    export_dict = build_export_dict(result, selected_data)
    export_yaml = to_yaml_str(export_dict)
    st.download_button(
        label="Download YAML",
        data=export_yaml,
        file_name=f"mem_bench_{result.scenario_name}_{result.memory_backend}.yaml",
        mime="text/yaml",
    )
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

    if st.button("▶ Run comparison", key="mem_bench_compare_run") and selected_paths and selected_backends:
        st.session_state["mem_bench_matrix"] = runner.run_matrix(selected_paths, selected_backends, rubric_path=rubric_path)

    matrix_runs: List[MemBenchResult] = st.session_state.get("mem_bench_matrix", [])
    if not matrix_runs:
        return

    scenario_order = list(dict.fromkeys(run.scenario_path for run in matrix_runs))
    backend_order = list(dict.fromkeys(run.memory_backend for run in matrix_runs))

    header = "| Scenario | " + " | ".join(backend_order) + " |"
    sep = "|---" * (len(backend_order) + 1) + "|"
    lines = [header, sep]
    for scenario_path in scenario_order:
        row = [os.path.basename(scenario_path)]
        for backend in backend_order:
            match = next((r for r in matrix_runs if r.scenario_path == scenario_path and r.memory_backend == backend), None)
            if not match:
                row.append("-")
                continue
            icon = "✅" if match.success else "❌"
            row.append(f"{icon} emb={_embedding_score(match):.2f} rub={_rubric_overall(match)}")
        lines.append("| " + " | ".join(row) + " |")
    st.markdown("\n".join(lines))

    for run in matrix_runs:
        title = f"{os.path.basename(run.scenario_path)} × {run.memory_backend}"
        with st.expander(title):
            st.markdown(f"**Memory**\n\n{run.memory_content or '_'}")
            st.markdown("**Checks**")
            for check in run.checks:
                st.write(f"{'✅' if check.found else '❌'} [{check.check_type}] {check.term}")
            rub = run.eval_results.get("rubric")
            if rub and rub.details.get("rubric_scores"):
                st.markdown("**Rubric breakdown**")
                st.json(rub.details.get("rubric_scores"))
            if run.is_cumulative and run.rounds:
                emb = run.eval_results.get("embedding")
                per_round = [
                    f"R{r.round_index}: {sum(1 for c in r.checks if c.found) / max(len(r.checks), 1):.1f}"
                    for r in run.rounds
                ]
                st.caption(" → ".join(per_round) + (f" (overall emb={emb.score:.2f})" if emb else ""))


def _render_results_tab() -> None:
    history: List[MemBenchResult] = st.session_state.get("mem_bench_history", [])
    matrix_runs: List[MemBenchResult] = st.session_state.get("mem_bench_matrix", [])

    if matrix_runs:
        st.subheader("Comparison results")
        scenario_order = list(dict.fromkeys(run.scenario_path for run in matrix_runs))
        backend_order = list(dict.fromkeys(run.memory_backend for run in matrix_runs))

        header = "| Scenario | " + " | ".join(backend_order) + " |"
        sep = "|---" * (len(backend_order) + 1) + "|"
        lines = [header, sep]
        for scenario_path in scenario_order:
            row = [os.path.basename(scenario_path)]
            for backend in backend_order:
                match = next((r for r in matrix_runs if r.scenario_path == scenario_path and r.memory_backend == backend), None)
                if not match:
                    row.append("-")
                    continue
                row.append(
                    f"{'✅' if match.success else '❌'} "
                    f"emb={_embedding_score(match):.2f} "
                    f"rub={_rubric_overall(match)}"
                )
            lines.append("| " + " | ".join(row) + " |")
        st.markdown("\n".join(lines))

        for idx, result in enumerate(matrix_runs):
            title = (
                f"{os.path.basename(result.scenario_path)} | {result.memory_backend} | "
                f"emb={_embedding_score(result):.2f} | rub={_rubric_overall(result)}"
            )
            with st.expander(title, expanded=False):
                st.markdown("**Memory output**")
                st.write(result.memory_content or "_")
                st.markdown("**Checks**")
                for check in result.checks:
                    st.write(f"{'✅' if check.found else '❌'} [{check.check_type}] {check.term}")

                for evaluator_id, eval_result in result.eval_results.items():
                    st.markdown(f"**Evaluator: {evaluator_id}**")
                    st.write(f"passed={eval_result.passed} | score={eval_result.score:.3f}")
                    for one_check in eval_result.checks:
                        st.write(
                            f"- {'✅' if one_check.passed else '❌'} {one_check.term} "
                            f"({one_check.method}, {one_check.score:.2f}) — {one_check.note}"
                        )

                scenario_data = _load_scenario(result.scenario_path) if result.scenario_path else {"setup": {}, "conversation": []}
                exported = to_yaml_str(build_export_dict(result, scenario_data))
                st.download_button(
                    label="Download comparison export",
                    data=exported,
                    file_name=f"mem_bench_compare_{idx}.yaml",
                    mime="text/yaml",
                    key=f"mem_bench_compare_dl_{idx}",
                )

    st.subheader("Run history")
    if not history:
        st.info("No single-run history yet.")
        return
    for idx, result in enumerate(history):
        title = (
            f"{result.scenario_name} | {result.memory_backend} | "
            f"emb={_embedding_score(result):.2f} | rub={_rubric_overall(result)}"
        )
        with st.expander(title, expanded=False):
            st.write(f"success: {result.success}")
            st.write(result.memory_content)
            dummy_scenario = {"setup": {}, "conversation": []}
            exported = to_yaml_str(build_export_dict(result, dummy_scenario))
            st.download_button(
                label="Download export",
                data=exported,
                file_name=f"mem_bench_history_{idx}.yaml",
                mime="text/yaml",
                key=f"mem_bench_hist_dl_{idx}",
            )


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
