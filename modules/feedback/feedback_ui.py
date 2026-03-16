"""Streamlit UI injection points for feedback module."""

import streamlit as st

from core.logging import log
from st_shared.cached import _, get_config, get_db_manager
from modules.feedback.feedback_core import get_feedback_config, submit_feedback


WARNED_GAPS_KEY = "feedback_warned_injection_gap"


def inject_ui_initialize() -> None:
    if "feedback_open" not in st.session_state:
        st.session_state["feedback_open"] = False


def _warn_missing_injection_points_once() -> None:
    if st.session_state.get(WARNED_GAPS_KEY):
        return
    st.session_state[WARNED_GAPS_KEY] = True
    log("info", "feedback: using sidebar injection for feedback entry points")


def _render_feedback_form() -> None:
    user = st.session_state.get("current_user")
    if not user:
        st.info(_("feedback.login_required"))
        return

    db = get_db_manager()
    current_conv = st.session_state.get("demo_selected_conv")

    with st.expander(_("feedback.title"), expanded=get_feedback_config(get_config())["sidebar_expanded"]):
        st.caption(_("feedback.description"))

        sentiment = st.radio(_("feedback.last_message_sentiment"), ["positive", "negative"], format_func=lambda x: "👍" if x == "positive" else "👎", key="feedback_last_msg_sentiment")
        msg_comment = st.text_area(_("feedback.last_message_comment"), key="feedback_last_msg_comment")
        if st.button(_("feedback.submit_last_message"), key="feedback_submit_last_message"):
            submit_feedback(
                db,
                user_id=user["id"],
                feedback_type="message",
                conversation_id=current_conv,
                message_id=f"manual-{current_conv or 'none'}",
                sentiment=sentiment,
                comment=msg_comment or None,
            )
            st.success(_("feedback.saved"))

        conv_comment = st.text_area(_("feedback.conversation_comment"), key="feedback_conv_comment")
        if st.button(_("feedback.submit_conversation"), key="feedback_submit_conversation"):
            submit_feedback(
                db,
                user_id=user["id"],
                feedback_type="conversation",
                conversation_id=current_conv,
                sentiment="neutral",
                comment=conv_comment or None,
            )
            st.success(_("feedback.saved"))

        app_comment = st.text_area(_("feedback.app_comment"), key="feedback_app_comment")
        app_rating = st.slider(_("feedback.app_rating"), 1, 5, 3, key="feedback_app_rating")
        if st.button(_("feedback.submit_app"), key="feedback_submit_app"):
            submit_feedback(
                db,
                user_id=user["id"],
                feedback_type="app",
                sentiment="neutral",
                rating=app_rating,
                comment=app_comment or None,
            )
            st.success(_("feedback.saved"))


def inject_ui_sidebar_bottom() -> None:
    _render_feedback_form()


def inject_ui_message_footer() -> None:
    _warn_missing_injection_points_once()


def inject_ui_sidebar() -> None:
    """Fallback injection point because sidebar_bottom is not supported by current app."""
    _warn_missing_injection_points_once()
    _render_feedback_form()
