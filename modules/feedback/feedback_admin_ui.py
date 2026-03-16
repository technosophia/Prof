"""Admin UI for feedback module."""

import streamlit as st

from st_shared.cached import _, get_config, get_db_manager, get_user_manager
from shared.common import UserRole
from modules.feedback.feedback_core import clear_feedback, get_feedback_config, get_feedback_rows, time_ago


def inject_ui_admin_tab():
    return ("Feedback", _render_feedback_admin)


def _render_feedback_admin() -> None:
    cfg = get_feedback_config(get_config())
    db = get_db_manager()
    user_manager = get_user_manager()

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
        st.markdown(
            f"**`{row['feedback_type']}`** {icon}  {comment or '-'}  \\\n{row['username']} · {time_ago(row['created_at'])}"
        )
        st.divider()
