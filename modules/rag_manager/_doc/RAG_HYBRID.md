# Hybrid RAG Engine — Technical Reference

## Overview

The Hybrid RAG engine (`rag_hybrid.py`) is a configurable retrieval-augmented generation system that combines multiple retrieval strategies. Every feature is independently togglable, making it possible to run controlled experiments or tune for specific corpora without changing code.

At indexing time, the engine splits documents into chunks, optionally enriches them with LLM-generated context prefixes, embeds them, and stores both a FAISS vector index and a BM25 keyword model. At query time, it can optionally generate a hypothetical answer (HyDE) before embedding the query, then blends cosine similarity and BM25 scores to rank candidates.

---

## Configuration Parameters

All parameters live under the relevant engine key in `config.json` → `rag_manager.engines`.

### Storage & Thresholds

| Parameter | Type | Default | Description |
|---|---|---|---|
| `index_path` | string | `data/hybrid_indexes/<engine_id>` | Where FAISS indexes and metadata are persisted on disk. Each named engine variant should use a distinct path to avoid cross-contamination. |
| `similarity_threshold` | float | `0.25` | Minimum blended score for a chunk to be included in results. Raise it to reduce noise; lower it to improve recall on vague queries. |

---

### Chunking Strategy

Controls how raw document text is split into retrievable units at index time. Chunking params take effect on the **next** `index_document` call — existing indexes are not retroactively changed.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `chunk_strategy` | string | `"sentence_window"` | One of `fixed`, `sentence`, `sentence_window`, or `dynamic`. See strategy details below. |
| `chunk_size` | int | `400` | Character length of each chunk when using `fixed` or `dynamic` strategies. |
| `chunk_overlap` | int | `60` | Character overlap between consecutive fixed chunks, to avoid cutting context at boundaries. |
| `sentence_window_size` | int | `3` | Half-width of the context window (±N sentences) returned alongside each matched sentence when using `sentence_window`. The matched sentence is embedded; the surrounding window is returned as display context. |
| `dynamic_chunk_sizes` | list | `[150, 300, 500]` | When `chunk_strategy` is `dynamic`, the engine indexes the document at all listed chunk sizes simultaneously. At query time the best-scoring hit from each size tier is retained. |

**Strategy comparison:**

- **`fixed`** — Slides a fixed-size window over the text with overlap. Simple and fast; can cut sentences mid-thought.
- **`sentence`** — One chunk per sentence. Highest precision, lowest context per chunk.
- **`sentence_window`** — Indexes at sentence granularity (tight embedding target) but returns the surrounding ±N sentences as context. Best balance of embedding focus and answer richness. **Recommended default.**
- **`dynamic`** — Indexes at multiple chunk sizes in parallel. Tests whether fine or coarse granularity better matches the query; increases index size significantly.

---

### HyDE — Hypothetical Document Embedding

Instead of embedding the raw user query, HyDE first asks an LLM to generate a short hypothetical answer, then embeds that answer. This bridges the vocabulary gap between short conversational queries and dense document prose.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `hyde` | bool | `true` | Enable/disable HyDE. When `false`, the raw query string is embedded directly. |
| `hyde_prompt_key` | string | `"rag_manager.hyde_prompt"` | Dotted key into the prompts YAML file (`prompts.en.yaml` / `prompts.fr.yaml`). The resolved text must contain `{query}`. If absent or unresolvable, a built-in fallback prompt is used. |
| `hyde_use_summaries` | bool | `false` | When `true`, up to 5 `>[!Résumé]` summary blocks (≤1500 chars total) are prepended to the HyDE prompt so the LLM generates a domain-grounded hypothetical answer rather than relying on its parametric world knowledge. Reduces hallucinated vocabulary in the embedding. |

**When HyDE helps:** queries that are short or conversational ("what is the role of attention?") where the document uses more formal or technical phrasing.

**When HyDE hurts:** very specific factual lookups where the LLM's hypothetical answer might introduce wrong vocabulary and steer the embedding away from the correct chunk.

---

### BM25 Hybrid Scoring

After cosine similarity retrieval, BM25 keyword scores can be blended in to boost chunks that share exact terminology with the query.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `bm25_hybrid` | bool | `true` | Enable BM25 scoring. Requires `rank_bm25` package. Falls back gracefully if not installed. |
| `bm25_alpha` | float | `0.5` | Weight of the cosine score in a full blend: `score = alpha × cosine_norm + (1−alpha) × bm25_norm`. Only used when `bm25_rerank_only` is `false`. |
| `bm25_rerank_only` | bool | `true` | When `true`, BM25 acts only as a fractional tiebreaker (`cosine + 0.01 × bm25`), never overriding cosine ranking. When `false`, BM25 is a co-equal signal weighted by `bm25_alpha`. **Set `false` for the `hybrid_bm25_blend` configuration.** |

**Rerank-only vs. full blend:**

- **Rerank-only (`bm25_rerank_only: true`):** Safe default for domain-specific corpora where one topic word (e.g. "attention") appears in nearly every chunk. BM25 would otherwise over-promote high-frequency words and drown out rare but critical phrases (e.g. negations like "cannot", "ne peut pas").
- **Full blend (`bm25_rerank_only: false`):** Treats BM25 as a co-equal retrieval signal. Works well when the corpus has diverse vocabulary and keyword matching genuinely discriminates between documents.

---

### Summary Injection

| Parameter | Type | Default | Description |
|---|---|---|---|
| `use_summaries` | bool | `true` | If the document contains `>[!Résumé]` or `>[!concepts]` callout blocks, they are extracted and injected as extra high-priority chunks at the front of the index. These summary chunks embed the chapter title alongside the block content so they score well on broad conceptual queries. |

Summary chunks are marked with `is_summary: true` in metadata and are surfaced in search results with their chapter name.

---

### Contextual Chunking

| Parameter | Type | Default | Description |
|---|---|---|---|
| `contextual_chunking` | bool | `false` | When `true`, each chunk is enriched at index time with a one-sentence LLM-generated prefix ("This passage covers…"). This adds context to chunks that would otherwise be hard to match because they lack identifying vocabulary. Significantly increases indexing time and LLM call count. |
| `contextual_model` | string or null | `null` | Which LLM model to use for contextual prefix generation. `null` uses the application's currently active model. |

---

## Named Engine Variants

The `config.json` ships with several pre-configured variants. Key ones:

| Engine ID | Key differences |
|---|---|
| `hybrid` | HyDE on, BM25 as tiebreaker only (`rerank_only: true`, `alpha: 0.5`) |
| `hybrid_no_hyde` | HyDE off — baseline for HyDE A/B comparison |
| `hybrid_no_hyde_no_dynamic` | HyDE off, no dynamic chunk sizes |
| `hybrid_wide_window` | Sentence window ±5 instead of ±3 |
| **`hybrid_bm25_blend`** | HyDE on, **full BM25 blend** (`rerank_only: false`, `alpha: 0.6`) — **default engine** |
| `hybrid_bm25_blend_no_hyde` | Full BM25 blend, HyDE off |
| `hybrid_hyde_summaries` | HyDE grounded with `>[!Résumé]` blocks injected into the HyDE prompt |

---

## `hybrid_bm25_blend` — Deep Dive

### 1. How It Works in This Configuration

`hybrid_bm25_blend` is the **default engine** (`default_engine` in `config.json`). Its distinguishing feature is that BM25 is a **co-equal retrieval signal**, not merely a tiebreaker.

**Effective settings:**

```json
{
  "hyde": true,
  "bm25_hybrid": true,
  "bm25_alpha": 0.6,
  "bm25_rerank_only": false,
  "chunk_strategy": "sentence_window",
  "sentence_window_size": 3,
  "similarity_threshold": 0.25,
  "use_summaries": true
}
```

**Query pipeline, step by step:**

```
User query
    │
    ▼
[HyDE] LLM generates a 3–5 sentence hypothetical answer
    │
    ▼
Embed hypothetical answer → query vector (cosine search)
    │
    ▼
FAISS IndexFlatIP: retrieve top k×6 candidates by cosine score
    │
    ▼
[BM25 blend] For every candidate:
    score = 0.6 × cosine_norm + 0.4 × bm25_norm
    │
    ▼
Sort all candidates by blended score
    │
    ▼
Filter: keep scores ≥ 0.25 (similarity_threshold)
    │
    ▼
Return top `limit` results (default: 5)
```

**Score formula:**

```
cosine_norm = (raw_cosine + 1.0) / 2.0   # maps [-1, 1] → [0, 1]
bm25_norm   = bm25_score / max_bm25       # normalised to [0, 1]

final_score = 0.6 × cosine_norm + 0.4 × bm25_norm
```

**Why this matters:** With `alpha = 0.6`, semantic similarity (cosine via HyDE) carries 60% of the weight and keyword overlap (BM25) carries 40%. A chunk that is semantically close but uses different vocabulary can still win — and a chunk that contains the exact query keywords but is semantically off-topic is held back by the cosine component.

**Why it is the default:** This configuration strikes the strongest balance for general-purpose corpora:
- HyDE closes the vocabulary gap between short user queries and long document prose.
- The full BM25 blend ensures that exact terminology in the query (technical terms, proper nouns, formulas) is rewarded, not just semantic proximity.
- Sentence-window chunking keeps embedding targets tight (one sentence) while returning rich context (±3 sentences) for answer generation.
- Summary injection gives broad conceptual queries a fast path to chapter-level context.

---

### 2. How to Structure Documents for `hybrid_bm25_blend`

This engine rewards documents that are **both semantically clear** (for HyDE/cosine) and **keyword-rich at the right granularity** (for BM25). The following practices maximise retrieval quality.

---

#### Use `>[!Résumé]` and `>[!concepts]` blocks

These blocks are extracted first and injected as high-priority summary chunks. They are the engine's best entry point for broad conceptual queries.

```markdown
# Chapter 3 — Attention Mechanisms

>[!Résumé]
> This chapter introduces the scaled dot-product attention mechanism and
> explains why softmax normalisation prevents gradient saturation. It covers
> multi-head attention, its computational complexity, and practical trade-offs
> versus recurrent architectures.

>[!concepts]
> attention · query · key · value · softmax · multi-head · self-attention · transformer
```

**Rules:**
- Place them immediately after the `#` chapter heading.
- Write the Résumé as 3–5 complete sentences. HyDE-generated embeddings will match this style.
- The concepts block is a flat list of key terms — it directly fuels BM25 recall.
- One Résumé + one concepts block per chapter is sufficient.

---

#### Write sentence-friendly prose

The `sentence_window` strategy embeds one sentence at a time. Make each sentence independently informative.

```markdown
✅  Good — each sentence carries standalone meaning
Scaled dot-product attention computes compatibility between a query vector and a
set of key vectors by taking their dot product and dividing by the square root
of the key dimension. This scaling prevents the softmax from entering a region
of extremely small gradients. The resulting weights are applied to the value
vectors to produce the output.

❌  Bad — meaning is split across sentences, first sentence is orphaned
It works as follows. The query is compared to the keys. Then values are weighted.
```

---

#### Use precise, consistent terminology

BM25 is an exact-match keyword model. If you alternate between synonyms ("attention weight", "attention score", "compatibility score") the BM25 signal fragments. Pick one canonical term per concept and use it consistently.

```markdown
✅  Consistent
The attention weight is computed via softmax. High attention weights indicate
strong relevance. The model learns which attention weights to prioritise.

❌  Fragmented
The compatibility score is computed via softmax. High attention weights indicate
strong relevance. The model learns which relevance coefficients to prioritise.
```

---

#### Structure with `##` section headings

Section headings provide chapter context that is embedded alongside the content. Clear headings also help when `>[!Résumé]` blocks reference them.

```markdown
# Chapter 3 — Attention Mechanisms

## 3.1 Scaled Dot-Product Attention

## 3.2 Multi-Head Attention

## 3.3 Complexity and Trade-offs
```

---

#### Keep paragraphs short and focused

The sentence-window retrieval returns ±3 sentences around the match. Paragraphs of 3–6 sentences mean a single window covers the entire paragraph — ideal. Very long paragraphs dilute the window with unrelated content.

```markdown
✅  Ideal paragraph length (~4 sentences)
Multi-head attention runs h independent attention functions in parallel. Each
head operates on a different learned linear projection of the queries, keys, and
values. The outputs of all heads are concatenated and projected once more. This
allows the model to jointly attend to information from different representation
subspaces.

❌  Too long — window cannot capture the full argument coherently
Multi-head attention ... [8+ sentences mixing multiple concepts]
```

---

#### Add inline definitions for key terms

BM25 rewards the co-occurrence of query terms and chunk terms. If a concept is defined where it is introduced, both the term and its explanation live in the same chunk.

```markdown
✅  Term and definition co-located
The key dimension d_k is the size of the key vectors. Dividing by √d_k prevents
the dot products from growing large in magnitude when d_k is large, which would
push the softmax into regions of very small gradients.
```

---

#### Avoid dense acronym-only sections

HyDE generates natural-language hypothetical answers. Acronym-dense text without expansion is poorly matched by cosine, and BM25 only helps if the user also types the acronym.

```markdown
✅  Expanded on first use
Multi-head attention (MHA) uses h = 8 heads in the original transformer.

❌  Acronym-only
MHA uses h = 8 in the standard setup.
```

---

#### Summary checklist

| Practice | Benefit |
|---|---|
| `>[!Résumé]` block per chapter | High-priority summary chunk; answers broad queries |
| `>[!concepts]` block per chapter | Pure keyword signal for BM25 |
| Short, self-contained sentences | Each sentence embeds cleanly for sentence-window |
| Consistent canonical terminology | BM25 score concentrates on the right term |
| `##` section headings | Structural context attached to each chunk |
| Paragraphs of 3–6 sentences | Window size ±3 captures the full paragraph |
| Inline definitions | Term + explanation co-located in one chunk |
| Expand acronyms on first use | HyDE cosine match works on natural language |


# Prompt — Document Formatting for the `hybrid_bm25_blend` RAG Engine

---

## System Prompt

```
You are an expert in structuring documents for hybrid semantic and keyword search systems.
You will reformat a document to make it optimal for a hybrid RAG engine that combines:
- Semantic search via embeddings (cosine similarity with HyDE)
- Keyword search (BM25, alpha=0.6)
- A sentence-window chunking strategy (sentence_window, ±3 sentences)
- Summary block injection as high-priority chunks

You must FULLY PRESERVE the content and information of the original document.
You do not delete, summarise, or invent anything. You reformat and enrich the structure.
```

---

## User Prompt

```
Reformat the following document so that it is optimally indexed by a hybrid RAG engine
(BM25 + semantic embeddings + HyDE).

Apply the following rules in order, without exception:

---

### 1. Structure into chapters with `#` headings

Each major logical section of the document must be introduced by a level-1 heading (`#`).
The heading must be descriptive and contain the key terms of the subject covered.

Example:
# Chapter 3 — Attention Mechanisms


---

### 2. Add a `>[!Résumé]` block after each `#` heading

Immediately below each `#` heading, insert a summary block following EXACTLY this format:

>[!Résumé]
> [3 to 5 complete sentences summarising the chapter. Each sentence must be self-contained
> and informative. Use the canonical vocabulary of the domain. Mention the key concepts,
> mechanisms described, and important conclusions of the chapter.]

Rules for the Résumé block:
- 3 to 5 sentences, no more, no less
- Each sentence must be readable independently and make sense on its own
- Use the same vocabulary as in the body text (no synonyms)
- Do not start every sentence with the same subject
- The block must answer: "What is this chapter about and what do we learn from it?"


---

### 3. Add a `>[!concepts]` block after the `>[!Résumé]` block

Immediately below the Résumé block, insert a concepts block:

>[!concepts]
> term1 · term2 · term3 · term4 · term5 · term6 · term7 · term8

Rules for the concepts block:
- Flat list of 6 to 12 technical terms or key concepts from the chapter
- Separated by ` · ` (space, middle dot, space)
- Canonical terms only: choose the form used in the body text
- Include acronyms in both their expanded and abbreviated form if both appear in the text
- No sentences, no trailing punctuation


---

### 4. Structure into subsections with `##` headings

Divide each chapter into logical subsections with level-2 headings (`##`).
`##` headings must be short, precise, and contain the key terms of the subject covered.

Example:
## 3.1 Scaled Dot-Product Attention


---

### 5. Reformat body text into short paragraphs

Each paragraph must meet the following constraints:
- **3 to 6 sentences per paragraph**, no more
- **Each sentence must be self-contained**: a sentence isolated from its paragraph must
  remain comprehensible and informative on its own
- **No orphan sentences**: avoid lead-in sentences ("Here is how it works.",
  "This can be explained as follows.") that have no meaning without what follows
- **One main idea per sentence**: do not compress two concepts into a single sentence with "and"
- Separate paragraphs with a blank line

❌ Bad example:
It works as follows. The query is compared to the keys. Then the values are weighted.

✅ Good example:
Scaled dot-product attention computes compatibility between a query vector and a set of
key vectors by taking their dot product and dividing by the square root of the key
dimension. This scaling prevents the softmax from entering regions of very small gradients.
The resulting weights are applied to the value vectors to produce the output.


---

### 6. Standardise terminology

The BM25 engine is sensitive to exact term repetition. Apply these rules:
- Identify all synonyms used for the same concept in the original document
- Choose **one canonical term** per concept and use it consistently throughout the document
- If an acronym is used, expand it on first occurrence then use the abbreviated form thereafter
- Record the terminology choices made in a note at the end of the document (see rule 9)

Example:
"compatibility score", "attention weight" and "relevance coefficient" → standardised to "attention weight"


---

### 7. Embed definitions next to terms

For every technical term introduced for the first time, place its definition in the same
sentence or paragraph. Do not defer to a separate "Definitions" section.

✅ Good example:
The key dimension d_k is the size of the key vectors. Dividing by √d_k prevents dot
products from growing large in magnitude when d_k is large, which would push the softmax
into regions of very small gradients.


---

### 8. Expand acronyms

At the first occurrence of each acronym, use the full form followed by the abbreviation
in parentheses. For subsequent occurrences, use the abbreviation alone.

✅ Good example:
Multi-head attention (MHA) runs h independent attention functions in parallel.
Each head of MHA operates on a different learned linear projection.


---

### 9. Add a reformatting note at the end of the document

After the last chapter, add a section:

---
## RAG Reformatting Note

**Terminology choices:**
- [original term 1] → [canonical term retained]
- [original term 2] → [canonical term retained]
- ...

**Structural changes:**
- [concise description of any groupings or splits performed]

**Unchanged content:** No information from the original document has been deleted or altered.


---

## Document to reformat:

[PASTE DOCUMENT HERE]
```

---

## Usage Notes

**This prompt is designed for:**
- Documents in English or French (the Markdown structure produced is identical)
- Technical, educational, or reference documents (courses, documentation, guides)
- Indexing into the `hybrid_bm25_blend` engine with `sentence_window_size: 3` and `use_summaries: true`

**This prompt is not suited for:**
- Very short documents (< 500 words) — apply rules 5 to 8 directly without summary blocks
- Documents already well structured in Markdown — check only the `>[!Résumé]` blocks and
  terminology consistency
- Tabular data or flat lists — these formats are better handled by the `simple` or `classic` engine

**Recommended temperature:** 0.2 — the model must be precise and faithful, not creative.

**Context length:** Process the document chapter by chapter if it exceeds ~6,000 tokens,
passing the `>[!Résumé]` block of the previous chapter as transition context.

## PageIndex optional engine

`rag_pageindex.py` integrates VectifyAI PageIndex as an optional engine type named
`pageindex`. PageIndex is expected under `vendor/PageIndex` as a git submodule and
must be installed separately because it is an optional, self-hosted backend:

```bash
git submodule update --init --recursive
python -m pip install -r vendor/PageIndex/requirements.txt
```

Enable it by setting the `pageindex` entry in `modules/rag_manager/config.json` to
`"enabled": true`. The engine keeps its indexes under `data/pageindex_indexes` and
is discovered through the normal RAG manager engine registry, so `rag_bench` can
benchmark it without importing the engine directly.
