"""
Suggest Plugin for Trainer Module.
Generates contextual suggestions for students based on their conversations.
Suggests questions or learning prompts at configurable intervals.

Migration status: COMPLETE
  - initialize() calls self._resolve_services(services)
  - Added legacy fallback for self.config when services=None
  - All data methods use self.db, self.user_manager, self.conversation_manager,
    self.llm_manager, self.config — no st_shared.cached imports elsewhere
  - All render methods call self.<data_method>() only — no db/cache access inline
  - When splitting into two classes: replace self.xxx() with self._logic.xxx()
    in every render method. No logic rewrite needed.
"""

from typing import List, Dict, Any, Optional, Tuple, Callable
from datetime import datetime, timedelta
import uuid
import json
import asyncio

from sqlalchemy import Column, String, Text, DateTime, JSON, Integer, Boolean, and_
from sqlalchemy.orm.attributes import flag_modified

from shared.common import get_prompt
from modules.trainer.plugin_base import PluginManifest
from modules.trainer.plugin_base_core import TrainerPluginCore
from shared.conversation import Message
from shared.common import llm_conversation_generate

from core.logging import log
from core.database import Base


# ============= DATABASE MODEL =============
class StudentSuggestionConfig(Base):
    """Store suggestion configuration per student."""
    __tablename__ = 'trainer_suggest_config'
    __table_args__ = {'extend_existing': True}

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id = Column(String(36), nullable=False, index=True)
    trainer_id = Column(String(36), nullable=False, index=True)
    message_interval = Column(Integer, default=5)  # Suggest every N messages
    is_enabled = Column(Boolean, default=True)
    last_suggestion_index = Column(Integer, default=0)  # Last message count when suggestion was made
    updated_at = Column(DateTime, default=datetime.utcnow)
    config_metadata = Column(JSON, default={})


class StudentSuggestion(Base):
    """Store generated suggestions for students."""
    __tablename__ = 'trainer_suggestions'
    __table_args__ = {'extend_existing': True}

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id = Column(String(36), nullable=False, index=True)
    trainer_id = Column(String(36), nullable=False, index=True)
    conversation_id = Column(String(36), nullable=True)  # Primary conversation that triggered this suggestion
    content = Column(Text, nullable=False)
    suggestion_type = Column(String(255), default="question")  # question, prompt, resource, etc.
    source = Column(String(255), default="auto")  # 'auto' or 'teacher'

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
    created_conversation_id = Column(String(36), nullable=True)  # Conversation created when suggestion was used
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



class SuggestPluginCore(TrainerPluginCore):

    def initialize(self, services=None) -> bool:
        """Initialize the plugin and ensure database tables exist."""
        try:
            self._resolve_services(services)

            # Legacy fallback: if config is still None, try to load it directly
            if self.config is None:
                try:
                    from st_shared.cached import get_config
                    self.config = get_config()
                    log("debug", "SuggestPlugin: loaded config from st_shared.cached fallback")
                except ImportError:
                    log("warning", "SuggestPlugin: no config available, using defaults")
                    self.config = {}

            if self.db and self.db.is_initialized() and not self.db._in_memory:
                # Create tables if they don't exist
                Base.metadata.create_all(self.db._engine, tables=[
                    StudentSuggestionConfig.__table__,
                    StudentSuggestion.__table__
                ], checkfirst=True)
                log("info", "Suggestion plugin tables created/verified")

            # Register for conversation callbacks
            self.conversation_manager.register_user_message_callback(self._on_user_message)
            log("info", "Suggest plugin registered for user message callbacks")

            return True
        except Exception as e:
            log("error", f"Failed to initialize suggestion plugin tables: {e}")
            return False

    def _on_user_message(self, conversation_id: str, messages: List[Message]) -> None:
        """
        Callback triggered when a user adds a message to a conversation.
        This is where we check if we should generate a new suggestion.
        """
        try:
            if not messages:
                return
            log("debug", "Received user message")

            # Get the conversation to find the student
            conversation = self.conversation_manager.get_conversation(conversation_id)
            if not conversation:
                return

            student_id = conversation.user_id

            # Get the student's trainer (parent)
            user = self.user_manager.get_user(student_id)

            if not user or not user.get('parent_id'):
                return

            trainer_id = user['parent_id']

            # Check if plugin is active for this trainer
            if self.trainer_manager is None:
                log("warning", "Suggest plugin callback called without trainer_manager")
                return
            if not self.trainer_manager.is_plugin_active(trainer_id, self.id):
                return

            # Get student configuration
            config = self._get_student_config(student_id, trainer_id)

            if not config or not config.get('is_enabled', True):
                return

            # Count user messages in this conversation
            user_message_count = sum(1 for msg in messages if msg.role == "user")
            last_index = config.get('last_suggestion_index', 0)
            interval = config.get('message_interval', 5)
            log("debug", f"User message count: {user_message_count}, last index: {last_index}, interval: {interval}")

            # Check if we should generate a new suggestion
            if user_message_count - last_index >= interval:
                # Create a new event loop for this thread
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                # Run the async generation synchronously
                loop.run_until_complete(
                    self._generate_suggestion_async(
                        student_id,
                        trainer_id,
                        conversation_id,
                        messages,
                        source="auto"
                    )
                )
                loop.close()
                log("debug", "Suggestion generated ...? ")

        except Exception as e:
            log("error", f"Error in suggestion callback: {e}", exc_info=True)

    async def _generate_suggestion_async(self, student_id: str, trainer_id: str,
                                        conversation_id: str, messages: List[Message],
                                        source: str = "auto") -> bool:
        """
        Generate a suggestion using LLM based on conversation context and training program.
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

            # Get training context from trainer manager
            if self.trainer_manager is None:
                log("warning", "Suggest plugin generating without trainer_manager")
                training_context = {}
            else:
                training_context = self.trainer_manager.get_all_contexts(student_id)

            # Format training context as a readable string
            context_parts = []
            for context_name, context_data in training_context.items():
                context_parts.append(f"\n=== {context_name} ===")
                if isinstance(context_data, dict):
                    for key, value in context_data.items():
                        context_parts.append(f"{key}: {value}")
                else:
                    context_parts.append(str(context_data))

            training_context_text = "\n".join(context_parts)

            # Get the suggestion prompt
            suggestion_prompt = get_prompt(
                'trainer.plugins.suggest.generate',
                """Based on the following conversation and training context, generate ONE helpful suggestion for the student.
                The suggestion should be a question, learning prompt, or resource recommendation that would help them progress
                within their training program.

                Conversation:
                {conversation}

                Training Context:
                {training_context}

                Generate a single, concise suggestion (max 100 characters) that is specific to the student's current conversation
                and aligned with their training context. Be specific and helpful.
                Suggestion:"""
            )

            prompt = suggestion_prompt.format(
                conversation=conversation_text,
                training_context=training_context_text
            )

            # Get current LLM ID
            from shared.common import get_current_llm_id
            try:
                llm_id = get_current_llm_id()
            except ValueError:
                log("error", "No LLM configured for suggestion generation")
                return False

            # Prepare messages for LLM (just the user prompt, no conversation history)
            messages_for_llm = [
                {"role": "system", "content": get_prompt('trainer.teacher.system_prompt')},
                {"role": "user", "content": prompt}
            ]

            # Call LLM directly using internal_response
            suggestion = await self.llm_manager.internal_response(
                llm_id=llm_id,
                messages=messages_for_llm,
                stream_callback=None  # No streaming needed for suggestions
            )

            if not suggestion or suggestion.startswith("Error"):
                log("warning", f"Failed to generate suggestion for student {student_id}: {suggestion}")
                return False

            # Clean up the suggestion
            suggestion = suggestion.strip().strip('"').strip("'")

            # Save the suggestion
            with self.db.get_session() as session:
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
                now = datetime.utcnow()

                # Initialize related_conversation_ids with the current conversation
                related_ids = [conversation_id] if conversation_id else []

                # Store the training context used for this suggestion in metadata
                suggestion_metadata = {
                    'trigger_message_count': len(messages) if source == "auto" else 0,
                    'conversation_id': conversation_id,
                    'teacher_id': trainer_id if source == "teacher" else None,
                    'training_context_used': list(training_context.keys())  # Store which contexts were used
                }

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
                    suggestion_metadata=suggestion_metadata,
                    interaction_history=[]  # Initialize empty list
                )

                # Add creation interaction
                suggestion_record.add_interaction('created', {
                    'source': source,
                    'conversation_id': conversation_id
                })

                session.add(suggestion_record)
                session.commit()

                log("debug", f"Generated {source} suggestion for student {student_id}: {suggestion[:50]}...")
                return True

        except Exception as e:
            log("error", f"Failed to generate suggestion: {e}", exc_info=True)
            return False

    def _get_student_config(self, student_id: str, trainer_id: str) -> Optional[Dict]:
        """Get suggestion configuration for a student."""
        with self.db.get_session() as session:
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
            with self.db.get_session() as session:
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
        with self.db.get_session() as session:
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
            with self.db.get_session() as session:
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
            with self.db.get_session() as session:
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
            with self.db.get_session() as session:
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

    def delete_suggestion_by_teacher(self, suggestion_id: str) -> bool:
        """Mark a suggestion as deleted by teacher."""
        try:
            with self.db.get_session() as session:
                suggestion = session.query(StudentSuggestion).filter_by(id=suggestion_id).first()
                if suggestion:
                    suggestion.add_interaction('deleted')
                    session.commit()  # Commit the delete interaction
                    return True
            return False
        except Exception as e:
            log("error", f"Failed to delete suggestion: {e}")
            return False

    def _get_suggestions_for_student(self, student_id: str, trainer_id: str, limit: int = 10) -> List[Dict]:
        """Get recent suggestions for a student."""
        with self.db.get_session() as session:
            suggestions = session.query(StudentSuggestion).filter_by(
                student_id=student_id,
                trainer_id=trainer_id
            ).order_by(StudentSuggestion.created_at.desc()).limit(limit).all()

            result = []
            for sugg in suggestions:
                result.append({
                    'id': sugg.id,
                    'content': sugg.content,
                    'type': sugg.suggestion_type,
                    'source': sugg.source,
                    'created_at': sugg.created_at,
                    'state': sugg.get_state(),
                    'is_displayed': sugg.is_displayed,
                    'is_clicked': sugg.is_clicked,
                    'is_dismissed': sugg.is_dismissed,
                    'is_deleted_by_teacher': sugg.is_deleted_by_teacher,
                    'created_conversation_id': sugg.created_conversation_id,
                    'related_conversation_ids': sugg.related_conversation_ids or [],
                    'interaction_history': sugg.interaction_history or [],
                    'viewed_at': sugg.viewed_at,
                    'used_at': sugg.used_at,
                    'dismissed_at': sugg.dismissed_at,
                    'deleted_at': sugg.deleted_at,
                    'expires_at': sugg.expires_at
                })
            return result

    def export_history(self, trainer_id: str, student_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Export suggestion history events with full interaction history."""
        events = []

        with self.db.get_session() as session:
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
