# modules/demo/demo_ui.py
"""
Demo module — Main page UI.

Two injection points:
  inject_ui_initialize()   — called once at app startup (headless-tolerant).
                             Only st.session_state initialization goes here.
  inject_ui_main_footer()  — called each render cycle to display the module.

All business logic is called from demo_core.py (Streamlit-free).
All shared singletons are retrieved from st_shared.cached.
"""

import streamlit as st
import os, sys
from st_shared.cached import (
    _,
    get_config,
    get_user_manager,
    get_conversation_manager,
    get_llm_manager,
    get_prompt_manager,
)
from shared.module_handler import module_handler
from modules.demo.demo_core import (
    get_demo_config_value,
    get_demo_translation,
    get_demo_prompt,
    list_users,
    list_user_conversations,
    get_conversation_messages,
    create_conversation,
    send_user_message,
    generate_response,
    get_available_llms,
    check_services,
    EXPECTED_SERVICES,
)


# ─── Injection point 1: session state initialization ─────────────────────────

def inject_ui_initialize() -> None:
    """
    Called once at app startup (before any render).
    Only initialize st.session_state defaults here.
    No business logic, no data fetching.
    """
    if "demo_selected_conv" not in st.session_state:
        st.session_state["demo_selected_conv"] = None
    if "demo_llm_response" not in st.session_state:
        st.session_state["demo_llm_response"] = None


# ─── Tab renderers ────────────────────────────────────────────────────────────

def _tab_infrastructure() -> None:
    """
    Visual health check for config, translations, and prompts.
    Each value is loaded from a separate source file.
    If loading fails, you see a ⚠ sentinel instead of the real value.
    """
    cfg = get_config()
    pm = get_prompt_manager()

    # Config
    st.markdown(f"**{_('demo.infra_config_label')}**")
    config_val = get_demo_config_value(cfg)
    if config_val.startswith("⚠"):
        st.error(config_val)
    else:
        st.success(config_val)
    st.caption("Source: `modules/demo/config.json` → key `greeting`")

    st.divider()

    # Translations — use a dedicated check key, not section_title (used in the tab itself)
    st.markdown(f"**{_('demo.infra_translation_label')}**")
    translation_val = get_demo_translation(_, "demo.check_translation")
    if translation_val.startswith("["):
        st.error(f"Missing translation key: {translation_val}")
    else:
        st.success(translation_val)
    st.caption("Source: `modules/demo/translations/en.json` → key `demo.check_translation`")

    st.divider()

    # Prompts
    st.markdown(f"**{_('demo.infra_prompt_label')}**")
    prompt_val = get_demo_prompt(pm)
    if prompt_val.startswith("⚠"):
        st.error(prompt_val)
    else:
        st.success(prompt_val)
    st.caption("Source: `modules/demo/prompt.en.yml` → key `system`")


def _tab_users() -> None:
    st.markdown(f"### {_('demo.users_title')}")
    users = list_users(get_user_manager())
    if not users:
        st.info("No users found.")
        return
    for u in users:
        st.write(f"**{u['username']}** `{u['id']}` — role: `{u['role']}`")


def _tab_conversations() -> None:
    st.markdown(f"### {_('demo.conversations_title')}")
    um = get_user_manager()
    cm = get_conversation_manager()

    users = list_users(um)
    if not users:
        st.warning(_("demo.conversations_no_user"))
        return

    user_options = {u["username"]: u["id"] for u in users}
    selected_username = st.selectbox("User", list(user_options.keys()), key="demo_conv_user")
    user_id = user_options[selected_username]

    if st.button(_("demo.conversations_create"), key="demo_create_conv"):
        cid = create_conversation(cm, user_id, "Demo conversation")
        if cid:
            st.session_state["demo_selected_conv"] = cid
            st.rerun()

    convs = list_user_conversations(cm, user_id)
    if not convs:
        st.info("No conversations yet.")
        return

    conv_options = {f"{c['title']} ({c['message_count']} msg)": c["id"] for c in convs}
    selected_label = st.selectbox("Conversation", list(conv_options.keys()), key="demo_conv_select")
    conv_id = conv_options[selected_label]

    for m in get_conversation_messages(cm, conv_id):
        with st.chat_message(m["role"]):
            st.write(m["content"])

    user_input = st.text_input(
        "Message", placeholder="Type a message...", key="demo_conv_input"
    )
    if st.button(_("demo.conversations_send"), key="demo_conv_send") and user_input.strip():
        send_user_message(cm, conv_id, user_input)
        st.rerun()


def _tab_llm() -> None:
    st.markdown(f"### {_('demo.llm_title')}")
    llm = get_llm_manager()

    llms = get_available_llms(llm)
    if llms:
        names = [l.get("name", l.get("id", "?")) for l in llms]
        st.caption(f"Available: {', '.join(names)}")

    prompt_input = st.text_area(
        "Prompt", placeholder="Ask something...", key="demo_llm_prompt", height=80
    )
    if st.button(_("demo.llm_send"), key="demo_llm_send") and prompt_input.strip():
        with st.spinner("Generating..."):
            st.session_state["demo_llm_response"] = generate_response(llm, prompt_input)

    if st.session_state.get("demo_llm_response"):
        st.markdown(f"**{_('demo.llm_response_label')}:**")
        st.write(st.session_state["demo_llm_response"])


def _tab_services() -> None:
    """
    Visual health check for the ServiceLocator.
    All services must be ✅ for the module system to work correctly.
    If any are ❌, check that register_all_services() was called at startup.
    """
    st.markdown(f"### {_('demo.services_title')}")
    st.caption(
        "Services are injected via `on_module_activated(services)`. "
        "Registered in `st_shared.cached.register_all_services()`."
    )

    services = module_handler.get_services()
    if services is None:
        st.error("⚠️ ServiceLocator is None — `register_all_services()` was not called.")
        return

    status = check_services(services)
    for name, available in status.items():
        if available:
            st.success(f"✅ `{name}`")
        else:
            st.error(f"❌ `{name}` — {_('demo.services_missing')}")


# ─── Injection point 2: main page display ────────────────────────────────────

def inject_ui_main_footer() -> None:
    """
    Rendered each cycle in the main page footer area.
    """
    test_mode = os.getenv("TEST_MODE") == "true" or "pytest" in sys.modules
    if not test_mode:
        st.caption("")
        return
    with st.expander(_("demo.section_title"), expanded=False):
        st.caption(_("demo.section_description"))
        tabs = st.tabs([
            _("demo.tab_infrastructure"),
            _("demo.tab_users"),
            _("demo.tab_conversations"),
            _("demo.tab_llm"),
            _("demo.tab_services"),
        ])
        with tabs[0]: _tab_infrastructure()
        with tabs[1]: _tab_users()
        with tabs[2]: _tab_conversations()
        with tabs[3]: _tab_llm()
        with tabs[4]: _tab_services()
