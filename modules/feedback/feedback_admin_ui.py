"""Admin UI for feedback module."""

import streamlit as st

from st_shared.cached import _, get_config, get_conversation_manager, get_db_manager, get_user_manager
from shared.common import UserRole
from modules.feedback.feedback_core import clear_feedback, get_feedback_config, get_feedback_rows, time_ago


def inject_ui_admin_tab():
    return ("Feedback", _render_feedback_admin)


def _render_feedback_admin() -> None:
    cfg = get_feedback_config(get_config())
    db = get_db_manager()
    user_manager = get_user_manager()
    conversation_manager = get_conversation_manager()

    st.subheader(_("feedback.admin_title"))

    filter_cols = st.columns(3)
    with filter_cols[0]:
        selected_type = st.selectbox(_("feedback.filter_type"), ["all", "message", "conversation", "app"], key="feedback_filter_type")
    with filter_cols[1]:
        selected_sentiment = st.selectbox(_("feedback.filter_sentiment"), ["all", "positive", "negative", "neutral"], key="feedback_filter_sentiment")
    with filter_cols[2]:
        if st.button(_("feedback.clear_all"), key="feedback_clear_all"):
            current_user = st.session_state.get("current_user") or {}
            if current_user.get("role") not in [UserRole.ADMIN.value, UserRole.MASTER.value]:
                st.error(_("feedback.admin_only"))
            else:
                deleted = clear_feedback(db)
                st.success(_("feedback.cleared").format(count=deleted))

    rows = get_feedback_rows(
        db,
        user_manager,
        limit=cfg["max_display"],
        feedback_type=None if selected_type == "all" else selected_type,
        sentiment=None if selected_sentiment == "all" else selected_sentiment,
    )

    if not rows:
        st.info(_("feedback.empty"))
        return

    for row in rows:
        icon = "⭐" if row["feedback_type"] == "app" else ("👍" if row.get("sentiment") == "positive" else "👎" if row.get("sentiment") == "negative" else "💬")
        comment = (row.get("comment") or "")
        if len(comment) > 80:
            comment = comment[:77] + "..."

        # Build context line with conversation title
        context_info = ""
        conv = None

        if row.get("conversation_id"):
            conv = conversation_manager.get_conversation(row["conversation_id"], include_messages=True)
            if conv:
                # FIX: Use attribute access, not .get()
                conv_title = conv.title or _("feedback.untitled_conversation")
                if row["feedback_type"] == "conversation":
                    context_info = f"  \n📝 {_('feedback.conversation')}: *{conv_title}*"

        st.markdown(
            f"**`{row['feedback_type']}`** {icon}  {comment or '-'}  \\\n{row['username']} · {time_ago(row['created_at'])}{context_info}"
        )

        # Show message context for message feedback
        if row["feedback_type"] == "message" and row.get("conversation_id") and row.get("message_id"):
            if conv:  # We already fetched it above
                # FIX: Use attribute access, not .get()
                messages = conv.messages or []

                # Find the exact message by ID using database query
                user_msg = None
                assistant_msg = None

                # Query the database to get the actual message objects with IDs
                try:
                    with db.get_session() as session:
                        from shared.conversation import MessageTable

                        # Find the message by ID
                        db_msg = session.query(MessageTable).filter_by(
                            id=row["message_id"]
                        ).first()

                        if db_msg:
                            # Find this message in the conversation messages
                            for idx, msg in enumerate(messages):
                                if msg.content == db_msg.content and msg.timestamp == db_msg.timestamp:
                                    user_msg = msg
                                    # Get the next message if it's from assistant
                                    if idx + 1 < len(messages) and messages[idx + 1].role == "assistant":
                                        assistant_msg = messages[idx + 1]
                                    break
                except Exception as e:
                    st.caption(f"⚠️ Error loading message: {e}")

                if user_msg:
                    with st.expander(_("feedback.view_message_context")):
                        # Show conversation title
                        conv_title = conv.title or _("feedback.untitled_conversation")
                        st.caption(f"📝 {_('feedback.conversation')}: {conv_title}")
                        st.divider()

                        # Show user message
                        st.markdown(f"**{_('feedback.user_message')}:**")
                        st.info(user_msg.content or "")

                        # Show assistant response if exists
                        if assistant_msg:
                            st.markdown(f"**{_('feedback.assistant_response')}:**")
                            st.success(assistant_msg.content or "")
                        else:
                            st.caption(_("feedback.no_response"))
                else:
                    # Debug: Show why we couldn't find the message
                    with st.expander(_("feedback.view_message_context") + " ⚠️"):
                        st.warning(_("feedback.message_not_found"))
                        st.caption(f"Looking for message_id: `{row['message_id']}`")
                        st.caption(f"Available messages in conversation: {len(messages)}")
                        if messages:
                            st.caption("First 3 messages:")
                            for i, msg in enumerate(messages[:3]):
                                st.caption(f"  - {i+1}. {msg.role}: {msg.content[:50]}...")
            else:
                with st.expander(_("feedback.view_message_context") + " ⚠️"):
                    st.warning(_("feedback.conversation_not_found"))

        st.divider()
