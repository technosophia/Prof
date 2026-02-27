"""UI layer for suggest plugin."""

import streamlit as st

from modules.trainer.plugin_base_ui import TrainerPluginUI
from .core import *
from .core import SuggestPluginCore


class SuggestPluginUI(TrainerPluginUI):

    def render_student_header_widgets(self, student_id: str, trainer_id: str) -> List[Callable]:
        """
        Render the suggestion banner in the student's header area.
        This is where students see and interact with suggestions.
        """
        def render_suggestion_banner():
            # Get active suggestion
            suggestion = self._get_active_suggestion(student_id, trainer_id)

            if not suggestion:
                return

            # Create a unique key for this suggestion
            suggestion_key = f"suggest_{suggestion['id']}"

            # Get only the first line for display, strip whitespace
            display_content = suggestion['content'].split('\n')[0].strip()
            # If the first line is empty, use the full content
            if not display_content:
                display_content = suggestion['content'].strip()

            # Create a container for the banner
            with st.container():
                # Style the banner
                st.markdown("""
                <style>
                .suggestion-banner {
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    padding: 1rem;
                    border-radius: 10px;
                    color: white;
                    margin: 1rem 0;
                }
                .suggestion-content {
                    font-size: 1.1rem;
                    font-weight: 500;
                }
                .suggestion-banner .stButton button {
                    background-color: white;
                    color: #667eea;
                    border: none;
                    border-radius: 20px;
                    padding: 0.25rem 1rem;
                    font-size: 0.9rem;
                }
                </style>
                """, unsafe_allow_html=True)

                # Banner layout
                cols = st.columns([5, 1, 1])

                with cols[0]:
                    source_icon = "👤" if suggestion['source'] == 'auto' else "👨‍🏫"
                    st.markdown(f"""
                    <div class="suggestion-banner">
                        <div class="suggestion-content">{source_icon} {display_content}</div>
                    </div>
                    """, unsafe_allow_html=True)

                with cols[1]:
                    # Use suggestion button
                    if st.button("Use", key=f"use_{suggestion_key}"):
                        # Create a new conversation with this suggestion as the title/prompt
                        new_conv_id = self.conversation_manager.create_conversation(
                            user_id=student_id,
                            title=display_content[:50],  # Use first line for title too
                            system_prompt=None  # Use default
                        )
                        # Add the FULL suggestion as the first user message
                        self.conversation_manager.add_message(
                            new_conv_id,
                            Message(role="user", content=suggestion['content'])  # Full content
                        )

                        # Mark as used with the created conversation
                        if self._mark_suggestion_clicked(suggestion['id'], new_conv_id):
                            # AUTO-ASSOCIATE: Also add to related conversations
                            self.associate_conversation_with_suggestion(suggestion['id'], new_conv_id)
                            st.success("🚀 Started!", icon="🚀")
                            st.rerun()

                with cols[2]:
                    # Dismiss button
                    if st.button("Dismiss", key=f"dismiss_{suggestion_key}"):
                        if self._dismiss_suggestion(suggestion['id']):
                            st.rerun()

        return [render_suggestion_banner]

    def render_student_widgets(self, trainer_id: str, student: Dict) -> List[Callable]:
        """Render configuration UI for teachers to adjust suggestion settings per student."""
        def render_suggestion_config():
            student_id = student['id']
            student_name = student.get('name', student_id)

            # Create a unique base key for this student
            base_key = f"suggest_{student_id}"

            st.markdown(f"### 💡 Suggestions for {student_name}")

            # Get current config
            config = self._get_student_config(student_id, trainer_id)
            current_interval = config.get('message_interval', 5) if config else 5
            current_enabled = config.get('is_enabled', True) if config else True

            # Configuration form
            with st.form(key=f"{base_key}_config_form"):
                col1, col2 = st.columns(2)

                with col1:
                    enabled = st.checkbox(
                        "Enable suggestions for this student",
                        value=current_enabled,
                        key=f"{base_key}_enabled"
                    )

                with col2:
                    interval = st.number_input(
                        "Suggest every N messages",
                        min_value=1,
                        max_value=20,
                        value=current_interval,
                        help="How many student messages between automatic suggestions",
                        key=f"{base_key}_interval"
                    )

                if st.form_submit_button("Save Settings", key=f"{base_key}_submit"):
                    if self._save_student_config(student_id, trainer_id, interval, enabled):
                        st.success("Settings saved")
                        st.rerun()
                    else:
                        st.error("Failed to save settings")

            # Manual suggestion section
            st.markdown(f"#### ✍️ Manual Suggestion")
            st.caption("Generate a suggestion based on a specific conversation")

            # Get recent conversations for context
            conversations = self.conversation_manager.get_user_conversations(student_id)

            if conversations:
                # Let teacher select which conversation to use for context
                conv_options = {}
                for conv in conversations[:5]:  # Last 5 conversations
                    conv_options[conv['id']] = f"{conv['title']} ({conv.get('message_count', 0)} messages)"

                selected_conv_id = st.selectbox(
                    "Use conversation for context",
                    options=list(conv_options.keys()),
                    format_func=lambda x: conv_options[x],
                    key=f"{base_key}_conv_select"
                )

                if st.button("Generate Suggestion", key=f"{base_key}_generate"):
                    with st.spinner("Generating suggestion..."):
                        # Get full conversation
                        conversation = self.conversation_manager.get_conversation(selected_conv_id, include_messages=True)
                        if conversation and conversation.messages:
                            # Store generation data in session state
                            st.session_state[f"{base_key}_generating"] = True
                            st.session_state[f"{base_key}_conv_id"] = selected_conv_id
                            st.session_state[f"{base_key}_messages"] = conversation.messages
                            st.rerun()
            else:
                st.info("No conversations available for context")

            # Check if we're in generation mode for this student
            gen_flag_key = f"{base_key}_generating"
            if st.session_state.get(gen_flag_key, False):

                st.markdown(f"#### ✏️ Edit Suggestion")

                # Get stored data
                conv_id = st.session_state.get(f"{base_key}_conv_id")
                messages = st.session_state.get(f"{base_key}_messages")

                # Run generation if we have the data
                if conv_id and messages:
                    # Check if we already have a generated suggestion in session state
                    sugg_text_key = f"{base_key}_suggestion_text"
                    sugg_id_key = f"{base_key}_suggestion_id"

                    if sugg_text_key not in st.session_state:
                        with st.spinner("AI is thinking..."):
                            # Create async task and run it synchronously for Streamlit
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            try:
                                success = loop.run_until_complete(
                                    self._generate_suggestion_async(
                                        student_id,
                                        trainer_id,
                                        conv_id,
                                        messages,
                                        source="teacher"
                                    )
                                )
                            finally:
                                loop.close()

                            if success:
                                # Get the most recent teacher suggestion
                                with self.db.get_session() as session:
                                    latest = session.query(StudentSuggestion).filter_by(
                                        student_id=student_id,
                                        trainer_id=trainer_id,
                                        source="teacher"
                                    ).order_by(StudentSuggestion.created_at.desc()).first()

                                    if latest:
                                        st.session_state[sugg_text_key] = latest.content
                                        st.session_state[sugg_id_key] = latest.id
                                        st.rerun()
                                    else:
                                        st.error("Failed to generate suggestion")
                                        # Clear generation state
                                        for key in [gen_flag_key, f"{base_key}_conv_id", f"{base_key}_messages"]:
                                            if key in st.session_state:
                                                del st.session_state[key]
                                        st.rerun()
                            else:
                                st.error("Failed to generate suggestion")
                                # Clear generation state
                                for key in [gen_flag_key, f"{base_key}_conv_id", f"{base_key}_messages"]:
                                    if key in st.session_state:
                                        del st.session_state[key]
                                st.rerun()

                    # Show editable suggestion if we have it
                    if sugg_text_key in st.session_state:
                        editable_suggestion = st.text_area(
                            "Edit the suggestion before sending (optional)",
                            value=st.session_state[sugg_text_key],
                            height=100,
                            key=f"{base_key}_edit_area"
                        )

                        col1, col2 = st.columns(2)
                        with col1:
                            if st.button("Send to Student", key=f"{base_key}_send"):
                                # Update the suggestion with edited text
                                with self.db.get_session() as session:
                                    sugg = session.query(StudentSuggestion).filter_by(
                                        id=st.session_state[sugg_id_key]
                                    ).first()
                                    if sugg:
                                        sugg.content = editable_suggestion
                                        sugg.add_interaction('edited', {'previous_content': st.session_state[sugg_text_key]})

                                        # Initialize related_conversation_ids if it's None
                                        if sugg.related_conversation_ids is None:
                                            sugg.related_conversation_ids = []

                                        # AUTO-ASSOCIATE: Associate with the selected conversation
                                        if conv_id and conv_id not in sugg.related_conversation_ids:
                                            sugg.related_conversation_ids.append(conv_id)
                                            sugg.add_interaction('conversation_associated', {
                                                'conversation_id': conv_id
                                            })

                                        session.commit()
                                        st.success("Suggestion sent to student")

                                # Clean up all session state for this student
                                keys_to_delete = [
                                    gen_flag_key,
                                    f"{base_key}_conv_id",
                                    f"{base_key}_messages",
                                    sugg_text_key,
                                    sugg_id_key
                                ]
                                for key in keys_to_delete:
                                    if key in st.session_state:
                                        del st.session_state[key]
                                st.rerun()

                        with col2:
                            if st.button("Cancel", key=f"{base_key}_cancel"):
                                # Delete the unsent suggestion
                                with self.db.get_session() as session:
                                    session.query(StudentSuggestion).filter_by(
                                        id=st.session_state[sugg_id_key]
                                    ).delete()
                                    session.commit()

                                # Clean up all session state for this student
                                keys_to_delete = [
                                    gen_flag_key,
                                    f"{base_key}_conv_id",
                                    f"{base_key}_messages",
                                    sugg_text_key,
                                    sugg_id_key
                                ]
                                for key in keys_to_delete:
                                    if key in st.session_state:
                                        del st.session_state[key]
                                st.rerun()
                else:
                    # Invalid state, clear it
                    for key in [gen_flag_key, f"{base_key}_conv_id", f"{base_key}_messages"]:
                        if key in st.session_state:
                            del st.session_state[key]

            # Show recent suggestions with enhanced information
            st.markdown(f"#### 📋 Recent Suggestions")
            recent = self._get_suggestions_for_student(student_id, trainer_id, limit=10)

            if recent:
                for sugg in recent:
                    state = sugg['state']
                    state_icons = {
                        'used': '✅',
                        'dismissed': '✗',
                        'displayed': '👁️',
                        'active': '⏳',
                        'expired': '⌛',
                        'deleted': '🗑️'
                    }
                    state_icon = state_icons.get(state, '❓')

                    source_icon = "👤 Auto" if sugg['source'] == 'auto' else "👨‍🏫 Teacher"

                    # Create unique keys for this suggestion
                    sugg_key = f"{base_key}_{sugg['id']}"

                    with st.expander(f"{state_icon} {sugg['content'][:100]}...", expanded=False):
                        col1, col2 = st.columns([2, 1])

                        with col1:
                            st.caption(f"📅 Created: {sugg['created_at'].strftime('%Y-%m-%d %H:%M')}")
                            st.caption(f"👤 {source_icon}")

                            # Display associated conversations
                            all_conv_ids = []
                            if sugg.get('created_conversation_id'):
                                all_conv_ids.append(('Created', sugg['created_conversation_id']))
                            if sugg.get('related_conversation_ids'):
                                for conv_id in sugg['related_conversation_ids']:
                                    if conv_id != sugg.get('created_conversation_id'):
                                        all_conv_ids.append(('Related', conv_id))

                            if all_conv_ids:
                                st.caption("💬 **Associated Conversations:**")
                                for conv_type, conv_id in all_conv_ids:
                                    # Try to get conversation title
                                    conv = self.conversation_manager.get_conversation(conv_id)
                                    conv_title = conv.title if conv else "Unknown"
                                    st.caption(f"  • {conv_type}: {conv_title[:50]} ({conv_id[:8]}...)")

                            # Show last interaction
                            if sugg.get('interaction_history') and len(sugg['interaction_history']) > 0:
                                last_interaction = sugg['interaction_history'][-1]
                                st.caption(f"📝 Last: {last_interaction['action']} at {last_interaction['timestamp'][:16]}")

                            # Full suggestion content
                            st.markdown(f"**Suggestion:** {sugg['content']}")

                            # Show interaction history if requested
                            if st.checkbox("Show history", key=f"{sugg_key}_show_history"):
                                if sugg.get('interaction_history') and len(sugg['interaction_history']) > 0:
                                    for i, interaction in enumerate(sugg['interaction_history']):
                                        action = interaction.get('action', 'unknown')
                                        timestamp = interaction.get('timestamp', '')[:16] if interaction.get('timestamp') else 'unknown'
                                        details = interaction.get('details', {})

                                        # Format details nicely
                                        details_str = ""
                                        if details:
                                            if 'conversation_id' in details:
                                                # Try to get conversation title
                                                conv = self.conversation_manager.get_conversation(details['conversation_id'])
                                                conv_title = conv.title if conv else "Unknown"
                                                details_str = f" - {conv_title[:30]} ({details['conversation_id'][:8]}...)"
                                            elif 'previous_content' in details:
                                                details_str = f" - Was: {details['previous_content'][:50]}..."
                                            else:
                                                details_str = f" - {details}"

                                        # Add icons for different actions
                                        action_icon = {
                                            'created': '🆕',
                                            'viewed': '👁️',
                                            'used': '✅',
                                            'dismissed': '✗',
                                            'deleted': '🗑️',
                                            'edited': '✏️',
                                            'conversation_associated': '🔗',
                                            'expired': '⌛'
                                        }.get(action, '📝')

                                        st.text(f"{action_icon} {timestamp}: {action}{details_str}")
                                else:
                                    st.text("No interaction history available")

                        with col2:
                            # Show state
                            st.metric("State", state.capitalize())

                            # Actions based on state
                            if state == 'displayed' or state == 'active':
                                if st.button("✗ Dismiss", key=f"{sugg_key}_dismiss"):
                                    self._dismiss_suggestion(sugg['id'])
                                    st.rerun()

                            if state != 'deleted':
                                if st.button("🗑️ Delete", key=f"{sugg_key}_delete"):
                                    self.delete_suggestion_by_teacher(sugg['id'])
                                    st.rerun()

                            # Associate with another conversation
                            if st.button("➕ Associate Conv", key=f"{sugg_key}_assoc"):
                                st.session_state[f"{sugg_key}_assoc_mode"] = True

                            if st.session_state.get(f"{sugg_key}_assoc_mode", False):
                                # Get available conversations (excluding already associated ones)
                                all_convs = self.conversation_manager.get_user_conversations(student_id)

                                # Build list of already associated conversation IDs
                                associated_ids = []
                                if sugg.get('created_conversation_id'):
                                    associated_ids.append(sugg['created_conversation_id'])
                                if sugg.get('related_conversation_ids'):
                                    associated_ids.extend(sugg['related_conversation_ids'])

                                # Filter out already associated conversations
                                available_convs = [c for c in all_convs if c['id'] not in associated_ids]

                                if available_convs:
                                    conv_options = {conv['id']: f"{conv['title']} ({conv.get('message_count', 0)} msgs)"
                                                  for conv in available_convs[:5]}
                                    selected_conv = st.selectbox(
                                        "Select conversation",
                                        options=list(conv_options.keys()),
                                        format_func=lambda x: conv_options[x],
                                        key=f"{sugg_key}_conv_select"
                                    )
                                    if st.button("Associate", key=f"{sugg_key}_assoc_confirm"):
                                        self.associate_conversation_with_suggestion(sugg['id'], selected_conv)
                                        del st.session_state[f"{sugg_key}_assoc_mode"]
                                        st.rerun()
                                else:
                                    st.info("No new conversations to associate")
                                    if st.button("Close", key=f"{sugg_key}_assoc_close"):
                                        del st.session_state[f"{sugg_key}_assoc_mode"]
                                        st.rerun()
                    st.divider()
            else:
                st.info("No suggestions yet")

        return [render_suggestion_config]

    def render_dashboard_widgets(self, trainer_id: str, students: List[Dict]) -> List[Callable]:
        """Add a dashboard widget showing suggestion stats."""
        def render_suggestion_stats():
            st.markdown("---")
            st.subheader("💡 Suggestion Overview")

            total_active = 0
            total_used = 0
            total_dismissed = 0
            students_with_suggestions = 0

            for student_idx, student in enumerate(students[:5]):  # Show first 5 students
                student_id = student['id']
                student_name = student.get('name', student_id)

                with self.db.get_session() as session:
                    stats = session.query(
                        StudentSuggestion.is_dismissed,
                        StudentSuggestion.is_clicked
                    ).filter_by(
                        student_id=student_id,
                        trainer_id=trainer_id
                    ).all()

                    active = sum(1 for s in stats if not s.is_dismissed and not s.is_clicked)
                    used = sum(1 for s in stats if s.is_clicked)
                    dismissed = sum(1 for s in stats if s.is_dismissed and not s.is_clicked)

                    if active + used + dismissed > 0:
                        students_with_suggestions += 1

                        with st.expander(f"{student_name}", expanded=False):
                            col1, col2, col3 = st.columns(3)
                            col1.metric("Active", active)
                            col2.metric("Used", used)
                            col3.metric("Dismissed", dismissed)

                        total_active += active
                        total_used += used
                        total_dismissed += dismissed

            if total_active + total_used + total_dismissed > 0:
                st.markdown("#### Overall Stats")
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Students", students_with_suggestions)
                col2.metric("Active", total_active)
                col3.metric("Used", total_used)
                col4.metric("Dismissed", total_dismissed)

                if total_used + total_dismissed > 0:
                    engagement = (total_used / (total_used + total_dismissed)) * 100
                    st.metric("Engagement Rate", f"{engagement:.1f}%")
            else:
                st.info("No suggestion activity yet")

        return [render_suggestion_stats]

    def render_get_admin_tabs(self, trainer_id: str) -> List[Tuple[str, Callable]]:
        """Add a suggestions analytics tab for teachers."""
        def render_analytics():
            st.subheader("📊 Suggestion Analytics")

            if self._core.trainer_manager is None:
                st.warning("Trainer manager unavailable.")
                return
            students = self._core.trainer_manager.get_trainer_students(trainer_id)

            if not students:
                st.info("No students available.")
                return

            with self.db.get_session() as session:
                # Overall stats
                total_suggestions = session.query(StudentSuggestion).filter_by(
                    trainer_id=trainer_id
                ).count()

                auto_suggestions = session.query(StudentSuggestion).filter_by(
                    trainer_id=trainer_id,
                    source="auto"
                ).count()

                teacher_suggestions = session.query(StudentSuggestion).filter_by(
                    trainer_id=trainer_id,
                    source="teacher"
                ).count()

                # State counts
                used = session.query(StudentSuggestion).filter_by(
                    trainer_id=trainer_id,
                    is_clicked=True
                ).count()

                dismissed = session.query(StudentSuggestion).filter_by(
                    trainer_id=trainer_id,
                    is_dismissed=True,
                    is_clicked=False
                ).count()

                displayed = session.query(StudentSuggestion).filter_by(
                    trainer_id=trainer_id,
                    is_displayed=True
                ).count()

                deleted = session.query(StudentSuggestion).filter_by(
                    trainer_id=trainer_id,
                    is_deleted_by_teacher=True
                ).count()

                active = total_suggestions - used - dismissed - deleted

                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Total Active", active)
                col2.metric("Total Used", used)
                col3.metric("Total Dismissed", dismissed)
                col4.metric("Displayed Now", displayed)

                st.subheader("Per-Student Breakdown")

                for student in students:
                    student_id = student['id']
                    student_name = student.get('name', student_id)

                    student_suggestions = session.query(StudentSuggestion).filter_by(
                        student_id=student_id,
                        trainer_id=trainer_id
                    ).all()

                    if student_suggestions:
                        student_used = sum(1 for s in student_suggestions if s.is_clicked)
                        student_dismissed = sum(1 for s in student_suggestions if s.is_dismissed and not s.is_clicked)
                        student_displayed = sum(1 for s in student_suggestions if s.is_displayed)

                        with st.expander(f"{student_name}", expanded=False):
                            col1, col2, col3, col4 = st.columns(4)
                            col1.metric("Total", len(student_suggestions))
                            col2.metric("Used", student_used)
                            col3.metric("Dismissed", student_dismissed)
                            col4.metric("Displayed", student_displayed)

                            # Show engagement rate
                            if len(student_suggestions) > 0:
                                engagement = (student_used / len(student_suggestions)) * 100
                                st.metric("Engagement Rate", f"{engagement:.1f}%")

        return [("Suggestions Analytics", render_analytics)]
