"""Streamlit UI for benchmarker module."""

import os
from typing import Dict, List

import streamlit as st
import yaml

from shared.common import get_driver

from modules.benchmarker.analyser import Analyser
from modules.benchmarker.matrix_runner import MatrixRunner

from modules.benchmarker.benchmarker import BenchmarkRun, ScoringRun
from modules.benchmarker.comparer import Comparer
from modules.benchmarker.runner import RunResult, ScenarioRunner
from modules.benchmarker.scoring_pipeline import get_scoring_pipeline


from st_shared.cached import _, get_db_manager

def _t(key: str) -> str:
    return _(f"benchmarker.{key}")


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

    with st.expander(_t("step_log"), expanded=False):
        for step in run_result.steps:
            status = "✅" if step.success else "❌"
            with st.expander(f"[{step.actor}] {step.action} — {status} ({step.duration_seconds:.2f}s)", expanded=False):
                st.code(yaml.safe_dump({"params": step.params, "result": step.result}, sort_keys=False), language="yaml")
                if step.error:
                    st.error(step.error)

    with st.expander(_t("raw_events"), expanded=False):
        st.code(yaml.safe_dump(events, sort_keys=False), language="yaml")
        if run_result.session_path and os.path.exists(run_result.session_path):
            with open(run_result.session_path, "r", encoding="utf-8") as handle:
                st.download_button(_t("download_session_yaml"), data=handle.read(), file_name=os.path.basename(run_result.session_path))


def _render_judge_tab(runner: ScenarioRunner) -> None:
    sessions_dir = runner.config.get("sessions_dir", "data/benchmarker/sessions")
    session_files = _list_sessions(sessions_dir)
    if not session_files:
        st.info(_t("no_history"))
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

    selected_label = st.selectbox(_t("judge_select_session"), labels)
    selected_index = labels.index(selected_label)
    selected_session = session_files[selected_index]

    session_data = {}
    if selected_session and os.path.exists(selected_session):
        with open(selected_session, "r", encoding="utf-8") as handle:
            session_data = yaml.safe_load(handle) or {}

    configuration = (session_data.get("meta", {}) or {}).get("configuration", {})
    with st.expander(_t("session_configuration"), expanded=False):
        st.code(yaml.safe_dump(configuration, sort_keys=False), language="yaml")

    scorers = pipeline.list_scorers()
    available = [item for item in scorers if item.get("available")]
    unavailable = [item for item in scorers if not item.get("available")]

    if unavailable:
        st.caption("Unavailable scorers: " + ", ".join(f"{item['name']} (unavailable)" for item in unavailable))

    if not available:
        st.warning(_t("no_available_scorers"))
        return

    automatable = [item for item in available if item.get("id") not in {"manual", "llm_external"}]
    if st.button(_t("score_all"), key=f"score_all_{selected_session}"):
        score_all_container = st.container()
        if not automatable:
            score_all_container.warning(_t("no_automatable_scorers"))
        else:
            completed = 0
            failed = 0
            for scorer_item in automatable:
                scorer = pipeline.get_scorer(scorer_item["id"])
                if scorer is None:
                    failed += 1
                    continue

                score_all_container.info(f"Running scorer: {scorer_item['name']} ({scorer_item['id']})")
                try:
                    if scorer_item["id"] == "llm_internal" and hasattr(scorer, "compute_score_all_rubrics"):
                        scorer.compute_score_all_rubrics(
                            session=session_data,
                            config={"session_path": selected_session, "batch_mode": True},
                            container=score_all_container,
                        )
                    else:
                        scorer.compute_score(
                            session=session_data,
                            config={"session_path": selected_session, "batch_mode": True},
                            container=score_all_container,
                        )
                    completed += 1
                except Exception as exc:
                    failed += 1
                    score_all_container.warning(f"Scorer {scorer_item['id']} failed: {exc}")

            score_all_container.info(
                f"Score All complete: {completed} scorer(s) completed, {failed} failed."
            )

    scorer_labels = [item["name"] for item in available]
    selected_scorer_label = st.selectbox(_t("scorer"), scorer_labels)
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
        st.subheader(_t("past_scores"))
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
        st.info(_t("compare_no_runs"))
        return

    scenario_name = st.selectbox(_t("compare_select_scenario"), scenarios)

    if st.button(_t("compare_clean_scores_button"), key=f"bench_compare_clean_scores_{scenario_name}"):
        with get_db_manager().get_session() as session:
            run_ids = [rid for (rid,) in session.query(BenchmarkRun.id).filter(BenchmarkRun.scenario_name == scenario_name).all()]
            if run_ids:
                deleted = session.query(ScoringRun).filter(ScoringRun.run_id.in_(run_ids)).delete(synchronize_session=False)
            else:
                deleted = 0
        st.success(_t("compare_scores_cleared").format(count=deleted, scenario=scenario_name))

    scenario_runs = [run for run in db_runs if run["scenario_name"] == scenario_name]
    available_group_choices = sorted(set(sorted(get_driver().list_options().keys())) | {key for run in scenario_runs for key in run["options"].keys()})
    if not available_group_choices:
        available_group_choices = ["memory_backend"]

    st.caption(_t("compare_runs_grouped_caption"))
    for group_name in available_group_choices:
        with st.expander(f"Group: {group_name}", expanded=False):
            preview_report = Comparer().compare(scenario_name, group_by=group_name)
            preview_rows = [
                {
                    "group_value": group.option_value,
                    "runs": group.run_count,
                    "assertions_pass_rate": round(group.assertions_pass_rate, 3),
                    "avg_tokens": round(group.avg_tokens, 1),
                    "avg_duration_seconds": round(group.avg_duration_seconds, 3),
                }
                for group in preview_report.groups
            ]
            st.dataframe(preview_rows, width="stretch")

    st.caption(_t("compare_help_caption"))
    group_by = st.selectbox(_t("compare_group_by"), available_group_choices)
    invert = st.checkbox("Invert rows/columns in display", key=f"compare_invert_{scenario_name}_{group_by}")

    if st.button(_t("compare_run_button")):
        report = Comparer().compare(scenario_name, group_by=group_by)
        if not report.groups:
            st.info(_t("compare_no_runs"))
            return

        has_scores = any(any((stats.get("runs_scored", 0) > 0) for stats in g.scoring.values()) for g in report.groups)
        if not has_scores:
            st.warning(_t("compare_no_scores"))

        table = []
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

        if invert and table:
            metrics = list(table[0].keys())
            inverted_rows = []
            for metric in metrics:
                inv_row = {"metric": metric}
                for row in table:
                    val = row.get(metric)
                    inv_row[row["option"]] = str(val) if val is not None else ""
                inverted_rows.append(inv_row)
            st.dataframe(inverted_rows, width="stretch")
        else:
            st.dataframe(table, width="stretch")

        yaml_report = Comparer().to_yaml(report)
        st.download_button(_t("compare_download"), data=yaml_report, file_name=f"compare__{scenario_name}__{group_by}.yaml")


def _config_label(llm_id: str, memory_backend: str, rag_engine: str) -> str:
    return f"{llm_id or '-'} / {memory_backend or '-'} / {rag_engine or '-'}"


def _render_matrix_tab(runner: ScenarioRunner) -> None:
    scenarios_dir = runner.config.get("scenarios_dir", "modules/benchmarker/scenarios")
    if not os.path.isdir(scenarios_dir):
        st.warning(_t("no_scenarios_found"))
        return

    scenario_files = sorted([f for f in os.listdir(scenarios_dir) if f.endswith(".yaml")])
    scenario_paths = st.multiselect(
        _t("matrix_scenarios_label"),
        [os.path.join(scenarios_dir, f) for f in scenario_files],
        format_func=lambda path: os.path.basename(path),
    )

    options_map = get_driver().list_options()
    llm_options = [opt.get("name") for opt in options_map.get("llm", []) if opt.get("name")]
    memory_options = [opt.get("name") for opt in options_map.get("memory_backend", []) if opt.get("name")]
    rag_options = [opt.get("name") for opt in options_map.get("rag_engine", []) if opt.get("name")]

    llm_selected = st.multiselect(_t("matrix_llm_label"), ["None"] + llm_options, default=["None"])
    memory_selected = st.multiselect(_t("matrix_memory_label"), ["None"] + memory_options, default=["None"])
    rag_selected = st.multiselect(_t("matrix_rag_label"), ["None"] + rag_options, default=["None"])

    llm_ids = ["" if item == "None" else item for item in llm_selected] or [""]
    memory_backends = ["" if item == "None" else item for item in memory_selected] or [""]
    rag_engines = ["" if item == "None" else item for item in rag_selected] or [""]

    student_override = st.text_input(_t("matrix_student_label"), value="")
    trainer_override = st.text_input(_t("matrix_trainer_label"), value="")

    n_scenarios = len(scenario_paths)
    n_combos = len(llm_ids or [""]) * len(memory_backends or [""]) * len(rag_engines or [""])
    total = n_scenarios * n_combos
    st.caption(_t("matrix_preview").format(
        n_scenarios=n_scenarios, n_combos=n_combos, total=total
    ))

    if st.button(_t("matrix_validate_button")):
        warnings = MatrixRunner().validate_matrix(scenario_paths, llm_ids, memory_backends, rag_engines)
        blocking = [w for w in warnings if w.blocking]
        non_blocking = [w for w in warnings if not w.blocking]
        st.caption(_t("matrix_warning_counts").format(
            blocking=len(blocking), non_blocking=len(non_blocking)
        ))
        if warnings:
            st.dataframe([
                {
                    "scenario": os.path.basename(w.scenario_path),
                    "llm": w.cell.llm_id or "-",
                    "memory_backend": w.cell.memory_backend or "-",
                    "rag_engine": w.cell.rag_engine or "-",
                    "message": w.message,
                    "blocking": w.blocking,
                }
                for w in warnings
            ], width="stretch")
        else:
            st.success(_t("matrix_no_warnings"))

        blocking_combo_count = len({f"{w.scenario_path}|{w.cell.llm_id}|{w.cell.memory_backend}|{w.cell.rag_engine}" for w in blocking})
        st.info(_t("matrix_ready").format(
            n=max(total - blocking_combo_count, 0), m=blocking_combo_count
        ))

    if not scenario_paths:
        st.warning(_t("matrix_need_scenarios"))
        return

    run_col, run_score_col = st.columns(2)
    run_clicked = run_col.button(_t("matrix_run_button"), width="stretch")
    run_and_score_clicked = run_score_col.button(_t("matrix_run_and_score_button"), width="stretch")

    if run_clicked or run_and_score_clicked:
        progress = st.empty()

        def _progress(i: int, total_count: int, label: str) -> None:
            progress.info(_t("matrix_running_progress").format(i=i, total=total_count, label=label))

        matrix_runner = MatrixRunner(progress_callback=_progress)
        with st.spinner(_t("matrix_running_spinner")):
            result = matrix_runner.run_matrix(
                scenario_paths=scenario_paths,
                llm_ids=llm_ids,
                memory_backends=memory_backends,
                rag_engines=rag_engines,
                setup_overrides={"student_id": student_override, "trainer_id": trainer_override},
                auto_score=run_and_score_clicked,
            )

        m1, m2, m3, m4 = st.columns(4)
        m1.metric(_t("matrix_metric_total"), result.total)
        m2.metric(_t("matrix_metric_completed"), result.completed)
        m3.metric(_t("matrix_metric_failed"), result.failed)
        m4.metric(_t("matrix_metric_skipped"), result.skipped)

        rows = []
        for cell in result.cells:
            rr = cell.run_result
            rows.append({
                _t("matrix_col_scenario"): cell.scenario_name,
                _t("matrix_col_llm"): cell.cell.llm_id or "-",
                _t("matrix_col_memory"): cell.cell.memory_backend or "-",
                _t("matrix_col_rag"): cell.cell.rag_engine or "-",
                _t("matrix_col_success"): bool(rr.success) if rr else False,
                _t("matrix_col_assertions"): f"{rr.assertions_passed}/{rr.assertions_total}" if rr else "0/0",
                _t("matrix_col_session"): cell.session_path,
            })
        st.dataframe(rows, width="stretch")


def _render_analysis_tab() -> None:
    with get_db_manager().get_session() as db:
        scenarios = sorted({row.scenario_name for row in db.query(BenchmarkRun).all()})

    selected_scenarios = st.multiselect(_t("analysis_scenario_filter"), scenarios)
    matrix_only = st.checkbox(_t("analysis_matrix_only"), value=False)

    if not st.button(_t("analysis_run_button")):
        return

    analyser = Analyser()
    dataset = analyser.load_data(scenario_filter=selected_scenarios or None, matrix_only=matrix_only)
    report = analyser.analyse(dataset)

    if report.n_runs == 0:
        st.info(_t("analysis_empty"))
        return

    with st.expander(_t("analysis_section_overview"), expanded=True):
        m1, m2, m3 = st.columns(3)
        m1.metric("n_runs", report.n_runs)
        m2.metric("n_scenarios", report.n_scenarios)
        m3.metric("n_configurations", len(report.configurations))
        counts = {}
        for row in report.raw_rows:
            label = _config_label(row.llm_id, row.memory_backend, row.rag_engine)
            counts[label] = counts.get(label, 0) + 1
        st.dataframe([{"configuration": k, "runs": v} for k, v in sorted(counts.items())], width="stretch")

    with st.expander(_t("analysis_section_metrics"), expanded=False):
        if not report.dimensions:
            st.info(_t("analysis_no_metrics"))
        else:
            scorer_groups = {}
            for dim in report.dimensions:
                scorer_groups.setdefault(dim.scorer_id or "built_in", []).append(dim)
            for scorer_id, dims in scorer_groups.items():
                with st.expander(f"{scorer_id}", expanded=False):
                    for dim in dims:
                        table = []
                        for config, stats in dim.config_stats.items():
                            table.append({"config": config, **stats.__dict__})
                        st.caption(f"{dim.metric_name} — best: {dim.best_config}")
                        st.dataframe(table, width="stretch")

    with st.expander(_t("analysis_section_pairwise"), expanded=False):
        pairs = report.config_comparison.pairwise
        if not pairs:
            st.info(_t("analysis_no_pairwise"))
        else:
            configs = report.configurations
            matrix_rows = []
            pair_map = {}
            for pair in pairs:
                pair_map[(pair.config_a, pair.config_b)] = pair
                pair_map[(pair.config_b, pair.config_a)] = pair
            for row_cfg in configs:
                row = {"config": row_cfg}
                for col_cfg in configs:
                    if row_cfg == col_cfg:
                        row[col_cfg] = "-"
                        continue
                    pair = pair_map.get((row_cfg, col_cfg))
                    if not pair:
                        row[col_cfg] = ""
                    elif pair.config_a == row_cfg:
                        row[col_cfg] = f"{pair.metrics_a_wins} / {pair.metrics_b_wins} / {pair.metrics_tied}"
                    else:
                        row[col_cfg] = f"{pair.metrics_b_wins} / {pair.metrics_a_wins} / {pair.metrics_tied}"
                matrix_rows.append(row)
            st.dataframe(matrix_rows, width="stretch")

            wins = {cfg: 0 for cfg in configs}
            for pair in pairs:
                wins[pair.config_a] += pair.metrics_a_wins
                wins[pair.config_b] += pair.metrics_b_wins
                if pair.a_always_better:
                    st.success(_t("analysis_always_better").format(a=pair.config_a, b=pair.config_b))
                if pair.b_always_better:
                    st.success(_t("analysis_always_better").format(a=pair.config_b, b=pair.config_a))
            for idx, item in enumerate(sorted(wins.items(), key=lambda x: x[1], reverse=True), start=1):
                st.write(f"{idx}. {item[0]} — {item[1]} metric wins across all comparisons")

    with st.expander(_t("analysis_section_dominance"), expanded=False):
        dom_rows = [
            {
                "config": item.config,
                "dominated_by": item.dominated_by or "",
                "dominates": ", ".join(item.dominates),
                "rank_by_wins": item.rank_by_wins,
            }
            for item in report.config_comparison.dominance
        ]
        if not dom_rows:
            st.info(_t("analysis_no_dominance"))
        else:
            st.dataframe(dom_rows, width="stretch")

    st.download_button(
        _t("analysis_download"),
        data=analyser.to_yaml(report),
        file_name="benchmarker_analysis.yaml",
    )


def render() -> None:
    """Render benchmarker UI with benchmark execution, scoring and analysis tabs."""
    runner = ScenarioRunner()

    run_tab, history_tab, judge_tab, compare_tab, matrix_tab, analysis_tab, diagnose_tab = st.tabs([
        _t("run_tab_title"),
        _t("history_tab_title"),
        _t("judge_tab_title"),
        _t("compare_tab_title"),
        _t("matrix_tab_title"),
        _t("analysis_tab_title"),
        _t("diagnose_tab_title"),
    ])

    with run_tab:
        scenarios_dir = runner.config.get("scenarios_dir", "modules/benchmarker/scenarios")
        if not os.path.isdir(scenarios_dir):
            st.warning(_t("no_scenarios_found"))
            return

        scenario_files = sorted([f for f in os.listdir(scenarios_dir) if f.endswith(".yaml")])
        if not scenario_files:
            st.warning(_t("no_scenarios_found"))
            return

        selected = st.selectbox(_t("scenario"), scenario_files)
        scenario_path = os.path.join(scenarios_dir, selected)
        scenario = _load_scenario(scenario_path)

        meta = scenario.get("meta", {})
        st.caption(meta.get("description", ""))
        st.caption(
            _t("scenario_preview").format(
                step_count=len(scenario.get("steps", [])),
                options_summary=str(scenario.get("options", {})),
            )
        )
        st.caption(
            _t("diagnose_actor_caption")
        )

        with st.expander(_t("scenario_steps"), expanded=True):
            for step in scenario.get("steps", []):
                st.write(f"- {step.get('id', '?')}: [{step.get('actor', '?')}] {step.get('action', '?')}")

        setup = scenario.get("setup", {})
        scenario_options = scenario.get("options", {})

        with st.expander(_t("overrides"), expanded=True):
            student_override = st.text_input(_t("student_id"), value=setup.get("student_id", ""))
            trainer_override = st.text_input(_t("teacher_id"), value=setup.get("trainer_id", ""))
            llm_override = st.text_input(_t("llm_id"), value=scenario.get("llm", "")).strip()

            options_map = get_driver().list_options()
            memory_choices = [opt["name"] for opt in options_map.get("memory_backend", [])]
            memory_default = scenario_options.get("memory_backend", "")
            if memory_choices:
                index = memory_choices.index(memory_default) if memory_default in memory_choices else 0
                memory_backend_override = st.selectbox(_t("memory_backend"), memory_choices, index=index)
            else:
                memory_backend_override = st.text_input(_t("memory_backend"), value=memory_default)

            rag_choices = [opt["name"] for opt in options_map.get("rag_engine", [])]
            rag_default = scenario_options.get("rag_engine", "")
            if rag_choices:
                index = rag_choices.index(rag_default) if rag_default in rag_choices else 0
                rag_engine_override = st.selectbox(_t("rag_engine"), rag_choices, index=index)
            else:
                rag_engine_override = st.text_input(_t("rag_engine"), value=rag_default)

        if st.button(_t("run_scenario_button")):
            with st.spinner(_t("running_spinner")):
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
            st.info(_t("no_history"))
        else:
            st.dataframe(rows, width="stretch")
            selected_session = st.selectbox(
                _t("history_select_session"),
                [r["session_file"] for r in rows],
                key="benchmarker_history_selected_session",
            )
            if selected_session and os.path.exists(selected_session):
                with st.expander(_t("session_yaml"), expanded=False):
                    with open(selected_session, "r", encoding="utf-8") as handle:
                        st.code(handle.read(), language="yaml")
            elif selected_session:
                st.warning(f"Session file not found: {selected_session}")

        if st.button(_t("clear_history")):
            with get_db_manager().get_session() as session:
                for record in session.query(BenchmarkRun).all():
                    if record.session_file and os.path.exists(record.session_file):
                        os.remove(record.session_file)
                    session.delete(record)
                for score in session.query(ScoringRun).all():
                    session.delete(score)
            st.success(_t("history_cleared"))

    with judge_tab:
        _render_judge_tab(runner)

    with compare_tab:
        _render_compare_tab()

    with matrix_tab:
        _render_matrix_tab(runner)

    with analysis_tab:
        _render_analysis_tab()

    with diagnose_tab:
        driver = get_driver()

        st.subheader(f"🔌 {_t('diagnose_options_header')}")
        options_map = driver.list_options()
        if not options_map:
            st.warning(
                _t("diagnose_no_options")
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

        st.subheader(f"⚡ {_t('diagnose_actions_header')}")
        actions = driver.list_actions()
        if not actions:
            st.warning(_t("diagnose_no_actions"))
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

        st.subheader(f"✅ {_t('diagnose_validator_header')}")
        scenarios_dir = runner.config.get("scenarios_dir", "modules/benchmarker/scenarios")
        if os.path.isdir(scenarios_dir):
            scenario_files = sorted([f for f in os.listdir(scenarios_dir) if f.endswith(".yaml")])
        else:
            scenario_files = []

        if not scenario_files:
            st.warning(_t("no_scenarios_found"))
        else:
            selected = st.selectbox(_t("scenario"), scenario_files, key="benchmarker_diagnose_scenario")
            scenario_path = os.path.join(scenarios_dir, selected)
            scenario = _load_scenario(scenario_path)
            validation_errors = ScenarioRunner().validate_scenario(scenario)
            if not validation_errors:
                st.success(_t("diagnose_scenario_valid"))
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

        st.subheader(f"🔍 {_t('diagnose_context_header')}")
        context = driver.get_context()
        not_set = _t("diagnose_context_not_set")
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
