"""
Suggest Plugin for Trainer Module.
Generates contextual suggestions for students based on their conversations.
Suggests questions or learning prompts at configurable intervals.
"""

from typing import List, Dict, Any, Optional, Tuple, Callable
import streamlit as st
from datetime import datetime, timedelta
import uuid
import json
import asyncio

from sqlalchemy import Column, String, Text, DateTime, JSON, Integer, Boolean, and_
from shared.common import Base, get_db_manager, get_prompt, log, _
from modules.trainer.plugin_base import TrainerPlugin, PluginManifest
from modules.trainer.manager import get_trainer_manager
from shared.conversation import get_conversation_manager, Message

# Import the async LLM function
try:
    from shared.common import llm_generate
except ImportError:
    # Fallback for testing
    async def llm_generate(prompt, user_id=None, system_prompt=None, max_tokens=500, temperature=0.7):
        log("warning", "Using mock llm_generate")
        return f"This is a mock suggestion based on: {prompt[:50]}..."

# ============= DATABASE MODEL =============
class StudentSuggestionConfig(Base):
    """Store suggestion configuration per student."""
    __tablename__ = 'trainer_suggest_config'
    __table_args__ = {'extend_existing': True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id = Column(String, nullable=False, index=True)
    trainer_id = Column(String, nullable=False, index=True)
    message_interval = Column(Integer, default=5)  # Suggest every N messages
    is_enabled = Column(Boolean, default=True)
    last_suggestion_index = Column(Integer, default=0)  # Last message count when suggestion was made
    updated_at = Column(DateTime, default=datetime.utcnow)
    config_metadata = Column(JSON, default={})


class StudentSuggestion(Base):
    """Store generated suggestions for students."""
    __tablename__ = 'trainer_suggestions'
    __table_args__ = {'extend_existing': True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id = Column(String, nullable=False, index=True)
    trainer_id = Column(String, nullable=False, index=True)
    conversation_id = Column(String, nullable=True)  # Conversation that triggered this suggestion
    content = Column(Text, nullable=False)
    suggestion_type = Column(String, default="question")  # question, prompt, resource, etc.
    source = Column(String, default="auto")  # 'auto' or 'teacher'
    is_dismissed = Column(Boolean, default=False)
    is_clicked = Column(Boolean, default=False)  # User clicked/used this suggestion
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)  # When this suggestion expires
    suggestion_metadata = Column(JSON, default={})
# ==========================================


class SuggestPlugin(TrainerPlugin):
    """Plugin that generates contextual suggestions for students."""

    def initialize(self) -> bool:
        """Initialize the plugin and ensure database tables exist."""
        try:
            db = get_db_manager()
            if db.is_initialized() and not db._in_memory:
                # Create tables if they don't exist
                Base.metadata.create_all(db._engine, tables=[
                    StudentSuggestionConfig.__table__,
                    StudentSuggestion.__table__
                ], checkfirst=True)
                log("info", "Suggestion plugin tables created/verified")
        except Exception as e:
            log("error", f"Failed to create suggestion plugin tables: {e}")

        # Register for conversation callbacks
        from shared.conversation import get_conversation_manager
        conv_manager = get_conversation_manager()
        conv_manager.register_user_message_callback(self._on_user_message)
        log("info", "Suggest plugin registered for user message callbacks")

        return True

    def _on_user_message(self, conversation_id: str, messages: List[Message]) -> None:
        """
        Callback triggered when a user adds a message to a conversation.
        This is where we check if we should generate a new suggestion.
        """
        try:
            if not messages:
                return

            # Get the conversation to find the student
            conv_manager = get_conversation_manager()
            conversation = conv_manager.get_conversation(conversation_id)
            if not conversation:
                return

            student_id = conversation.user_id

            # Get the student's trainer (parent)
            from shared.common import get_user_manager
            user_manager = get_user_manager()
            user = user_manager.get_user(student_id)

            if not user or not user.get('parent_id'):
                return

            trainer_id = user['parent_id']

            # Check if plugin is active for this trainer
            trainer_manager = get_trainer_manager()
            if not trainer_manager.is_plugin_active(trainer_id, self.id):
                return

            # Get student configuration
            config = self._get_student_config(student_id, trainer_id)

            if not config or not config.get('is_enabled', True):
                return

            # Count user messages in this conversation
            user_message_count = sum(1 for msg in messages if msg.role == "user")
            last_index = config.get('last_suggestion_index', 0)
            interval = config.get('message_interval', 5)

            # Check if we should generate a new suggestion
            if user_message_count - last_index >= interval:
                # Run async generation in background
                asyncio.create_task(
                    self._generate_suggestion_async(
                        student_id,
                        trainer_id,
                        conversation_id,
                        messages,
                        source="auto"
                    )
                )

        except Exception as e:
            log("error", f"Error in suggestion callback: {e}", exc_info=True)

    async def _generate_suggestion_async(self, student_id: str, trainer_id: str,
                                        conversation_id: str, messages: List[Message],
                                        source: str = "auto") -> bool:
        """
        Generate a suggestion using LLM based on conversation context.
        Async version to be called from callback.
        """
        try:
            # Get recent messages for context (last 10 messages)
            recent_messages = messages[-10:] if len(messages) > 10 else messages

            # Format conversation history for the prompt
            conversation_text = ""
            for msg in recent_messages:
                role = "Student" if msg.role == "user" else "Teacher"
                conversation_text += f"{role}: {msg.content}\n\n"

            # Get the suggestion prompt
            suggestion_prompt = get_prompt(
                'trainer.plugins.suggest.generate',
                """Based on the following conversation, generate ONE helpful suggestion for the student.
                The suggestion should be a question, learning prompt, or resource recommendation that would help them progress.

                Conversation:
                {conversation}

                Generate a single, concise suggestion (max 100 characters). Be specific and helpful.
                Suggestion:"""
            )

            prompt = suggestion_prompt.format(conversation=conversation_text)

            # Call LLM to generate suggestion (async)
            # The context will be automatically added by the LLM context callbacks
            suggestion = await llm_generate(
                message=prompt,
                user_id=student_id,
            )

            if not suggestion:
                log("warning", f"Failed to generate suggestion for student {student_id}")
                return False

            # Clean up the suggestion
            suggestion = suggestion.strip().strip('"').strip("'")

            # Save the suggestion
            db = get_db_manager()
            with db.get_session() as session:
                # Get current config to update last suggestion index
                config = session.query(StudentSuggestionConfig).filter_by(
                    student_id=student_id,
                    trainer_id=trainer_id
                ).first()

                if config and source == "auto":
                    # Count current user messages
                    user_message_count = sum(1 for msg in messages if msg.role == "user")
                    config.last_suggestion_index = user_message_count
                    config.updated_at = datetime.utcnow()
                    session.add(config)

                # Create new suggestion (expires in 7 days by default)
                suggestion_record = StudentSuggestion(
                    student_id=student_id,
                    trainer_id=trainer_id,
                    conversation_id=conversation_id,
                    content=suggestion,
                    suggestion_type="question",
                    source=source,
                    created_at=datetime.utcnow(),
                    expires_at=datetime.utcnow() + timedelta(days=7),
                    suggestion_metadata={
                        'trigger_message_count': len(messages) if source == "auto" else 0,
                        'conversation_id': conversation_id,
                        'teacher_id': trainer_id if source == "teacher" else None
                    }
                )
                session.add(suggestion_record)
                session.commit()

                log("info", f"Generated {source} suggestion for student {student_id}: {suggestion[:50]}...")
                return True

        except Exception as e:
            log("error", f"Failed to generate suggestion: {e}", exc_info=True)
            return False

    def _get_student_config(self, student_id: str, trainer_id: str) -> Optional[Dict]:
        """Get suggestion configuration for a student."""
        db = get_db_manager()
        with db.get_session() as session:
            config = session.query(StudentSuggestionConfig).filter_by(
                student_id=student_id,
                trainer_id=trainer_id
            ).first()

            if config:
                return {
                    'message_interval': config.message_interval,
                    'is_enabled': config.is_enabled,
                    'last_suggestion_index': config.last_suggestion_index
                }
            return None

    def _save_student_config(self, student_id: str, trainer_id: str,
                            interval: int, enabled: bool) -> bool:
        """Save or update student configuration."""
        try:
            db = get_db_manager()
            with db.get_session() as session:
                config = session.query(StudentSuggestionConfig).filter_by(
                    student_id=student_id,
                    trainer_id=trainer_id
                ).first()

                if config:
                    config.message_interval = interval
                    config.is_enabled = enabled
                    config.updated_at = datetime.utcnow()
                else:
                    config = StudentSuggestionConfig(
                        student_id=student_id,
                        trainer_id=trainer_id,
                        message_interval=interval,
                        is_enabled=enabled,
                        last_suggestion_index=0
                    )
                    session.add(config)
                session.commit()
                return True
        except Exception as e:
            log("error", f"Failed to save student config: {e}")
            return False

    def _get_active_suggestion(self, student_id: str, trainer_id: str) -> Optional[Dict]:
        """Get the most recent active (not dismissed, not expired) suggestion."""
        db = get_db_manager()
        with db.get_session() as session:
            now = datetime.utcnow()
            suggestion = session.query(StudentSuggestion).filter(
                StudentSuggestion.student_id == student_id,
                StudentSuggestion.trainer_id == trainer_id,
                StudentSuggestion.is_dismissed == False,
                (StudentSuggestion.expires_at.is_(None) | (StudentSuggestion.expires_at > now))
            ).order_by(StudentSuggestion.created_at.desc()).first()

            if suggestion:
                return {
                    'id': suggestion.id,
                    'content': suggestion.content,
                    'type': suggestion.suggestion_type,
                    'source': suggestion.source,
                    'created_at': suggestion.created_at
                }
            return None

    def _dismiss_suggestion(self, suggestion_id: str) -> bool:
        """Mark a suggestion as dismissed."""
        try:
            db = get_db_manager()
            with db.get_session() as session:
                suggestion = session.query(StudentSuggestion).filter_by(id=suggestion_id).first()
                if suggestion:
                    suggestion.is_dismissed = True
                    session.commit()
                    return True
            return False
        except Exception as e:
            log("error", f"Failed to dismiss suggestion: {e}")
            return False

    def _mark_suggestion_clicked(self, suggestion_id: str) -> bool:
        """Mark a suggestion as clicked/used."""
        try:
            db = get_db_manager()
            with db.get_session() as session:
                suggestion = session.query(StudentSuggestion).filter_by(id=suggestion_id).first()
                if suggestion:
                    suggestion.is_clicked = True
                    # Also dismiss it since it's been used
                    suggestion.is_dismissed = True
                    session.commit()
                    return True
            return False
        except Exception as e:
            log("error", f"Failed to mark suggestion clicked: {e}")
            return False

    # ============= RENDER METHODS =============

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
                        <div class="suggestion-content">{source_icon} {suggestion['content']}</div>
                    </div>
                    """, unsafe_allow_html=True)

                with cols[1]:
                    # Use suggestion button
                    if st.button(_("trainer_plugin_suggest.use"), key=f"use_{suggestion_key}"):
                        if self._mark_suggestion_clicked(suggestion['id']):
                            # Create a new conversation with this suggestion as the title/prompt
                            conv_manager = get_conversation_manager()
                            new_conv_id = conv_manager.create_conversation(
                                user_id=student_id,
                                title=suggestion['content'][:50],  # Truncate for title
                                system_prompt=None  # Use default
                            )
                            # Add the suggestion as the first user message
                            conv_manager.add_message(
                                new_conv_id,
                                Message(role="user", content=suggestion['content'])
                            )
                            st.success(_("trainer_plugin_suggest.started"), icon="🚀")
                            st.rerun()

                with cols[2]:
                    # Dismiss button
                    if st.button(_("trainer_plugin_suggest.dismiss"), key=f"dismiss_{suggestion_key}"):
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
                        help="Generate a new suggestion after this many student messages",
                        key=f"{base_key}_interval"
                    )

                if st.form_submit_button("Save settings", key=f"{base_key}_submit"):
                    if self._save_student_config(student_id, trainer_id, interval, enabled):
                        st.success("Settings saved!")
                        st.rerun()
                    else:
                        st.error("Failed to save settings")

            # Manual suggestion section
            st.markdown("#### ✨ Manual Suggestion")
            st.caption("Generate a suggestion now based on recent conversations")

            # Get recent conversations for context
            conv_manager = get_conversation_manager()
            conversations = conv_manager.get_user_conversations(student_id)

            if conversations:
                # Let teacher select which conversation to use for context
                conv_options = {conv['id']: f"{conv['title']} ({conv.get('message_count', 0)} messages)"
                              for conv in conversations[:5]}  # Last 5 conversations

                selected_conv_id = st.selectbox(
                    "Use conversation for context",
                    options=list(conv_options.keys()),
                    format_func=lambda x: conv_options[x],
                    key=f"{base_key}_conv_select"
                )

                if st.button("🪄 Generate Suggestion", key=f"{base_key}_generate"):
                    with st.spinner("Generating suggestion..."):
                        # Get full conversation
                        conversation = conv_manager.get_conversation(selected_conv_id, include_messages=True)
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

                st.markdown("#### 📝 Edit Suggestion")

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
                                db = get_db_manager()
                                with db.get_session() as session:
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
                            "You can edit this suggestion before sending:",
                            value=st.session_state[sugg_text_key],
                            height=100,
                            key=f"{base_key}_edit_area"
                        )

                        col1, col2 = st.columns(2)
                        with col1:
                            if st.button("✅ Send to Student", key=f"{base_key}_send"):
                                # Update the suggestion with edited text
                                db = get_db_manager()
                                with db.get_session() as session:
                                    sugg = session.query(StudentSuggestion).filter_by(
                                        id=st.session_state[sugg_id_key]
                                    ).first()
                                    if sugg:
                                        sugg.content = editable_suggestion
                                        session.commit()
                                        st.success("Suggestion sent to student!")

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
                            if st.button("❌ Cancel", key=f"{base_key}_cancel"):
                                # Delete the unsent suggestion
                                db = get_db_manager()
                                with db.get_session() as session:
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

            # Show recent suggestions
            st.markdown("#### Recent Suggestions")
            db = get_db_manager()
            with db.get_session() as session:
                recent = session.query(StudentSuggestion).filter_by(
                    student_id=student_id,
                    trainer_id=trainer_id
                ).order_by(StudentSuggestion.created_at.desc()).limit(5).all()

                if recent:
                    for sugg in recent:
                        status = "✓ Used" if sugg.is_clicked else "✗ Dismissed" if sugg.is_dismissed else "⏳ Active"
                        source_icon = "👤 Auto" if sugg.source == 'auto' else "👨‍🏫 Teacher"

                        # Create unique keys for this suggestion
                        sugg_key = f"{base_key}_{sugg.id}"

                        cols = st.columns([3, 1, 1, 1])
                        with cols[0]:
                            st.caption(f"📅 {sugg.created_at.strftime('%Y-%m-%d %H:%M')} {source_icon}")
                            st.write(sugg.content[:100] + "..." if len(sugg.content) > 100 else sugg.content)
                        with cols[1]:
                            st.caption(status)
                        with cols[2]:
                            if not sugg.is_dismissed and not sugg.is_clicked:
                                if st.button("Dismiss", key=f"{sugg_key}_dismiss"):
                                    self._dismiss_suggestion(sugg.id)
                                    st.rerun()
                        with cols[3]:
                            # Preview button
                            if st.button("👁️", key=f"{sugg_key}_preview", help="Preview suggestion"):
                                st.info(f"**Suggestion:** {sugg.content}")
                        st.divider()
                else:
                    st.info("No suggestions generated yet")

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

            db = get_db_manager()
            with db.get_session() as session:
                for student_idx, student in enumerate(students[:5]):  # Show first 5 students
                    student_id = student['id']
                    student_name = student.get('name', student_id)

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

    # ============= EXPORT/IMPORT METHODS =============

    def export_config(self, trainer_id: str) -> Optional[Dict]:
        """Export suggestion configuration for all students."""
        db = get_db_manager()
        configs = {}

        with db.get_session() as session:
            student_configs = session.query(StudentSuggestionConfig).filter_by(
                trainer_id=trainer_id
            ).all()

            for cfg in student_configs:
                configs[cfg.student_id] = {
                    'message_interval': cfg.message_interval,
                    'is_enabled': cfg.is_enabled,
                    'last_suggestion_index': cfg.last_suggestion_index
                }

        return {'student_configs': configs} if configs else None

    def import_config(self, trainer_id: str, config: Dict) -> bool:
        """Import suggestion configuration."""
        student_configs = config.get('student_configs', {})

        success = True
        for student_id, cfg_data in student_configs.items():
            if not self._save_student_config(
                student_id,
                trainer_id,
                cfg_data.get('message_interval', 5),
                cfg_data.get('is_enabled', True)
            ):
                success = False

        return success

    def export_history(self, trainer_id: str, student_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Export suggestion history events."""
        db = get_db_manager()
        events = []

        with db.get_session() as session:
            query = session.query(StudentSuggestion).filter_by(trainer_id=trainer_id)

            if student_id:
                query = query.filter_by(student_id=student_id)

            suggestions = query.order_by(StudentSuggestion.created_at).all()

            for sugg in suggestions:
                event = {
                    'timestamp': sugg.created_at.isoformat(),
                    'type': 'plugin.suggest.generated',
                    'plugin_id': self.id,
                    'student_id': sugg.student_id,
                    'suggestion_id': sugg.id,
                    'content': sugg.content,
                    'suggestion_type': sugg.suggestion_type,
                    'source': sugg.source,
                }

                if sugg.is_clicked:
                    event['action'] = 'clicked'
                elif sugg.is_dismissed:
                    event['action'] = 'dismissed'

                if sugg.expires_at:
                    event['expires_at'] = sugg.expires_at.isoformat()

                if sugg.suggestion_metadata:
                    event['metadata'] = sugg.suggestion_metadata

                events.append(event)

        return events

    def import_history(self, trainer_id: str, events: List[Dict[str, Any]], student_info: Dict = None) -> bool:
        """Import suggestion history events."""
        db = get_db_manager()

        try:
            with db.get_session() as session:
                for event in events:
                    if event.get('plugin_id') != self.id:
                        continue

                    # Check if suggestion already exists
                    existing = None
                    if event.get('suggestion_id'):
                        existing = session.query(StudentSuggestion).filter_by(
                            id=event['suggestion_id']
                        ).first()

                    if not existing:
                        # Parse timestamps
                        created_at = None
                        expires_at = None

                        try:
                            if event.get('timestamp'):
                                created_at = datetime.fromisoformat(event['timestamp'].replace('Z', '+00:00'))
                        except (ValueError, TypeError):
                            created_at = datetime.utcnow()

                        try:
                            if event.get('expires_at'):
                                expires_at = datetime.fromisoformat(event['expires_at'].replace('Z', '+00:00'))
                        except (ValueError, TypeError):
                            pass

                        # Determine dismissed/clicked status
                        action = event.get('action')
                        is_clicked = action == 'clicked'
                        is_dismissed = action == 'dismissed' or is_clicked

                        # Create suggestion
                        suggestion = StudentSuggestion(
                            id=event.get('suggestion_id', str(uuid.uuid4())),
                            student_id=event['student_id'],
                            trainer_id=trainer_id,
                            content=event.get('content', ''),
                            suggestion_type=event.get('suggestion_type', 'question'),
                            source=event.get('source', 'auto'),
                            is_dismissed=is_dismissed,
                            is_clicked=is_clicked,
                            created_at=created_at,
                            expires_at=expires_at,
                            suggestion_metadata=event.get('metadata', {})
                        )
                        session.add(suggestion)

                session.commit()
                return True

        except Exception as e:
            log("error", f"Failed to import suggestion history: {e}", exc_info=True)
            return False

    def get_admin_tabs(self, trainer_id: str) -> List[Tuple[str, Callable]]:
        """Add a suggestions analytics tab for teachers."""
        def render_analytics():
            st.subheader("📊 Suggestions Analytics")

            trainer_manager = get_trainer_manager()
            students = trainer_manager.get_trainer_students(trainer_id)

            if not students:
                st.info("No students available.")
                return

            db = get_db_manager()
            with db.get_session() as session:
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

                clicked = session.query(StudentSuggestion).filter_by(
                    trainer_id=trainer_id,
                    is_clicked=True
                ).count()

                dismissed = session.query(StudentSuggestion).filter_by(
                    trainer_id=trainer_id,
                    is_dismissed=True,
                    is_clicked=False
                ).count()

                active = total_suggestions - clicked - dismissed

                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Total", total_suggestions)
                col2.metric("Auto", auto_suggestions)
                col3.metric("Teacher", teacher_suggestions)
                col4.metric("Active", active)

                col1, col2, col3 = st.columns(3)
                col1.metric("Used", clicked)
                col2.metric("Dismissed", dismissed)
                if total_suggestions > 0:
                    col3.metric("Engagement Rate", f"{(clicked/total_suggestions*100):.1f}%")

                # Per-student breakdown
                st.subheader("Per-Student Breakdown")

                for student in students:
                    student_id = student['id']
                    student_name = student.get('name', student_id)

                    student_suggestions = session.query(StudentSuggestion).filter_by(
                        student_id=student_id,
                        trainer_id=trainer_id
                    ).count()

                    if student_suggestions > 0:
                        student_clicked = session.query(StudentSuggestion).filter_by(
                            student_id=student_id,
                            trainer_id=trainer_id,
                            is_clicked=True
                        ).count()

                        with st.expander(f"{student_name}", expanded=False):
                            col1, col2, col3 = st.columns(3)
                            col1.metric("Total", student_suggestions)
                            col2.metric("Used", student_clicked)
                            if student_suggestions > 0:
                                col3.metric("Engagement", f"{(student_clicked/student_suggestions*100):.1f}%")

        return [("Suggestions Analytics", render_analytics)]

# Plugin entry point - must be named 'plugin'
plugin = SuggestPlugin
