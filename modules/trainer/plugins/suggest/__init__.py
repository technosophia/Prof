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
from sqlalchemy.orm.attributes import flag_modified
from shared.common import Base, get_db_manager, get_prompt, log, _
from modules.trainer.plugin_base import TrainerPlugin, PluginManifest
from modules.trainer.manager import get_trainer_manager
from shared.conversation import get_conversation_manager, Message
from shared.common import llm_generate


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
    conversation_id = Column(String, nullable=True)  # Primary conversation that triggered this suggestion
    content = Column(Text, nullable=False)
    suggestion_type = Column(String, default="question")  # question, prompt, resource, etc.
    source = Column(String, default="auto")  # 'auto' or 'teacher'

    # State management
    is_dismissed = Column(Boolean, default=False)
    is_clicked = Column(Boolean, default=False)  # User clicked/used this suggestion
    is_displayed = Column(Boolean, default=False)  # Currently being displayed to student
    is_deleted_by_teacher = Column(Boolean, default=False)  # Teacher deleted/archived

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    viewed_at = Column(DateTime, nullable=True)  # When student first saw it
    used_at = Column(DateTime, nullable=True)  # When student used it
    dismissed_at = Column(DateTime, nullable=True)  # When student dismissed it
    deleted_at = Column(DateTime, nullable=True)  # When teacher deleted it
    expires_at = Column(DateTime, nullable=True)  # When this suggestion expires

    # Relationships
    created_conversation_id = Column(String, nullable=True)  # Conversation created when suggestion was used
    related_conversation_ids = Column(JSON, default=list)  # List of conversation IDs associated with this suggestion

    # Metadata and history
    suggestion_metadata = Column(JSON, default={})
    interaction_history = Column(JSON, default=list)  # List of {action: str, timestamp: str, details: dict}

    def add_interaction(self, action: str, details: dict = None):
        """Add an interaction to the history."""
        # Initialize interaction_history if it's None
        if self.interaction_history is None:
            self.interaction_history = []

        # Create the interaction record
        interaction = {
            'action': action,
            'timestamp': datetime.utcnow().isoformat(),
            'details': details or {}
        }

        # Add to history
        self.interaction_history.append(interaction)

        log("info", f"Added {action} interaction to suggestion {getattr(self, 'id', 'new')}. History now has {len(self.interaction_history)} entries")

        # Update corresponding timestamp fields
        now = datetime.utcnow()
        if action == 'viewed':
            if not self.viewed_at:
                self.viewed_at = now
            self.is_displayed = True
        elif action == 'used':
            self.used_at = now
            self.is_clicked = True
            self.is_displayed = False
        elif action == 'dismissed':
            self.dismissed_at = now
            self.is_dismissed = True
            self.is_displayed = False
        elif action == 'deleted':
            self.deleted_at = now
            self.is_deleted_by_teacher = True
            self.is_displayed = False
        elif action == 'created':
            self.created_at = now
        elif action == 'expired':
            self.is_displayed = False
        elif action == 'edited':
            # Just log the edit, no state change
            pass
        elif action == 'conversation_associated':
            # Just log the association, no state change
            pass
        flag_modified(self, "interaction_history")

        return self.interaction_history

    def get_last_interaction(self) -> dict:
        """Get the most recent interaction."""
        if self.interaction_history:
            return self.interaction_history[-1]
        return None

    def get_state(self) -> str:
        """Get the current state of the suggestion."""
        if self.is_deleted_by_teacher:
            return 'deleted'
        if self.is_clicked:
            return 'used'
        if self.is_dismissed:
            return 'dismissed'
        if self.expires_at and self.expires_at < datetime.utcnow():
            return 'expired'
        if self.is_displayed:
            return 'displayed'
        return 'active'
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
                # ... (previous config code)

                # Initialize related_conversation_ids with the current conversation
                related_ids = [conversation_id] if conversation_id else []

                suggestion_record = StudentSuggestion(
                    student_id=student_id,
                    trainer_id=trainer_id,
                    conversation_id=conversation_id,
                    content=suggestion,
                    suggestion_type="question",
                    source=source,
                    created_at=now,
                    expires_at=now + timedelta(days=7),
                    related_conversation_ids=related_ids,
                    suggestion_metadata={
                        'trigger_message_count': len(messages) if source == "auto" else 0,
                        'conversation_id': conversation_id,
                        'teacher_id': trainer_id if source == "teacher" else None
                    },
                    interaction_history=[]  # Initialize empty list
                )

                # Add creation interaction - this will now work because interaction_history is initialized
                suggestion_record.add_interaction('created', {
                    'source': source,
                    'conversation_id': conversation_id
                })

                session.add(suggestion_record)
                session.commit()  # Commit the creation with its interaction

                log("debug", f"Generated {source} suggestion for student {student_id}: {suggestion[:50]}...")
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
        """Get the most recent active (not dismissed, not expired, not deleted) suggestion."""
        db = get_db_manager()
        with db.get_session() as session:
            now = datetime.utcnow()
            suggestion = session.query(StudentSuggestion).filter(
                StudentSuggestion.student_id == student_id,
                StudentSuggestion.trainer_id == trainer_id,
                StudentSuggestion.is_deleted_by_teacher == False,
                StudentSuggestion.is_dismissed == False,
                StudentSuggestion.is_clicked == False,
                (StudentSuggestion.expires_at.is_(None) | (StudentSuggestion.expires_at > now))
            ).order_by(StudentSuggestion.created_at.desc()).first()

            if suggestion:
                # Mark as displayed and add view interaction if not already viewed
                if not suggestion.is_displayed:
                    suggestion.add_interaction('viewed')
                    suggestion.is_displayed = True
                    session.commit()  # Commit the view interaction

                return {
                    'id': suggestion.id,
                    'content': suggestion.content,
                    'type': suggestion.suggestion_type,
                    'source': suggestion.source,
                    'created_at': suggestion.created_at,
                    'state': suggestion.get_state()
                }
            return None

    def _dismiss_suggestion(self, suggestion_id: str) -> bool:
        """Mark a suggestion as dismissed."""
        try:
            db = get_db_manager()
            with db.get_session() as session:
                suggestion = session.query(StudentSuggestion).filter_by(id=suggestion_id).first()
                if suggestion:
                    suggestion.add_interaction('dismissed')
                    # No need for flag_modified here - it's in add_interaction
                    session.commit()
                    return True
            return False
        except Exception as e:
            log("error", f"Failed to dismiss suggestion: {e}")
            return False

    def _mark_suggestion_clicked(self, suggestion_id: str, created_conv_id: str = None) -> bool:
        """Mark a suggestion as clicked/used."""
        try:
            db = get_db_manager()
            with db.get_session() as session:
                suggestion = session.query(StudentSuggestion).filter_by(id=suggestion_id).first()
                if suggestion:
                    details = {}
                    if created_conv_id:
                        suggestion.created_conversation_id = created_conv_id
                        details['conversation_id'] = created_conv_id

                        # Also add to related_conversation_ids if not already there
                        if suggestion.related_conversation_ids is None:
                            suggestion.related_conversation_ids = []
                        if created_conv_id not in suggestion.related_conversation_ids:
                            suggestion.related_conversation_ids.append(created_conv_id)
                            # Flag this field too
                            flag_modified(suggestion, "related_conversation_ids")
                            details['added_to_related'] = True

                    suggestion.add_interaction('used', details)
                    # flag_modified for interaction_history is handled inside add_interaction
                    session.commit()
                    return True
            return False
        except Exception as e:
            log("error", f"Failed to mark suggestion clicked: {e}")
            return False

    def associate_conversation_with_suggestion(self, suggestion_id: str, conversation_id: str) -> bool:
        """Associate an additional conversation with a suggestion."""
        try:
            db = get_db_manager()
            with db.get_session() as session:
                suggestion = session.query(StudentSuggestion).filter_by(id=suggestion_id).first()
                if suggestion:
                    # Initialize related_conversation_ids if it's None
                    if suggestion.related_conversation_ids is None:
                        suggestion.related_conversation_ids = []

                    if conversation_id not in suggestion.related_conversation_ids:
                        suggestion.related_conversation_ids.append(conversation_id)
                        # Flag this field
                        flag_modified(suggestion, "related_conversation_ids")

                        suggestion.add_interaction('conversation_associated', {
                            'conversation_id': conversation_id
                        })
                        # flag_modified for interaction_history is handled inside add_interaction

                        session.commit()
                        log("debug", f"Associated conversation {conversation_id} with suggestion {suggestion_id}")
                    return True
            return False
        except Exception as e:
            log("error", f"Failed to associate conversation: {e}")
            return False

    def debug_check_suggestion(self, suggestion_id: str):
        """Debug function to check what's in the database for a suggestion."""
        db = get_db_manager()
        with db.get_session() as session:
            suggestion = session.query(StudentSuggestion).filter_by(id=suggestion_id).first()
            if suggestion:
                log("info", f"=== DEBUG for suggestion {suggestion_id} ===")
                log("info", f"Content: {suggestion.content[:50]}...")
                log("info", f"is_displayed: {suggestion.is_displayed}")
                log("info", f"is_clicked: {suggestion.is_clicked}")
                log("info", f"is_dismissed: {suggestion.is_dismissed}")
                log("info", f"viewed_at: {suggestion.viewed_at}")
                log("info", f"used_at: {suggestion.used_at}")
                log("info", f"dismissed_at: {suggestion.dismissed_at}")
                log("info", f"interaction_history: {suggestion.interaction_history}")
                log("info", f"interaction_history type: {type(suggestion.interaction_history)}")
                log("info", f"interaction_history length: {len(suggestion.interaction_history) if suggestion.interaction_history else 0}")
                return suggestion
        return None

    def delete_suggestion_by_teacher(self, suggestion_id: str) -> bool:
        """Mark a suggestion as deleted by teacher."""
        try:
            db = get_db_manager()
            with db.get_session() as session:
                suggestion = session.query(StudentSuggestion).filter_by(id=suggestion_id).first()
                if suggestion:
                    suggestion.add_interaction('deleted')
                    session.commit()  # Commit the delete interaction
                    return True
            return False
        except Exception as e:
            log("error", f"Failed to delete suggestion: {e}")
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

                        # Mark as used with the created conversation
                        if self._mark_suggestion_clicked(suggestion['id'], new_conv_id):
                            # AUTO-ASSOCIATE: Also add to related conversations
                            self.associate_conversation_with_suggestion(suggestion['id'], new_conv_id)
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

            st.markdown(f"### 💡 {_('trainer_plugin_suggest.name')} for {student_name}")

            # Get current config
            config = self._get_student_config(student_id, trainer_id)
            current_interval = config.get('message_interval', 5) if config else 5
            current_enabled = config.get('is_enabled', True) if config else True

            # Configuration form
            with st.form(key=f"{base_key}_config_form"):
                col1, col2 = st.columns(2)

                with col1:
                    enabled = st.checkbox(
                        _("trainer_plugin_suggest.enable_for_student"),
                        value=current_enabled,
                        key=f"{base_key}_enabled"
                    )

                with col2:
                    interval = st.number_input(
                        _("trainer_plugin_suggest.suggest_every"),
                        min_value=1,
                        max_value=20,
                        value=current_interval,
                        help=_("trainer_plugin_suggest.config_help"),
                        key=f"{base_key}_interval"
                    )

                if st.form_submit_button(_("trainer_plugin_suggest.save_settings"), key=f"{base_key}_submit"):
                    if self._save_student_config(student_id, trainer_id, interval, enabled):
                        st.success(_("trainer_plugin_suggest.settings_saved"))
                        st.rerun()
                    else:
                        st.error("Failed to save settings")

            # Manual suggestion section
            st.markdown(f"#### {_('trainer_plugin_suggest.manual_suggestion')}")
            st.caption(_("trainer_plugin_suggest.generate_now"))

            # Get recent conversations for context
            conv_manager = get_conversation_manager()
            conversations = conv_manager.get_user_conversations(student_id)

            if conversations:
                # Let teacher select which conversation to use for context
                conv_options = {}
                for conv in conversations[:5]:  # Last 5 conversations
                    conv_options[conv['id']] = f"{conv['title']} ({conv.get('message_count', 0)} messages)"

                selected_conv_id = st.selectbox(
                    _("trainer_plugin_suggest.use_conversation"),
                    options=list(conv_options.keys()),
                    format_func=lambda x: conv_options[x],
                    key=f"{base_key}_conv_select"
                )

                if st.button(_("trainer_plugin_suggest.generate_button"), key=f"{base_key}_generate"):
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

                st.markdown(f"#### {_('trainer_plugin_suggest.edit_suggestion')}")

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
                            _("trainer_plugin_suggest.edit_instruction"),
                            value=st.session_state[sugg_text_key],
                            height=100,
                            key=f"{base_key}_edit_area"
                        )

                        col1, col2 = st.columns(2)
                        with col1:
                            if st.button(_("trainer_plugin_suggest.send_to_student"), key=f"{base_key}_send"):
                                # Update the suggestion with edited text
                                db = get_db_manager()
                                with db.get_session() as session:
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
                                        st.success(_("trainer_plugin_suggest.suggestion_sent"))

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
                            if st.button(_("trainer_plugin_suggest.cancel"), key=f"{base_key}_cancel"):
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

            # Show recent suggestions with enhanced information
            st.markdown(f"#### {_('trainer_plugin_suggest.recent_suggestions')}")
            db = get_db_manager()
            with db.get_session() as session:
                recent = session.query(StudentSuggestion).filter_by(
                    student_id=student_id,
                    trainer_id=trainer_id
                ).order_by(StudentSuggestion.created_at.desc()).limit(10).all()

                if recent:
                    for sugg in recent:
                        state = sugg.get_state()
                        state_icons = {
                            'used': '✅',
                            'dismissed': '✗',
                            'displayed': '👁️',
                            'active': '⏳',
                            'expired': '⌛',
                            'deleted': '🗑️'
                        }
                        state_icon = state_icons.get(state, '❓')

                        source_icon = "👤 Auto" if sugg.source == 'auto' else "👨‍🏫 Teacher"

                        # Create unique keys for this suggestion
                        sugg_key = f"{base_key}_{sugg.id}"

                        with st.expander(f"{state_icon} {sugg.content[:100]}...", expanded=False):
                            col1, col2 = st.columns([2, 1])

                            with col1:
                                st.caption(f"📅 Created: {sugg.created_at.strftime('%Y-%m-%d %H:%M')}")
                                st.caption(f"👤 {source_icon}")

                                # Display associated conversations
                                all_conv_ids = []
                                if sugg.created_conversation_id:
                                    all_conv_ids.append(('Created', sugg.created_conversation_id))
                                if sugg.related_conversation_ids:
                                    for conv_id in sugg.related_conversation_ids:
                                        if conv_id != sugg.created_conversation_id:
                                            all_conv_ids.append(('Related', conv_id))

                                if all_conv_ids:
                                    st.caption("💬 **Associated Conversations:**")
                                    for conv_type, conv_id in all_conv_ids:
                                        # Try to get conversation title
                                        conv = conv_manager.get_conversation(conv_id)
                                        conv_title = conv.title if conv else "Unknown"
                                        st.caption(f"  • {conv_type}: {conv_title[:50]} ({conv_id[:8]}...)")

                                # Show last interaction
                                last_interaction = sugg.get_last_interaction()
                                if last_interaction:
                                    st.caption(f"📝 Last: {last_interaction['action']} at {last_interaction['timestamp'][:16]}")

                                # Full suggestion content
                                st.markdown(f"**Suggestion:** {sugg.content}")

                                # Show interaction history if requested
                                # Show interaction history if requested
                                if st.checkbox("Show history", key=f"{sugg_key}_show_history"):
                                    if sugg.interaction_history and len(sugg.interaction_history) > 0:
                                        for i, interaction in enumerate(sugg.interaction_history):
                                            action = interaction.get('action', 'unknown')
                                            timestamp = interaction.get('timestamp', '')[:16] if interaction.get('timestamp') else 'unknown'
                                            details = interaction.get('details', {})

                                            # Format details nicely
                                            details_str = ""
                                            if details:
                                                if 'conversation_id' in details:
                                                    # Try to get conversation title
                                                    conv = conv_manager.get_conversation(details['conversation_id'])
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
                                        self._dismiss_suggestion(sugg.id)
                                        st.rerun()

                                if state != 'deleted':
                                    if st.button("🗑️ Delete", key=f"{sugg_key}_delete"):
                                        self.delete_suggestion_by_teacher(sugg.id)
                                        st.rerun()

                                # Associate with another conversation
                                if st.button("➕ Associate Conv", key=f"{sugg_key}_assoc"):
                                    st.session_state[f"{sugg_key}_assoc_mode"] = True

                                if st.session_state.get(f"{sugg_key}_assoc_mode", False):
                                    # Get available conversations (excluding already associated ones)
                                    all_convs = conv_manager.get_user_conversations(student_id)

                                    # Build list of already associated conversation IDs
                                    associated_ids = []
                                    if sugg.created_conversation_id:
                                        associated_ids.append(sugg.created_conversation_id)
                                    if sugg.related_conversation_ids:
                                        associated_ids.extend(sugg.related_conversation_ids)

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
                                            self.associate_conversation_with_suggestion(sugg.id, selected_conv)
                                            del st.session_state[f"{sugg_key}_assoc_mode"]
                                            st.rerun()
                                    else:
                                        st.info("No new conversations to associate")
                                        if st.button("Close", key=f"{sugg_key}_assoc_close"):
                                            del st.session_state[f"{sugg_key}_assoc_mode"]
                                            st.rerun()
                    st.divider()
                else:
                    st.info(_("trainer_plugin_suggest.no_suggestions_yet"))

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
        """Export suggestion history events with full interaction history."""
        db = get_db_manager()
        events = []

        with db.get_session() as session:
            query = session.query(StudentSuggestion).filter_by(trainer_id=trainer_id)

            if student_id:
                query = query.filter_by(student_id=student_id)

            suggestions = query.order_by(StudentSuggestion.created_at).all()

            for sugg in suggestions:
                # Get the current state
                current_state = sugg.get_state()

                # Export the complete suggestion with its interaction history
                event = {
                    'timestamp': sugg.created_at.isoformat(),
                    'type': 'plugin.suggest.suggestion',
                    'plugin_id': self.id,
                    'student_id': sugg.student_id,
                    'suggestion_id': sugg.id,
                    'content': sugg.content,
                    'suggestion_type': sugg.suggestion_type,
                    'source': sugg.source,
                    'current_state': current_state,
                    'interaction_history': sugg.interaction_history,
                }

                # Add timestamps
                if sugg.viewed_at:
                    event['viewed_at'] = sugg.viewed_at.isoformat()
                if sugg.used_at:
                    event['used_at'] = sugg.used_at.isoformat()
                if sugg.dismissed_at:
                    event['dismissed_at'] = sugg.dismissed_at.isoformat()
                if sugg.deleted_at:
                    event['deleted_at'] = sugg.deleted_at.isoformat()
                if sugg.expires_at:
                    event['expires_at'] = sugg.expires_at.isoformat()

                # Add conversation associations
                if sugg.created_conversation_id:
                    event['created_conversation_id'] = sugg.created_conversation_id
                if sugg.related_conversation_ids:
                    event['related_conversation_ids'] = sugg.related_conversation_ids

                if sugg.suggestion_metadata:
                    event['metadata'] = sugg.suggestion_metadata

                events.append(event)

        return events

    def import_history(self, trainer_id: str, events: List[Dict[str, Any]], student_info: Dict = None) -> bool:
        """Import suggestion history events with full interaction history."""
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
                        viewed_at = None
                        used_at = None
                        dismissed_at = None
                        deleted_at = None
                        expires_at = None

                        try:
                            if event.get('timestamp'):
                                created_at = datetime.fromisoformat(event['timestamp'].replace('Z', '+00:00'))
                        except (ValueError, TypeError):
                            created_at = datetime.utcnow()

                        # Parse other timestamps
                        for ts_field in ['viewed_at', 'used_at', 'dismissed_at', 'deleted_at', 'expires_at']:
                            if event.get(ts_field):
                                try:
                                    locals()[ts_field] = datetime.fromisoformat(event[ts_field].replace('Z', '+00:00'))
                                except (ValueError, TypeError):
                                    pass

                        # Get interaction history or create from individual fields
                        interaction_history = event.get('interaction_history', [])

                        # Create suggestion
                        suggestion = StudentSuggestion(
                            id=event.get('suggestion_id', str(uuid.uuid4())),
                            student_id=event['student_id'],
                            trainer_id=trainer_id,
                            content=event.get('content', ''),
                            suggestion_type=event.get('suggestion_type', 'question'),
                            source=event.get('source', 'auto'),
                            created_at=created_at,
                            viewed_at=viewed_at,
                            used_at=used_at,
                            dismissed_at=dismissed_at,
                            deleted_at=deleted_at,
                            expires_at=expires_at,
                            created_conversation_id=event.get('created_conversation_id'),
                            related_conversation_ids=event.get('related_conversation_ids', []),
                            suggestion_metadata=event.get('metadata', {}),
                            interaction_history=interaction_history
                        )

                        # Set state flags based on timestamps and history
                        if used_at:
                            suggestion.is_clicked = True
                        if dismissed_at:
                            suggestion.is_dismissed = True
                        if deleted_at:
                            suggestion.is_deleted_by_teacher = True

                        # Check if currently displayed (if within expiration and not used/dismissed/deleted)
                        now = datetime.utcnow()
                        if (not suggestion.is_clicked and not suggestion.is_dismissed and
                            not suggestion.is_deleted_by_teacher and
                            (not suggestion.expires_at or suggestion.expires_at > now)):
                            # Check if last interaction was view within reasonable time
                            last_interaction = suggestion.get_last_interaction()
                            if last_interaction and last_interaction['action'] == 'viewed':
                                view_time = datetime.fromisoformat(last_interaction['timestamp'].replace('Z', '+00:00'))
                                if (now - view_time).total_seconds() < 3600:  # Within last hour
                                    suggestion.is_displayed = True

                        session.add(suggestion)

                session.commit()
                return True

        except Exception as e:
            log("error", f"Failed to import suggestion history: {e}", exc_info=True)
            return False

    def get_admin_tabs(self, trainer_id: str) -> List[Tuple[str, Callable]]:
        """Add a suggestions analytics tab for teachers."""
        def render_analytics():
            st.subheader("📊 " + _("trainer_plugin_suggest.analytics"))

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
                col1.metric(_("trainer_plugin_suggest.total_active"), active)
                col2.metric(_("trainer_plugin_suggest.total_used"), used)
                col3.metric(_("trainer_plugin_suggest.total_dismissed"), dismissed)
                col4.metric("Displayed Now", displayed)

                st.subheader(_("trainer_plugin_suggest.per_student_breakdown"))

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
                                st.metric(_("trainer_plugin_suggest.engagement_rate"), f"{engagement:.1f}%")

        return [(_("trainer_plugin_suggest.analytics"), render_analytics)]

# Plugin entry point - must be named 'plugin'
plugin = SuggestPlugin
