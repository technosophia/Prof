"""Streamlit UI for benchmarker module."""

import os
from typing import Dict, List, Optional

import streamlit as st
import yaml

from shared.common import get_db_manager, get_driver, get_prompt

from . import BenchmarkRun
from .runner import RunResult, ScenarioRunner


def _p(key: str, default: str) -> str:
    return get_prompt(f"benchmarker.{key}", default)


def _load_scenario(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _render_results(run_result: RunResult, events: List[Dict]) -> None:
    failed = run_result.assertions_total - run_result.assertions_passed
    bar = (
        f"{run_result.assertions_passed}/{run_result.assertions_total} assertions passed"
        f"  |  {len(run_result.steps)} steps"
        f"  |  {run_result.summary.get('total_llm_calls', 0)} LLM calls"
        f"  |  {run_result.summary.get('total_tokens', 0)} tokens"
        f"  |  {run_result.summary.get('duration_seconds', 0):.1f}s"
    )
    if failed == 0:
        st.success(f"✅ {bar}")
    else:
        st.error(f"❌ {bar}")

    rows = [
        {
            "status": "✓" if a.passed else "✗",
            "id": a.id,
            "type": a.assertion_type,
            "message": a.message,
        }
        for a in run_result.assertions
    ]
    st.dataframe(rows, use_container_width=True)

    with st.expander("Step log", expanded=False):
        for step in run_result.steps:
            status = "✅" if step.success else "❌"
            with st.expander(f"[{step.actor}] {step.action} — {status} ({step.duration_seconds:.2f}s)", expanded=False):
                st.code(yaml.safe_dump({"params": step.params, "result": step.result}, sort_keys=False), language="yaml")
                if step.error:
                    st.error(step.error)

    with st.expander("Raw events", expanded=False):
        st.code(yaml.safe_dump(events, sort_keys=False), language="yaml")
        if run_result.session_path and os.path.exists(run_result.session_path):
            with open(run_result.session_path, "r", encoding="utf-8") as handle:
                st.download_button("Download session YAML", data=handle.read(), file_name=os.path.basename(run_result.session_path))


def render() -> None:
    """Render benchmarker UI with Run and History tabs."""
    runner = ScenarioRunner()

    run_tab, history_tab = st.tabs([
        _p("run_tab_title", "Run Scenario"),
        _p("history_tab_title", "History"),
    ])

    with run_tab:
        scenarios_dir = runner.config.get("scenarios_dir", "modules/benchmarker/scenarios")
        if not os.path.isdir(scenarios_dir):
            st.warning(_p("no_scenarios_found", "No scenario files found in the scenarios directory."))
            return

        scenario_files = sorted([f for f in os.listdir(scenarios_dir) if f.endswith(".yaml")])
        if not scenario_files:
            st.warning(_p("no_scenarios_found", "No scenario files found in the scenarios directory."))
            return

        selected = st.selectbox("Scenario", scenario_files)
        scenario_path = os.path.join(scenarios_dir, selected)
        scenario = _load_scenario(scenario_path)

        meta = scenario.get("meta", {})
        st.caption(meta.get("description", ""))
        st.caption(
            _p("scenario_preview", "Steps: {step_count} | Options: {options_summary}").format(
                step_count=len(scenario.get("steps", [])),
                options_summary=str(scenario.get("options", {})),
            )
        )

        overrides = {}
        with st.expander("Option overrides", expanded=False):
            for group, values in get_driver().list_options().items():
                names = [o["name"] for o in values]
                default_val = scenario.get("options", {}).get(group)
                if names:
                    default_index = names.index(default_val) if default_val in names else 0
                    overrides[group] = st.selectbox(
                        f"Override: {group} (default: {default_val})",
                        names,
                        index=default_index,
                    )

        if st.button("▶ Run Scenario"):
            with st.spinner(_p("running_spinner", "Replaying scenario...")):
                result = runner.run(scenario_path, option_overrides=overrides)
                st.session_state["benchmarker_last_result"] = result
                st.session_state["benchmarker_last_events"] = get_driver().get_session_events()

        if "benchmarker_last_result" in st.session_state:
            _render_results(st.session_state["benchmarker_last_result"], st.session_state.get("benchmarker_last_events", []))

    with history_tab:
        with get_db_manager().get_session() as session:
            runs = session.query(BenchmarkRun).order_by(BenchmarkRun.run_at.desc()).all()

        if not runs:
            st.info(_p("no_history", "No benchmark runs recorded yet."))
        else:
            rows = [
                {
                    "run_at": str(r.run_at),
                    "scenario_name": r.scenario_name,
                    "options": str(r.options),
                    "success": bool(r.success),
                    "assertions": f"{r.assertions_passed}/{r.assertions_total}",
                    "duration_seconds": r.duration_seconds,
                    "session_file": r.session_file,
                }
                for r in runs
            ]
            st.dataframe(rows, use_container_width=True)

        if st.button("Clear history"):
            with get_db_manager().get_session() as session:
                for record in session.query(BenchmarkRun).all():
                    if record.session_file and os.path.exists(record.session_file):
                        os.remove(record.session_file)
                    session.delete(record)
            st.success("History cleared")


def inject_ui_main_content():
    """Injection point for module handler."""
    render()
