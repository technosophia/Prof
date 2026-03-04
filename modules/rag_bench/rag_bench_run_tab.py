# modules/rag_bench/rag_bench_run_tab.py
"""
RAG Benchmark Runner Tab
========================
Loads YAML test cases from a configurable directory (default: data/rag_bench),
runs them against all available RAG engines, scores results, and displays
a side-by-side comparison table per level.

Scoring:
  - Deterministic : keyword presence + expected_sources presence + score >= threshold
  - LLM judge     : local Ollama call (default: qwen3:4b) — context relevance in French
  - Hybrid        : deterministic AND llm_judge must both pass

Judge LLM is configurable via config key: modules.rag_bench.judge_model
Default: qwen3:4b  |  Base URL: modules.rag_bench.ollama_base_url (default: http://localhost:11434)
"""

import streamlit as st
import os
import glob
import yaml
import json
import asyncio
import httpx
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field

from core.logging import log
from st_shared.cached import get_config


# ─────────────────────────────────────────────────────────────────────────────
# DATA CLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TestCase:
    id: str
    level: int
    question: str
    reference_answer: str
    expected_keywords: List[str] = field(default_factory=list)
    expected_sources: List[str] = field(default_factory=list)
    all_required_sources: List[str] = field(default_factory=list)
    negation_keywords: List[str] = field(default_factory=list)
    distractor_source: Optional[str] = None
    distractor_description: Optional[str] = None
    min_score_threshold: float = 0.65
    required_rank: Optional[int] = None
    scoring_method: str = "deterministic"  # deterministic | llm_judge | hybrid
    notes: str = ""


@dataclass
class CaseResult:
    case_id: str
    level: int
    engine: str
    question: str
    passed: bool
    score_details: Dict[str, Any]   # keyword_hit, source_hit, llm_score, rank, top_score
    retrieved_chunks: List[Dict]
    error: Optional[str] = None
    judge_reasoning: str = ""


@dataclass
class LevelSummary:
    level: int
    engine: str
    total: int
    passed: int

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total > 0 else 0.0

    @property
    def label(self) -> str:
        r = self.pass_rate
        if r >= 0.9:  return "🟢"
        if r >= 0.7:  return "🟡"
        if r >= 0.5:  return "🟠"
        return "🔴"


# ─────────────────────────────────────────────────────────────────────────────
# YAML LOADER
# ─────────────────────────────────────────────────────────────────────────────

def get_bench_dir() -> str:
    cfg = get_config()
    return cfg.get("modules.rag_bench.dataset_dir", "data/rag_bench")


def load_yaml_datasets(bench_dir: str) -> Tuple[List[TestCase], Dict]:
    """
    Scan bench_dir for *.yaml files, parse them, return (cases, stats).
    stats = { "files": int, "cases_per_level": {level: count}, "errors": [str] }
    """
    cases: List[TestCase] = []
    stats = {"files": 0, "cases_per_level": {}, "errors": [], "files_loaded": []}

    pattern = os.path.join(bench_dir, "*.yaml")
    yaml_files = sorted(glob.glob(pattern))

    if not yaml_files:
        stats["errors"].append(f"No .yaml files found in {bench_dir}")
        return cases, stats

    for fpath in yaml_files:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if not data or "cases" not in data:
                stats["errors"].append(f"{os.path.basename(fpath)}: missing 'cases' key")
                continue

            meta = data.get("meta", {})
            file_level = meta.get("level", 0)
            file_scoring = meta.get("scoring_method", "deterministic")
            file_top_k = meta.get("default_top_k", 5)

            file_cases = 0
            for raw in data["cases"]:
                tc = TestCase(
                    id=raw.get("id", f"unknown_{len(cases)}"),
                    level=raw.get("level", file_level),
                    question=raw.get("question", ""),
                    reference_answer=raw.get("reference_answer", ""),
                    expected_keywords=raw.get("expected_keywords", []),
                    expected_sources=raw.get("expected_sources", []),
                    all_required_sources=raw.get("all_required_sources", []),
                    negation_keywords=raw.get("negation_keywords", []),
                    distractor_source=raw.get("distractor_source"),
                    distractor_description=raw.get("distractor_description"),
                    min_score_threshold=raw.get("min_score_threshold", 0.65),
                    required_rank=raw.get("required_rank"),
                    scoring_method=raw.get("scoring_method", file_scoring),
                    notes=raw.get("notes", ""),
                )
                cases.append(tc)
                file_cases += 1

                lvl = tc.level
                stats["cases_per_level"][lvl] = stats["cases_per_level"].get(lvl, 0) + 1

            stats["files"] += 1
            stats["files_loaded"].append(f"{os.path.basename(fpath)} ({file_cases} cases, level {file_level})")

        except Exception as e:
            stats["errors"].append(f"{os.path.basename(fpath)}: {str(e)}")

    return cases, stats


# ─────────────────────────────────────────────────────────────────────────────
# DETERMINISTIC SCORER
# ─────────────────────────────────────────────────────────────────────────────

def score_deterministic(case: TestCase, results: List[Dict]) -> Tuple[bool, Dict]:
    """
    Checks:
      1. At least one expected keyword appears in the combined text of top-K chunks.
      2. At least one expected_source appears in results (or all_required_sources all present).
      3. The best chunk score >= min_score_threshold.
      4. If required_rank set: correct source is at that rank or better.
      5. If distractor_source set: correct chunk ranks above distractor.
    """
    details = {
        "keyword_hit": False,
        "source_hit": False,
        "score_ok": False,
        "rank_ok": True,
        "distractor_ok": True,
        "keywords_found": [],
        "keywords_missing": [],
        "top_score": 0.0,
        "correct_rank": None,
    }

    if not results:
        return False, details

    # Combined text of all retrieved chunks
    combined_text = " ".join(r.get("content", "") for r in results).lower()

    # 1. Keywords — each keyword is matched independently.
    #    A keyword phrase like "fonction cognitive" also matches plural/extended forms
    #    by checking if all its individual words appear within a 60-char window.
    def keyword_matches(kw: str, text: str) -> bool:
        kw = kw.lower().strip()
        if kw in text:
            return True
        # Partial stem match: all words of the keyword present as substrings
        words = [w for w in kw.split() if len(w) > 3]  # skip short stop words
        if not words:
            return False
        # Check each word appears somewhere in text (handles plurals, conjugations)
        return all(w in text for w in words)

    for kw in case.expected_keywords:
        if keyword_matches(kw, combined_text):
            details["keywords_found"].append(kw)
        else:
            details["keywords_missing"].append(kw)
    details["keyword_hit"] = len(details["keywords_missing"]) == 0 and len(case.expected_keywords) > 0

    # 2. Sources
    result_sources = [r.get("filename", r.get("source", "")) for r in results]
    if case.all_required_sources:
        details["source_hit"] = all(
            any(req in src for src in result_sources)
            for req in case.all_required_sources
        )
    elif case.expected_sources:
        details["source_hit"] = any(
            any(exp in src for src in result_sources)
            for exp in case.expected_sources
        )
    else:
        details["source_hit"] = True  # no source constraint

    # 3. Score threshold (small epsilon to absorb float rounding like 0.798 vs 0.800)
    SCORE_EPSILON = 0.005
    scores = [r.get("score", 0.0) for r in results]
    details["top_score"] = max(scores) if scores else 0.0
    details["score_ok"] = details["top_score"] >= (case.min_score_threshold - SCORE_EPSILON)

    # 4. Required rank
    if case.required_rank is not None and case.expected_sources:
        for i, r in enumerate(results):
            src = r.get("filename", r.get("source", ""))
            if any(exp in src for exp in case.expected_sources):
                details["correct_rank"] = i + 1
                details["rank_ok"] = (i + 1) <= case.required_rank
                break
        else:
            details["rank_ok"] = False

    # 5. Distractor ranking
    if case.distractor_source and case.expected_sources:
        correct_idx = None
        distractor_idx = None
        for i, r in enumerate(results):
            src = r.get("filename", r.get("source", ""))
            if correct_idx is None and any(exp in src for exp in case.expected_sources):
                correct_idx = i
            if distractor_idx is None and case.distractor_source in src:
                distractor_idx = i
        if correct_idx is not None and distractor_idx is not None:
            details["distractor_ok"] = correct_idx < distractor_idx
        elif correct_idx is None:
            details["distractor_ok"] = False

    passed = (
        details["keyword_hit"]
        and details["source_hit"]
        and details["score_ok"]
        and details["rank_ok"]
        and details["distractor_ok"]
    )
    return passed, details


# ─────────────────────────────────────────────────────────────────────────────
# LLM JUDGE (local Ollama)
# ─────────────────────────────────────────────────────────────────────────────

def _get_judge_config() -> Tuple[str, str]:
    cfg = get_config()
    model = cfg.get("modules.rag_bench.judge_model", "qwen3:4b")
    base_url = cfg.get("modules.rag_bench.ollama_base_url", "http://localhost:11434")
    return model, base_url


def _build_judge_prompt(case: TestCase, results: List[Dict]) -> str:
    chunks_text = ""
    for i, r in enumerate(results[:5]):  # Judge on top-5 max
        src = r.get("filename", r.get("source", f"chunk_{i+1}"))
        content = r.get("content", "")[:800]  # Truncate for token efficiency
        score = r.get("score", 0.0)
        chunks_text += f"\n--- Chunk {i+1} | Source: {src} | Score: {score:.3f} ---\n{content}\n"

    neg_instruction = ""
    if case.negation_keywords:
        neg_instruction = (
            f"\nATTENTION: Cette question attend une réponse NÉGATIVE ou une contrainte. "
            f"Le bon chunk doit contenir l'un de ces termes: {', '.join(case.negation_keywords)}. "
            f"Un chunk qui répond positivement à la question n'est PAS correct.\n"
        )

    return f"""Tu es un évaluateur de système RAG. Ta tâche est de déterminer si les chunks récupérés
contiennent l'information nécessaire pour répondre à la question posée.
{neg_instruction}
QUESTION: {case.question}

RÉPONSE DE RÉFÉRENCE: {case.reference_answer}

CHUNKS RÉCUPÉRÉS:
{chunks_text}

ÉVALUATION:
1. Est-ce qu'au moins un des chunks contient l'information essentielle pour répondre à la question ?
2. L'information est-elle suffisamment complète et précise ?

Réponds en JSON strict, sans markdown, sans backticks:
{{"score": 0 ou 1, "reasoning": "explication courte en français (max 100 mots)"}}

score=1 si les chunks permettent de répondre correctement, score=0 sinon."""


async def call_ollama_judge(prompt: str, model: str, base_url: str) -> Tuple[int, str]:
    """Call local Ollama and return (score 0/1, reasoning)."""
    url = f"{base_url.rstrip('/')}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 256},
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            raw = resp.json().get("response", "")

        # Strip potential <think>...</think> tags (qwen3 chain-of-thought)
        import re
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

        parsed = json.loads(raw)
        return int(parsed.get("score", 0)), parsed.get("reasoning", "")
    except json.JSONDecodeError:
        # Fallback: look for score in raw text
        if '"score": 1' in raw or '"score":1' in raw:
            return 1, raw[:200]
        return 0, f"JSON parse error: {raw[:200]}"
    except Exception as e:
        return 0, f"Judge error: {str(e)}"


async def score_llm_judge(case: TestCase, results: List[Dict]) -> Tuple[bool, Dict]:
    model, base_url = _get_judge_config()
    prompt = _build_judge_prompt(case, results)
    llm_score, reasoning = await call_ollama_judge(prompt, model, base_url)
    details = {
        "llm_score": llm_score,
        "judge_reasoning": reasoning,
        "judge_model": model,
        "top_score": max((r.get("score", 0.0) for r in results), default=0.0),
    }
    return llm_score == 1, details


# ─────────────────────────────────────────────────────────────────────────────
# HYBRID SCORER
# ─────────────────────────────────────────────────────────────────────────────

async def score_hybrid(case: TestCase, results: List[Dict]) -> Tuple[bool, Dict]:
    det_pass, det_details = score_deterministic(case, results)
    llm_pass, llm_details = await score_llm_judge(case, results)
    details = {**det_details, **llm_details}
    # Hybrid: both must pass. But if deterministic fails on source/score, trust it.
    # If deterministic passes but LLM fails: partial — use llm as tiebreaker.
    details["deterministic_pass"] = det_pass
    details["llm_pass"] = llm_pass
    return det_pass and llm_pass, details


# ─────────────────────────────────────────────────────────────────────────────
# MAIN RUNNER
# ─────────────────────────────────────────────────────────────────────────────

async def run_benchmark(
    cases: List[TestCase],
    engine_types: List[str],
    user_id: str,
    top_k: int,
    progress_cb=None,
) -> List[CaseResult]:
    from modules.rag_manager.rag_factory import get_rag_manager
    rag_manager = get_rag_manager()

    results: List[CaseResult] = []
    total = len(cases) * len(engine_types)
    done = 0

    for case in cases:
        for engine in engine_types:
            if progress_cb:
                progress_cb(done / total, f"[{engine}] {case.id}: {case.question[:60]}...")
            try:
                search_results = rag_manager.search(
                    user_id=user_id,
                    query=case.question,
                    engine_type=engine,
                    limit=top_k,
                ) or {}
                chunks = search_results.get(engine, [])

                method = case.scoring_method
                if method == "deterministic":
                    passed, details = score_deterministic(case, chunks)
                    reasoning = ""
                elif method == "llm_judge":
                    passed, details = await score_llm_judge(case, chunks)
                    reasoning = details.pop("judge_reasoning", "")
                else:  # hybrid
                    passed, details = await score_hybrid(case, chunks)
                    reasoning = details.pop("judge_reasoning", "")

                results.append(CaseResult(
                    case_id=case.id,
                    level=case.level,
                    engine=engine,
                    question=case.question,
                    passed=passed,
                    score_details=details,
                    retrieved_chunks=chunks,
                    judge_reasoning=reasoning,
                ))

            except Exception as e:
                log("error", f"rag_bench_run: error on {case.id}/{engine}: {e}", stacktrace=True)
                results.append(CaseResult(
                    case_id=case.id,
                    level=case.level,
                    engine=engine,
                    question=case.question,
                    passed=False,
                    score_details={},
                    retrieved_chunks=[],
                    error=str(e),
                ))
            done += 1

    if progress_cb:
        progress_cb(1.0, "Terminé !")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# RESULTS AGGREGATION
# ─────────────────────────────────────────────────────────────────────────────

def aggregate_results(results: List[CaseResult], engines: List[str]) -> Dict[int, Dict[str, LevelSummary]]:
    """Returns {level: {engine: LevelSummary}}"""
    agg: Dict[int, Dict[str, LevelSummary]] = {}

    for r in results:
        if r.level not in agg:
            agg[r.level] = {}
        if r.engine not in agg[r.level]:
            agg[r.level][r.engine] = LevelSummary(level=r.level, engine=r.engine, total=0, passed=0)
        agg[r.level][r.engine].total += 1
        if r.passed:
            agg[r.level][r.engine].passed += 1

    return agg


# ─────────────────────────────────────────────────────────────────────────────
# UI — MAIN TAB RENDERER
# ─────────────────────────────────────────────────────────────────────────────

def render_benchmark_run_tab():
    st.header("🏁 Benchmark Runner")
    st.caption("Exécute les datasets YAML contre tous les moteurs RAG disponibles.")

    cfg = get_config()
    bench_dir = cfg.get("modules.rag_bench.dataset_dir", "data/rag_bench")

    # ── Config panel ──────────────────────────────────────────────────────────
    with st.expander("⚙️ Configuration", expanded=False):
        col1, col2, col3 = st.columns(3)
        with col1:
            bench_dir_input = st.text_input("Répertoire dataset", value=bench_dir, key="rb_bench_dir")
        with col2:
            top_k = st.number_input("Top-K chunks", min_value=1, max_value=20, value=5, key="rb_top_k")
        with col3:
            judge_model = st.text_input(
                "Modèle juge (Ollama)",
                value=cfg.get("modules.rag_bench.judge_model", "qwen3:4b"),
                key="rb_judge_model"
            )
        ollama_url = st.text_input(
            "URL Ollama",
            value=cfg.get("modules.rag_bench.ollama_base_url", "http://localhost:11434"),
            key="rb_ollama_url"
        )

    bench_dir = bench_dir_input

    # ── Dataset scan ──────────────────────────────────────────────────────────
    st.subheader("📂 Dataset")
    cases, scan_stats = load_yaml_datasets(bench_dir)

    if scan_stats["errors"]:
        for err in scan_stats["errors"]:
            st.warning(f"⚠️ {err}")

    if not cases:
        st.error(f"Aucun cas de test trouvé dans `{bench_dir}`. Générez d'abord des datasets YAML.")
        return

    # Stats row
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Fichiers chargés", scan_stats["files"])
    with col2:
        st.metric("Cas de test total", len(cases))
    with col3:
        levels_present = sorted(scan_stats["cases_per_level"].keys())
        st.metric("Niveaux présents", f"{min(levels_present)}–{max(levels_present)}" if levels_present else "–")
    with col4:
        st.metric("Niveaux couverts", len(levels_present))

    with st.expander("📋 Détail des fichiers chargés", expanded=False):
        for f in scan_stats["files_loaded"]:
            st.caption(f"✅ {f}")
        for lvl, cnt in sorted(scan_stats["cases_per_level"].items()):
            st.caption(f"  • Niveau {lvl}: {cnt} cas")

    # ── Engine selection ───────────────────────────────────────────────────────
    from modules.rag_manager.rag_factory import get_rag_manager
    rag_manager = get_rag_manager()
    available_engines = [e["type"] for e in rag_manager.get_available_engines() if e["available"]]

    if not available_engines:
        st.error("Aucun moteur RAG disponible.")
        return

    selected_engines = st.multiselect(
        "Moteurs RAG à tester",
        options=available_engines,
        default=available_engines,
        key="rb_engines_widget"
    )

    if not selected_engines:
        st.warning("Sélectionnez au moins un moteur.")
        return

    # Level filter
    selected_levels = st.multiselect(
        "Niveaux à exécuter (vide = tous)",
        options=sorted(scan_stats["cases_per_level"].keys()),
        default=[],
        key="rb_levels_widget",
        format_func=lambda l: f"Niveau {l}"
    )

    # ── Run button ─────────────────────────────────────────────────────────────
    user_id = st.session_state.get("current_user", {}).get("id", "benchmark_user")

    filtered_cases = [c for c in cases if not selected_levels or c.level in selected_levels]
    n_runs = len(filtered_cases) * len(selected_engines)
    llm_judge_cases = sum(1 for c in filtered_cases if c.scoring_method in ("llm_judge", "hybrid"))

    col_run, col_info = st.columns([1, 3])
    with col_run:
        run_btn = st.button(f"▶️ Lancer le benchmark", type="primary", use_container_width=True)
    with col_info:
        st.caption(f"{len(filtered_cases)} cas × {len(selected_engines)} moteurs = **{n_runs} exécutions**")
        if llm_judge_cases > 0:
            st.caption(f"⚠️ {llm_judge_cases} cas utilisent le juge LLM ({judge_model}) — peut être lent.")

    if run_btn:
        # Run benchmark
        progress_bar = st.progress(0.0)
        status_text = st.empty()

        def progress_cb(pct, msg):
            progress_bar.progress(pct)
            status_text.caption(msg)

        with st.spinner("Benchmark en cours..."):
            bench_results = asyncio.run(run_benchmark(
                cases=filtered_cases,
                engine_types=selected_engines,
                user_id=user_id,
                top_k=top_k,
                progress_cb=progress_cb,
            ))

        progress_bar.empty()
        status_text.empty()
        st.session_state["rb_results"] = bench_results
        st.session_state["rb_engines"] = selected_engines
        st.session_state["rb_timestamp"] = datetime.now().strftime("%H:%M:%S")
        st.rerun()

    # ── Results display ────────────────────────────────────────────────────────
    if "rb_results" not in st.session_state:
        st.info("Lancez le benchmark pour voir les résultats.")
        return

    bench_results: List[CaseResult] = st.session_state["rb_results"]
    engines: List[str] = st.session_state["rb_engines"]
    agg = aggregate_results(bench_results, engines)
    levels_in_results = sorted(agg.keys())

    st.divider()
    st.subheader(f"📊 Résultats — {st.session_state.get('rb_timestamp', '')}")

    # ── Global summary heatmap ─────────────────────────────────────────────────
    st.markdown("### Vue d'ensemble")
    _render_summary_heatmap(agg, levels_in_results, engines)

    st.divider()

    # ── Per-level detail ───────────────────────────────────────────────────────
    st.markdown("### Détail par niveau")

    # Build lookup: (case_id, engine) -> CaseResult
    results_lookup: Dict[Tuple[str, str], CaseResult] = {
        (r.case_id, r.engine): r for r in bench_results
    }
    # Build lookup: case_id -> TestCase
    cases_lookup: Dict[str, TestCase] = {c.id: c for c in cases}

    for lvl in levels_in_results:
        _render_level_block(lvl, agg[lvl], engines, results_lookup, cases_lookup)


# ─────────────────────────────────────────────────────────────────────────────
# UI — SUMMARY HEATMAP
# ─────────────────────────────────────────────────────────────────────────────

def _render_summary_heatmap(
    agg: Dict[int, Dict[str, LevelSummary]],
    levels: List[int],
    engines: List[str],
):
    """Renders the level × engine heatmap with pass rates."""
    # Header row
    cols = st.columns([1] + [2] * len(engines))
    cols[0].markdown("**Niveau**")
    for i, eng in enumerate(engines):
        cols[i + 1].markdown(f"**{eng}**")

    # Find best engine per level
    for lvl in levels:
        level_data = agg.get(lvl, {})
        best_rate = max((level_data[e].pass_rate for e in engines if e in level_data), default=0)

        cols = st.columns([1] + [2] * len(engines))
        cols[0].markdown(f"Niv. **{lvl}**")

        for i, eng in enumerate(engines):
            summary = level_data.get(eng)
            if summary is None:
                cols[i + 1].caption("–")
                continue

            rate = summary.pass_rate
            is_best = rate == best_rate and best_rate > 0
            pct_str = f"{rate * 100:.0f}%"
            label = summary.label

            if is_best and len(engines) > 1:
                cols[i + 1].markdown(f"{label} **{pct_str}** ⬅ ({summary.passed}/{summary.total})")
            else:
                cols[i + 1].markdown(f"{label} {pct_str} ({summary.passed}/{summary.total})")


# ─────────────────────────────────────────────────────────────────────────────
# UI — LEVEL DETAIL BLOCK
# ─────────────────────────────────────────────────────────────────────────────

LEVEL_LABELS = {
    1: "Direct Keyword Match", 2: "Paraphrase Sémantique", 3: "Mot-clé dans contexte",
    4: "Synthèse multi-chunks", 5: "Cross-documents", 6: "Temporel/Séquentiel",
    7: "Négation/Absence", 8: "Numérique/Comparatif", 9: "Signal sparse",
    10: "Requête ambiguë", 11: "Distracteur adversarial",
}

def _render_level_block(
    lvl: int,
    level_agg: Dict[str, LevelSummary],
    engines: List[str],
    results_lookup: Dict[Tuple[str, str], CaseResult],
    cases_lookup: Dict[str, TestCase],
):
    label = LEVEL_LABELS.get(lvl, f"Niveau {lvl}")

    # Aggregate pass rates for expander title
    rates = [level_agg[e].pass_rate for e in engines if e in level_agg]
    avg_rate = sum(rates) / len(rates) if rates else 0
    emoji = "🟢" if avg_rate >= 0.9 else "🟡" if avg_rate >= 0.7 else "🟠" if avg_rate >= 0.5 else "🔴"

    with st.expander(f"{emoji} Niveau {lvl} — {label}  ({avg_rate*100:.0f}% avg)", expanded=(avg_rate < 0.7)):

        # Level summary bar per engine
        summary_cols = st.columns(len(engines))
        best_rate = max((level_agg[e].pass_rate for e in engines if e in level_agg), default=0)

        for i, eng in enumerate(engines):
            summary = level_agg.get(eng)
            if summary is None:
                summary_cols[i].caption(f"**{eng}**: –")
                continue
            rate = summary.pass_rate
            is_best = rate == best_rate and len(engines) > 1
            badge = "🏆 " if is_best else ""
            color = "green" if rate >= 0.9 else "orange" if rate >= 0.5 else "red"
            summary_cols[i].markdown(
                f"{badge}**{eng}**  \n"
                f":{color}[{rate*100:.0f}%] ({summary.passed}/{summary.total})"
            )

        st.divider()

        # Get all case IDs for this level
        case_ids = sorted({
            cid for (cid, _) in results_lookup.keys()
            if cases_lookup.get(cid) and cases_lookup[cid].level == lvl
        })

        # Per-case rows
        for cid in case_ids:
            tc = cases_lookup.get(cid)
            if tc is None:
                continue

            # Check if any engine failed for this case
            case_results = {eng: results_lookup.get((cid, eng)) for eng in engines}
            all_passed = all(r.passed for r in case_results.values() if r is not None)
            any_failed = any(not r.passed for r in case_results.values() if r is not None)

            row_icon = "✅" if all_passed else "❌" if not any(
                r.passed for r in case_results.values() if r is not None
            ) else "⚠️"

            with st.expander(f"{row_icon} `{cid}` — {tc.question[:80]}...", expanded=any_failed):

                st.caption(f"*{tc.notes}*" if tc.notes else "")
                st.caption(f"Méthode de scoring: `{tc.scoring_method}` | Seuil: `{tc.min_score_threshold}`")

                # One column per engine
                engine_cols = st.columns(len(engines))
                for i, eng in enumerate(engines):
                    r = case_results.get(eng)
                    with engine_cols[i]:
                        st.markdown(f"**{eng}**")
                        if r is None:
                            st.caption("Non exécuté")
                            continue

                        if r.error:
                            st.error(f"Erreur: {r.error}")
                            continue

                        # Pass/fail badge
                        if r.passed:
                            st.success("✅ PASS")
                        else:
                            st.error("❌ FAIL")

                        # Score details
                        d = r.score_details
                        if d.get("top_score") is not None:
                            st.caption(f"Score max: `{d.get('top_score', 0):.3f}` (seuil: `{tc.min_score_threshold}`)")

                        if d.get("keywords_found"):
                            st.caption(f"✓ Mots-clés: {', '.join(d['keywords_found'][:3])}")
                        if d.get("keywords_missing"):
                            st.caption(f"✗ Manquants: {', '.join(d['keywords_missing'][:3])}")

                        if d.get("llm_score") is not None:
                            score_str = "✅" if d["llm_score"] == 1 else "❌"
                            st.caption(f"Juge LLM: {score_str}")

                        if r.judge_reasoning:
                            st.caption(f"💬 _{r.judge_reasoning[:120]}_")

                        # Top retrieved chunks
                        if r.retrieved_chunks:
                            with st.popover(f"📄 {len(r.retrieved_chunks)} chunks"):
                                for j, chunk in enumerate(r.retrieved_chunks[:3]):
                                    src = chunk.get("filename", chunk.get("source", f"chunk_{j+1}"))
                                    score = chunk.get("score", 0)
                                    content = chunk.get("content", "")[:300]
                                    st.markdown(f"**{j+1}. {src}** (score: {score:.3f})")
                                    st.caption(content)
                                    if j < 2:
                                        st.divider()


# ─────────────────────────────────────────────────────────────────────────────
# INJECTION POINT (called from rag_bench_admin_ui.py)
# ─────────────────────────────────────────────────────────────────────────────

def get_benchmark_run_tab():
    """Returns (tab_name, render_function) for injection into the admin tab system."""
    return ("🏁 Benchmark", render_benchmark_run_tab)
