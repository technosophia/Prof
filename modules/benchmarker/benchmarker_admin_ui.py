"""Benchmarker admin UI injection."""

from modules.benchmarker.benchmarker_ui import render


def inject_ui_admin_tab():
    """Inject Benchmarker as an admin tab."""
    return ("Benchmarker", render)
