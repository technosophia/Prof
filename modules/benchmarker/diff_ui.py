"""Diff tab for benchmarker UI - side-by-side session comparison."""

from datetime import datetime
import os
from typing import Dict, List, Optional, Tuple

import streamlit as st
import yaml

from modules.benchmarker.benchmarker import BenchmarkRun
from modules.benchmarker.runner import ScenarioRunner
from st_shared.cached import get_db_manager


def _format_session_label(run: BenchmarkRun) -> str:
    """Format session label for selectbox."""
    try:
        # Handle different possible formats of run_at
        run_at = run.run_at
        if run_at:
            if isinstance(run_at, str):
                dt = datetime.fromisoformat(run_at.replace('Z', '+00:00'))
            else:
                dt = run_at
        else:
            dt = datetime.now()
    except (ValueError, TypeError, AttributeError):
        dt = datetime.now()
    return f"{dt.strftime('%Y-%m-%d %H:%M')} — {str(run.id)[:8]}"


def _load_session_steps(session_path: str) -> Tuple[List[Dict], Dict]:
    """Load session steps and summary from YAML file."""
    if not session_path or not os.path.exists(session_path):
        return [], {}

    try:
        with open(session_path, "r", encoding="utf-8") as handle:
            session_data = yaml.safe_load(handle) or {}

        steps = session_data.get("steps", [])
        summary = {
            "assertions_passed": session_data.get("summary", {}).get("assertions_passed", 0),
            "assertions_total": session_data.get("summary", {}).get("assertions_total", 0),
            "total_steps": session_data.get("summary", {}).get("total_steps", 0),
            "steps_succeeded": session_data.get("summary", {}).get("steps_succeeded", 0),
            "run_at": session_data.get("meta", {}).get("run_at", ""),
        }
        return steps, summary
    except Exception as e:
        st.error(f"Failed to load session {session_path}: {e}")
        return [], {}


def _get_session_context(step: Dict) -> Optional[Dict]:
    """Extract context from step result if available."""
    result = step.get("result", {})

    # Check for injected contexts
    injected = result.get("injected_contexts", [])
    if injected:
        return {"injected_contexts": injected}

    # Check for other context-like data
    context_keys = ["context", "metadata", "rag_context", "memory_context"]
    for key in context_keys:
        if key in result:
            return {key: result[key]}

    return None


def _render_step_badge(success: bool) -> str:
    """Render a simple badge for step success/failure."""
    return "✅" if success else "❌"


def _render_assertions_summary(session_path: str, col) -> None:
    """Render assertions summary in a column."""
    if not session_path or not os.path.exists(session_path):
        col.info("No session selected")
        return

    try:
        with open(session_path, "r", encoding="utf-8") as handle:
            session_data = yaml.safe_load(handle) or {}

        assertions = session_data.get("assertions", [])
        passed = sum(1 for a in assertions if a.get("passed", False))
        total = len(assertions)

        meta = session_data.get("meta", {})
        run_at = meta.get("run_at", "")
        scenario_name = meta.get("scenario", "Unknown")

        if run_at:
            try:
                dt = datetime.fromisoformat(run_at.replace("Z", "+00:00"))
                date_str = dt.strftime("%Y-%m-%d %H:%M")
            except (ValueError, AttributeError):
                date_str = run_at[:16] if len(run_at) > 16 else run_at
        else:
            date_str = "Unknown date"

        # Create a compact summary
        col.markdown(f"**{scenario_name}**")
        col.caption(date_str)

        if total > 0:
            if passed == total:
                col.success(f"✅ {passed}/{total} assertions")
            elif passed > 0:
                col.warning(f"⚠️ {passed}/{total} assertions")
            else:
                col.error(f"❌ {passed}/{total} assertions")
        else:
            col.info("No assertions")

        # Show step success rate
        steps = session_data.get("steps", [])
        step_success = sum(1 for s in steps if s.get("success", False))
        step_total = len(steps)
        if step_total > 0:
            col.caption(f"Steps: {step_success}/{step_total} ✓")

    except Exception as e:
        col.error(f"Error loading summary: {e}")


def _get_scenario_files() -> List[str]:
    """Get list of available scenario files."""
    runner = ScenarioRunner()
    scenarios_dir = runner.config.get("scenarios_dir", "modules/benchmarker/scenarios")

    if not os.path.isdir(scenarios_dir):
        return []

    return sorted([f for f in os.listdir(scenarios_dir) if f.endswith(".yaml")])


def _get_scenario_name_from_file(scenario_file: str) -> str:
    """Extract scenario name from file content (meta.name) or fallback to filename."""
    runner = ScenarioRunner()
    scenarios_dir = runner.config.get("scenarios_dir", "modules/benchmarker/scenarios")
    scenario_path = os.path.join(scenarios_dir, scenario_file)

    try:
        scenario = runner._load_scenario(scenario_path)
        # First try to get name from meta
        meta_name = scenario.get("meta", {}).get("name")
        if meta_name:
            return meta_name
    except Exception:
        pass

    # Fallback to filename without extension
    return os.path.splitext(scenario_file)[0]


def _load_scenario_from_file(scenario_file: str) -> Dict:
    """Load scenario from file by filename."""
    runner = ScenarioRunner()
    scenarios_dir = runner.config.get("scenarios_dir", "modules/benchmarker/scenarios")
    scenario_path = os.path.join(scenarios_dir, scenario_file)

    try:
        return runner._load_scenario(scenario_path)
    except Exception as e:
        st.error(f"Failed to load scenario {scenario_file}: {e}")
        return {}


def render_diff_tab() -> None:
    """Render the diff tab for side-by-side session comparison."""

    # Get available scenario files (like in the execute tab)
    scenario_files = _get_scenario_files()

    if not scenario_files:
        st.warning("No scenario files found in scenarios directory.")
        return

    # Selection row at top
    sel_col1, sel_col2, sel_col3 = st.columns([1, 2, 2])

    with sel_col1:
        selected_scenario_file = st.selectbox(
            "Scenario",
            scenario_files,
            format_func=lambda x: os.path.splitext(x)[0],  # Show without .yaml
            key="diff_scenario"
        )
        # Get the actual scenario name from meta (for DB query)
        selected_scenario_name = _get_scenario_name_from_file(selected_scenario_file)

    # Get runs for the selected scenario (by scenario_name from DB, like in compare tab)
    with get_db_manager().get_session() as db:
        # First get all runs to see what's available
        all_runs = db.query(BenchmarkRun).all()
        if not all_runs:
            st.info("No benchmark runs found in database.")
            return

        # Then filter by scenario_name (like in compare tab)
        runs = db.query(BenchmarkRun)\
                 .filter(BenchmarkRun.scenario_name == selected_scenario_name)\
                 .order_by(BenchmarkRun.run_at.desc())\
                 .all()

        # Debug info
        if not runs:
            st.caption(f"No runs found for scenario name: '{selected_scenario_name}'")
            # Show available scenarios in DB for debugging
            available = db.query(BenchmarkRun.scenario_name).distinct().all()
            if available:
                st.caption("Available scenarios in DB: " + ", ".join([a[0] for a in available]))

        session_options = {_format_session_label(r): r.session_file for r in runs}
        session_labels = list(session_options.keys())

    with sel_col2:
        if session_labels:
            selected_a_label = st.selectbox(
                "Session A",
                session_labels,
                index=0 if session_labels else None,
                key="diff_session_a"
            )
            session_a_path = session_options.get(selected_a_label, "")
        else:
            st.info(f"No sessions for '{selected_scenario_name}'")
            session_a_path = ""
            selected_a_label = None

    with sel_col3:
        if len(session_labels) > 1:
            # Default to second session if available
            default_b = 1
            selected_b_label = st.selectbox(
                "Session B",
                session_labels,
                index=default_b,
                key="diff_session_b"
            )
            session_b_path = session_options.get(selected_b_label, "")
        elif session_labels:
            # Only one session available
            st.info("Only one session available")
            session_b_path = ""
            selected_b_label = None
        else:
            session_b_path = ""
            selected_b_label = None

    st.divider()

    st.set_page_config(layout="wide")

    # Check if we have valid selections
    if not session_labels:
        st.info(f"No benchmark runs found for scenario: {selected_scenario_name}")
        return

    if not session_a_path:
        st.warning("Please select Session A")
        return

    # Check if sessions are identical (only if both are selected)
    if session_b_path and session_a_path == session_b_path:
        st.warning("⚠️ Both selected sessions are identical.")

    # Load reference scenario from file
    scenario = _load_scenario_from_file(selected_scenario_file)
    if not scenario:
        st.error(f"Unable to load scenario file: {selected_scenario_file}")
        return

    ref_steps = scenario.get("steps", [])
    ref_assertions = scenario.get("assertions", [])

    # Load session data
    steps_a, summary_a = _load_session_steps(session_a_path)
    steps_b, summary_b = _load_session_steps(session_b_path) if session_b_path else ([], {})

    # Map steps by ID for easier lookup
    steps_by_id_a = {s.get("id", f"step_{i}"): s for i, s in enumerate(steps_a)}
    steps_by_id_b = {s.get("id", f"step_{i}"): s for i, s in enumerate(steps_b)}

    # Create columns for the diff view
    col_scenario, col_a, col_b = st.columns([1, 2, 2])

    # Column headers
    with col_scenario:
        st.markdown("### 📋 Expected")
        st.caption(f"Scenario: {selected_scenario_name}")
        if ref_assertions:
            st.info(f"📋 {len(ref_assertions)} assertions defined")

    with col_a:
        st.markdown("### 🔵 Session A")
        _render_assertions_summary(session_a_path, col_a)

    with col_b:
        st.markdown("### 🟢 Session B")
        if session_b_path:
            _render_assertions_summary(session_b_path, col_b)
        else:
            col_b.info("No session selected")

    # Render each step
    max_steps = max(len(ref_steps), len(steps_a), len(steps_b) if steps_b else 0)

    for i in range(max_steps):
        # Create a new row for this step
        step_cols = st.columns([1, 2, 2])
        step_scenario, step_a, step_b = step_cols

        # Scenario column (reference)
        with step_scenario:
            if i < len(ref_steps):
                ref_step = ref_steps[i]
                step_id = ref_step.get("id", f"step_{i+1}")

                with st.container(border=True):
                    st.markdown(f"**`[{step_id}]`**")
                    st.markdown(f"**action:** `{ref_step.get('action', '?')}`")

                    # Show expected value if present
                    if "expected_response" in ref_step:
                        expected = ref_step["expected_response"]
                        if len(expected) > 100:
                            expected = expected[:100] + "..."
                        st.markdown(f"**expected:** {expected}")

                    # Show assertions that apply to this step
                    step_assertions = [a for a in ref_assertions
                                      if a.get("params", {}).get("step_id") == step_id]
                    if step_assertions:
                        with st.expander(f"📋 Assertions ({len(step_assertions)})", expanded=False):
                            for a in step_assertions:
                                st.code(yaml.dump(a), language="yaml")
            else:
                # Grayed out placeholder for missing steps
                st.container(border=True).markdown("—")

        # Session A column
        with step_a:
            if i < len(ref_steps):
                step_data = steps_by_id_a.get(ref_steps[i].get("id"))
            else:
                step_data = steps_by_id_a.get(f"step_{i}")

            if step_data:
                success = step_data.get("success", False)
                badge = _render_step_badge(success)

                with st.container(border=True):
                    st.markdown(f"{badge} **`[{step_data.get('id', f'step_{i+1}')}]`**")
                    st.markdown(f"**action:** `{step_data.get('action', '?')}`")

                    # Show result
                    result = step_data.get("result", {})
                    if result:
                        # Truncate long responses
                        if "llm_response" in result and len(result["llm_response"]) > 200:
                            result_display = result.copy()
                            result_display["llm_response"] = result_display["llm_response"][:200] + "..."
                        else:
                            result_display = result

                        with st.expander("📦 Result", expanded=False):
                            st.json(result_display)

                    # Show error if any
                    if step_data.get("error"):
                        st.error(f"❌ {step_data['error']}")

                    # Show context
                    context = _get_session_context(step_data)
                    if context:
                        with st.expander("🔍 Context", expanded=False):
                            if "injected_contexts" in context:
                                # Format injected contexts nicely
                                for ctx in context["injected_contexts"]:
                                    st.markdown(f"**Source:** `{ctx.get('source', 'unknown')}`")
                                    preview = ctx.get("content_preview", ctx.get("content", ""))
                                    if preview:
                                        st.text(preview[:200])
                                        if len(preview) > 200:
                                            st.caption("(truncated)")
                                    st.divider()
                            else:
                                st.json(context)
            else:
                # Grayed out placeholder for missing steps
                st.container(border=True).markdown("—")

        # Session B column
        with step_b:
            if session_b_path:
                if i < len(ref_steps):
                    step_data = steps_by_id_b.get(ref_steps[i].get("id"))
                else:
                    step_data = steps_by_id_b.get(f"step_{i}")

                if step_data:
                    success = step_data.get("success", False)
                    badge = _render_step_badge(success)

                    with st.container(border=True):
                        st.markdown(f"{badge} **`[{step_data.get('id', f'step_{i+1}')}]`**")
                        st.markdown(f"**action:** `{step_data.get('action', '?')}`")

                        # Show result
                        result = step_data.get("result", {})
                        if result:
                            # Truncate long responses
                            if "llm_response" in result and len(result["llm_response"]) > 200:
                                result_display = result.copy()
                                result_display["llm_response"] = result_display["llm_response"][:200] + "..."
                            else:
                                result_display = result

                            with st.expander("📦 Result", expanded=False):
                                st.json(result_display)

                        # Show error if any
                        if step_data.get("error"):
                            st.error(f"❌ {step_data['error']}")

                        # Show context
                        context = _get_session_context(step_data)
                        if context:
                            with st.expander("🔍 Context", expanded=False):
                                if "injected_contexts" in context:
                                    # Format injected contexts nicely
                                    for ctx in context["injected_contexts"]:
                                        st.markdown(f"**Source:** `{ctx.get('source', 'unknown')}`")
                                        preview = ctx.get("content_preview", ctx.get("content", ""))
                                        if preview:
                                            st.text(preview[:200])
                                            if len(preview) > 200:
                                                st.caption("(truncated)")
                                        st.divider()
                                else:
                                    st.json(context)
                else:
                    # Grayed out placeholder for missing steps
                    st.container(border=True).markdown("—")
            else:
                # No session B selected
                st.container(border=True).markdown("—")

    # Show assertions at the bottom if we have both sessions
    if ref_assertions and session_b_path:
        st.divider()
        st.markdown("### 📋 All Assertions")

        # Load full assertion results from sessions
        def load_assertions(session_path):
            if not session_path or not os.path.exists(session_path):
                return []
            try:
                with open(session_path, "r", encoding="utf-8") as handle:
                    data = yaml.safe_load(handle) or {}
                return data.get("assertions", [])
            except:
                return []

        assertions_a = load_assertions(session_a_path)
        assertions_b = load_assertions(session_b_path)
        assertions_by_id_a = {a.get("id"): a for a in assertions_a}
        assertions_by_id_b = {a.get("id"): a for a in assertions_b}

        # Create assertions table
        for assertion in ref_assertions:
            aid = assertion.get("id")
            cols = st.columns([1, 2, 2])

            with cols[0]:
                st.markdown(f"**`{aid}`**")
                st.caption(f"type: {assertion.get('type', '?')}")

            with cols[1]:
                a_result = assertions_by_id_a.get(aid, {})
                if a_result:
                    if a_result.get("passed"):
                        st.success(f"✅ {a_result.get('message', 'Passed')}")
                    else:
                        st.error(f"❌ {a_result.get('message', 'Failed')}")
                else:
                    st.info("—")

            with cols[2]:
                b_result = assertions_by_id_b.get(aid, {})
                if b_result:
                    if b_result.get("passed"):
                        st.success(f"✅ {b_result.get('message', 'Passed')}")
                    else:
                        st.error(f"❌ {b_result.get('message', 'Failed')}")
                else:
                    st.info("—")
