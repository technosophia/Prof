"""Compatibility exports for step definitions.

Pytest hooks and bootstrap live in repository-level `conftest.py`.
This module only re-exports fixture symbols imported explicitly by
`tests/step_defs/*` files.
"""

from conftest import TEST_PORT, context, debug_dir, page  # noqa: F401
