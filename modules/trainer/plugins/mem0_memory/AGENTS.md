<!-- /modules/trainer/plugins/mem0_memory/AGENTS.md -->

# mem0_memory plugin

Trainer memory plugin backed by **mem0 OSS** (local FAISS + Ollama).

## Goal

Maintain a persistent, semantic memory of each student's learning journey and
inject *relevant* facts into the teacher LLM's context at call time.

## How it differs from the `memory` plugin

| | `memory` | `mem0_memory` |
|---|---|---|
| Who extracts facts? | Our LLM, via custom prompts | mem0's internal LLM |
| Storage | SQL (one summary row per student) | FAISS vector store (atomic facts) |
| Retrieval | Full summary blob, always injected | Semantic search on the current message |
| Prompts needed | `analysis_system`, `analysis_user`, `context_injection` | `context_injection` only |

## Principles

- **mem0 owns extraction.** Raw `[{"role": ..., "content": ...}]` messages go
  directly into `mem0_client.add()`. Do NOT pre-summarise them.
- **Semantic retrieval.** At context injection time, call `mem0_client.search(last_user_message)`
  to get the *K* most relevant facts. Do not dump all memories.
- **No analysis prompts.** `prompts.en.yaml` contains only `context_injection`.
  Adding `analysis_system` / `analysis_user` here would be a regression back to the
  `memory` plugin pattern and must be avoided.
- **Namespaced user keys.** `trainer:{trainer_id}:student:{student_id}` prevents
  cross-trainer contamination.

## Key methods

| Method | Purpose |
|---|---|
| `ingest_messages(student_id, trainer_id, messages)` | Push raw messages to mem0 |
| `search_memories(student_id, trainer_id, query)` | Semantic recall |
| `get_memory_context(user_id, messages)` | LLM context callback — calls search |
| `on_conversation_message(...)` | Hook for post-exchange ingestion |
| `list_all_memories(...)` | For UI display and export |

## What to avoid

- Do NOT call `_analyze_with_llm` or any equivalent — there is no such method here.
- Do NOT store a serialised text blob into mem0 via `add(string, ...)`.
- Do NOT copy prompts from the `memory` plugin into this plugin's `prompts.en.yaml`.

## Configuration (`config.json`)

```json
{
  "mem0_memory": {
    "storage_dir": "data/mem0_memory",
    "ollama_base_url": "http://127.0.0.1:11434",
    "embedding_model": "nomic-embed-text",
    "embedding_dimensions": 768,
    "llm_model": "qwen2.5:7b",
    "top_k": 5
  }
}
```

`top_k` controls how many memories are injected per conversation turn.
