# ADR-001 — Hybrid RAG Engine & Multi-Instance Engine Registry

**Context:** `modules/rag_manager`

---

## Context

The RAG pipeline in Professor was originally built around three engines (`simple`, `classic`, `faiss_hierarchical`) each hardcoded as a singleton and registered by name in `rag_manager.py`. This worked fine until benchmarking revealed that retrieval quality varied significantly by query type, and that no single configuration was optimal across all difficulty levels.

A systematic benchmark (`rag_bench_report.py`) across 66 test cases covering 11 difficulty levels (direct keyword match → cross-document synthesis) showed:

- `classic` and `faiss_hierarchical` plateaued around **0.85–0.87** global pass rate
- Several level-8 (multi-chunk synthesis) cases failed universally due to missing cross-section signal
- Level-6 (negation/absence) cases were unreliable across all engines
- No mechanism existed to compare variants (e.g. HyDE on vs off) without code changes

This ADR documents the decisions made to address these problems.

---

## Decisions

### 1. New engine class: `HybridRAGEngine`

**File:** `modules/rag_manager/rag_engines/rag_hybrid.py`  
**Registered type slug:** `"hybrid"`

A new engine combining multiple independently-togglable retrieval strategies:

| Feature | Config key | Default | Notes |
|---|---|---|---|
| Sentence-window chunking | `chunk_strategy` | `sentence_window` | Index at sentence level, return ±N sentences as context |
| Window size | `sentence_window_size` | `3` | ±3 sentences returned around the matched sentence |
| Summary chunk injection | `use_summaries` | `true` | `>[!Résumé]` / `>[!concepts]` blocks indexed as high-signal extra chunks |
| HyDE | `hyde` | `true` | Embed a hypothetical answer instead of the raw query |
| HyDE grounding | `hyde_use_summaries` | `false` | Prepend indexed `>[!Résumé]` blocks to the HyDE prompt to ground generation |
| HyDE prompt | `hyde_prompt_key` | `rag_manager.hyde_prompt` | Dotted key into prompts YAML |
| BM25 hybrid | `bm25_hybrid` | `true` | Combine BM25 keyword score with cosine score |
| BM25 mode | `bm25_rerank_only` | `true` | Tiebreaker only (`cosine + 0.01 * bm25`), not full blend |
| BM25 blend alpha | `bm25_alpha` | `0.5` | Used only when `bm25_rerank_only=false` |
| Contextual chunking | `contextual_chunking` | `false` | LLM-generated per-chunk context prefix at index time (slow) |

**Why `bm25_rerank_only=true` by default:**  
Full BM25 blend (`alpha * cosine + (1-alpha) * bm25`) failed level-6 negation queries because BM25 scored every "attention"-heavy chunk equally, drowning out the rare negation phrase ("ne peut pas"). Tiebreaker mode preserves cosine ranking while letting BM25 break ties — fixes negation without hurting synthesis queries.

**Why HyDE underperforms on this corpus:**  
HyDE was designed assuming the LLM has reasonable parametric knowledge of the domain. This corpus is a specialist proprietary training document with specific vocabulary (extase, enstase, locus coeruleus, mur de l'absurde). The LLM's hypothetical answer diverges from the document's actual framing, steering the embedding search in the wrong direction for precise queries. `hyde=false` is the recommended default for proprietary/specialist corpora.

**Why `hyde_use_summaries` helps when HyDE is enabled:**  
When HyDE is used, injecting the indexed `>[!Résumé]` summary blocks into the prompt grounds the LLM's generation in the document's actual vocabulary. This recovers most of the cases where ungrounded HyDE fails, without requiring external context injection or module coupling — the summaries are already in the engine's own index.

**Benchmark results (66 cases, 11 levels):**

| Engine | Global avg | Notes |
|---|---|---|
| `hybrid` (HyDE on, ungrounded) | 0.872 | HyDE hurts on levels 5, 6, 8 |
| `hybrid_no_hyde` | 0.929 | Clean baseline |
| `hybrid_hyde_summaries` | **0.946** | HyDE grounded with `>[!Résumé]` blocks — best overall |
| `hybrid_bm25_blend_no_hyde` | 0.924 | Full BM25 blend fails level-5/8 |
| `hybrid_wide_window` (±5) | 0.854 | Wider window hurts precision |

**Remaining hard failure:** `l6_002` ("Peut-on se passer complètement de l'attention ?") fails all engines — the negation phrase `"ne peut pas"` appears in a chunk that no strategy retrieves consistently. Requires either chunk size reduction or document annotation.

---

### 2. Async wrapper pattern for `_llm_one_shot`

HyDE and contextual chunking both require synchronous LLM calls from within the engine. The engine has no access to Streamlit's async context. Three patterns were tried:

**❌ `asyncio.run()` directly** — fails in Streamlit: `"asyncio.run() cannot be called from a running event loop"`.

**❌ `get_running_loop()` + thread executor** — flaky; the detection races with Streamlit's rerun mechanism and occasionally fails with service-not-initialized errors.

**✅ Always spawn a thread, always call `asyncio.run()` inside it:**

```python
def _run_in_thread():
    return asyncio.run(
        manager.internal_response(manager.current_llm, messages)
    )

with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
    return pool.submit(_run_in_thread).result(timeout=30)
```

A fresh thread has no event loop, so `asyncio.run()` always works. This pattern is safe in both Streamlit (running loop on the main thread) and bench/subprocess contexts (no running loop anywhere). See also: commit `22f7201` in `modules/trainer/plugins/pedagogical_memory/core.py` which solved the same problem.

**LLM manager resolution (`_get_llm_manager`):**  
The engine resolves the LLM manager via a two-path fallback:
1. `shared.common.get_llm_manager()` — standard app runtime via service locator
2. `get_rag_manager().llm_manager` — bench/early-init contexts where the service locator is not yet initialized but the rag_manager already holds a direct reference

---

### 3. Multi-instance engine registry in `rag_manager.py`

**Problem:** The original registry instantiated exactly one engine per class, identified by a hardcoded name. Running multiple configurations of the same engine class (e.g. `hybrid_no_hyde`, `hybrid_wide_window`) was impossible without code changes.

**Solution:** Decouple *instance name* (config key) from *engine type* (class slug) via an explicit `"type"` field in config.

#### config.json structure

```json
"engines": {
  "hybrid_no_hyde": {
    "type": "hybrid",
    "hyde": false,
    "sentence_window_size": 3,
    ...
  },
  "hybrid_hyde_summaries": {
    "type": "hybrid",
    "hyde": true,
    "hyde_use_summaries": true,
    ...
  }
}
```

- The **config key** (`hybrid_no_hyde`) is the instance name shown in bench/UI and used as the default `index_path` suffix.
- The **`"type"` field** maps to the engine class slug (what `super().__init__("X")` sets on the class).
- If `"type"` is absent, it falls back to the config key — backward compatible with `classic`, `simple`, `faiss_hierarchical`.
- Special case: `"llama_index"` (config key with underscore) requires `"type": "llamaindex"` explicitly since the class registers without underscore.

#### `rag_manager.py` changes

**`discover_engines()`** — builds `self._engine_classes {engine_type → class}` by scanning `rag_engines/` without instantiating. Detects `engine_type` via:
1. `ENGINE_TYPE` class constant (preferred, explicit)
2. Regex on `super().__init__("X")` in source
3. Strip `"rag_"` prefix from module filename (fallback)

**`instantiate_engines()`** — new method called at the end of `__init__`, after `discover_engines()`:
- Reads `self._get_rag_config().get("engines", {})` (not `self.config`)
- Resolves class via `ecfg.get("type", engine_id)`
- Skips `engine_id` already in `self.engines` (guard against double-instantiation)
- Passes `config=ecfg` and `engine_id=engine_id` to the constructor
- Each `HybridRAGEngine` instance uses `engine_id` to isolate its `index_path` automatically: `data/hybrid_indexes/{engine_id}`

**`get_engine_ids()`** — new method returning `list(self.engines.keys())`, used to make `__init__.py` driver registration fully dynamic instead of hardcoding `("simple", "classic", "faiss_hierarchical")` as candidates.

#### `__init__.py` changes

`_resolve_activation_engine()` and `on_module_activated()` now iterate `manager.get_engine_ids()` instead of a hardcoded list — any engine declared in `config.json` is automatically registered as a driver option with its `description` attribute as the display label.

---

## Consequences

**Positive:**
- Any number of engine variants can be declared in `config.json` and benchmarked without code changes
- HyDE, BM25 mode, window size, summary injection are all independently controlled per instance
- `hybrid_hyde_summaries` achieves **94.6%** global pass rate vs **87.2%** for the original `hybrid` — a +7.4 point improvement
- The async pattern is now documented and consistent with the fix applied in `pedagogical_memory`

**Negative / watch-outs:**
- Each named engine variant with a different `index_path` requires a separate index build — adding variants has a one-time indexing cost
- `hyde_use_summaries` requires `>[!Résumé]` blocks to be present in the document; if none are indexed, it silently falls back to ungrounded HyDE
- The `_get_llm_manager` two-path fallback assumes `rag_manager.llm_manager` exists as a direct attribute — verify this holds if the rag_manager architecture changes
- Level-6 negation failures (`l6_002`, `l6_005`) are a **document/chunking problem**, not an engine problem — no retrieval strategy can find a phrase that isn't in any returned chunk

---

## Files Changed

| File | Change |
|---|---|
| `modules/rag_manager/rag_engines/rag_hybrid.py` | New engine class |
| `modules/rag_manager/rag_engine.py` | Added `engine_id`, `get_config()`, `update_config()` stubs to base class |
| `modules/rag_manager/rag_manager.py` | `discover_engines()`, `instantiate_engines()`, `get_engine_ids()` |
| `modules/rag_manager/__init__.py` | Dynamic driver registration via `get_engine_ids()` |
| `modules/rag_manager/rag_admin_ui.py` | Engine config editor tab with `bm25_rerank_only` toggle |
| `modules/rag_manager/prompts.en.yaml` | Added `rag_manager.hyde_prompt` |
| `modules/rag_manager/prompts.fr.yaml` | Added `rag_manager.hyde_prompt` |
| `config.json` | Engine registry with typed multi-instance declarations |

---

## References

- Benchmark tool: `rag_bench_report.py`
- Test document: `RAG - Formation Attention.md`
- HyDE paper: Gao et al., "Precise Zero-Shot Dense Retrieval without Relevance Labels" (2022)
- Related fix: commit `22f7201` — async pattern in `pedagogical_memory/core.py`
