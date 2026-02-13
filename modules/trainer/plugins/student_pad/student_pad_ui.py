"""
Student Pad UI for Trainer Module.
Injects a personal note-taking pad in the main header for normal users (students).
File ends with _ui.py and implements inject_ui_main_header() injection point.
"""

import streamlit as st
from datetime import datetime
from shared.common import _, get_user_manager, UserRole
from modules.trainer.manager import get_trainer_manager


def inject_ui_main_header():
    """
    Inject a text area in the main header for students to edit their personal pad.
    This is the required injection point for main header content.
    Only visible to normal users (students) who have a master as parent.
    """
    # Only show for logged-in normal users (students)
    if not ("current_user" in st.session_state and st.session_state.current_user):
        return

    user = st.session_state.current_user
    user_id = user['id']
    user_role = st.session_state.current_user['role']

    if user_role != UserRole.NORMAL.value:
        return

    # Get the student's trainer (parent)
    parent_id = user.get('parent_id')
    if not parent_id:
        return

    # Render the pad in a clean container
    with st.container():
        st.markdown("---")
        col1, col2 = st.columns([1, 5])

        with col1:
            st.markdown("### 📝")

        with col2:
            st.markdown("### " + _("My Personal Notes"))

            trainer_manager = get_trainer_manager()
            student_id = user['id']
            trainer_id = parent_id

            # Get current pad content
            current_content = trainer_manager.get_student_note(
                student_id, trainer_id, "student_pad"
            )

            # Show last updated hint
            if current_content:
                st.caption(f"📄 {len(current_content)} {_('characters')}")

            # Editable text area - auto-saving on change
            new_content = st.text_area(
                _("Write your notes here..."),
                value=current_content,
                height=200,
                key=f"student_pad_{student_id}",
                label_visibility="collapsed",
                placeholder=_("Take notes, write down questions, or keep track of what you've learned..."),
                help=_("Auto-saves when you type")
            )

            # Auto-save on change (Streamlit reruns on interaction)
            if new_content != current_content:
                if trainer_manager.save_student_note(
                    student_id, trainer_id, new_content, "student_pad"
                ):
                    st.success(_("✓ Notes saved"), icon="✅")
                else:
                    st.error(_("Failed to save notes"))

        st.markdown("---")
