<!-- /modules/rag_manager/AGENTS.md -->

## Purpose
Inject training context (provided by a MASTER role) into student (NORMAL role) conversations. Multiple RAG engines can coexist — the goal is to benchmark them and activate the best one.

## Key files
- `rag_manager.py` — discovers, instantiates, and exposes all engines; entry point for index/search
- `rag_engine.py` — base class: `engine_type`, `engine_id`, `get_config()`, `update_config()`
- `rag_engines/rag_hybrid.py` — configurable hybrid engine (HyDE, sentence-window, BM25, summaries)
- `rag_engines/` — one file per engine class; auto-discovered at startup
- `rag_admin_ui.py` — Streamlit config editor; reads `get_config()` / writes `update_config()`
- `__init__.py` — driver registration; dynamically iterates `manager.get_engine_ids()`
- `config.json` (root) — engine registry under `rag_manager.engines`
- `prompts.en/fr.yaml` — prompt keys including `rag_manager.hyde_prompt`

## Engine registry

Engines are declared in `config.json`, not hardcoded. Each entry under `rag_manager.engines` is an independent instance:

```json
"hybrid_no_hyde": {
  "type": "hybrid",   ← class slug (ENGINE_TYPE on the class)
  "hyde": false,
  "enabled": true,
  ...
}
```

- **Config key** = instance name (`engine_id`), used as index path suffix and UI label
- **`"type"`** = class slug registered by the engine class; falls back to config key if absent (backward compat for `classic`, `simple`, `faiss_hierarchical`)
- Multiple instances of the same class are allowed and benchmarkable independently
- Each instance gets its own isolated index at `data/hybrid_indexes/{engine_id}`

## Driver integration

Registers with `shared/driver.py` at `initialize()`:

### Option group: `rag_engine`
All enabled engines in `config.json` are registered dynamically — no hardcoded list. Display label comes from the engine's `description` attribute.

### No actions registered.
RAG retrieval is automatic via the LLM context callback. The active engine registers its context callback on activate.

## Do / Don't
- Do: declare new engine variants in `config.json` with a `"type"` field — no code change needed
- Do: use `manager.get_engine_ids()` wherever engine names are iterated (never hardcode)
- Do: run `_llm_one_shot` via `ThreadPoolExecutor` always — never call `asyncio.run()` directly (Streamlit has a running loop); see `_get_llm_manager()` for the two-path fallback
- Do: add `ENGINE_TYPE = "slug"` as a class constant on new engine classes for reliable discovery
- Don't: instantiate engines outside `instantiate_engines()` — guard against double-instantiation is there
- Don't: import RAG code from the benchmarker — options are the only interface (invariant)
- Don't: use `bm25_rerank_only=false` on domain-specific corpora with a dominant topic word — BM25 blend drowns out negation phrases

## See also
- `_doc/_adr/001_hybrid_engine.md` — full rationale, benchmark results, async pattern decision
- `/_docs/_adr/013_async_get_running_loop_BUG.md` — auto-generated API reference
