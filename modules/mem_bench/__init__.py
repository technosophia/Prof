"""Memory benchmark module activation hooks."""

from __future__ import annotations

import os

from core.logging import log
from shared.common import check_services


def on_module_activated(services) -> None:
    """Initialize mem_bench module services."""
    required = check_services(["config", "driver", "user_manager", "conversation_manager"], services=services, module_name="mem_bench")
    config = required["config"]
    scenarios_dir = config.get("scenarios_dir", "data/mem_bench/scenarios")
    output_dir = config.get("output_dir", "data/mem_bench/output")
    os.makedirs(scenarios_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)
    log("info", "mem_bench: activated")


def on_module_deactivated() -> None:
    """No explicit teardown required for mem_bench."""
    log("info", "mem_bench: deactivated")
