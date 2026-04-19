# modules/rag_bench/rag_bench_run_tab.py
"""
RAG Benchmark Runner Tab
========================
- Gauge scoring (0.0–1.0) instead of binary pass/fail
- Per-test best-engine trophy icon
- Global threshold override slider in UX
- Judge prompt via prompt_manager (judge_prompt)
- Enhanced error logging with raw response capture
"""

import streamlit as st
import os, glob, yaml, json, asyncio, re, httpx
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field

from core.logging import log
from st_shared.cached import get_config
from shared.prompt_manager import get_prompt
from shared.settings import UserSettingsManager
from modules.rag_bench.rag_bench_models import (
    TestCase, CaseResult, LevelSummary, aggregate_results,
    LEVEL_LABELS, FIXABLE_LEVELS, PARTIAL_LEVELS, ENGINE_LEVELS,
)
from modules.rag_bench.rag_bench_report import render_export_section, render_step_export
from json_repair import repair_json


GAUGE_WIDTH=130

# Global error log for the current benchmark session
BENCH_ERROR_LOG: List[Dict[str, Any]] = []

def log_bench_error(error_type: str, case_id: str, engine: str, details: Dict[str, Any]):
    """Log an error during benchmark execution with full context."""
    BENCH_ERROR_LOG.append({
        "timestamp": datetime.now().isoformat(),
        "type": error_type,
        "case_id": case_id,
        "engine": engine,
        **details
    })

def clear_bench_error_log():
    """Clear the error log for a new benchmark session."""
    global BENCH_ERROR_LOG
    BENCH_ERROR_LOG = []

def render_error_log():
    """Display the error log in the UI if there are errors."""
    if not BENCH_ERROR_LOG:
        return

    with st.expander(f"⚠️ Benchmark Errors ({len(BENCH_ERROR_LOG)})", expanded=True):
        for i, err in enumerate(BENCH_ERROR_LOG):
            with st.container():
                st.markdown(f"**Error {i+1}**: `{err['type']}` at {err['timestamp']}")
                st.markdown(f"**Case**: `{err['case_id']}` | **Engine**: `{err['engine']}`")

                if err['type'] == 'judge_json_parse':
                    st.error("JSON Parse Error - Raw Response:")
                    st.code(err.get('raw_response', 'No raw response'), language='text')
                    if 'stripped_response' in err:
                        st.info("Stripped Response (after <think> removal):")
                        st.code(err['stripped_response'], language='text')
                    if 'exception' in err:
                        st.caption(f"Exception: {err['exception']}")

                elif err['type'] == 'judge_http_error':
                    st.error(f"HTTP Error: {err.get('status_code', 'N/A')}")
                    st.code(err.get('response_text', 'No response'), language='text')

                elif err['type'] == 'judge_timeout':
                    st.error(f"Timeout after {err.get('timeout', 60)}s")

                elif err['type'] == 'search_error':
                    st.error(f"Search Error: {err.get('exception', 'Unknown')}")

                elif err['type'] == 'scoring_error':
                    st.error(f"Scoring Error: {err.get('exception', 'Unknown')}")

                elif err['type'] == 'unexpected_error':
                    st.error(f"Unexpected Error: {err.get('exception', 'Unknown')}")
                    if 'stacktrace' in err:
                        st.code(err['stacktrace'], language='text')

                st.divider()


# ─────────────────────────────────────────────────────────────────────────────
# BENCHMARK SETTINGS (via UserSettingsManager for persistence)
# ─────────────────────────────────────────────────────────────────────────────

def get_user_settings_manager() -> UserSettingsManager:
    """Get or create the UserSettingsManager instance."""
    if "_bench_settings_mgr" not in st.session_state:
        st.session_state._bench_settings_mgr = UserSettingsManager()
    return st.session_state._bench_settings_mgr


def get_bench_dir(user_id: Optional[str] = None) -> str:
    """Get the benchmark dataset directory with user preference support.

    Resolution order:
    1. User's personal preference
    2. Master's preference (via parent_id inheritance)
    3. Config default

    Args:
        user_id: Optional user ID. If None, returns config default.

    Returns:
        Directory path string
    """
    cfg = get_config()
    default_dir = cfg.get("dataset_dir", "material/rag_bench")

    if not user_id:
        return default_dir

    user_mgr = get_user_settings_manager()
    settings = user_mgr.get_user_settings(user_id)

    user_dir = settings.get("bench_dataset_dir")
    if user_dir:
        log("debug", f"Using user {user_id} bench_dataset_dir: {user_dir}")
        return user_dir

    user_info = user_mgr.user_manager.get_user(user_id)
    if user_info:
        parent_id = user_info.get("parent_id")
        if parent_id:
            master_settings = user_mgr.get_user_settings(parent_id)
            master_dir = master_settings.get("bench_dataset_dir")
            if master_dir:
                log("debug", f"Using master {parent_id} bench_dataset_dir for {user_id}: {master_dir}")
                return master_dir

    log("debug", f"Using config default bench_dataset_dir: {default_dir}")
    return default_dir


def set_bench_dir(bench_dir: str, user_id: str) -> bool:
    """Set the benchmark dataset directory for a user.

    Args:
        bench_dir: The directory path to set
        user_id: User ID to set preference for

    Returns:
        True if successful
    """
    log("info", f"Setting bench_dataset_dir for {user_id}: {bench_dir}")
    user_mgr = get_user_settings_manager()
    return user_mgr.update_user_settings(user_id, {"bench_dataset_dir": bench_dir})


def get_bench_judge_model(user_id: Optional[str] = None) -> str:
    """Get the judge's model for benchmarking with master inheritance.

    Args:
        user_id: Optional user ID. If None, returns config default.

    Returns:
        Model name string
    """
    cfg = get_config()
    default_model = cfg.get("judge_model", "qwen3:4b")

    if not user_id:
        return default_model

    user_mgr = get_user_settings_manager()
    user_settings = user_mgr.get_user_settings(user_id)

    user_model = user_settings.get("bench_judge_model")
    if user_model:
        return user_model

    user_info = user_mgr.user_manager.get_user(user_id)
    if user_info:
        parent_id = user_info.get("parent_id")
        if parent_id:
            master_settings = user_mgr.get_user_settings(parent_id)
            master_model = master_settings.get("bench_judge_model")
            if master_model:
                log("debug", f"Using master {parent_id} bench_judge_model for {user_id}: {master_model}")
                return master_model

    return default_model


def set_bench_judge_model(judge_model: str, user_id: str) -> bool:
    """Set the judge's model for a user.

    Args:
        judge_model: Model name to set
        user_id: User ID to set preference for

    Returns:
        True if successful
    """
    log("info", f"Setting bench_judge_model for {user_id}: {judge_model}")
    user_mgr = get_user_settings_manager()
    return user_mgr.update_user_settings(user_id, {"bench_judge_model": judge_model})


def get_bench_top_k(user_id: Optional[str] = None) -> int:
    """Get the top-K chunks for benchmarking with master inheritance.

    Args:
        user_id: Optional user ID. If None, returns config default.

    Returns:
        Top-K integer
    """
    cfg = get_config()
    default_top_k = cfg.get("bench_top_k", 5)

    if not user_id:
        return default_top_k

    user_mgr = get_user_settings_manager()
    user_settings = user_mgr.get_user_settings(user_id)

    user_top_k = user_settings.get("bench_top_k")
    if user_top_k is not None:
        return int(user_top_k)

    user_info = user_mgr.user_manager.get_user(user_id)
    if user_info:
        parent_id = user_info.get("parent_id")
        if parent_id:
            master_settings = user_mgr.get_user_settings(parent_id)
            master_top_k = master_settings.get("bench_top_k")
            if master_top_k is not None:
                log("debug", f"Using master {parent_id} bench_top_k for {user_id}: {master_top_k}")
                return int(master_top_k)

    return default_top_k


def set_bench_top_k(top_k: int, user_id: str) -> bool:
    """Set the top-K chunks for a user.

    Args:
        top_k: Top-K value to set
        user_id: User ID to set preference for

    Returns:
        True if successful
    """
    log("info", f"Setting bench_top_k for {user_id}: {top_k}")
    user_mgr = get_user_settings_manager()
    return user_mgr.update_user_settings(user_id, {"bench_top_k": top_k})


def load_yaml_datasets(bench_dir: str) -> Tuple[List[TestCase], Dict]:
    cases, stats = [], {"files": 0, "cases_per_level": {}, "errors": [], "files_loaded": []}
    for fpath in sorted(glob.glob(os.path.join(bench_dir, "*.yaml"))):
        try:
            with open(fpath, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not data or "cases" not in data:
                stats["errors"].append(f"{os.path.basename(fpath)}: missing 'cases'")
                continue
            meta = data.get("meta", {})
            file_level   = meta.get("level", 0)
            file_scoring = meta.get("scoring_method", "deterministic")
            file_count   = 0
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
                file_count += 1
                lvl = tc.level
                stats["cases_per_level"][lvl] = stats["cases_per_level"].get(lvl, 0) + 1
            stats["files"] += 1
            stats["files_loaded"].append(f"{os.path.basename(fpath)} ({file_count} cases, level {file_level})")
        except Exception as e:
            stats["errors"].append(f"{os.path.basename(fpath)}: {e}")
    return cases, stats


# ─────────────────────────────────────────────────────────────────────────────
# GAUGE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _keyword_matches(kw: str, text: str) -> bool:
    kw = kw.lower().strip()
    if kw in text:
        return True
    words = [w for w in kw.split() if len(w) > 3]
    return bool(words) and all(w in text for w in words)


def _gauge_color(gauge: float, threshold: float) -> str:
    """Return a hex color: red below threshold, white at threshold, green above."""
    delta = gauge - threshold
    if delta >= 0:
        # white → green
        t = min(delta / max(threshold, 0.1), 1.0)
        r = int(255 * (1 - t))
        g = 255
        b = int(255 * (1 - t))
    else:
        # red → white
        t = min(-delta / max(threshold, 0.1), 1.0)
        r = 255
        g = int(255 * (1 - t))
        b = int(255 * (1 - t))
    return f"#{r:02x}{g:02x}{b:02x}"


def _gauge_html(gauge: float, threshold: float, width: int = GAUGE_WIDTH, show_trophy: bool = False) -> str:
    """Render an inline HTML progress bar with threshold marker and color gradient."""
    pct       = int(gauge * 100)
    thr_pct   = int(threshold * 100)
    color     = _gauge_color(gauge, threshold)
    delta     = gauge - threshold
    sign      = "+" if delta >= 0 else ""
    label     = f"{pct}% ({sign}{delta*100:.1f}%)"
    trophy    = "🏆 " if show_trophy else ""

    return f"""
<div style="width:{width}px;display:inline-block;vertical-align:middle;">
  <div style="position:relative;height:14px;background:#333;border-radius:7px;overflow:hidden;">
    <div style="width:{pct}%;height:100%;background:{color};border-radius:7px;transition:width 0.3s;"></div>
    <div style="position:absolute;top:0;left:{thr_pct}%;width:2px;height:100%;background:#fff;opacity:0.8;"></div>
  </div>
  <div style="font-size:11px;color:{color};margin-top:2px;">{trophy}{label}</div>
</div>"""


# ─────────────────────────────────────────────────────────────────────────────
# DETERMINISTIC GAUGE  (0.0 – 1.0)
# ─────────────────────────────────────────────────────────────────────────────

def score_deterministic(case: TestCase, results: List[Dict]) -> Tuple[float, Dict]:
    """
    Returns a gauge in [0, 1] built from sub-scores:
      - keyword coverage  (40%)
      - source presence   (30%)
      - similarity score  (20%)
      - rank / distractor (10%)
    """
    details = {
        "keyword_hit": False, "source_hit": False,
        "score_ok": False, "rank_ok": True, "distractor_ok": True,
        "keywords_found": [], "keywords_missing": [],
        "top_score": 0.0, "correct_rank": None,
    }
    if not results:
        return 0.0, details

    combined = " ".join(r.get("content", "") for r in results).lower()

    # Keywords
    for kw in case.expected_keywords:
        if _keyword_matches(kw, combined):
            details["keywords_found"].append(kw)
        else:
            details["keywords_missing"].append(kw)
    kw_ratio = len(details["keywords_found"]) / len(case.expected_keywords) if case.expected_keywords else 1.0
    details["keyword_hit"] = kw_ratio == 1.0

    # Sources
    srcs = [r.get("filename", r.get("source", "")) for r in results]
    required = case.all_required_sources or case.expected_sources
    if required:
        matched = sum(1 for req in required if any(req in s for s in srcs))
        src_ratio = matched / len(required)
    else:
        src_ratio = 1.0
    details["source_hit"] = src_ratio == 1.0

    # Similarity score — normalised against threshold
    scores = [r.get("score", 0.0) for r in results]
    details["top_score"] = max(scores) if scores else 0.0
    sim_ratio = min(details["top_score"] / max(case.min_score_threshold, 0.01), 1.0)
    details["score_ok"] = details["top_score"] >= case.min_score_threshold - 0.005

    # Rank
    rank_ratio = 1.0
    if case.required_rank is not None and case.expected_sources:
        for i, r in enumerate(results):
            s = r.get("filename", r.get("source", ""))
            if any(exp in s for exp in case.expected_sources):
                details["correct_rank"] = i + 1
                details["rank_ok"] = (i + 1) <= case.required_rank
                rank_ratio = 1.0 if details["rank_ok"] else max(0.0, 1.0 - (i / len(results)))
                break
        else:
            rank_ratio = 0.0
            details["rank_ok"] = False

    # Distractor
    dist_ratio = 1.0
    if case.distractor_source and case.expected_sources:
        ci, di = None, None
        for i, r in enumerate(results):
            s = r.get("filename", r.get("source", ""))
            if ci is None and any(exp in s for exp in case.expected_sources): ci = i
            if di is None and case.distractor_source in s: di = i
        if ci is not None and di is not None:
            details["distractor_ok"] = ci < di
            dist_ratio = 1.0 if ci < di else 0.0
        elif ci is None:
            dist_ratio = 0.0
            details["distractor_ok"] = False

    # Weighted gauge
    gauge = (kw_ratio * 0.40 + src_ratio * 0.30 + sim_ratio * 0.20 + ((rank_ratio + dist_ratio) / 2) * 0.10)
    return round(min(gauge, 1.0), 4), details


# ─────────────────────────────────────────────────────────────────────────────
# LLM JUDGE GAUGE
# ─────────────────────────────────────────────────────────────────────────────

def _get_judge_config() -> Tuple[str, str]:
    cfg = get_config()
    return (
        cfg.get("judge_model", "qwen3:4b"),
        cfg.get("ollama_base_url", "http://localhost:11434"),
    )


def _build_judge_prompt(case: TestCase, results: List[Dict]) -> str:
    chunks_text = ""
    for i, r in enumerate(results[:5]):
        src     = r.get("filename", r.get("source", f"chunk_{i+1}"))
        content = r.get("content", "")[:800]
        score   = r.get("score", 0.0)
        chunks_text += f"\n--- Chunk {i+1} | Source: {src} | Score: {score:.3f} ---\n{content}\n"

    negation_instruction = ""
    if case.negation_keywords:
        neg_template = get_prompt("judge_negation_instruction")
        negation_instruction = neg_template.format(
            negation_keywords=", ".join(case.negation_keywords)
        )

    template = get_prompt("judge_prompt")
    return template.format(
        question=case.question,
        reference_answer=case.reference_answer,
        negation_instruction=negation_instruction,
        chunks_text=chunks_text,
    )

async def _call_ollama(prompt: str, model: str, base_url: str, case_id: str, engine: str) -> Tuple[int, str]:
    url = f"{base_url.rstrip('/')}/api/generate"

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.0,
            "num_predict": -1,
            "no_thinking": True
        }
    }

    raw_response = ""

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            raw_response = resp.json().get("response", "")

        # Remove <think> blocks if model ignored no_thinking
        stripped_response = re.sub(
            r"<think>.*?</think>",
            "",
            raw_response,
            flags=re.DOTALL
        ).strip()

        parsed = None
        parse_error = None

        try:
            # json-repair handles malformed JSON automatically
            parsed = repair_json(stripped_response, return_objects=True)
        except Exception as e:
            parse_error = e

        if isinstance(parsed, dict):
            score = int(parsed.get("score", 0))
            reasoning = parsed.get("reasoning", "")
            return score, reasoning

        # Parsing failed → log detailed error
        log_bench_error(
            error_type="judge_json_parse",
            case_id=case_id,
            engine=engine,
            details={
                "raw_response": raw_response,
                "stripped_response": stripped_response,
                "exception": str(parse_error) if parse_error else "Unknown parse error",
                "model": model,
                "prompt_preview": prompt[:500] + "..."
            }
        )

        # Heuristic fallback (rarely needed)
        if '"score": 1' in stripped_response:
            return 1, "Recovered score=1 after JSON repair failure"

        if '"score": 0' in stripped_response:
            return 0, "Recovered score=0 after JSON repair failure"

        return 0, f"JSON parse error: {stripped_response[:200]}"

    except httpx.TimeoutException as e:
        log_bench_error(
            error_type="judge_timeout",
            case_id=case_id,
            engine=engine,
            details={
                "exception": str(e),
                "model": model,
                "timeout": 60
            }
        )
        return 0, f"Judge timeout: {e}"

    except httpx.HTTPStatusError as e:
        log_bench_error(
            error_type="judge_http_error",
            case_id=case_id,
            engine=engine,
            details={
                "status_code": e.response.status_code,
                "response_text": e.response.text[:500] if hasattr(e.response, "text") else str(e),
                "model": model,
                "url": url
            }
        )
        return 0, f"Judge HTTP error: {e}"

    except Exception as e:
        log_bench_error(
            error_type="judge_unexpected",
            case_id=case_id,
            engine=engine,
            details={
                "exception": str(e),
                "model": model,
                "raw_response": raw_response[:500] if raw_response else "No response"
            }
        )
        return 0, f"Judge error: {e}"


async def score_llm_judge(case: TestCase, results: List[Dict], case_id: str, engine: str) -> Tuple[float, Dict]:
    model, base_url = _get_judge_config()
    prompt = _build_judge_prompt(case, results)
    llm_score, reasoning = await _call_ollama(prompt, model, base_url, case_id, engine)
    top = max((r.get("score", 0.0) for r in results), default=0.0)
    details = {"llm_score": llm_score, "judge_reasoning": reasoning,
               "judge_model": model, "top_score": top}
    # Gauge: binary LLM verdict + similarity bonus
    sim_bonus = min(top / max(case.min_score_threshold, 0.01), 1.0) * 0.2
    gauge = (llm_score * 0.8) + (sim_bonus if llm_score else 0.0)
    return round(min(gauge, 1.0), 4), details


async def score_hybrid(case: TestCase, results: List[Dict], case_id: str, engine: str) -> Tuple[float, Dict]:
    det_gauge, det_details = score_deterministic(case, results)
    llm_gauge, llm_details = await score_llm_judge(case, results, case_id, engine)
    details = {**det_details, **llm_details,
               "deterministic_gauge": det_gauge, "llm_gauge": llm_gauge}
    reasoning = details.pop("judge_reasoning", "")
    gauge = round((det_gauge * 0.5 + llm_gauge * 0.5), 4)
    return gauge, details


# ─────────────────────────────────────────────────────────────────────────────
# RUNNER
# ─────────────────────────────────────────────────────────────────────────────

async def run_benchmark(cases, engine_types, user_id, top_k,
                        threshold_override: Optional[float], progress_cb=None):
    from modules.rag_manager.rag_factory import get_rag_manager
    rag_mgr = get_rag_manager()
    results, done, total = [], 0, len(cases) * len(engine_types)

    # Clear error log for new benchmark session
    clear_bench_error_log()

    for case in cases:
        effective_threshold = threshold_override if threshold_override is not None else case.min_score_threshold
        for engine in engine_types:
            if progress_cb:
                progress_cb(done / total, f"[{engine}] {case.id}: {case.question[:55]}...")
            try:
                search = rag_mgr.search(user_id=user_id, query=case.question,
                                        engine_type=engine, limit=top_k) or {}
                chunks = search.get(engine, [])

                m = case.scoring_method
                try:
                    if m == "deterministic":
                        gauge, details = score_deterministic(case, chunks)
                        reasoning = ""
                    elif m == "llm_judge":
                        gauge, details = await score_llm_judge(case, chunks, case.id, engine)
                        reasoning = details.pop("judge_reasoning", "")
                    else:
                        gauge, details = await score_hybrid(case, chunks, case.id, engine)
                        reasoning = details.pop("judge_reasoning", "")
                except Exception as e:
                    log_bench_error(
                        error_type="scoring_error",
                        case_id=case.id,
                        engine=engine,
                        details={
                            "exception": str(e),
                            "scoring_method": m,
                            "stacktrace": __import__('traceback').format_exc()
                        }
                    )
                    # Continue with default values
                    gauge, details, reasoning = 0.0, {}, f"Scoring error: {e}"

                results.append(CaseResult(
                    case_id=case.id, level=case.level, engine=engine,
                    question=case.question, gauge=gauge,
                    threshold=effective_threshold,
                    score_details=details, retrieved_chunks=chunks,
                    judge_reasoning=reasoning,
                ))
            except Exception as e:
                error_msg = str(e)
                log_bench_error(
                    error_type="search_error",
                    case_id=case.id,
                    engine=engine,
                    details={
                        "exception": error_msg,
                        "stacktrace": __import__('traceback').format_exc()
                    }
                )
                log("error", f"rag_bench_run: {case.id}/{engine}: {e}", stacktrace=True)
                results.append(CaseResult(
                    case_id=case.id, level=case.level, engine=engine,
                    question=case.question, gauge=0.0,
                    threshold=effective_threshold,
                    score_details={}, retrieved_chunks=[], error=error_msg,
                ))
            done += 1

    if progress_cb:
        progress_cb(1.0, "Done!")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# UI — MAIN
# ─────────────────────────────────────────────────────────────────────────────


def render_benchmark_run_tab():
    st.header("🏁 Benchmark Runner")
    st.caption("Run YAML datasets against all available RAG engines.")

    cfg = get_config()

    current_user = st.session_state.get("current_user", {})
    user_id = current_user.get("id") if current_user else None
    user_role = current_user.get("role", "normal") if current_user else "normal"

    bench_dir = get_bench_dir(user_id)
    judge_model = get_bench_judge_model(user_id)
    top_k = get_bench_top_k(user_id)

    default_source = "default"
    if user_id:
        user_settings = get_user_settings_manager().get_user_settings(user_id)
        if user_settings.get("bench_dataset_dir"):
            default_source = "user"
        elif current_user and current_user.get("parent_id"):
            parent_id = current_user.get("parent_id")
            parent_settings = get_user_settings_manager().get_user_settings(parent_id)
            if parent_settings and parent_settings.get("bench_dataset_dir"):
                default_source = "master"

    # ── Config ────────────────────────────────────────────────────────────────
    with st.expander("⚙️ Configuration", expanded=False):
        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            bench_dir = st.text_input("Dataset directory", value=bench_dir, key="rb_dir_widget")
            if user_id and user_role in ("admin", "master"):
                col_save, col_info = st.columns([1, 2])
                with col_save:
                    if st.button("💾 Set as default", key="rb_save_dir_btn", use_container_width=True):
                        if set_bench_dir(bench_dir, user_id):
                            st.success(f"Saved: {bench_dir}")
                            st.rerun()
                with col_info:
                    st.caption(f"Source: **{default_source}**")
        with col2:
            top_k = st.number_input("Top-K chunks", min_value=1, max_value=20, value=top_k, key="rb_topk_widget")
            if user_id:
                if st.button("💾", key="rb_save_topk_btn", help="Save Top-K"):
                    if set_bench_top_k(top_k, user_id):
                        st.success(f"Saved Top-K: {top_k}")
        with col3:
            judge_model = st.text_input(
                "Judge model (Ollama)",
                value=judge_model,
                key="rb_judge_widget"
            )
            if user_id:
                if st.button("💾", key="rb_save_judge_btn", help="Save Judge model"):
                    if set_bench_judge_model(judge_model, user_id):
                        st.success(f"Saved Judge: {judge_model}")
        st.text_input(
            "Ollama URL",
            value=cfg.get("ollama_base_url", "http://localhost:11434"),
            key="rb_ollama_widget"
        )

    # ── Dataset scan ──────────────────────────────────────────────────────────
    st.subheader("📂 Dataset")
    cases, scan_stats = load_yaml_datasets(bench_dir)

    for err in scan_stats["errors"]:
        st.warning(f"⚠️ {err}")

    if not cases:
        st.error(f"No test cases found in `{bench_dir}`.")
        return

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Files", scan_stats["files"])
    col2.metric("Total cases", len(cases))
    levels_present = sorted(scan_stats["cases_per_level"].keys())
    col3.metric("Levels", f"{min(levels_present)}–{max(levels_present)}")
    col4.metric("Levels covered", len(levels_present))

    with st.expander("📋 Loaded files", expanded=False):
        for f in scan_stats["files_loaded"]:
            st.caption(f"✅ {f}")

    # ── Threshold override ────────────────────────────────────────────────────
    st.subheader("🎯 Threshold calibration")
    col_tog, col_sld = st.columns([1, 3])
    with col_tog:
        use_override = st.toggle("Global threshold override", value=False, key="rb_override_toggle")
    with col_sld:
        threshold_override = None
        if use_override:
            threshold_override = st.slider(
                "Global threshold (overrides YAML thresholds)",
                min_value=0.0, max_value=1.0, value=0.70, step=0.01,
                key="rb_threshold_slider",
                help="Slide to see how results change. "
                     "Gauges will recalculate on next run."
            )
            st.caption(f"Active threshold: **{threshold_override:.2f}** (overrides all YAML min_score_threshold)")
        else:
            st.caption("Individual YAML thresholds used per test.")

    # ── Engine + level selection ───────────────────────────────────────────────
    from modules.rag_manager.rag_factory import get_rag_manager
    rag_mgr = get_rag_manager()
    available_engines = [e["type"] for e in rag_mgr.get_available_engines() if e["available"]]

    if not available_engines:
        st.error("No RAG engines available.")
        return

    col_e, col_l = st.columns(2)
    with col_e:
        selected_engines = st.multiselect(
            "RAG engines", options=available_engines,
            default=available_engines, key="rb_engines_widget"
        )
    with col_l:
        selected_levels = st.multiselect(
            "Levels (empty = all)", options=levels_present,
            default=[], key="rb_levels_widget",
            format_func=lambda l: f"Level {l} — {LEVEL_LABELS.get(l, '')}"
        )

    if not selected_engines:
        st.warning("Select at least one engine.")
        return

    filtered = [c for c in cases if not selected_levels or c.level in selected_levels]
    n_llm = sum(1 for c in filtered if c.scoring_method in ("llm_judge", "hybrid"))
    user_id = st.session_state.get("current_user", {}).get("id", "benchmark_user")

    col_run, col_info = st.columns([1, 3])
    with col_run:
        run_btn = st.button("▶️ Run", type="primary", width='stretch')
    with col_info:
        st.caption(f"{len(filtered)} cases × {len(selected_engines)} engines = **{len(filtered)*len(selected_engines)} executions**")
        if n_llm:
            st.caption(f"⚠️ {n_llm} cases use LLM judge — may be slow.")

    if run_btn:
        pb = st.progress(0.0)
        st_txt = st.empty()
        bench_results = asyncio.run(run_benchmark(
            cases=filtered, engine_types=selected_engines,
            user_id=user_id, top_k=top_k,
            threshold_override=threshold_override,
            progress_cb=lambda p, m: (pb.progress(p), st_txt.caption(m)),
        ))
        pb.empty(); st_txt.empty()
        st.session_state["rb_results"]   = bench_results
        st.session_state["rb_engines"]   = selected_engines
        st.session_state["rb_timestamp"] = datetime.now().strftime("%H:%M:%S")
        st.rerun()

    # ── Results ───────────────────────────────────────────────────────────────
    # Display errors FIRST with a prominent banner
    if BENCH_ERROR_LOG:
        st.error(f"⚠️ {len(BENCH_ERROR_LOG)} error(s) occurred during benchmark. See details below.")

    render_error_log()

    if "rb_results" not in st.session_state:
        if BENCH_ERROR_LOG:
            st.warning("Errors occurred but no results were generated.")
        else:
            st.info("Run the benchmark to see results.")
        return

    bench_results: List[CaseResult] = st.session_state["rb_results"]
    engines: List[str]              = st.session_state["rb_engines"]
    agg = aggregate_results(bench_results, engines)
    levels_in_results = sorted(agg.keys())

    st.divider()
    st.subheader(f"📊 Results — {st.session_state.get('rb_timestamp', '')}")

    _render_summary_heatmap(agg, levels_in_results, engines)
    st.divider()
    st.markdown("### Detail by level")

    rlookup  = {(r.case_id, r.engine): r for r in bench_results}
    clookup  = {c.id: c for c in cases}

    for lvl in levels_in_results:
        _render_level_block(lvl, agg[lvl], engines, rlookup, clookup)

    render_export_section(
        results=bench_results,
        cases_lookup=clookup,
        engines=engines,
        threshold_override=st.session_state.get("rb_threshold_slider") if st.session_state.get("rb_override_toggle") else None,
        run_timestamp=st.session_state.get("rb_timestamp", "unknown"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# UI — SUMMARY HEATMAP
# ─────────────────────────────────────────────────────────────────────────────

def _render_summary_heatmap(agg, levels, engines):
    # Calculate overall scores per engine (sum of gauges across all levels)
    overall_scores = {}
    for engine in engines:
        total_gauge_sum = 0
        total_cases = 0
        for lvl in levels:
            if engine in agg[lvl]:
                # Use avg_gauge * total to get the sum of gauges for this level
                total_gauge_sum += agg[lvl][engine].avg_gauge * agg[lvl][engine].total
                total_cases += agg[lvl][engine].total
        overall_scores[engine] = total_gauge_sum / total_cases if total_cases > 0 else 0

    # Find best overall engine
    best_overall = max(overall_scores.items(), key=lambda x: x[1])[0] if overall_scores else None

    # Engine names header
    cols = st.columns([1] + [2] * len(engines))
    cols[0].markdown("")  # Empty cell for alignment
    for i, e in enumerate(engines):
        cols[i+1].markdown(f"**{e}**")

    # Overall scores row
    cols = st.columns([1] + [2] * len(engines))
    cols[0].markdown("**Overall**")
    for i, e in enumerate(engines):
        is_best = e == best_overall and len(engines) > 1
        cols[i+1].markdown(
            _gauge_html(overall_scores[e], 0.70, width=140, show_trophy=is_best),
            unsafe_allow_html=True
        )

    # Per-level rows
    for lvl in levels:
        ld = agg.get(lvl, {})
        best_avg = max((ld[e].avg_gauge for e in engines if e in ld), default=0)
        thr = 0.70  # display threshold for heatmap (informational)

        cols = st.columns([1] + [2] * len(engines))
        cols[0].markdown(f"Level **{lvl}**")
        for i, e in enumerate(engines):
            s = ld.get(e)
            if s is None:
                cols[i+1].caption("–")
                continue
            is_best = s.avg_gauge == best_avg and len(engines) > 1
            cols[i+1].markdown(
                f"{_gauge_html(s.avg_gauge, thr, width=140, show_trophy=is_best)} "
                f"<small>({s.passed}/{s.total})</small>",
                unsafe_allow_html=True
            )

# ─────────────────────────────────────────────────────────────────────────────
# UI — LEVEL DETAIL
# ─────────────────────────────────────────────────────────────────────────────

def _render_level_block(lvl, level_agg, engines, rlookup, clookup):
    label    = LEVEL_LABELS.get(lvl, f"Level {lvl}")
    avgs     = [level_agg[e].avg_gauge for e in engines if e in level_agg]
    avg_rate = sum(avgs) / len(avgs) if avgs else 0
    emoji    = "🟢" if avg_rate >= 0.85 else "🟡" if avg_rate >= 0.65 else "🟠" if avg_rate >= 0.45 else "🔴"

    with st.expander(f"{emoji} Level {lvl} — {label}  (avg {avg_rate*100:.0f}%)", expanded=(avg_rate < 0.65)):

        # Per-engine summary bar
        best_avg = max((level_agg[e].avg_gauge for e in engines if e in level_agg), default=0)
        scols = st.columns(len(engines))
        for i, e in enumerate(engines):
            s = level_agg.get(e)
            if s is None: continue
            is_best = s.avg_gauge == best_avg and len(engines) > 1
            badge   = "🏆 " if is_best else ""
            scols[i].markdown(
                f"{badge}**{e}**  \n" +
                _gauge_html(s.avg_gauge, 0.70, width=GAUGE_WIDTH, show_trophy=is_best) +
                f"<br><small>({s.passed}/{s.total} pass)</small>",
                unsafe_allow_html=True
            )

        st.divider()

        # Per-case rows
        case_ids = sorted({cid for (cid, _) in rlookup if clookup.get(cid) and clookup[cid].level == lvl})

        for cid in case_ids:
            tc = clookup.get(cid)
            if tc is None: continue

            case_results = {e: rlookup.get((cid, e)) for e in engines}

            # Best engine for this specific test case
            best_gauge   = max((r.gauge for r in case_results.values() if r), default=0)
            any_fail     = any(r and not r.passed for r in case_results.values())
            all_pass     = all(r and r.passed for r in case_results.values() if r)
            row_icon     = "✅" if all_pass else "⚠️" if any_fail and not all_pass else "❌"

            with st.expander(f"{row_icon} `{cid}` — {tc.question[:80]}", expanded=any_fail):
                if tc.notes:
                    st.caption(f"_{tc.notes}_")
                st.caption(f"Method: `{tc.scoring_method}` | YAML threshold: `{tc.min_score_threshold}`")

                ecols = st.columns(len(engines))
                for i, e in enumerate(engines):
                    r = case_results.get(e)
                    with ecols[i]:
                        st.markdown(f"**{e}**")
                        if r is None:
                            st.caption("Not executed"); continue
                        if r.error:
                            st.error(f"Error: {r.error}"); continue

                        # Trophy on best engine for this test
                        is_best = r.gauge == best_gauge and len(engines) > 1
                        trophy  = "🏆 " if is_best else ""

                        st.markdown(
                            f"{trophy}" + _gauge_html(r.gauge, r.threshold, width=GAUGE_WIDTH, show_trophy=is_best),
                            unsafe_allow_html=True
                        )

                        d = r.score_details
                        if d.get("top_score") is not None:
                            st.caption(f"Sim: `{d['top_score']:.3f}` / threshold `{r.threshold:.2f}`")
                        if d.get("keywords_found"):
                            st.caption(f"✓ {', '.join(d['keywords_found'][:3])}")
                        if d.get("keywords_missing"):
                            st.caption(f"✗ {', '.join(d['keywords_missing'][:3])}")
                        if d.get("llm_score") is not None:
                            st.caption(f"Judge: {'✅' if d['llm_score']==1 else '❌'}")
                        if r.judge_reasoning:
                            st.caption(f"💬 _{r.judge_reasoning[:120]}_")

                        if r.retrieved_chunks:
                            with st.popover(f"📄 {len(r.retrieved_chunks)} chunks"):
                                for j, chunk in enumerate(r.retrieved_chunks[:3]):
                                    src     = chunk.get("filename", chunk.get("source", f"chunk_{j+1}"))
                                    score   = chunk.get("score", 0)
                                    content = chunk.get("content", "")[:300]
                                    st.markdown(f"**{j+1}. {src}** ({score:.3f})")
                                    st.caption(content)
                                    if j < 2: st.divider()

                # Per-step export — all engines for this case in one shot
                render_step_export(
                    case_id=cid,
                    tc=tc,
                    case_results=case_results,
                    engines=engines,
                )


# ─────────────────────────────────────────────────────────────────────────────
# INJECTION
# ─────────────────────────────────────────────────────────────────────────────

def get_benchmark_run_tab():
    return ("🏁 Benchmark", render_benchmark_run_tab)
