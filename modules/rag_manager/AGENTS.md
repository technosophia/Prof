<!-- /modules/rag_manager/AGENTS.md -->

RAG module : it's purpose is to inject training context provided by a teacher (MASTER role) into a student (NORMAL role) discussion for the LLM to answer specifically.

The RAG system can work with multiple RAG engine : the goal is to compare them and use the best.

## Driver integration

The RAG module registers the following with `shared/driver.py` at initialize():

### Option group: `rag_engine`
- `simple` — keyword-based retrieval
- `classic` — vector similarity retrieval
- `faiss_hierarchical` — hierarchical chunking and retrieval

Only engines that exist and are enabled are registered.

### No actions registered.
RAG retrieval is automatic via the LLM context callback system.
The active engine registers its context callback on activate.

### Invariant:
The benchmarker never imports RAG code. Options are the only interface.
