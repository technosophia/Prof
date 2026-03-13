<!-- /tests/frontend/AGENTS.md -->

# Frontend API integration tests scope

This directory contains HTTP-level integration tests for the FastAPI backend used by the React frontend.

## Rules
- Use HTTP tests only (`httpx` with ASGI transport).
- Do not import Streamlit UI code.
- Keep tests independent (each test creates its own conversation state).
- Use the `create_conversation` fixture from `tests/frontend/conftest.py` (DRY).
- LLM tests must be marked `@pytest.mark.ollama`.
- `@pytest.mark.ollama` tests must enforce `ollama_qwen` and reject mock outputs.
- RAG-heavy tests must be marked `@pytest.mark.slow`.

## Bootstrap strategy
- Root `conftest.py` performs DB reset, user creation, module activation, and RAG indexing.
- `api/__init__.py` is refactored to expose `create_app()` and avoid a second bootstrap in `TEST_MODE`.
- During tests, `api` reuses global services created by root `conftest.py`.

## Sync/async decision
- Test client uses `httpx.AsyncClient` with `ASGITransport` (httpx version in this repo exposes async-only ASGI transport methods).
- SSE responses are consumed via `async with client.stream(...)` and parsed with `tests/frontend/helpers.py`.

## Open issues
- LLM calls require local Ollama runtime availability.
- RAG answer wording can vary; assertions focus on key fictional facts.
