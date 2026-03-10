"""Compatibility ASGI entrypoint.

`uvicorn api:app` resolves to the `api` package because `api/` exists.
This file is kept for backward compatibility, while the canonical app lives in
`api/__init__.py`.
"""

from api import app, bootstrap_services

__all__ = ["app", "bootstrap_services"]
