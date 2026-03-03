"""
RAG Manager UI

STREAMLIT-ONLY FILE. All functions here use Streamlit (st.*).
No functional/business logic lives here.

Injection points:
    inject_ui_initialize()          — st.session_state setup only
    inject_ui_sidebar()             — sidebar controls (admin/master)
    inject_ui_inside_conversation() — RAG debug context display
    inject_ui_admin_tab()           — admin tab registration

The actual RAG logic (search, context retrieval, callback registration)
lives in rag_manager.py and __init__.py.
"""

import streamlit as st
from datetime import datetime
from pathlib import Path
import json

from core.config import CONFIG_FILE
from core.logging import log
from shared.module_handler import module_handler, notify_module_config_changed


def _get_rag_manager():
    """Lazy accessor — never called at module import time."""
    from modules.rag_manager.rag_factory import get_rag_manager
    return get_rag_manager()


# ---------------------------------------------------------------------------
# inject_ui_initialize  — session_state only, no functional setup
# ---------------------------------------------------------------------------

def inject_ui_initialize() -> bool:
    """
    Initialize Streamlit session state for RAG UI.

    Functional setup (driver registration, LLM callbacks) was already done
    by on_module_activated() via module_handler. This function ONLY touches
    st.session_state.
    """
    if 'rag_debug_enabled' not in st.session_state:
        st.session_state.rag_debug_enabled = False

    # Don't set this here - let the actual engine state determine it
    # We'll check the actual registered callbacks when rendering
    # if 'rag_injection_enabled' not in st.session_state:
    #     st.session_state.rag_injection_enabled = True

    if 'last_rag_context' not in st.session_state:
        st.session_state.last_rag_context = ""
    if 'last_rag_query' not in st.session_state:
        st.session_state.last_rag_query = ""
    if 'last_rag_timestamp' not in st.session_state:
        st.session_state.last_rag_timestamp = 0

    return True

# ---------------------------------------------------------------------------
# inject_ui_sidebar
# ---------------------------------------------------------------------------

def inject_ui_sidebar():
    """Inject RAG settings into the sidebar (admin/master only)."""
    current_user = st.session_state.get('current_user')
    if not current_user:
        return
    if current_user['role'] not in ['admin', 'master']:
        return

    rag_manager = _get_rag_manager()

    with st.sidebar.expander("⚙️ RAG Settings", expanded=False):
        engines = rag_manager.get_available_engines()
        available_engines = [e for e in engines if e['available']]

        if not available_engines:
            st.warning("No engines available")
            return

        from st_shared.cached import get_config
        config = get_config()
        current_default = config.get("modules.rag_manager.default_engine", "simple")

        engine_options = [e['type'] for e in available_engines]
        current_index = engine_options.index(current_default) if current_default in engine_options else 0

        selected_engine = st.selectbox(
            "Default RAG Engine",
            options=engine_options,
            index=current_index,
            help="Select the default engine for searches and indexing",
        )

        st.divider()
        st.subheader("Debug")

        rag_debug_enabled = st.toggle(
            "Show RAG Context",
            value=st.session_state.get('rag_debug_enabled', False),
            help="Shows the RAG context used for LLM queries in an expander",
        )
        if rag_debug_enabled != st.session_state.get('rag_debug_enabled', False):
            st.session_state.rag_debug_enabled = rag_debug_enabled
            st.rerun()

        st.caption("Displays retrieved document context in chat")

        # FIX: Always ensure the toggle reflects the actual state
        # Check if the current engine is active by seeing if its callback is registered
        from modules.rag_manager import _ENGINE_CONTEXT_CALLBACKS
        current_engine_active = rag_manager.default_engine in _ENGINE_CONTEXT_CALLBACKS

        rag_injection_enabled = st.toggle(
            "Enable RAG Context Injection",
            value=current_engine_active,  # Use actual state instead of session state
            help="When enabled, RAG context is injected into LLM queries",
        )

        # FIX: Handle toggle changes properly
        if rag_injection_enabled != current_engine_active:
            from modules.rag_manager import _activate_rag_engine, _deactivate_rag_engine
            if rag_injection_enabled:
                _activate_rag_engine(rag_manager.default_engine)
                log("info", f"[RAG UI] RAG ENABLED via UI toggle for engine {rag_manager.default_engine}")
                st.sidebar.success("RAG context injection enabled")
            else:
                _deactivate_rag_engine(rag_manager.default_engine)
                log("info", f"[RAG UI] RAG DISABLED via UI toggle for engine {rag_manager.default_engine}")
                st.sidebar.info("RAG context injection disabled")

        if st.button("Apply Changes", type="secondary", use_container_width=True):
            changes_made = False

            # Handle engine change
            if selected_engine != current_default:
                rag_config_path = Path(__file__).parent / CONFIG_FILE
                try:
                    if rag_config_path.exists():
                        with open(rag_config_path, 'r', encoding='utf-8') as f:
                            rag_config_data = json.load(f)
                    else:
                        rag_config_data = {"rag_manager": {}}

                    if "rag_manager" not in rag_config_data:
                        rag_config_data["rag_manager"] = {}

                    rag_config_data["rag_manager"]["default_engine"] = selected_engine

                    with open(rag_config_path, 'w', encoding='utf-8') as f:
                        json.dump(rag_config_data, f, indent=2, ensure_ascii=False)

                    config.set("modules.rag_manager.default_engine", selected_engine)
                    rag_manager.default_engine = selected_engine
                    changes_made = True

                except Exception as e:
                    st.sidebar.error(f"Failed to update config: {str(e)}")

            # Handle the changes
            if changes_made:
                notify_module_config_changed("rag_manager")

                # FIX: Re-activate the new engine if injection is enabled
                if rag_injection_enabled:
                    from modules.rag_manager import _activate_rag_engine
                    _activate_rag_engine(selected_engine)

                st.sidebar.success(f"Default engine set to: {selected_engine}")
                st.rerun()
            else:
                st.sidebar.info("No changes made")

        st.caption(f"Current: {current_default}")
        st.divider()
        st.caption("Engine Status:")
        for engine in available_engines:
            status_icon = "✅" if engine['available'] else "❌"
            default_icon = "⭐" if engine['type'] == current_default else ""
            active_icon = "🔵" if engine['type'] in _ENGINE_CONTEXT_CALLBACKS else ""
            st.caption(f"{status_icon} {default_icon} {active_icon} {engine['type']}")


# ---------------------------------------------------------------------------
# inject_ui_inside_conversation
# ---------------------------------------------------------------------------

def inject_ui_inside_conversation():
    """Render RAG debug context after conversation (when debug toggle is on)."""
    if not st.session_state.get('rag_debug_enabled', False):
        return
    if not st.session_state.get('last_rag_context'):
        return

    with st.expander("🔍 RAG Debug Context", expanded=False):
        st.write("**Last RAG context injected into LLM:**")
        context_text = st.session_state.last_rag_context
        formatted = context_text.replace("---", "\n---")
        st.text_area(
            "Context",
            formatted,
            height=200,
            key="rag_debug_context_display",
            label_visibility="collapsed",
        )

        col1, col2 = st.columns(2)
        with col1:
            if st.session_state.get('last_rag_query'):
                st.caption(f"**Query:** {st.session_state.last_rag_query}")
        with col2:
            if st.session_state.get('last_rag_timestamp'):
                ts = datetime.fromtimestamp(st.session_state.last_rag_timestamp)
                st.caption(f"**Retrieved:** {ts.strftime('%Y-%m-%d %H:%M:%S')}")

        if st.button("Clear RAG Context History", type="secondary"):
            st.session_state.last_rag_context = ""
            st.session_state.last_rag_query = ""
            st.session_state.last_rag_timestamp = 0
            st.rerun()

    return None


# ---------------------------------------------------------------------------
# inject_ui_admin_tab
# ---------------------------------------------------------------------------

def inject_ui_admin_tab():
    """Register the RAG Manager admin tab."""
    from modules.rag_manager.rag_admin_ui import show_rag_admin_content
    return ("RAG Manager", show_rag_admin_content)


# ---------------------------------------------------------------------------
# inject_ui_main_content  (kept as stub for compatibility)
# ---------------------------------------------------------------------------

def inject_ui_main_content():
    return None
