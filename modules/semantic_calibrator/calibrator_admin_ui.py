"""
modules/semantic_calibrator/calibrator_admin_ui.py
===================================================
Streamlit admin tab for the semantic calibrator module.

Injection point: inject_ui_admin_tab()
  → returns ("Semantic Calibrator", show_calibrator_admin_content)

UI flow
-------
1. Upload semantic_benchmark.yaml  (or paste YAML directly)
2. Select embedding models to test
3. Configure chunking parameters
4. Run calibration  (progress shown live via st.status)
5. View results per model: ranking table, per-category breakdown, raw scores
6. Download calibration_results.json  (consumed by test suite)
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st

from core.logging import log


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_module_config() -> dict:
    """Load this module's config from the app config."""
    try:
        from st_shared.cached import get_config
        cfg = get_config()
        return cfg.get("semantic_calibrator", {})
    except Exception:
        return {}


def _get_available_models(module_cfg: dict) -> List[dict]:
    """Return model list from engine (merges config + defaults)."""
    try:
        from modules.semantic_calibrator.calibrator_engine import list_available_models
        return list_available_models({"semantic_calibrator": module_cfg})
    except Exception as exc:
        log("warning", f"[calibrator_ui] Could not load model list: {exc}")
        return []


def _openai_key_available() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


def _render_ranking_table(results: dict):
    """Render a sortable model ranking table."""
    rows = []
    for model_key, cal in results.items():
        if cal.get("skipped"):
            rows.append({
                "Model": model_key,
                "Status": f"⚠ {cal.get('error', 'skipped')}",
                "Strict threshold": "—",
                "Weak threshold": "—",
                "Cont. threshold": "—",
                "Strict acc.": "—",
                "Cont. acc.": "—",
                "Sim separability": "—",
                "Cont separability": "—",
            })
        else:
            rows.append({
                "Model": model_key,
                "Status": "✓ OK",
                "Strict threshold": cal.get("recommended_similarity_threshold", "—"),
                "Weak threshold": cal.get("weak_similarity_threshold", "—"),
                "Cont. threshold": cal.get("recommended_containment_threshold", "—"),
                "Strict acc.": f"{cal.get('strong_similarity_accuracy', 0):.1%}",
                "Cont. acc.": f"{cal.get('containment_accuracy', 0):.1%}",
                "Sim separability": f"{cal.get('similarity_separability', 0):.4f}",
                "Cont separability": f"{cal.get('containment_separability', 0):.4f}",
            })

    # Sort by combined separability (best first)
    def _sort_key(row):
        try:
            # Convert string values back to floats for sorting
            sim_sep = float(row["Sim separability"]) if row["Sim separability"] != "—" else -999.0
            cont_sep = float(row["Cont separability"]) if row["Cont separability"] != "—" else -999.0
            return sim_sep + cont_sep
        except (ValueError, TypeError, KeyError):
            return -999.0

    rows.sort(key=_sort_key, reverse=True)
    st.dataframe(rows, width='stretch')


def _render_model_detail(model_key: str, cal: dict, benchmark: dict):
    """Render the per-model detail section."""
    if cal.get("skipped"):
        st.error(f"Model skipped: {cal.get('error', 'unknown error')}")
        return

    st.markdown("**Similarity thresholds**")
    col1, col2, col3 = st.columns(3)
    col1.metric(
        "Strict threshold (validation)",
        cal.get("recommended_similarity_threshold"),
        help="identical+strongly_related vs rest. For validating LLM responses.",
    )
    col2.metric(
        "Weak threshold (RAG)",
        cal.get("weak_similarity_threshold"),
        help="identical+strongly_related+related vs rest. For RAG retrieval.",
    )
    col3.metric(
        "Containment threshold",
        cal.get("recommended_containment_threshold"),
        help="Threshold for contains_concept().",
    )

    col4, col5, col6 = st.columns(3)
    col4.metric("Strict threshold accuracy", f"{cal.get('strong_similarity_accuracy', 0):.1%}")
    col5.metric("Weak threshold accuracy", f"{cal.get('weak_similarity_accuracy', 0):.1%}")
    col6.metric("Containment accuracy", f"{cal.get('containment_accuracy', 0):.1%}")

    # Label score distributions
    label_dist = cal.get("label_distributions", {})
    if label_dist:
        st.markdown("**Score distribution by label**")
        VALID_LABELS = ["identical", "strongly_related", "related", "weakly_related", "unrelated"]
        dist_rows = []
        for label in VALID_LABELS:
            if label in label_dist:
                d = label_dist[label]
                dist_rows.append({
                    "Label": label,
                    "N": d["count"],
                    "Mean": f"{d['mean']:.4f}",
                    "Min": f"{d['min']:.4f}",
                    "Max": f"{d['max']:.4f}",
                    "StdDev": f"{d['std']:.4f}",
                })
        if dist_rows:
            st.dataframe(dist_rows, width='stretch')
            st.caption(
                "💡 Well calibrated if mean(identical) > mean(strongly_related) > "
                "mean(related) > mean(weakly_related) > mean(unrelated)."
            )

    col5, col6 = st.columns(2)
    col5.metric("Sim Separability", f"{cal.get('similarity_separability', 0):.4f}",
                help="Mean(related) − Mean(unrelated). Higher = better separation.")
    col6.metric("Cont Separability", f"{cal.get('containment_separability', 0):.4f}",
                help="Mean(present) − Mean(absent). Higher = better separation.")

    # Category breakdown
    cat_report = cal.get("category_report", {})
    if cat_report:
        st.markdown("**Category breakdown**")
        cat_rows = []
        for cat, stats in sorted(cat_report.items()):
            cat_rows.append({
                "Category": cat,
                "N+": stats.get("n_positive", 0),
                "N-": stats.get("n_negative", 0),
                "Mean+": f"{stats['mean_positive']:.4f}" if stats.get("mean_positive") is not None else "—",
                "Mean-": f"{stats['mean_negative']:.4f}" if stats.get("mean_negative") is not None else "—",
                "Min+": f"{stats['min_positive']:.4f}" if stats.get("min_positive") is not None else "—",
                "Max-": f"{stats['max_negative']:.4f}" if stats.get("max_negative") is not None else "—",
            })
        st.dataframe(cat_rows, width='stretch')

    # Similarity scores
    sim_scores = cal.get("similarity_scores", [])
    if sim_scores:
        with st.expander("Similarity pair scores"):
            sim_thresh = cal.get("recommended_similarity_threshold", 0.5)
            sim_rows = []
            for s in sorted(sim_scores, key=lambda x: x["score"], reverse=True):
                predicted = s["score"] >= sim_thresh
                expected_pos = s["label"] in ("related", "identical")
                correct = predicted == expected_pos
                sim_rows.append({
                    "ID": s["pair_id"],
                    "Label": s["label"],
                    "Category": s["category"],
                    "Lang": s["language"],
                    "Score": f"{s['score']:.4f}",
                    "Correct": "✓" if correct else "✗",
                })
            st.dataframe(sim_rows, width='stretch')

    # Containment scores
    cont_scores = cal.get("containment_scores", [])
    if cont_scores:
        with st.expander("Containment case scores"):
            cont_thresh = cal.get("recommended_containment_threshold", 0.45)
            cont_rows = []
            for s in sorted(cont_scores, key=lambda x: x["best_score"], reverse=True):
                predicted = s["best_score"] >= cont_thresh
                correct = predicted == s["expected"]
                cont_rows.append({
                    "ID": s["case_id"],
                    "Expected": "present" if s["expected"] else "absent",
                    "Category": s["category"],
                    "Lang": s["language"],
                    "BestScore": f"{s['best_score']:.4f}",
                    "Correct": "✓" if correct else "✗",
                    "BestChunk": s["best_chunk"][:60] + "…",
                })
            st.dataframe(cont_rows, width='stretch')


# ---------------------------------------------------------------------------
# Main UI
# ---------------------------------------------------------------------------

def show_calibrator_admin_content():
    """Render the Semantic Calibrator admin tab."""
    st.header("🔬 Semantic Embedding Calibrator")
    st.caption(
        "Benchmark multiple embedding models, derive optimal thresholds, "
        "and export calibration_results.json for the test suite."
    )

    module_cfg = _get_module_config()
    available_models = _get_available_models(module_cfg)
    chunk_window_default = module_cfg.get("chunk_window", 3)
    chunk_step_default = module_cfg.get("chunk_step", 1)

    # -----------------------------------------------------------------------
    # SESSION STATE
    # -----------------------------------------------------------------------
    if "calibration_results" not in st.session_state:
        st.session_state.calibration_results = None
    if "calibration_benchmark" not in st.session_state:
        st.session_state.calibration_benchmark = None
    if "calibration_log" not in st.session_state:
        st.session_state.calibration_log = []

    # -----------------------------------------------------------------------
    # STEP 1 — BENCHMARK UPLOAD
    # -----------------------------------------------------------------------
    st.subheader("Step 1 — Load benchmark dataset")

    input_mode = st.radio(
        "Source",
        ["Upload YAML file", "Paste YAML content"],
        horizontal=True,
        label_visibility="collapsed",
    )

    benchmark_raw: Optional[str] = None

    if input_mode == "Upload YAML file":
        uploaded = st.file_uploader(
            "Upload semantic_benchmark.yaml",
            type=["yaml", "yml"],
            label_visibility="collapsed",
        )
        if uploaded:
            benchmark_raw = uploaded.read().decode("utf-8")
    else:
        benchmark_raw = st.text_area(
            "Paste YAML content",
            height=200,
            placeholder="meta:\n  version: '1.0'\n\nsimilarity_pairs:\n  ...",
            label_visibility="collapsed",
        )

    benchmark: Optional[dict] = None
    if benchmark_raw and benchmark_raw.strip():
        try:
            from modules.semantic_calibrator.calibrator_engine import load_benchmark
            benchmark = load_benchmark(benchmark_raw)
            sim_pairs = benchmark.get("similarity_pairs", [])
            cont_cases = benchmark.get("containment_cases", [])
            st.success(
                f"✓ Benchmark loaded: **{len(sim_pairs)}** similarity pairs, "
                f"**{len(cont_cases)}** containment cases"
            )
            st.session_state.calibration_benchmark = benchmark
        except Exception as exc:
            st.error(f"Failed to parse YAML: {exc}")
            benchmark = None

    # -----------------------------------------------------------------------
    # STEP 2 — MODEL SELECTION
    # -----------------------------------------------------------------------
    st.subheader("Step 2 — Select embedding models")

    if not available_models:
        st.warning("No models configured. Check `modules/semantic_calibrator/config.json`.")
        return

    # Group by type
    st_models = [m for m in available_models if m["type"] == "sentence_transformer"]
    oai_models = [m for m in available_models if m["type"] == "openai"]

    selected_keys: List[str] = []

    st.markdown("**Sentence-Transformers** (local, no API key required)")

    # Add a refresh button for model info
    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("🔄 Refresh download status", key="refresh_model_info"):
            if "model_info_cache" in st.session_state:
                del st.session_state.model_info_cache
            st.rerun()

    for m in st_models:
        # Get model info (cached in session state to avoid repeated API calls)
        if "model_info_cache" not in st.session_state:
            st.session_state.model_info_cache = {}

        if m["key"] not in st.session_state.model_info_cache:
            with st.spinner(f"Fetching info for {m['key']}..."):
                from modules.semantic_calibrator.calibrator_engine import get_model_info
                st.session_state.model_info_cache[m["key"]] = get_model_info(m["key"])

        model_info = st.session_state.model_info_cache[m["key"]]

        # Create a nicer display with columns
        col1, col2, col3 = st.columns([3, 1, 1])

        with col1:
            checked = st.checkbox(
                f"`{m['key']}`",
                value=False,
                help=m.get("description", ""),
                key=f"model_check_{m['key']}",
            )

        with col2:
            # Display download status
            if model_info["downloaded"]:
                st.markdown(f"✅ Downloaded")
            else:
                st.markdown(f"🔄 Not cached")

        with col3:
            # Display size
            if model_info.get("size_readable"):
                st.markdown(f"📦 {model_info['size_readable']}")
            elif model_info.get("hf_size_readable"):
                st.markdown(f"📦 {model_info['hf_size_readable']} (remote)")
            else:
                st.markdown("📦 Size unknown")

        if checked:
            selected_keys.append(m["key"])

    if oai_models:
        st.markdown("**OpenAI** (requires `OPENAI_API_KEY` environment variable)")
        oai_available = _openai_key_available()
        if not oai_available:
            st.caption("⚠ `OPENAI_API_KEY` not set — OpenAI models will be skipped.")
        for m in oai_models:
            checked = st.checkbox(
                f"`{m['key']}`",
                value=False,
                help=m.get("description", ""),
                disabled=not oai_available,
                key=f"model_check_{m['key']}",
            )
            if checked and oai_available:
                selected_keys.append(m["key"])

    # -----------------------------------------------------------------------
    # STEP 3 — CHUNKING PARAMETERS
    # -----------------------------------------------------------------------
    with st.expander("⚙ Chunking parameters (advanced)"):
        col1, col2 = st.columns(2)
        chunk_window = col1.number_input(
            "Window size (sentences per chunk)",
            min_value=1, max_value=10,
            value=chunk_window_default,
            help="How many consecutive sentences form one chunk for containment search.",
        )
        chunk_step = col2.number_input(
            "Step (overlap control)",
            min_value=1, max_value=10,
            value=chunk_step_default,
            help="Step between windows. step < window → overlapping chunks.",
        )

    # -----------------------------------------------------------------------
    # STEP 4 — RUN
    # -----------------------------------------------------------------------
    st.subheader("Step 3 — Run calibration")

    run_disabled = not benchmark or not selected_keys
    if not benchmark:
        st.caption("⬆ Load a benchmark dataset first.")
    elif not selected_keys:
        st.caption("⬆ Select at least one model.")

    if st.button("▶ Run calibration", disabled=run_disabled, type="primary"):
        st.session_state.calibration_results = None
        st.session_state.calibration_log = []

        selected_configs = [
            m for m in available_models if m["key"] in selected_keys
        ]

        log_lines: List[str] = []

        def progress_cb(msg: str):
            ts = datetime.now().strftime("%H:%M:%S")
            line = f"[{ts}] {msg}"
            log_lines.append(line)
            st.session_state.calibration_log = log_lines.copy()

        with st.status("Running calibration…", expanded=True) as status:
            log_placeholder = st.empty()

            def _refresh_log():
                log_placeholder.code("\n".join(log_lines[-30:]), language="")

            # We need a wrapper that refreshes the UI on each callback
            # Streamlit re-renders on each write when inside st.status
            def ui_progress_cb(msg: str):
                progress_cb(msg)
                _refresh_log()

            try:
                from modules.semantic_calibrator.calibrator_engine import run_calibration
                results = run_calibration(
                    benchmark=benchmark,
                    model_configs=selected_configs,
                    chunk_window=int(chunk_window),
                    chunk_step=int(chunk_step),
                    progress_cb=ui_progress_cb,
                )
                st.session_state.calibration_results = results
                status.update(label="✓ Calibration complete", state="complete")
            except Exception as exc:
                log("error", f"[calibrator_ui] Calibration failed: {exc}", stacktrace=True)
                status.update(label=f"✗ Calibration failed: {exc}", state="error")
                st.error(f"Calibration error: {exc}")

    # -----------------------------------------------------------------------
    # STEP 5 — RESULTS
    # -----------------------------------------------------------------------
    results = st.session_state.calibration_results
    if not results:
        return

    st.subheader("Step 4 — Results")

    model_results: Dict[str, dict] = results.get("models", {})
    if not model_results:
        st.warning("No model results found.")
        return

    st.markdown("#### Model ranking")
    st.caption("Sorted by combined separability score (higher = better threshold gap between positive/negative).")
    _render_ranking_table(model_results)

    # Best model callout
    successful = {
        k: v for k, v in model_results.items()
        if not v.get("skipped")
    }
    if successful:
        best_key = max(
            successful,
            key=lambda k: (
                successful[k].get("similarity_separability", 0)
                + successful[k].get("containment_separability", 0)
            ),
        )
        best = successful[best_key]
        st.success(
            f"**Best model for your use case: `{best_key}`**  \n"
            f"Strict threshold (validation): `{best['recommended_similarity_threshold']}`  |  "
            f"Weak threshold (RAG): `{best.get('weak_similarity_threshold', '—')}`  |  "
            f"Containment threshold: `{best['recommended_containment_threshold']}`"
        )

    # Per-model tabs
    st.markdown("#### Per-model detail")
    model_tabs = st.tabs(list(model_results.keys()))
    for tab, (model_key, cal) in zip(model_tabs, model_results.items()):
        with tab:
            _render_model_detail(model_key, cal, benchmark or {})

    # -----------------------------------------------------------------------
    # STEP 6 — DOWNLOAD
    # -----------------------------------------------------------------------
    st.subheader("Step 5 — Export")

    output_json = json.dumps(results, indent=2, ensure_ascii=False)

    col1, col2 = st.columns(2)

    col1.download_button(
        label="⬇ Download calibration_results.json",
        data=output_json,
        file_name="calibration_results.json",
        mime="application/json",
        type="primary",
        help=(
            "Place this file in calibration_results/calibration_results.json "
            "relative to shared/tests/ so the test suite can read it. "
            "It contains both thresholds: recommended_similarity_threshold (strict) "
            "and weak_similarity_threshold (RAG)."
        ),
    )

    # Show placement instructions
    with col2.expander("Where to put this file"):
        st.code(
            "shared/tests/calibration_results/calibration_results.json",
            language="",
        )
        st.caption(
            "Or set the `CALIBRATION_FILE` environment variable to point "
            "to any path before running pytest."
        )

    with st.expander("Preview JSON"):
        st.code(output_json[:4000] + ("\n… (truncated)" if len(output_json) > 4000 else ""), language="json")

    # Full log
    if st.session_state.calibration_log:
        with st.expander("Full calibration log"):
            st.code("\n".join(st.session_state.calibration_log), language="")


# ---------------------------------------------------------------------------
# Injection point
# ---------------------------------------------------------------------------

def inject_ui_admin_tab():
    """Register the Semantic Calibrator admin tab."""
    return ("Semantic Calibrator", show_calibrator_admin_content)
