<!-- /api/AGENTS.md -->

# API module scope

This directory contains the FastAPI student frontend backend.

## Rules
- Keep routes thin and focused on HTTP translation.
- Reuse business logic through `shared/common.py`.
- Do not import anything from `st_shared/`.
- Keep authentication centralized in `api/deps.py`.
