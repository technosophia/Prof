"""Memory benchmark admin tab injection."""

from modules.mem_bench.ui import render


def inject_ui_admin_tab():
    """Inject Memory Bench in admin tabs."""
    return ("Mem Bench", render)
