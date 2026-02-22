"""Project-wide pytest entrypoint.

Delegates to tests.conftest so hooks/fixtures apply to all test paths,
including module-local integration tests.
"""

from tests.conftest import *  # noqa: F401,F403
