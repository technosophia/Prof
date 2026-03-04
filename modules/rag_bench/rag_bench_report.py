# modules/rag_bench/rag_bench_report.py
"""
RAG Benchmark — Report Exporter
================================
Two export modes:
  1. Full run report  (build_report / render_export_section)
     Structured Markdown for LLM analysis of an entire benchmark run.

  2. Per-step export  (build_step_report / render_step_export)
     Complete dump of one test case across all engines — full chunks,
     scores, expected values — designed to be pasted to an LLM along
     with engine source code for targeted debugging.
"""

from __future__ import annotations
import io
from datetime import datetime
from statistics import mean, stdev
from typing import Dict, List, Optional

from modules.rag_bench.rag_bench_models import (
    CaseResult, LevelSummary, TestCase, aggregate_results,
    LEVEL_LABELS, FIXABLE_LEVELS, PARTIAL_LEVELS, ENGINE_LEVELS,
    ANOMALY_CATEGORIES,
)


# ─────────────────────────────────────────────────────────────────────────────
# PER-STEP REPORT
# ─────────────────────────────────────────────────────────────────────────────

def build_step_report(
    case_id: str,
    tc: TestCase,
    case_results: Dict[str, Optional[CaseResult]],
    engines: List[str],
) -> str:
    buf = io.StringIO()
    w = lambda s="": buf.write(s + "\n")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fixability = (
        "✅ fixable by refactoring" if tc.level in FIXABLE_LEVELS
        else "⚠️ partially fixable"  if tc.level in PARTIAL_LEVELS
        else "❌ engine-only"
    )

    # ── YAML front-matter ────────────────────────────────────────────────────
    w("---")
    w(f"export_type: rag_bench_step")
    w(f"case_id: \"{case_id}\"")
    w(f"level: {tc.level}")
    w(f"level_label: \"{LEVEL_LABELS.get(tc.level, '')}\"")
    w(f"fixability: \"{fixability}\"")
    w(f"scoring_method: \"{tc.scoring_method}\"")
    w(f"yaml_threshold: {tc.min_score_threshold}")
    w(f"engines_compared: {engines}")
    w(f"exported_at: \"{now}\"")
    gauges = {e: case_results[e].gauge if case_results.get(e) else None for e in engines}
    w(f"gauges: {gauges}")
    best = max((e for e in engines if gauges.get(e) is not None), key=lambda e: gauges[e], default="N/A")
    w(f"best_engine: \"{best}\"")
    w("---")
    w()

    # ── Context ───────────────────────────────────────────────────────────────
    w(f"# Step Export — `{case_id}`")
    w()
    w(f"**Level {tc.level}** — {LEVEL_LABELS.get(tc.level, '')} | {fixability}")
    w()
    w("## Test Case Definition")
    w()
    w(f"**Question:** {tc.question}")
    w()
    w(f"**Reference answer:**")
    w(f"> {tc.reference_answer.strip()}")
    w()
    w(f"**Scoring method:** `{tc.scoring_method}`")
    w(f"**YAML threshold:** `{tc.min_score_threshold}`")
    if tc.expected_keywords:
        w(f"**Expected keywords:** {tc.expected_keywords}")
    if tc.expected_sources:
        w(f"**Expected sources:** {tc.expected_sources}")
    if tc.all_required_sources:
        w(f"**All required sources:** {tc.all_required_sources}")
    if tc.negation_keywords:
        w(f"**Negation keywords:** {tc.negation_keywords}")
    if tc.required_rank:
        w(f"**Required rank:** {tc.required_rank}")
    if tc.distractor_description:
        w(f"**Distractor description:** {tc.distractor_description}")
    if tc.notes:
        w(f"**Notes:** _{tc.notes}_")
    w()

    # ── Per-engine results ────────────────────────────────────────────────────
    w("## Engine Results")
    w()

    for engine in engines:
        r = case_results.get(engine)
        w(f"### Engine: `{engine}`")
        w()

        if r is None:
            w("_Not executed._")
            w()
            continue

        if r.error:
            w(f"**ERROR:** `{r.error}`")
            w()
            continue

        status = "✅ PASS" if r.passed else "❌ FAIL"
        delta  = r.gauge - r.threshold
        sign   = "+" if delta >= 0 else ""
        is_best = engine == best

        w(f"**Result:** {status} {'🏆 best engine' if is_best else ''}")
        w(f"**Gauge:** `{r.gauge:.4f}` | **Threshold:** `{r.threshold:.3f}` | "
          f"**Delta:** `{sign}{delta*100:.1f}%`")
        w()

        # Score breakdown
        d = r.score_details
        w("**Score breakdown:**")
        if d.get("top_score") is not None:
            w(f"- Top similarity score: `{d['top_score']:.4f}`")
        if d.get("keywords_found"):
            w(f"- Keywords found: {d['keywords_found']}")
        if d.get("keywords_missing"):
            w(f"- Keywords MISSING: **{d['keywords_missing']}**")
        if d.get("source_hit") is not None:
            w(f"- Source hit: `{d['source_hit']}`")
        if d.get("correct_rank") is not None:
            w(f"- Correct source rank: `{d['correct_rank']}`")
        if d.get("llm_score") is not None:
            w(f"- LLM judge score: `{d['llm_score']}` (1=pass, 0=fail)")
        if d.get("deterministic_gauge") is not None:
            w(f"- Deterministic sub-gauge: `{d['deterministic_gauge']:.4f}`")
        if d.get("llm_gauge") is not None:
            w(f"- LLM sub-gauge: `{d['llm_gauge']:.4f}`")
        if r.judge_reasoning:
            w(f"- Judge reasoning: _{r.judge_reasoning}_")
        w()

        # Full retrieved chunks — NO truncation
        w(f"**Retrieved chunks ({len(r.retrieved_chunks)} total):**")
        w()
        if r.retrieved_chunks:
            for j, chunk in enumerate(r.retrieved_chunks):
                src     = chunk.get("filename", chunk.get("source", f"chunk_{j+1}"))
                score   = chunk.get("score", 0.0)
                content = chunk.get("content", "").strip()
                metadata = {k: v for k, v in chunk.items()
                            if k not in ("filename", "source", "content", "score")}

                w(f"#### Chunk {j+1} — `{src}` (score: `{score:.4f}`)")
                w()
                # Highlight if this chunk contains expected keywords
                found_kw = [kw for kw in tc.expected_keywords if kw.lower() in content.lower()]
                if found_kw:
                    w(f"_✓ Contains expected keywords: {found_kw}_")
                else:
                    w(f"_✗ Does not contain any expected keywords_")
                w()
                w("```")
                w(content)
                w("```")
                if metadata:
                    w()
                    w(f"_Metadata: {metadata}_")
                w()
        else:
            w("_No chunks retrieved._")
            w()

    # ── Cross-engine comparison ───────────────────────────────────────────────
    if len(engines) > 1:
        w("## Cross-Engine Comparison")
        w()
        w("| Engine | Gauge | Threshold | Delta | Pass | Top Sim | KW Found | KW Missing |")
        w("|---|---|---|---|---|---|---|---|")
        for engine in engines:
            r = case_results.get(engine)
            if r is None:
                w(f"| {engine} | — | — | — | — | — | — | — |")
                continue
            d = r.score_details
            delta = r.gauge - r.threshold
            sign  = "+" if delta >= 0 else ""
            w(f"| `{engine}` "
              f"| {r.gauge:.4f} "
              f"| {r.threshold:.3f} "
              f"| {sign}{delta*100:.1f}% "
              f"| {'✅' if r.passed else '❌'} "
              f"| {d.get('top_score', 0):.4f} "
              f"| {d.get('keywords_found', [])} "
              f"| {d.get('keywords_missing', [])} |")
        w()

        # Highlight interesting divergences
        results_list = [case_results[e] for e in engines if case_results.get(e)]
        pass_count = sum(1 for r in results_list if r.passed)
        fail_count = len(results_list) - pass_count

        if pass_count > 0 and fail_count > 0:
            passing_engines = [e for e in engines if case_results.get(e) and case_results[e].passed]
            failing_engines = [e for e in engines if case_results.get(e) and not case_results[e].passed]
            w(f"⚠️ **Split result**: `{'`, `'.join(passing_engines)}` pass, "
              f"`{'`, `'.join(failing_engines)}` fail.")
            w()
            w("This is the most informative case for engine comparison.")
            w("Feed this export + engine source code to an LLM with the question:")
            w(f'> *"Why does `{passing_engines[0]}` retrieve the correct chunk but '
              f'`{failing_engines[0]}` does not? What in the engine code explains this?"*')
        elif fail_count == len(results_list):
            w("❌ **All engines fail.** Likely a dataset/chunking issue, not an engine issue.")
            w("Check: are the expected_keywords present verbatim in any chunk above?")
        elif pass_count == len(results_list):
            w("✅ **All engines pass.** No discrimination signal from this test case.")
        w()

    # ── Suggested prompt for LLM analysis ────────────────────────────────────
    w("## How to Use This Export")
    w()
    w("Paste this file into a new LLM conversation along with your engine source code.")
    w("Suggested prompts depending on your situation:")
    w()
    w("**If engines disagree:**")
    w("```")
    w(f"Here is a RAG benchmark step export for test `{case_id}`.")
    w("One engine passes, one fails. Here is the source code of both engines: [paste code]")
    w("Why does one engine find the correct chunk and the other doesn't?")
    w("What specific part of the engine logic causes this difference?")
    w("```")
    w()
    w("**If all engines fail:**")
    w("```")
    w(f"Here is a RAG benchmark step export for test `{case_id}`.")
    w("All engines fail. The expected keywords are not found in any retrieved chunk.")
    w("Looking at the full chunk contents above, what do you think is wrong?")
    w("Is it a chunking issue, a YAML issue, or an embedding issue?")
    w("```")
    w()
    w("**If you want threshold tuning advice:**")
    w("```")
    w(f"Here is a RAG benchmark step export for test `{case_id}`.")
    w("The gauge is close to the threshold. Is the current threshold appropriate")
    w("for this type of question, or should it be adjusted? What would you recommend?")
    w("```")

    return buf.getvalue()


def render_step_export(
    case_id: str,
    tc: TestCase,
    case_results: Dict[str, Optional[CaseResult]],
    engines: List[str],
):
    """Renders export button + copy area for a single test case. Call inside each case expander."""
    import streamlit as st

    with st.expander("📤 Exporter ce step", expanded=False):
        report = build_step_report(case_id, tc, case_results, engines)

        col_dl, col_hint = st.columns([1, 2])
        with col_dl:
            fname = f"step_{case_id}_{datetime.now().strftime('%H%M%S')}.md"
            st.download_button(
                label="⬇️ Télécharger",
                data=report.encode("utf-8"),
                file_name=fname,
                mime="text/markdown",
                use_container_width=True,
                key=f"dl_step_{case_id}_{id(report)}",
            )
        with col_hint:
            st.caption("Colle ce fichier à Claude avec le code de tes moteurs RAG "
                       "pour obtenir une analyse ciblée.")

        st.text_area(
            "Copier-coller",
            value=report,
            height=200,
            key=f"ta_step_{case_id}_{id(report)}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# FULL RUN REPORT
# ─────────────────────────────────────────────────────────────────────────────

def detect_anomalies(results, cases_lookup, engines):
    anomalies = []
    rlookup = {(r.case_id, r.engine): r for r in results}
    all_case_ids = sorted({r.case_id for r in results})

    for cid in all_case_ids:
        tc = cases_lookup.get(cid)
        if tc is None:
            continue
        case_results = [rlookup[(cid, e)] for e in engines if (cid, e) in rlookup]
        if not case_results:
            continue

        gauges    = [r.gauge for r in case_results]
        avg_gauge = mean(gauges)
        all_fail  = all(not r.passed for r in case_results)
        top_scores = [r.score_details.get("top_score", 0) for r in case_results]
        avg_sim   = mean(top_scores) if top_scores else 0

        if all_fail:
            det_fails = [r for r in case_results if r.score_details.get("keywords_missing")]
            llm_pass  = [r for r in case_results if r.score_details.get("llm_score") == 1]
            if llm_pass and det_fails:
                anomalies.append({
                    "category": "bad_test", "case_id": cid, "level": tc.level,
                    "detail": (f"LLM judge PASSES but deterministic FAILS on all engines. "
                               f"Missing keywords: {det_fails[0].score_details.get('keywords_missing')}. "
                               f"Likely the expected_keywords in YAML don't match actual document text."),
                    "action": "Review and fix expected_keywords in YAML for this test case.",
                })
            elif tc.level in FIXABLE_LEVELS:
                anomalies.append({
                    "category": "chunking", "case_id": cid, "level": tc.level,
                    "detail": (f"Level {tc.level} (fixable) fails on ALL engines. "
                               f"Avg similarity: {avg_sim:.3f}. Likely a chunk boundary issue."),
                    "action": "Inspect chunk boundaries around this answer.",
                })

        if avg_sim >= 0.75 and avg_gauge < 0.5 and not all_fail:
            anomalies.append({
                "category": "chunking", "case_id": cid, "level": tc.level,
                "detail": (f"High similarity ({avg_sim:.3f}) but low gauge ({avg_gauge:.3f}). "
                           f"Right document, wrong chunk."),
                "action": "Reduce chunk size or add overlap.",
            })

        if avg_sim < 0.55 and avg_gauge > 0.6:
            anomalies.append({
                "category": "threshold", "case_id": cid, "level": tc.level,
                "detail": (f"Low similarity ({avg_sim:.3f}) but keywords found (gauge {avg_gauge:.3f}). "
                           f"Lucky partial match — threshold may be too permissive."),
                "action": "Raise min_score_threshold or tighten expected_keywords.",
            })

        if tc.level == 1 and all_fail:
            anomalies.append({
                "category": "embedding", "case_id": cid, "level": 1,
                "detail": (f"Level 1 (direct keyword) fails on all engines. Avg sim: {avg_sim:.3f}."),
                "action": "Consider a domain-adapted or French-specific embedding model.",
            })

    for engine in engines:
        eng_results = [r for r in results if r.engine == engine]
        by_level: Dict[int, List[float]] = {}
        for r in eng_results:
            by_level.setdefault(r.level, []).append(r.gauge)
        avg_by_level = {lvl: mean(g) for lvl, g in by_level.items()}
        easy_avg = mean([avg_by_level[l] for l in FIXABLE_LEVELS if l in avg_by_level] or [0])
        hard_avg = mean([avg_by_level[l] for l in ENGINE_LEVELS  if l in avg_by_level] or [0])
        if hard_avg > easy_avg + 0.15 and easy_avg < 0.6:
            anomalies.append({
                "category": "contradiction", "case_id": None, "level": None, "engine": engine,
                "detail": (f"Engine '{engine}' scores better on hard levels ({hard_avg:.2f}) "
                           f"than easy ({easy_avg:.2f}). Statistically suspicious."),
                "action": f"Inspect level 1–4 failures for engine '{engine}' specifically.",
            })

    if len(engines) > 1:
        for lvl in sorted({r.level for r in results}):
            by_engine = {}
            for r in [r for r in results if r.level == lvl]:
                by_engine.setdefault(r.engine, []).append(r.gauge)
            avgs = [mean(g) for g in by_engine.values()]
            if len(avgs) >= 2 and max(avgs) - min(avgs) < 0.05:
                anomalies.append({
                    "category": "threshold", "case_id": None, "level": lvl,
                    "detail": (f"Level {lvl}: all engines within 5% ({min(avgs):.2f}–{max(avgs):.2f}). "
                               f"No discrimination signal."),
                    "action": "Add more varied test cases at this level.",
                })

    return anomalies


def generate_recommendations(anomalies, agg, engines, results):
    recs = []
    cat_counts = {}
    for a in anomalies:
        cat_counts[a["category"]] = cat_counts.get(a["category"], 0) + 1

    if cat_counts.get("bad_test", 0) >= 2:
        recs.append({"priority": 1, "category": "Fix dataset (YAML)",
                     "detail": f"{cat_counts['bad_test']} test cases have incorrect expected_keywords. Fix before drawing conclusions."})

    if cat_counts.get("chunking", 0) >= 2:
        recs.append({"priority": 2, "category": "Chunking strategy",
                     "detail": (f"{cat_counts['chunking']} tests show chunking issues. Consider: "
                                "(a) smaller chunks with overlap, (b) sentence-level chunking, "
                                "(c) chunk metadata repeating section headers.")})

    if cat_counts.get("threshold", 0) >= 1:
        passing = [r.score_details.get("top_score", 0) for r in results if r.passed and r.score_details]
        failing = [r.score_details.get("top_score", 0) for r in results if not r.passed and r.score_details]
        if passing and failing:
            suggested = (mean(passing) + mean(failing)) / 2
            recs.append({"priority": 3, "category": "Threshold calibration",
                         "detail": (f"Passing avg: {mean(passing):.3f}, failing avg: {mean(failing):.3f}. "
                                    f"Suggested global threshold: {suggested:.3f}.")})

    if cat_counts.get("embedding", 0) >= 1:
        recs.append({"priority": 4, "category": "Embedding model",
                     "detail": ("Level 1 failures suggest embedding model issues. Consider: "
                                "sentence-camembert-large, multilingual-e5-large, or domain fine-tuning.")})

    if len(engines) > 1:
        engine_wins = {e: 0 for e in engines}
        for lvl, ld in agg.items():
            avgs = {e: ld[e].avg_gauge for e in engines if e in ld}
            if avgs:
                best = max(avgs, key=avgs.get)
                if avgs[best] > min(avgs.values()) + 0.03:
                    engine_wins[best] += 1
        best_overall = max(engine_wins, key=engine_wins.get)
        recs.append({"priority": 5, "category": "Engine selection",
                     "detail": (f"Win counts: {engine_wins}. '{best_overall}' leads. "
                                "For engine selection, focus on levels 5–9 (can't be fixed by refactoring).")})

    recs.append({"priority": 6, "category": "Future: BM25 baseline",
                 "detail": ("Add a BM25 keyword engine as a floor. "
                            "If your semantic engine can't beat BM25 on levels 1–3, embeddings add no value.")})

    return sorted(recs, key=lambda r: r["priority"])


def build_report(results, cases_lookup, engines, threshold_override, run_timestamp):
    agg = aggregate_results(results, engines)
    levels = sorted(agg.keys())
    anomalies = detect_anomalies(results, cases_lookup, engines)
    recommendations = generate_recommendations(anomalies, agg, engines, results)

    buf = io.StringIO()
    w = lambda s="": buf.write(s + "\n")
    rlookup = {(r.case_id, r.engine): r for r in results}

    all_gauges    = [r.gauge for r in results]
    passing       = [r for r in results if r.passed]
    global_pass   = len(passing) / len(results) if results else 0
    eng_avgs      = {e: round(mean([r.gauge for r in results if r.engine == e]), 4) for e in engines}
    best_engine   = max(eng_avgs, key=eng_avgs.get) if eng_avgs else "N/A"
    fix_results   = [r for r in results if r.level in FIXABLE_LEVELS]
    eng_results_l = [r for r in results if r.level in ENGINE_LEVELS]
    fix_avg       = mean([r.gauge for r in fix_results])  if fix_results  else 0
    eng_avg       = mean([r.gauge for r in eng_results_l]) if eng_results_l else 0

    w("---")
    w(f"report_type: rag_benchmark_full")
    w(f"generated_at: \"{run_timestamp}\"")
    w(f"engines_tested: {engines}")
    w(f"levels_tested: {levels}")
    w(f"total_test_cases: {len({r.case_id for r in results})}")
    w(f"total_executions: {len(results)}")
    w(f"global_pass_rate: {global_pass:.3f}")
    w(f"threshold_override: {threshold_override}")
    w(f"anomalies_detected: {len(anomalies)}")
    w(f"best_engine_overall: \"{best_engine}\"")
    w(f"engine_global_averages:")
    for e, avg in eng_avgs.items():
        w(f"  {e}: {avg}")
    w("---")
    w()
    w("# RAG Benchmark Full Report")
    w()
    w("## Executive Summary")
    w()
    w(f"Run at **{run_timestamp}** | Engines: `{'`, `'.join(engines)}` | "
      f"{len({r.case_id for r in results})} cases / {len(results)} executions")
    w()
    w(f"- Global pass rate: **{global_pass*100:.1f}%**")
    w(f"- Fixable levels (1–4) avg: **{fix_avg:.3f}** — "
      f"{'✅ Good' if fix_avg >= 0.75 else '⚠️ Needs attention'}")
    w(f"- Engine-only levels (10–11) avg: **{eng_avg:.3f}** — "
      f"{'✅ Strong' if eng_avg >= 0.70 else '⚠️ Weak semantic retrieval'}")
    w(f"- Best engine: **`{best_engine}`** ({eng_avgs.get(best_engine, 0):.3f})")
    w(f"- Anomalies: **{len(anomalies)}**")
    if threshold_override:
        w(f"- ⚠️ Global threshold override active: `{threshold_override:.2f}`")
    w()

    w("## Anomalies")
    w()
    if not anomalies:
        w("_None detected._")
    else:
        by_cat: Dict = {}
        for a in anomalies:
            by_cat.setdefault(a["category"], []).append(a)
        for cat, items in by_cat.items():
            w(f"### {ANOMALY_CATEGORIES.get(cat, cat)} ({len(items)})")
            for a in items:
                loc = f"`{a['case_id']}`" if a.get("case_id") else f"Level {a.get('level','?')}"
                if a.get("engine"):
                    loc += f" / `{a['engine']}`"
                w(f"- **{loc}**: {a['detail']}")
                w(f"  → {a['action']}")
            w()

    w("## Engine Comparison")
    w()
    header = "| Level | Description |" + "".join(f" {e} |" for e in engines)
    w(header)
    w("|---|---|" + "".join("---|" for _ in engines))
    for lvl in levels:
        ld   = agg.get(lvl, {})
        avgs = {e: ld[e].avg_gauge for e in engines if e in ld}
        best = max(avgs, key=avgs.get) if avgs else None
        row  = f"| {lvl} | {LEVEL_LABELS.get(lvl,'')} |"
        for e in engines:
            avg = avgs.get(e)
            star_suffix = ' ★' if e == best and len(engines) > 1 else ''
            row += f" {'—' if avg is None else f'{avg:.3f}{star_suffix}'} |"
        w(row)
    w()

    w("## Level-by-Level Analysis")
    w()
    for lvl in levels:
        ld    = agg.get(lvl, {})
        avgs  = {e: ld[e].avg_gauge for e in engines if e in ld}
        overall = mean(avgs.values()) if avgs else 0
        fix   = "✅" if lvl in FIXABLE_LEVELS else "⚠️" if lvl in PARTIAL_LEVELS else "❌"
        trend = "🟢" if overall >= 0.85 else "🟡" if overall >= 0.65 else "🟠" if overall >= 0.45 else "🔴"
        w(f"### Level {lvl} — {LEVEL_LABELS.get(lvl,'')} [{fix}] {trend} (avg {overall:.3f})")
        w()
        case_ids = sorted({r.case_id for r in results if cases_lookup.get(r.case_id) and cases_lookup[r.case_id].level == lvl})
        for cid in case_ids:
            tc = cases_lookup.get(cid)
            if not tc:
                continue
            w(f"**`{cid}`** — _{tc.question}_")
            for e in engines:
                r = rlookup.get((cid, e))
                if r is None:
                    continue
                d = r.score_details
                det = f"sim={d.get('top_score',0):.3f}"
                if d.get("keywords_missing"):
                    det += f", missing={d['keywords_missing']}"
                if d.get("llm_score") is not None:
                    det += f", llm={d['llm_score']}"
                if r.judge_reasoning:
                    det += f", judge=\"{r.judge_reasoning[:80]}\""
                w(f"  - `{e}`: gauge={r.gauge:.3f}/thr={r.threshold:.2f} → "
                  f"**{'PASS' if r.passed else 'FAIL'}** ({det})")
            w()

    w("## Threshold Calibration")
    w()
    ps = [r.score_details.get("top_score",0) for r in results if r.passed and r.score_details]
    fs = [r.score_details.get("top_score",0) for r in results if not r.passed and r.score_details]
    if ps:
        w(f"Passing: min={min(ps):.3f} avg={mean(ps):.3f} max={max(ps):.3f}"
          + (f" stdev={stdev(ps):.3f}" if len(ps)>1 else ""))
    if fs:
        w(f"Failing: min={min(fs):.3f} avg={mean(fs):.3f} max={max(fs):.3f}"
          + (f" stdev={stdev(fs):.3f}" if len(fs)>1 else ""))
    if ps and fs:
        w(f"Suggested threshold: `{(mean(ps)+mean(fs))/2:.3f}`")
    w()

    w("## Raw Scores")
    w()
    w("| Case ID | Level | Method | Threshold |" + "".join(f" {e} |" for e in engines))
    w("|---|---|---|---|" + "".join("---|" for _ in engines))
    for cid in sorted({r.case_id for r in results}):
        tc = cases_lookup.get(cid)
        if tc is None:
            continue
        row = f"| {cid} | {tc.level} | {tc.scoring_method} | {tc.min_score_threshold} |"
        for e in engines:
            r = rlookup.get((cid, e))
            status_icon = '✅' if r.passed else '❌' if r is not None else ''
            row += f" {'—' if r is None else f'{r.gauge:.3f} {status_icon}'} |"
        w(row)
    w()

    w("## Recommendations")
    w()
    for rec in generate_recommendations(anomalies, agg, engines, results):
        w(f"### {rec['priority']}. {rec['category']}")
        w(rec["detail"])
        w()

    w("---")
    w(f"_Generated by rag_bench_report.py — {run_timestamp}_")
    return buf.getvalue()


def render_export_section(results, cases_lookup, engines, threshold_override, run_timestamp):
    import streamlit as st
    st.divider()
    st.subheader("📤 Export du rapport complet")
    st.caption("Rapport structuré pour analyse LLM. Colle-le dans une nouvelle conversation.")

    report = build_report(results, cases_lookup, engines, threshold_override, run_timestamp)

    col_copy, col_file = st.columns(2)
    with col_copy:
        st.text_area("📋 Copier-coller", value=report, height=300, key="rb_export_text")
    with col_file:
        fname = f"rag_bench_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        st.download_button(
            label="⬇️ Télécharger (.md)",
            data=report.encode("utf-8"),
            file_name=fname,
            mime="text/markdown",
            use_container_width=True,
        )
        st.caption("Prompt suggéré :")
        st.code(
            "Voici mon rapport de benchmark RAG.\n"
            "Analyse les anomalies et dis-moi quoi améliorer en priorité.",
            language=None
        )
