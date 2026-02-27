<!-- /modules/trainer/plugins/pedagogical_memory/AGENTS.md -->

# pedagogical_memory plugin

Structured pedagogical fact memory plugin for Trainer.

## Goal

Maintain a durable, evolvable memory of each student's learning journey as atomic facts, then inject only relevant facts at response time.

## Architecture

- Two-table SQL schema:
  - `PedagogicalFact`: atomic facts + embeddings + confidence lifecycle
  - `PedagogicalAnalysisLog`: analysis run metadata and versioning
- Three-step compaction:
  1. Extraction (LLM JSON facts)
  2. Reconciliation (semantic similarity + targeted LLM decision)
  3. Confidence decay (time-based, no LLM)
- Embedding-based retrieval at context injection:
  - Embed last user message
  - Rank active facts by cosine similarity × confidence
  - Inject top-K with prompt formatting

## Principles

- Taxonomy must be evolvable via `config.json` only.
- Compaction is manual-trigger only (UI button), no automatic background runs.
- Embeddings are lazy runtime operations; never load embedding models at plugin init.

## Key methods

| Method | Purpose |
|---|---|
| `refresh_memory(trainer_id, student_id)` | Run extraction → reconciliation → decay and write analysis log |
| `_extract_candidate_facts(...)` | LLM call #1, parse JSON candidates |
| `_decide_reconciliation(...)` | LLM call #2 decision for near-matches |
| `_run_confidence_decay(...)` | Call #3 confidence decay and soft delete |
| `get_memory_context(user_id, messages)` | Embed current query, retrieve and inject top-K facts |

## What to avoid

- Do NOT add analysis prompts to `memory` plugin — keep plugins separate.
- Do NOT hardcode fact types in Python; always read taxonomy from config.
- Do NOT run embeddings at plugin initialization time.
- Do NOT store embedding bytes in export files.

## Trainer guidance

For writing better training-program descriptions, use `SCAFFOLDING_TEMPLATE.md` in this directory.
