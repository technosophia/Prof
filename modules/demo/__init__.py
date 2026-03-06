# modules/demo/__init__.py
"""
Demo module — starter kit and living reference for building new modules.

Files:
  demo_core.py      — all business logic, organized by demo section
  demo_ui.py        — Streamlit main-page injection (inject_ui_main_footer)
  demo_admin_ui.py  — Streamlit admin injection (inject_ui_admin_tab)

Lifecycle hooks called by module_handler:
  on_module_activated(services)
  on_module_deactivated()
"""

from .demo_core import demo_on_module_activated, demo_on_module_deactivated


def on_module_activated(services) -> None:
    demo_on_module_activated(services)


def on_module_deactivated() -> None:
    demo_on_module_deactivated()
