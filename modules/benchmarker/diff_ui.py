"""Diff tab for benchmarker UI - side-by-side session comparison."""

from datetime import datetime
import os
from typing import Dict, List, Optional

import streamlit as st
import yaml

from modules.benchmarker.benchmarker import BenchmarkRun, ScoringRun
from modules.benchmarker.runner import ScenarioRunner
from st_shared.cached import get_db_manager


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _format_session_label(run: BenchmarkRun) -> str:
    """Format session label with date + config for selectbox."""
    try:
        run_at = run.run_at
        if isinstance(run_at, str):
            dt = datetime.fromisoformat(run_at.replace("Z", "+00:00"))
        else:
            dt = run_at or datetime.now()
    except (ValueError, TypeError, AttributeError):
        dt = datetime.now()

    options = run.options or {}
    config_parts = [f"{k}={v}" for k, v in sorted(options.items()) if v]
    config_str = " · ".join(config_parts) if config_parts else "default"
    return f"{dt.strftime('%Y-%m-%d %H:%M')} — {config_str} [{str(run.id)[:8]}]"


def _load_session(session_path: str) -> Dict:
    """Load full session data from YAML."""
    if not session_path or not os.path.exists(session_path):
        return {}
    try:
        with open(session_path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception as e:
        st.error(f"Failed to load session {session_path}: {e}")
        return {}


def _get_scenario_files(runner: ScenarioRunner) -> List[str]:
    scenarios_dir = runner.config.get("scenarios_dir", "modules/benchmarker/scenarios")
    if not os.path.isdir(scenarios_dir):
        return []
    return sorted([f for f in os.listdir(scenarios_dir) if f.endswith(".yaml")])


def _get_scenario_name_from_file(runner: ScenarioRunner, scenario_file: str) -> str:
    scenarios_dir = runner.config.get("scenarios_dir", "modules/benchmarker/scenarios")
    scenario_path = os.path.join(scenarios_dir, scenario_file)
    try:
        scenario = runner._load_scenario(scenario_path)
        name = scenario.get("meta", {}).get("name")
        if name:
            return name
    except Exception:
        pass
    return os.path.splitext(scenario_file)[0]


def _load_scenario_from_file(runner: ScenarioRunner, scenario_file: str) -> Dict:
    scenarios_dir = runner.config.get("scenarios_dir", "modules/benchmarker/scenarios")
    scenario_path = os.path.join(scenarios_dir, scenario_file)
    try:
        return runner._load_scenario(scenario_path)
    except Exception as e:
        st.error(f"Failed to load scenario {scenario_file}: {e}")
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# Score Display Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _format_score_bar(score: float, max_score: float = 1.0) -> str:
    """Format a score with a colored bar and emoji indicator."""
    if score > max_score:
        # For 5-point scales
        normalized = (score - 1) / 4  # Convert 1-5 to 0-1
        bar_len = int(round(normalized * 10))
        bar = "\u2588" * bar_len + "\u2591" * (10 - bar_len)
        if score >= 4:
            color = "\U0001f7e2"  # green
        elif score >= 2.5:
            color = "\U0001f7e1"  # yellow
        else:
            color = "\U0001f534"  # red
        return f"{color} **{score:.1f}/5**  {bar}"
    else:
        # For 0-1 scales
        bar_len = int(round(score * 10))
        bar = "\u2588" * bar_len + "\u2591" * (10 - bar_len)
        if score >= 0.7:
            color = "\U0001f7e2"  # green
        elif score >= 0.4:
            color = "\U0001f7e1"  # yellow
        else:
            color = "\U0001f534"  # red
        return f"{color} **{score:.3f}**  {bar}"


def _render_score_dict(scores: Dict, step_id: Optional[str] = None, action: Optional[str] = None) -> None:
    """Render a dictionary of scores with consistent formatting."""
    if not scores:
        st.caption("*(no scores)*")
        return

    for key, value in scores.items():
        if value is not None:
            try:
                fval = float(value)
                if step_id and action and key == step_id:
                    # This is a per-step score matching the current step
                    st.markdown(f"{_format_score_bar(fval)} `{action}`")
                else:
                    # This is a dimension or other score
                    st.markdown(f"{_format_score_bar(fval)} `{key}`")
            except (ValueError, TypeError):
                st.markdown(f"`{key}`: {value}")


# ─────────────────────────────────────────────────────────────────────────────
# Renderers
# ─────────────────────────────────────────────────────────────────────────────

def _render_session_header(session_data: Dict, col, label: str) -> None:
    """Render session header with metadata and assertion summary."""
    if not session_data:
        col.info("No session selected")
        return

    meta = session_data.get("meta", {})
    summary = session_data.get("summary", {})
    options = meta.get("configuration") or meta.get("options") or {}

    run_at = meta.get("run_at", "")
    try:
        dt = datetime.fromisoformat(run_at.replace("Z", "+00:00"))
        date_str = dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        date_str = run_at[:19] if run_at else "Unknown"

    passed = summary.get("assertions_passed", 0)
    total = summary.get("assertions_total", 0)
    steps_ok = summary.get("steps_succeeded", 0)
    steps_total = summary.get("total_steps", 0)
    duration = meta.get("duration_seconds", 0)
    llm = meta.get("llm") or "?"

    col.markdown(f"### {label}")
    col.caption(f"🕐 {date_str}  ·  ⏱ {duration:.1f}s  ·  🤖 `{llm}`")

    # Configuration badges
    if options:
        config_md = "  ".join(f"`{k}: {v}`" for k, v in sorted(options.items()) if v)
        col.markdown(f"⚙️ {config_md}")
    else:
        col.caption("⚙️ default configuration")

    # Assertion summary
    if total > 0:
        if passed == total:
            col.success(f"✅ {passed}/{total} assertions  ·  steps {steps_ok}/{steps_total}")
        elif passed > 0:
            col.warning(f"⚠️ {passed}/{total} assertions  ·  steps {steps_ok}/{steps_total}")
        else:
            col.error(f"❌ {passed}/{total} assertions  ·  steps {steps_ok}/{steps_total}")
    else:
        col.info(f"Steps: {steps_ok}/{steps_total}")


def _expander_title(prefix: str, text: str, max_preview: int = 80) -> str:
    """Build expander title: prefix + start of text + char count."""
    if not text:
        return f"{prefix} (empty)"
    preview = text[:max_preview].replace("\n", " ").strip()
    if len(text) > max_preview:
        preview += "…"
    return f"{prefix} · {len(text)} chars — {preview}"


def _render_step_scores_expander(step_scoring_runs: List[Dict], step_action: Optional[str] = None) -> None:
    """Render step-level scoring runs inside the fancy step-score expander."""
    if not step_scoring_runs:
        return

    with st.expander(f"🏅 Step scores ({len(step_scoring_runs)})", expanded=False):
        for idx, score_run in enumerate(step_scoring_runs):
            scorer_id = score_run.get("scorer_id", "?")
            score_cfg = score_run.get("scorer_config") or {}
            scored_at = str(score_run.get("scored_at") or "")[:16]

            st.markdown(f"**`{scorer_id}`** · {scored_at}")

            # Display scores using the same visual style as evaluations
            scores = score_run.get("scores") or {}
            overall = score_run.get("overall_score")

            if overall is not None:
                st.markdown(f"**Overall:** {_format_score_bar(overall)}")

            if scores:
                st.markdown("**Scores:**")
                _render_score_dict(scores)

            # Show config and source in a compact way
            config_info = []
            if score_cfg:
                rubric = score_cfg.get("rubric") or score_cfg.get("model") or ""
                if rubric:
                    config_info.append(f"rubric: {rubric}")
                else:
                    config_info.append(f"config: {str(score_cfg)[:60]}")
            if score_run.get("source"):
                config_info.append(f"source: {score_run['source']}")

            if config_info:
                st.caption(" · ".join(config_info))

            if score_run.get("notes"):
                st.info(f"\U0001f4dd {score_run['notes']}")

            if idx < len(step_scoring_runs) - 1:
                st.markdown("---")


def _render_session_step(
    step_data: Dict,
    ref_step: Optional[Dict],
    assertions_for_step: List[Dict],
    assertions_results: Dict[str, Dict],
    step_scores_by_id: Dict[str, List[Dict]],
    session_key: str,
    step_idx: int,
) -> None:
    """Render a single session step cell."""
    if not step_data:
        with st.container(border=True):
            st.markdown("*— step not present —*")
        return

    success = step_data.get("success", False)
    badge = "✅" if success else "❌"
    action = step_data.get("action", "?")
    step_id = step_data.get("id", f"step_{step_idx + 1}")
    step_scoring_runs = step_scores_by_id.get(step_id, [])
    duration = step_data.get("duration_seconds", 0.0)
    result = step_data.get("result", {})
    # injected_contexts is serialized at step level by session.py, NOT inside result
    injected_contexts = step_data.get("injected_contexts", [])

    # Assertion results for this step
    step_assertion_results = [(a, assertions_results.get(a.get("id"), {})) for a in assertions_for_step]
    all_passed = all(r.get("passed", False) for _, r in step_assertion_results if r)
    any_failed = any(not r.get("passed", True) for _, r in step_assertion_results if r)

    with st.container(border=True):
        # Header line
        assertion_badge = ""
        if step_assertion_results:
            assertion_badge = " 🟢" if all_passed else " 🔴"
        st.markdown(f"{badge} **`{step_id}`** · `{action}` · ⏱ {duration:.2f}s{assertion_badge}")

        # Error
        if step_data.get("error"):
            st.error(f"❌ {step_data['error']}")

        # ── LLM response + context together for user_send_message ────────────
        if action == "user_send_message":
            llm_response = result.get("llm_response", "")

            # 1. Response expander — always shown
            resp_title = _expander_title("💬 LLM response", llm_response)
            with st.expander(resp_title, expanded=False):
                if llm_response:
                    st.markdown(llm_response)
                else:
                    st.caption("(no response)")

            # 2. Assertion results
            for assertion, a_result in step_assertion_results:
                if a_result:
                    if a_result.get("passed"):
                        st.success(f"✅ `{assertion.get('id')}` {a_result.get('message', '')}")
                    else:
                        st.error(f"❌ `{assertion.get('id')}` {a_result.get('message', 'Failed')}")

            # 3. Context expander
            if injected_contexts:
                by_source: Dict[str, List[Dict]] = {}
                for ctx in injected_contexts:
                    by_source.setdefault(ctx.get("source", "unknown"), []).append(ctx)
                source_summary = " · ".join(
                    f"`{src}` ({sum(len(c.get('content') or '') for c in items)}c)"
                    for src, items in by_source.items()
                )
                with st.expander(f"🔍 Context — {source_summary}", expanded=False):
                    for src, items in by_source.items():
                        st.markdown(f"**`{src}`**")
                        for idx, ctx in enumerate(items):
                            role = ctx.get("role", "system")
                            # content is stored in-session; preview is computed at render time when needed
                            content = ctx.get("content") or ""
                            st.caption(f"role: {role}")
                            st.text(content)
                            if idx < len(items) - 1:
                                st.markdown("---")
                        st.divider()
            else:
                st.caption("*(no context injected)*")

            # 4. Step scoring
            _render_step_scores_expander(step_scoring_runs, action)

            # 5. Raw result
            raw_result = {k: v for k, v in result.items()}
            if raw_result:
                with st.expander("🗂 Raw result", expanded=False):
                    st.code(yaml.dump(raw_result, allow_unicode=True, sort_keys=False), language="yaml")

        elif action not in ("create_conversation", "switch_option"):
            # For other actions: compact result + assertions
            clean_result = {k: v for k, v in result.items()
                           if k not in ("injected_contexts", "conversation_id")}
            if clean_result:
                result_str = yaml.dump(clean_result, allow_unicode=True, sort_keys=False)
                result_title = _expander_title("📦 Result", result_str)
                with st.expander(result_title, expanded=False):
                    st.code(result_str, language="yaml")

            _render_step_scores_expander(step_scoring_runs, action)

            for assertion, a_result in step_assertion_results:
                if a_result:
                    if a_result.get("passed"):
                        st.success(f"✅ `{assertion.get('id')}` {a_result.get('message', '')}")
                    else:
                        st.error(f"❌ `{assertion.get('id')}` {a_result.get('message', 'Failed')}")


def _session_config_description(session_data: Dict) -> Dict:
    """Return session configuration metadata used in exports."""
    meta = session_data.get("meta", {}) if session_data else {}
    return {
        "run_at": meta.get("run_at"),
        "llm": meta.get("llm"),
        "configuration": meta.get("configuration") or meta.get("options") or {},
    }


def _build_step_export_yaml(
    *,
    scenario_step: Dict,
    session_a_step: Optional[Dict],
    session_b_step: Optional[Dict],
    session_a_config: Dict,
    session_b_config: Dict,
    session_a_scores: List[Dict],
    session_b_scores: List[Dict],
) -> str:
    """Build YAML export payload for one compared step."""
    payload = {
        "scenario_step": scenario_step,
        "session_a_step": {
            "session": session_a_config,
            "step": session_a_step,
            "evaluations": session_a_scores,
        },
        "session_b_step": {
            "session": session_b_config,
            "step": session_b_step,
            "evaluations": session_b_scores,
        },
    }
    return yaml.dump(payload, allow_unicode=True, sort_keys=False)


def _render_expected_step(
    ref_step: Dict,
    assertions_for_step: List[Dict],
    session_a_step: Optional[Dict],
    session_b_step: Optional[Dict],
    session_a_config: Dict,
    session_b_config: Dict,
    session_a_scores: List[Dict],
    session_b_scores: List[Dict],
    export_key: str,
) -> None:
    """Render the expected/scenario column for a step."""
    with st.container(border=True):
        step_id = ref_step.get("id", "?")
        action = ref_step.get("action", "?")
        actor = ref_step.get("actor", "?")
        params = ref_step.get("params", {})

        st.markdown(f"**`{step_id}`** · `{actor}` · `{action}`")

        # For user_send_message: show the user message AND expected response
        if action == "user_send_message":
            content = params.get("content", "")
            if content:
                st.markdown(f"💬 *{content}*")

        # Show expected response if present (below user message)
        expected = ref_step.get("expected_response", "")
        if expected and expected.strip():
            exp_title = _expander_title("📝 Expected", expected)
            with st.expander(exp_title, expanded=False):
                st.markdown(expected)

        # For other actions: show params compactly
        elif action not in ("user_send_message",):
            if params:
                compact = {k: (str(v)[:80] + "…" if isinstance(v, str) and len(str(v)) > 80 else v)
                           for k, v in params.items()}
                st.caption(yaml.dump(compact, allow_unicode=True, default_flow_style=True).strip())

        # Assertions linked to this step
        if assertions_for_step:
            with st.expander(f"📋 {len(assertions_for_step)} assertion(s)", expanded=False):
                for a in assertions_for_step:
                    st.code(yaml.dump(a, allow_unicode=True, sort_keys=False), language="yaml")

        export_yaml = _build_step_export_yaml(
            scenario_step=ref_step,
            session_a_step=session_a_step,
            session_b_step=session_b_step,
            session_a_config=session_a_config,
            session_b_config=session_b_config,
            session_a_scores=session_a_scores,
            session_b_scores=session_b_scores,
        )
        if st.button("📤 Export this step", key=f"export_step_{export_key}"):
            st.warning("Copy/paste export YAML below")
            st.code(export_yaml, language="yaml")


def _row_to_scoring_run_dict(row: ScoringRun) -> Dict:
    """Convert a ScoringRun row to a detached plain dict."""
    return {
        "scorer_id": row.scorer_id,
        "scores": dict(row.scores or {}),
        "overall_score": row.overall_score,
        "scored_at": row.scored_at,
        "scorer_config": dict(row.scorer_config or {}),
        "source": row.source,
        "notes": row.notes,
    }


def _load_scoring_runs(session_path: str) -> List[Dict]:
    """Load session-level (aggregated) scoring runs for a session file."""
    if not session_path:
        return []
    with get_db_manager().get_session() as db:
        rows = db.query(ScoringRun).filter(ScoringRun.session_file == session_path).all()
        return [
            _row_to_scoring_run_dict(row)
            for row in rows
            if (row.scorer_config or {}).get("level") in (None, "session")
        ]


def _load_step_scores_by_step(session_path: str) -> Dict[str, List[Dict]]:
    """Load step-level scoring runs grouped by step_id for a session file."""
    if not session_path:
        return {}

    by_step: Dict[str, List[Dict]] = {}
    with get_db_manager().get_session() as db:
        rows = db.query(ScoringRun).filter(ScoringRun.session_file == session_path).all()
        for row in rows:
            config = dict(row.scorer_config or {})
            if config.get("level") != "step":
                continue
            step_id = config.get("step_id")
            if not step_id:
                continue
            by_step.setdefault(str(step_id), []).append(_row_to_scoring_run_dict(row))

    for step_id in by_step:
        by_step[step_id] = sorted(by_step[step_id], key=lambda r: r.get("scored_at") or "", reverse=True)

    return by_step


def _render_scoring_run(run: Dict, ref_steps: List[Dict]) -> None:
    """Render one scoring run dict: overall + per-step or per-dimension breakdown."""
    scores = run.get("scores") or {}
    overall = run.get("overall_score")
    scored_at = run.get("scored_at")
    config = run.get("scorer_config") or {}
    notes = run.get("notes") or ""

    # Detect whether scores keys match step ids from the scenario
    step_ids = {s.get("id") for s in ref_steps}
    scores_are_steps = bool(scores) and all(k in step_ids for k in scores.keys())

    # Header: overall score
    if overall is not None:
        st.markdown(f"**Overall:** {_format_score_bar(overall)}")
    else:
        st.caption("Overall: \u2014")

    col_meta1, col_meta2 = st.columns(2)
    col_meta1.caption(f"source: `{run.get('source', '?')}` \u00b7 scored: {str(scored_at)[:16]}")
    if config:
        rubric = config.get("rubric") or config.get("model") or ""
        col_meta2.caption(f"config: {rubric}" if rubric else f"config: {str(config)[:60]}")

    if notes:
        st.info(f"\U0001f4dd {notes}")

    if not scores:
        st.caption("*(no dimension scores stored)*")
        return

    if scores_are_steps:
        st.markdown("**Per-step scores:**")
        for step in ref_steps:
            sid = step.get("id", "?")
            val = scores.get(sid)
            action = step.get("action", "?")
            if val is not None:
                st.markdown(f"{_format_score_bar(val)} `{sid}` `{action}`")
            else:
                st.markdown(f"\u26aa `{sid}` `{action}` \u2014 \u2014")
    else:
        st.markdown("**Dimension scores:**")
        _render_score_dict(scores)


def _render_evaluations_section(
    session_a_path: str,
    session_b_path: str,
    ref_steps: List[Dict],
) -> None:
    """Render all scoring runs for both sessions in a side-by-side expander."""
    runs_a = _load_scoring_runs(session_a_path)
    runs_b = _load_scoring_runs(session_b_path) if session_b_path else []

    if not runs_a and not runs_b:
        return

    st.divider()
    all_scorer_ids = sorted({r["scorer_id"] for r in runs_a} | {r["scorer_id"] for r in runs_b})

    title = f"\U0001f3c5 Evaluations \u2014 {len(all_scorer_ids)} scorer(s)"
    if runs_a:
        title += f"  \u00b7  A: {len(runs_a)} run(s)"
    if runs_b:
        title += f"  \u00b7  B: {len(runs_b)} run(s)"

    with st.expander(title, expanded=True):
        for scorer_id in all_scorer_ids:
            st.markdown(f"### scorer: `{scorer_id}`")
            cols = st.columns([1, 2, 2])
            with cols[0]:
                st.caption("scorer")

            scorer_runs_a = sorted([r for r in runs_a if r["scorer_id"] == scorer_id],
                                   key=lambda r: r["scored_at"] or "", reverse=True)
            with cols[1]:
                if scorer_runs_a:
                    for i, run in enumerate(scorer_runs_a):
                        if i > 0:
                            st.markdown("---")
                            st.caption(f"earlier run ({str(run['scored_at'])[:16]})")
                        _render_scoring_run(run, ref_steps)
                else:
                    st.caption("*(not scored)*")

            scorer_runs_b = sorted([r for r in runs_b if r["scorer_id"] == scorer_id],
                                   key=lambda r: r["scored_at"] or "", reverse=True)
            with cols[2]:
                if session_b_path:
                    if scorer_runs_b:
                        for i, run in enumerate(scorer_runs_b):
                            if i > 0:
                                st.markdown("---")
                                st.caption(f"earlier run ({str(run['scored_at'])[:16]})")
                            _render_scoring_run(run, ref_steps)
                    else:
                        st.caption("*(not scored)*")
                else:
                    st.caption("\u2014")

            st.divider()


# ─────────────────────────────────────────────────────────────────────────────
# Main render
# ─────────────────────────────────────────────────────────────────────────────

def render_diff_tab() -> None:
    """Render the diff tab for side-by-side session comparison."""
    runner = ScenarioRunner()
    scenario_files = _get_scenario_files(runner)

    if not scenario_files:
        st.warning("No scenario files found in scenarios directory.")
        return

    # ── Scenario + session selectors ────────────────────────────────────────
    sel_col1, sel_col2, sel_col3 = st.columns([1, 2, 2])

    with sel_col1:
        selected_scenario_file = st.selectbox(
            "Scenario",
            scenario_files,
            format_func=lambda x: os.path.splitext(x)[0],
            key="diff_scenario",
        )
        selected_scenario_name = _get_scenario_name_from_file(runner, selected_scenario_file)

    with get_db_manager().get_session() as db:
        runs = (
            db.query(BenchmarkRun)
            .filter(BenchmarkRun.scenario_name == selected_scenario_name)
            .order_by(BenchmarkRun.run_at.desc())
            .all()
        )
        if not runs:
            available = db.query(BenchmarkRun.scenario_name).distinct().all()
            st.caption(f"No runs found for '{selected_scenario_name}'.")
            if available:
                st.caption("Available: " + ", ".join(a[0] for a in available))
            return

        session_options = {_format_session_label(r): r.session_file for r in runs}
        session_labels = list(session_options.keys())

    with sel_col2:
        selected_a_label = st.selectbox("Session A", session_labels, index=0, key="diff_session_a")
        session_a_path = session_options.get(selected_a_label, "")

    with sel_col3:
        if len(session_labels) > 1:
            selected_b_label = st.selectbox("Session B", session_labels, index=1, key="diff_session_b")
            session_b_path = session_options.get(selected_b_label, "")
        else:
            st.info("Only one session available")
            session_b_path = ""

    if session_b_path and session_a_path == session_b_path:
        st.warning("⚠️ Both selected sessions are identical.")

    # ── Load data ────────────────────────────────────────────────────────────
    scenario = _load_scenario_from_file(runner, selected_scenario_file)
    if not scenario:
        st.error(f"Unable to load scenario file: {selected_scenario_file}")
        return

    ref_steps = scenario.get("steps", [])
    ref_assertions = scenario.get("assertions", [])

    session_a = _load_session(session_a_path)
    session_b = _load_session(session_b_path) if session_b_path else {}

    steps_by_id_a = {s.get("id"): s for s in session_a.get("steps", [])}
    steps_by_id_b = {s.get("id"): s for s in session_b.get("steps", [])}
    assertions_by_id_a = {a.get("id"): a for a in session_a.get("assertions", [])}
    assertions_by_id_b = {a.get("id"): a for a in session_b.get("assertions", [])}
    step_scores_by_id_a = _load_step_scores_by_step(session_a_path)
    step_scores_by_id_b = _load_step_scores_by_step(session_b_path) if session_b_path else {}

    # Build map: step_id → list of assertions
    assertions_by_step: Dict[str, List[Dict]] = {}
    for a in ref_assertions:
        sid = a.get("params", {}).get("step_id")
        if sid:
            assertions_by_step.setdefault(sid, []).append(a)
    unlinked_assertions = [a for a in ref_assertions if not a.get("params", {}).get("step_id")]

    # ── Column headers ───────────────────────────────────────────────────────
    st.divider()
    hdr_scenario, hdr_a, hdr_b = st.columns([1, 2, 2])

    with hdr_scenario:
        st.markdown("### 📋 Scenario")
        st.caption(f"`{selected_scenario_name}`")
        st.caption(f"{len(ref_steps)} steps · {len(ref_assertions)} assertions")

    _render_session_header(session_a, hdr_a, "🔵 Session A")
    if session_b_path:
        _render_session_header(session_b, hdr_b, "🟢 Session B")
    else:
        hdr_b.markdown("### — Session B")
        hdr_b.info("No session selected")

    # ── Steps ────────────────────────────────────────────────────────────────
    st.divider()

    for i, ref_step in enumerate(ref_steps):
        step_id = ref_step.get("id", f"step_{i + 1}")
        step_assertions = assertions_by_step.get(step_id, [])

        cols = st.columns([1, 2, 2])

        with cols[0]:
            _render_expected_step(
                ref_step=ref_step,
                assertions_for_step=step_assertions,
                session_a_step=steps_by_id_a.get(step_id),
                session_b_step=steps_by_id_b.get(step_id) if session_b_path else None,
                session_a_config=_session_config_description(session_a),
                session_b_config=_session_config_description(session_b) if session_b_path else {},
                session_a_scores=step_scores_by_id_a.get(step_id, []),
                session_b_scores=step_scores_by_id_b.get(step_id, []) if session_b_path else [],
                export_key=f"{selected_scenario_name}_{step_id}_{i}",
            )

        with cols[1]:
            step_a = steps_by_id_a.get(step_id)
            _render_session_step(
                step_data=step_a,
                ref_step=ref_step,
                assertions_for_step=step_assertions,
                assertions_results=assertions_by_id_a,
                step_scores_by_id=step_scores_by_id_a,
                session_key="a",
                step_idx=i,
            )

        with cols[2]:
            if session_b_path:
                step_b = steps_by_id_b.get(step_id)
                _render_session_step(
                    step_data=step_b,
                    ref_step=ref_step,
                    assertions_for_step=step_assertions,
                    assertions_results=assertions_by_id_b,
                    step_scores_by_id=step_scores_by_id_b,
                    session_key="b",
                    step_idx=i,
                )
            else:
                with st.container(border=True):
                    st.markdown("—")

    # ── Unlinked assertions summary ──────────────────────────────────────────
    if unlinked_assertions and (session_a or session_b):
        st.divider()
        st.markdown("### 📋 Global Assertions")
        for assertion in unlinked_assertions:
            aid = assertion.get("id")
            cols = st.columns([1, 2, 2])
            with cols[0]:
                st.markdown(f"**`{aid}`** · `{assertion.get('type', '?')}`")
                st.caption(assertion.get("description", ""))
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
                if session_b_path:
                    b_result = assertions_by_id_b.get(aid, {})
                    if b_result:
                        if b_result.get("passed"):
                            st.success(f"✅ {b_result.get('message', 'Passed')}")
                        else:
                            st.error(f"❌ {b_result.get('message', 'Failed')}")
                    else:
                        st.info("—")
                else:
                    st.info("—")

    # ── Evaluations (scoring runs) ───────────────────────────────────────────
    _render_evaluations_section(session_a_path, session_b_path, ref_steps)

def inject_ui_main_footer():
    pass
