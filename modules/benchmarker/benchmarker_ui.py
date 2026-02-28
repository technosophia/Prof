"""Streamlit UI for benchmarker module."""

import os
from typing import Dict, List

import streamlit as st
import yaml

from shared.common import get_driver, get_prompt

from modules.benchmarker.benchmarker import BenchmarkRun, ScoringRun
from modules.benchmarker.comparer import Comparer
from modules.benchmarker.runner import RunResult, ScenarioRunner
from modules.benchmarker.scoring_pipeline import get_scoring_pipeline


from st_shared.cached import get_db_manager
def _p(key: str, default: str) -> str:
    return get_prompt(f"benchmarker.{key}", default)


def _load_scenario(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _list_sessions(sessions_dir: str) -> List[str]:
    if not os.path.isdir(sessions_dir):
        return []
    return sorted([os.path.join(sessions_dir, f) for f in os.listdir(sessions_dir) if f.endswith(".yaml")], reverse=True)




def _flatten_options(options: Dict) -> Dict:
    flattened = {}
    for key, value in (options or {}).items():
        flattened[f"option_{key}"] = value
    return flattened


def _render_results(run_result: RunResult, events: List[Dict]) -> None:
    if run_result.errors:
        st.error("Run errors:\n" + "\n".join(f"- {err}" for err in run_result.errors))

    failed = run_result.assertions_total - run_result.assertions_passed
    bar = (
        f"{run_result.assertions_passed}/{run_result.assertions_total} assertions passed"
        f"  |  {len(run_result.steps)} steps"
        f"  |  {run_result.summary.get('total_llm_calls', 0)} LLM calls"
        f"  |  {run_result.summary.get('total_tokens', 0)} tokens"
        f"  |  {run_result.summary.get('duration_seconds', 0):.1f}s"
    )
    if failed == 0 and not run_result.errors:
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
    st.dataframe(rows, width="stretch")

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


def _render_judge_tab(runner: ScenarioRunner) -> None:
    sessions_dir = runner.config.get("sessions_dir", "data/benchmarker/sessions")
    session_files = _list_sessions(sessions_dir)
    if not session_files:
        st.info(_p("no_history", "No benchmark runs recorded yet."))
        return

    pipeline = get_scoring_pipeline()

    labels = []
    for path in session_files:
        label = os.path.basename(path)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    meta = (yaml.safe_load(handle) or {}).get("meta", {})
                run_at = meta.get("run_at")
                if run_at:
                    label = f"{os.path.basename(path)}  |  {run_at}"
            except Exception:
                pass
        labels.append(label)

    selected_label = st.selectbox(_p("judge_select_session", "Select session to score"), labels)
    selected_index = labels.index(selected_label)
    selected_session = session_files[selected_index]

    session_data = {}
    if selected_session and os.path.exists(selected_session):
        with open(selected_session, "r", encoding="utf-8") as handle:
            session_data = yaml.safe_load(handle) or {}

    configuration = (session_data.get("meta", {}) or {}).get("configuration", {})
    with st.expander("Session configuration", expanded=False):
        st.code(yaml.safe_dump(configuration, sort_keys=False), language="yaml")

    scorers = pipeline.list_scorers()
    available = [item for item in scorers if item.get("available")]
    unavailable = [item for item in scorers if not item.get("available")]

    if unavailable:
        st.caption("Unavailable scorers: " + ", ".join(f"{item['name']} (unavailable)" for item in unavailable))

    if not available:
        st.warning("No available scorers found.")
        return

    scorer_labels = [item["name"] for item in available]
    selected_scorer_label = st.selectbox("Scorer", scorer_labels)
    selected_scorer = available[scorer_labels.index(selected_scorer_label)]

    scorer = pipeline.get_scorer(selected_scorer["id"])
    judge_container = st.container()
    if scorer is not None:
        scorer.compute_score(
            session=session_data,
            config={"session_path": selected_session},
            container=judge_container,
        )

    results = pipeline.load_results(selected_session)
    if results:
        st.subheader("Past scores")
        st.dataframe(
            [
                {
                    "scorer_id": result.scorer_id,
                    "source": result.source,
                    "scored_at": result.scored_at,
                    "scores": result.scores,
                    "overall_score": result.overall,
                    "complete": result.complete,
                }
                for result in results
            ],
            width="stretch",
        )


def _render_compare_tab() -> None:
    with get_db_manager().get_session() as db:
        db_rows = db.query(BenchmarkRun).order_by(BenchmarkRun.run_at.desc()).all()
        db_runs = [
            {
                "run_at": row.run_at,
                "scenario_name": row.scenario_name,
                "session_file": row.session_file,
                "options": dict(row.options or {}),
            }
            for row in db_rows
        ]
        scenarios = sorted({run["scenario_name"] for run in db_runs})

    if not scenarios:
        st.info(_p("compare_no_runs", "No runs found for this scenario."))
        return

    st.caption("Runs grouped by available option groups")
    all_groups = sorted({key for run in db_runs for key in run["options"].keys()})
    for group_name in all_groups:
        with st.expander(f"Group: {group_name}", expanded=False):
            grouped_rows = []
            for run in db_runs:
                grouped_rows.append(
                    {
                        "run_at": str(run["run_at"]),
                        "scenario": run["scenario_name"],
                        "session_file": run["session_file"],
                        "value": run["options"].get(group_name, "<unset>"),
                        **_flatten_options(run["options"]),
                    }
                )
            st.dataframe(grouped_rows, width="stretch")

    scenario_name = st.selectbox(_p("compare_select_scenario", "Select scenario"), scenarios)
    st.caption(
        "Select a scenario, then choose which option to compare across runs. "
        "Each run with a different option value becomes one column in the comparison."
    )
    group_choices = sorted(get_driver().list_options().keys()) or ["memory_backend"]
    group_by = st.selectbox(_p("compare_group_by", "Group by option"), group_choices)
    invert = st.checkbox("Invert rows/columns in display", key=f"compare_invert_{scenario_name}_{group_by}")

    if st.button(_p("compare_run_button", "Generate comparison")):
        report = Comparer().compare(scenario_name, group_by=group_by)
        if not report.groups:
            st.info(_p("compare_no_runs", "No runs found for this scenario."))
            return

        has_scores = any(any((stats.get("runs_scored", 0) > 0) for stats in g.scoring.values()) for g in report.groups)
        if not has_scores:
            st.warning(_p("compare_no_scores", "No scores available yet — run scoring first."))

        table = []
        scorer_names = sorted({scorer_name for group in report.groups for scorer_name in group.scoring.keys()})
        for g in report.groups:
            row = {
                "option": g.option_value,
                "run_count": g.run_count,
                "assertions_pass_rate": round(g.assertions_pass_rate, 3),
                "avg_tokens": round(g.avg_tokens, 1),
                "avg_duration_seconds": round(g.avg_duration_seconds, 3),
            }
            for scorer_name, scorer_stats in g.scoring.items():
                row[f"{scorer_name}.runs_scored"] = scorer_stats.get("runs_scored", 0)
                row[f"{scorer_name}.scores"] = scorer_stats.get("scores", {})
                row[f"{scorer_name}.overall"] = scorer_stats.get("overall")
            table.append(row)

        if invert:
            inverted = []
            for scorer_name in scorer_names:
                inv_row = {"scorer": scorer_name}
                for g in report.groups:
                    inv_row[f"{g.option_value}.runs_scored"] = g.scoring.get(scorer_name, {}).get("runs_scored", 0)
                    inv_row[f"{g.option_value}.scores"] = g.scoring.get(scorer_name, {}).get("scores", {})
                    inv_row[f"{g.option_value}.overall"] = g.scoring.get(scorer_name, {}).get("overall")
                inverted.append(inv_row)
            st.dataframe(inverted, width="stretch")
        else:
            st.dataframe(table, width="stretch")

        yaml_report = Comparer().to_yaml(report)
        st.download_button(_p("compare_download", "Download report YAML"), data=yaml_report, file_name=f"compare__{scenario_name}__{group_by}.yaml")


def render() -> None:
    """Render benchmarker UI with Run, History, Judge, Compare and Diagnose tabs."""
    runner = ScenarioRunner()

    run_tab, history_tab, judge_tab, compare_tab, diagnose_tab = st.tabs([
        _p("run_tab_title", "Run Scenario"),
        _p("history_tab_title", "History"),
        _p("judge_tab_title", "Judge"),
        _p("compare_tab_title", "Compare"),
        _p("diagnose_tab_title", "Diagnose"),
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
        st.caption(
            _p(
                "diagnose_actor_caption",
                "Actor mapping: 'student' → student_id | 'teacher' → trainer_id | 'system' → setup actions",
            )
        )

        with st.expander("Scenario steps", expanded=True):
            for step in scenario.get("steps", []):
                st.write(f"- {step.get('id', '?')}: [{step.get('actor', '?')}] {step.get('action', '?')}")

        setup = scenario.get("setup", {})
        scenario_options = scenario.get("options", {})

        with st.expander("Overrides", expanded=True):
            student_override = st.text_input("Student ID", value=setup.get("student_id", ""))
            trainer_override = st.text_input("Teacher ID", value=setup.get("trainer_id", ""))
            llm_override = st.text_input("LLM ID", value=scenario.get("llm", "")).strip()

            options_map = get_driver().list_options()
            memory_choices = [opt["name"] for opt in options_map.get("memory_backend", [])]
            memory_default = scenario_options.get("memory_backend", "")
            if memory_choices:
                index = memory_choices.index(memory_default) if memory_default in memory_choices else 0
                memory_backend_override = st.selectbox("Memory backend", memory_choices, index=index)
            else:
                memory_backend_override = st.text_input("Memory backend", value=memory_default)

            rag_choices = [opt["name"] for opt in options_map.get("rag_engine", [])]
            rag_default = scenario_options.get("rag_engine", "")
            if rag_choices:
                index = rag_choices.index(rag_default) if rag_default in rag_choices else 0
                rag_engine_override = st.selectbox("RAG engine", rag_choices, index=index)
            else:
                rag_engine_override = st.text_input("RAG engine", value=rag_default)

        if st.button("▶ Run Scenario"):
            with st.spinner(_p("running_spinner", "Replaying scenario...")):
                option_overrides = {}
                if memory_backend_override:
                    option_overrides["memory_backend"] = memory_backend_override
                if rag_engine_override:
                    option_overrides["rag_engine"] = rag_engine_override

                setup_overrides = {
                    "student_id": student_override,
                    "trainer_id": trainer_override,
                }
                result = runner.run(
                    scenario_path,
                    option_overrides=option_overrides,
                    setup_overrides=setup_overrides,
                    llm_override=llm_override,
                )
                st.session_state["benchmarker_last_result"] = result
                st.session_state["benchmarker_last_events"] = get_driver().get_session_events()

        if "benchmarker_last_result" in st.session_state:
            _render_results(st.session_state["benchmarker_last_result"], st.session_state.get("benchmarker_last_events", []))

    with history_tab:
        with get_db_manager().get_session() as session:
            db_runs = session.query(BenchmarkRun).order_by(BenchmarkRun.run_at.desc()).all()
            rows = [
                {
                    "run_at": str(r.run_at),
                    "scenario_name": r.scenario_name,
                    **_flatten_options(r.options or {}),
                    "success": bool(r.success),
                    "assertions": f"{r.assertions_passed}/{r.assertions_total}",
                    "duration_seconds": r.duration_seconds,
                    "session_file": r.session_file,
                }
                for r in db_runs
            ]

        if not rows:
            st.info(_p("no_history", "No benchmark runs recorded yet."))
        else:
            st.dataframe(rows, width="stretch")
            selected_session = st.selectbox(
                "Select session file",
                [r["session_file"] for r in rows],
                key="benchmarker_history_selected_session",
            )
            if selected_session and os.path.exists(selected_session):
                with st.expander("Session YAML", expanded=False):
                    with open(selected_session, "r", encoding="utf-8") as handle:
                        st.code(handle.read(), language="yaml")
            elif selected_session:
                st.warning(f"Session file not found: {selected_session}")

        if st.button("Clear history"):
            with get_db_manager().get_session() as session:
                for record in session.query(BenchmarkRun).all():
                    if record.session_file and os.path.exists(record.session_file):
                        os.remove(record.session_file)
                    session.delete(record)
                for score in session.query(ScoringRun).all():
                    session.delete(score)
            st.success("History cleared")

    with judge_tab:
        _render_judge_tab(runner)

    with compare_tab:
        _render_compare_tab()

    with diagnose_tab:
        driver = get_driver()

        st.subheader(f"🔌 {_p('diagnose_options_header', 'Registered Options')}")
        options_map = driver.list_options()
        if not options_map:
            st.warning(
                _p(
                    "diagnose_no_options",
                    "No options registered. Check that modules with driver registration are enabled.",
                )
            )
        else:
            for group, options in options_map.items():
                st.markdown(f"**{group}**")
                active_name = driver.get_active_option(group)
                for option in options:
                    is_active = active_name == option.get("name")
                    marker = "🟢 ✓ active" if is_active else "⚪"
                    st.write(
                        f"{marker} `{option.get('name', '')}` — {option.get('description', '')}"
                    )

        st.subheader(f"⚡ {_p('diagnose_actions_header', 'Registered Actions')}")
        actions = driver.list_actions()
        if not actions:
            st.warning(_p("diagnose_no_actions", "No actions registered. Check that the benchmarker initialized correctly."))
        else:
            st.dataframe(
                [
                    {
                        "action name": action.get("name", ""),
                        "description": action.get("description", ""),
                        "required context": ", ".join(action.get("required_context", [])) or "(none)",
                    }
                    for action in actions
                ],
                width="stretch",
            )

        st.subheader(f"✅ {_p('diagnose_validator_header', 'Scenario Validator')}")
        scenarios_dir = runner.config.get("scenarios_dir", "modules/benchmarker/scenarios")
        if os.path.isdir(scenarios_dir):
            scenario_files = sorted([f for f in os.listdir(scenarios_dir) if f.endswith(".yaml")])
        else:
            scenario_files = []

        if not scenario_files:
            st.warning(_p("no_scenarios_found", "No scenario files found in the scenarios directory."))
        else:
            selected = st.selectbox("Scenario", scenario_files, key="benchmarker_diagnose_scenario")
            scenario_path = os.path.join(scenarios_dir, selected)
            scenario = _load_scenario(scenario_path)
            validation_errors = ScenarioRunner().validate_scenario(scenario)
            if not validation_errors:
                st.success(_p("diagnose_scenario_valid", "Scenario is valid — all options and actions are registered."))
            else:
                for err in validation_errors:
                    st.error(err)

            steps = scenario.get("steps", [])
            actor_counts: Dict[str, int] = {}
            required_actions = []
            for step in steps:
                actor = step.get("actor", "?")
                actor_counts[actor] = actor_counts.get(actor, 0) + 1
                action_name = step.get("action", "")
                if action_name and action_name not in required_actions:
                    required_actions.append(action_name)

            actors_summary = ", ".join([f"{actor} ({count})" for actor, count in actor_counts.items()])
            options_required = ", ".join(list((scenario.get("options") or {}).keys())) or "(none)"
            actions_required = ", ".join(required_actions) or "(none)"
            st.caption(
                f"Steps: {len(steps)} | Actors: {actors_summary}"
            )
            st.caption(f"Options required: {options_required}")
            st.caption(f"Actions required: {actions_required}")

        st.subheader(f"🔍 {_p('diagnose_context_header', 'Current Driver Context')}")
        context = driver.get_context()
        not_set = _p("diagnose_context_not_set", "not set")
        st.dataframe(
            [
                {"field": "student_id", "value": context.student_id or not_set},
                {"field": "trainer_id", "value": context.trainer_id or not_set},
                {"field": "conversation_id", "value": context.conversation_id or not_set},
                {"field": "llm_id", "value": context.llm_id or not_set},
            ],
            width="stretch",
            hide_index=True,
        )
        st.caption("Context is set at scenario run time. Between runs it may be stale from the last run.")


# Just to remove warning
def inject_ui_main_content():
    pass
