"""Streamlit UI injection points for feedback module."""

import streamlit as st

from core.logging import log
from st_shared.cached import _, get_config, get_conversation_manager, get_db_manager
from modules.feedback.feedback_core import get_feedback_config, submit_feedback


def inject_ui_main_before_conversation() -> None:
    """Inject conversation feedback at the top of the conversation."""
    user = st.session_state.get("current_user")
    if not user:
        log("debug", "Feedback: No current_user, skipping conversation feedback")
        return

    conversation_id = st.session_state.get('current_conversation_id')
    if not conversation_id:
        log("debug", "Feedback: No current_conversation_id, skipping conversation feedback")
        return

    db = get_db_manager()
    conversation_manager = get_conversation_manager()

    # Get conversation details
    conv = conversation_manager.get_conversation(conversation_id, include_messages=False)
    if not conv:
        log("debug", f"Feedback: Conversation {conversation_id} not found")
        return

    conv_title = conv.title or _("feedback.untitled_conversation")

    log("debug", f"Feedback: Rendering conversation feedback for {conversation_id}")

    with st.expander(f"💬 {_('feedback.conversation_feedback_title')}", expanded=False):
        st.caption(_("feedback.conversation_feedback_description"))

        conv_comment = st.text_area(
            _("feedback.conversation_comment"),
            key=f"feedback_conv_comment_{conversation_id}",
            placeholder=_("feedback.conversation_placeholder")
        )

        if st.button(_("feedback.submit_conversation"), key=f"feedback_submit_conv_{conversation_id}"):
            try:
                feedback_id = submit_feedback(
                    db,
                    user_id=user["id"],
                    feedback_type="conversation",
                    conversation_id=conversation_id,
                    sentiment="neutral",
                    comment=conv_comment or None,
                )
                log("info", f"Feedback: Conversation feedback submitted - {feedback_id}")
                st.success(_("feedback.saved"))
                st.rerun()
            except Exception as e:
                log("error", f"Feedback submission failed: {e}", stacktrace=True)


def inject_ui_main_after_conversation() -> None:
    """Inject message feedback after the last message in the conversation."""
    user = st.session_state.get("current_user")
    if not user:
        log("debug", "Feedback: No current_user, skipping message feedback")
        return

    conversation_id = st.session_state.get('current_conversation_id')
    if not conversation_id:
        log("debug", "Feedback: No current_conversation_id, skipping message feedback")
        return

    db = get_db_manager()
    conversation_manager = get_conversation_manager()

    # Get the conversation and find the last message
    conv = conversation_manager.get_conversation(conversation_id, include_messages=True)
    if not conv:
        log("debug", f"Feedback: Conversation {conversation_id} not found")
        return

    messages = conv.messages or []
    if not messages:
        log("debug", "Feedback: No messages in conversation, skipping message feedback")
        return

    # Find the last user message and its response
    last_user_msg = None
    last_assistant_msg = None

    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        # Message is a dataclass, use attribute access
        if msg.role == "user":
            last_user_msg = msg
            # Check if there's an assistant response after it
            if i + 1 < len(messages) and messages[i + 1].role == "assistant":
                last_assistant_msg = messages[i + 1]
            break

    if not last_user_msg:
        log("debug", "Feedback: No user message found, skipping message feedback")
        return

    # Get the actual message ID from the database
    # We need to query the database to find the message ID for this message
    # Match by conversation_id, role, content, and timestamp
    last_message_id = None
    try:
        with db.get_session() as session:
            from shared.conversation import MessageTable
            db_message = session.query(MessageTable).filter_by(
                conversation_id=conversation_id,
                role="user",
                content=last_user_msg.content
            ).order_by(MessageTable.timestamp.desc()).first()

            if db_message:
                last_message_id = db_message.id
                log("debug", f"Feedback: Found message ID {last_message_id} for last user message")
            else:
                log("warning", "Feedback: Could not find message ID in database")
                return
    except Exception as e:
        log("error", f"Feedback: Failed to get message ID: {e}", stacktrace=True)
        return

    log("debug", f"Feedback: Rendering message feedback for message {last_message_id}")

    # Create the feedback UI
    with st.expander(f"👍👎 {_('feedback.message_feedback_title')}", expanded=False):
        st.caption(_("feedback.message_feedback_description"))

        # Show the message being rated (collapsed preview)
        with st.container():
            st.markdown(f"**{_('feedback.rating_message')}:**")
            user_content = last_user_msg.content or ""
            if len(user_content) > 100:
                st.info(user_content[:100] + "...")
            else:
                st.info(user_content)

        # Sentiment selection
        col1, col2 = st.columns(2)
        with col1:
            positive = st.button(
                "👍 " + _("feedback.positive"),
                key=f"feedback_positive_{last_message_id}",
                use_container_width=True
            )
        with col2:
            negative = st.button(
                "👎 " + _("feedback.negative"),
                key=f"feedback_negative_{last_message_id}",
                use_container_width=True
            )

        # Optional comment
        msg_comment = st.text_area(
            _("feedback.optional_comment"),
            key=f"feedback_msg_comment_{last_message_id}",
            placeholder=_("feedback.message_placeholder")
        )

        # Handle submission
        if positive:
            try:
                feedback_id = submit_feedback(
                    db,
                    user_id=user["id"],
                    feedback_type="message",
                    conversation_id=conversation_id,
                    message_id=last_message_id,
                    sentiment="positive",
                    comment=msg_comment or None,
                )
                log("info", f"Feedback: Positive message feedback submitted - {feedback_id}")
                st.success(_("feedback.saved"))
                st.rerun()
            except Exception as e:
                log("error", f"Feedback submission failed: {e}", stacktrace=True)

        if negative:
            try:
                feedback_id = submit_feedback(
                    db,
                    user_id=user["id"],
                    feedback_type="message",
                    conversation_id=conversation_id,
                    message_id=last_message_id,
                    sentiment="negative",
                    comment=msg_comment or None,
                )
                log("info", f"Feedback: Negative message feedback submitted - {feedback_id}")
                st.success(_("feedback.saved"))
                st.rerun()
            except Exception as e:
                log("error", f"Feedback submission failed: {e}", stacktrace=True)


def inject_ui_sidebar() -> None:
    """Sidebar injection for app-level feedback only."""
    user = st.session_state.get("current_user")
    if not user:
        log("debug", "Feedback: No current_user, skipping app feedback in sidebar")
        return

    db = get_db_manager()

    with st.expander(_("feedback.app_feedback_title"), expanded=False):
        st.caption(_("feedback.app_feedback_description"))

        app_rating = st.slider(
            _("feedback.app_rating"),
            1, 5, 3,
            key="feedback_app_rating"
        )

        app_comment = st.text_area(
            _("feedback.app_comment"),
            key="feedback_app_comment",
            placeholder=_("feedback.app_placeholder")
        )

        if st.button(_("feedback.submit_app"), key="feedback_submit_app"):
            try:
                feedback_id = submit_feedback(
                    db,
                    user_id=user["id"],
                    feedback_type="app",
                    sentiment="neutral",
                    rating=app_rating,
                    comment=app_comment or None,
                )
                log("info", f"Feedback: App feedback submitted - {feedback_id}")
                st.success(_("feedback.saved"))
                st.rerun()
            except Exception as e:
                log("error", f"Feedback submission failed: {e}", stacktrace=True)
