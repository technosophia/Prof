# modules/demo/demo_admin_ui.py
"""
Demo module — Admin UI injection.
"""

import streamlit as st
from st_shared.cached import _


def _show_admin_content():
    st.header(_("demo.section_title"))
    st.caption(_("demo.section_description"))

    st.markdown("### Module files")
    st.markdown("""
| File | Purpose |
|------|---------|
| `demo_core.py` | All business logic (no Streamlit) |
| `demo_ui.py` | Main-page UI — `inject_ui_main_footer()` |
| `demo_admin_ui.py` | Admin UI — `inject_ui_admin_tab()` |
| `__init__.py` | Lifecycle hooks wired to demo_core |
| `config.json` | Module config (auto-loaded under `modules.demo.*`) |
| `translations/en.json` | UI strings |
| `prompt.en.yml` | LLM prompts |
    """)

    st.markdown("### Injection points")
    st.code("""
# Main page (demo_ui.py)
def inject_ui_main_footer(): ...

# Admin tab (demo_admin_ui.py)
def inject_ui_admin_tab(): ...   # returns (tab_name, render_fn)

# Module lifecycle (__init__.py)
def on_module_activated(services): ...
def on_module_deactivated(): ...
    """, language="python")


def inject_ui_admin_tab():
    """Returns (tab_name, render_function) for the admin panel."""
    return (_("demo.section_title"), _show_admin_content)
