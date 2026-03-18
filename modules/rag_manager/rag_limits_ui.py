"""
RAG Result Limits UI Components

Streamlit UI components for managing result limits.
"""

import streamlit as st
import uuid
from typing import Optional, Dict, Any
from datetime import datetime

from modules.rag_manager.rag_result_limits import ResultLimitContext


def render_limit_controls_in_search(
    rag_manager,
    user_id: str,
    key_prefix: str = "search"
) -> Dict[str, Any]:
    """
    Render result limit controls in search interface.

    Returns:
        Dict with:
            - limit: The effective limit to use
            - query_id: Query ID for override tracking
            - is_override: Whether this is an override
    """
    # Get current user's role
    current_user = st.session_state.get('current_user', {})
    user_role = current_user.get('role', 'normal')

    # Check if this is an admin/master for override options
    can_override = user_role in ['admin', 'master']

    col1, col2 = st.columns([3, 1])

    with col2:
        if can_override:
            # Admin/master: can set temporary override
            default_limit = rag_manager.limit_manager.get_limit(
                context=ResultLimitContext.SEARCH_TEST,
                user_id=user_id
            )

            limit = st.number_input(
                "Results",
                min_value=rag_manager.limit_manager.config.min,
                max_value=rag_manager.limit_manager.config.max,
                value=default_limit,
                key=f"{key_prefix}_limit",
                help="Temporary override for this search only"
            )

            # Generate a query ID for this search
            if f"{key_prefix}_query_id" not in st.session_state:
                st.session_state[f"{key_prefix}_query_id"] = str(uuid.uuid4())

            query_id = st.session_state[f"{key_prefix}_query_id"]

            # Set the override
            if limit != default_limit:
                rag_manager.limit_manager.set_query_override(query_id, limit)
                is_override = True
            else:
                # Clear any existing override
                rag_manager.limit_manager.clear_query_override(query_id)
                is_override = False

            return {
                "limit": limit,
                "query_id": query_id,
                "is_override": is_override
            }
        else:
            # Normal user: shows current limit with preference option
            current_limit = rag_manager.limit_manager.get_limit(
                context=ResultLimitContext.SEARCH,
                user_id=user_id
            )

            st.metric("Results", current_limit)

            # Option to set preference (in expander to keep UI clean)
            with st.popover("⚙️"):
                st.caption("Set your preferred number of results")
                pref_limit = st.slider(
                    "Results",
                    min_value=rag_manager.limit_manager.config.min,
                    max_value=rag_manager.limit_manager.config.max,
                    value=current_limit,
                    key=f"{key_prefix}_pref"
                )

                if st.button("Save Preference", key=f"{key_prefix}_save_pref"):
                    rag_manager.limit_manager.set_user_preference(user_id, pref_limit)
                    st.success("Preference saved!")
                    st.rerun()

                if st.button("Reset to Default", key=f"{key_prefix}_reset_pref"):
                    rag_manager.limit_manager.clear_user_preference(user_id)
                    st.info("Reset to default")
                    st.rerun()

            return {
                "limit": current_limit,
                "query_id": None,
                "is_override": False
            }

    with col1:
        # Just a placeholder for the actual search input
        # This will be filled by the calling function
        pass

    return {"limit": 5, "query_id": None, "is_override": False}


def render_limit_management_panel(rag_manager):
    """
    Render the result limits management panel in admin UI.
    """
    st.subheader("🔢 Result Limits Configuration")

    tab1, tab2, tab3 = st.tabs([
        "Global Settings",
        "Engine Overrides",
        "User Preferences"
    ])

    with tab1:
        _render_global_settings(rag_manager)

    with tab2:
        _render_engine_overrides(rag_manager)

    with tab3:
        _render_user_preferences(rag_manager)


def _render_global_settings(rag_manager):
    """Render global result limits settings"""
    config = rag_manager.limit_manager.config

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Default Limits**")

        default_limit = st.number_input(
            "Default Search Results",
            min_value=1,
            max_value=50,
            value=config.default,
            help="Default number of results for general searches"
        )

        context_limit = st.number_input(
            "Context Injection Results",
            min_value=1,
            max_value=20,
            value=config.context_injection,
            help="Number of results injected into LLM context"
        )

        search_test_limit = st.number_input(
            "Search Test Results",
            min_value=1,
            max_value=50,
            value=config.search_test,
            help="Default for Search Test tab"
        )

    with col2:
        st.markdown("**Bounds**")

        min_limit = st.number_input(
            "Minimum Allowed",
            min_value=1,
            max_value=10,
            value=config.min
        )

        max_limit = st.number_input(
            "Maximum Allowed",
            min_value=5,
            max_value=100,
            value=config.max
        )

        st.markdown("**Stats**")
        st.metric("Active Overrides", rag_manager.limit_manager.get_active_overrides_count())

    if st.button("Save Global Settings", type="primary"):
        # Update config
        new_config = {
            "default": default_limit,
            "context_injection": context_limit,
            "search_test": search_test_limit,
            "min": min_limit,
            "max": max_limit,
            "per_engine": config.per_engine
        }

        # Update limit manager
        rag_manager.limit_manager.update_config(new_config)

        # Update rag_config
        if "result_limits" not in rag_manager.rag_config:
            rag_manager.rag_config["result_limits"] = {}
        rag_manager.rag_config["result_limits"].update(new_config)

        st.success("Global settings updated!")

        # Option to save to config.json
        if st.button("💾 Save to config.json"):
            _save_limits_to_config(rag_manager, new_config)


def _render_engine_overrides(rag_manager):
    """Render engine-specific result limits"""
    config = rag_manager.limit_manager.config
    per_engine = dict(config.per_engine)  # Make a copy

    st.markdown("Set specific result limits for each engine type")
    st.caption("Leave blank to use global default")

    # Get all available engines
    engines = rag_manager.get_available_engines()

    cols = st.columns(3)
    updated = False

    for i, engine in enumerate(engines):
        engine_type = engine['type']
        col = cols[i % 3]

        with col:
            current = per_engine.get(engine_type, config.default)
            new_limit = st.number_input(
                f"{engine_type}",
                min_value=config.min,
                max_value=config.max,
                value=current,
                key=f"engine_limit_{engine_type}",
                help=f"Default: {config.default}"
            )

            if new_limit != current:
                per_engine[engine_type] = new_limit
                updated = True

    if updated and st.button("Save Engine Overrides"):
        # Update config
        new_config = {
            "default": config.default,
            "context_injection": config.context_injection,
            "search_test": config.search_test,
            "min": config.min,
            "max": config.max,
            "per_engine": per_engine
        }

        rag_manager.limit_manager.update_config(new_config)

        if "result_limits" not in rag_manager.rag_config:
            rag_manager.rag_config["result_limits"] = {}
        rag_manager.rag_config["result_limits"]["per_engine"] = per_engine

        st.success("Engine overrides saved!")


def _render_user_preferences(rag_manager):
    """Show and manage user preferences"""
    preferences = rag_manager.limit_manager.get_all_user_preferences()

    if not preferences:
        st.info("No user preferences set yet")
        return

    st.markdown(f"**{len(preferences)} users have custom preferences**")

    # Create a table of preferences
    data = []
    for user_id, limit in preferences.items():
        # Try to get username from user manager
        user_info = rag_manager._user_manager.get_user(user_id)
        username = user_info.get('username', user_id) if user_info else user_id

        data.append({
            "User": username,
            "User ID": user_id,
            "Preferred Limit": limit,
            "Default": rag_manager.limit_manager.config.default
        })

    st.dataframe(data, use_container_width=True)

    # Option to clear all preferences
    if st.button("Clear All User Preferences", type="secondary"):
        for user_id in list(preferences.keys()):
            rag_manager.limit_manager.clear_user_preference(user_id)
        st.success("All user preferences cleared")
        st.rerun()


def _save_limits_to_config(rag_manager, limits_config: Dict[str, Any]):
    """Save limits to config.json"""
    import json
    from pathlib import Path
    from core.config import CONFIG_FILE

    try:
        config_path = Path(__file__).parent.parent.parent / CONFIG_FILE

        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                full_config = json.load(f)
        else:
            full_config = {}

        # Ensure rag_manager section exists
        if "rag_manager" not in full_config:
            full_config["rag_manager"] = {}

        # Update result limits
        if "result_limits" not in full_config["rag_manager"]:
            full_config["rag_manager"]["result_limits"] = {}

        full_config["rag_manager"]["result_limits"].update(limits_config)

        # Save back
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(full_config, f, indent=2, ensure_ascii=False)

        st.success("✅ Limits saved to config.json")

    except Exception as e:
        st.error(f"Failed to save to config.json: {str(e)}")
