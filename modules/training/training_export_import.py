"""
Training Session Export/Import Module
=====================================

Provides functionality to export and import training sessions in YAML format.
Includes conversations, state updates, and master configuration.
"""

import yaml
import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict, field
from pathlib import Path

from shared.common import log, get_conversation_manager, get_user_manager, get_current_llm_id, llm_generate
from modules.training.training_logic import get_training_manager, StateHistoryEntry, StudentStatus
from modules.training.training_models import StudentStateHistoryTable, AnalyzedMessageTable


@dataclass
class TrainingExportEvent:
    """Base class for training export events."""
    event_type: str
    timestamp: str
    metadata: Dict[str, Any]


@dataclass
class ConversationStartEvent(TrainingExportEvent):
    """Event for when a conversation starts."""
    conversation_id: str
    title: str
    system_prompt: Optional[str] = None
    llm_config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class UserMessageEvent(TrainingExportEvent):
    """Event for user messages."""
    conversation_id: str
    message_id: str
    role: str
    content: str
    llm_id: Optional[str] = None
    state_history_id: Optional[str] = None
    # metadata is inherited from parent


@dataclass
class LLMResponseEvent(TrainingExportEvent):
    """Event for LLM responses."""
    conversation_id: str
    message_id: str
    role: str
    content: str
    llm_id: Optional[str] = None
    state_history_id: Optional[str] = None
    # metadata is inherited from parent


@dataclass
class StateUpdateEvent(TrainingExportEvent):
    """Event for state updates."""
    state_history_id: str
    previous_state: str
    new_state: str
    change_reason: str
    llm_id: Optional[str] = None
    analyzed_message_ids: List[str] = field(default_factory=list)
    analyzed_message_count: int = 0
    # metadata is inherited from parent


class TrainingSessionExporter:
    """Handles exporting training sessions to YAML format."""

    @staticmethod
    def export_training_session(master_id: str, student_id: str) -> Optional[str]:
        """
        Export a complete training session for a student.

        Args:
            master_id: Master user ID
            student_id: Student user ID

        Returns:
            YAML string or None if export failed
        """
        try:
            training_manager = get_training_manager()

            # Verify student belongs to master
            if not training_manager.is_student_of_master(master_id, student_id):
                log("error", f"Student {student_id} doesn't belong to master {master_id}")
                return None

            # Get master config
            master_config = training_manager.get_master_config(master_id)
            if not master_config:
                log("warning", f"No config found for master {master_id}")
                master_config = {}

            # Get student info
            student = get_user_manager().get_user(student_id)
            if not student:
                log("error", f"Student {student_id} not found")
                return None

            # Get state history
            state_history = training_manager.get_student_state_history(master_id, student_id, limit=1000)

            # Get all conversations for the student
            conv_manager = get_conversation_manager()
            conversations = conv_manager.get_user_conversations(student_id, include_inactive=True)

            # Collect all events in chronological order
            events = []

            # Track state-history to message mappings
            state_to_messages = {}
            analyzed_messages = {}

            # Build state to messages mapping
            for state_entry in state_history:
                state_id = state_entry.id
                # Get analyzed message IDs from metadata
                analyzed_ids = state_entry.metadata.get("analyzed_message_ids", [])
                if analyzed_ids:
                    state_to_messages[state_id] = analyzed_ids

            # Process each conversation
            for conv_data in conversations:
                conversation = conv_manager.get_conversation(conv_data["id"], include_messages=True)
                if not conversation:
                    continue

                # Add conversation start event FIRST
                conversation_start_event = ConversationStartEvent(
                    event_type="conversation_start",
                    conversation_id=conversation.id,
                    title=conversation.title,
                    system_prompt=conversation.system_prompt,
                    llm_config=conversation.llm_config or {},
                    timestamp=conversation.created_at.isoformat(),
                    metadata={"created_at": conversation.created_at.isoformat()}
                )
                events.append(conversation_start_event)

                # Process messages in this conversation
                for message in conversation.messages:
                    # Determine which state this message was analyzed under
                    state_history_id = None
                    for state_id, message_ids in state_to_messages.items():
                        # Create message key similar to training logic
                        message_key = f"{conversation.id}_{message.timestamp.timestamp() if message.timestamp else 0}"
                        if message_key in message_ids:
                            state_history_id = state_id
                            break

                    # Create message event
                    if message.role == "user":
                        event = UserMessageEvent(
                            event_type="user_message",
                            conversation_id=conversation.id,
                            message_id=f"{conversation.id}_{message.timestamp.timestamp() if message.timestamp else 0}",
                            content=message.content,
                            role=message.role,
                            timestamp=message.timestamp.isoformat() if message.timestamp else datetime.utcnow().isoformat(),
                            llm_id=None,  # User messages don't have llm_id
                            state_history_id=state_history_id,
                            metadata=message.metadata or {}
                        )
                    else:  # assistant/system
                        event = LLMResponseEvent(
                            event_type="llm_response",
                            conversation_id=conversation.id,
                            message_id=f"{conversation.id}_{message.timestamp.timestamp() if message.timestamp else 0}",
                            content=message.content,
                            role=message.role,
                            timestamp=message.timestamp.isoformat() if message.timestamp else datetime.utcnow().isoformat(),
                            llm_id=message.llm_id,
                            state_history_id=state_history_id,
                            metadata=message.metadata or {}
                        )

                    events.append(event)

            # Add state update events
            for state_entry in state_history:
                # Get analyzed message IDs from metadata
                analyzed_ids = state_entry.metadata.get("analyzed_message_ids", [])

                event = StateUpdateEvent(
                    event_type="state_update",
                    state_history_id=state_entry.id,
                    previous_state=state_entry.previous_state or "",
                    new_state=state_entry.new_state,
                    change_reason=state_entry.change_reason,
                    timestamp=state_entry.created_at.isoformat(),
                    llm_id=state_entry.llm_id,
                    analyzed_message_count=state_entry.analyzed_message_count,
                    analyzed_message_ids=analyzed_ids,
                    metadata=state_entry.metadata
                )
                events.append(event)

            # Sort all events by timestamp AND event type priority
            def get_event_priority(event):
                """Sort key to ensure proper event processing order."""
                if isinstance(event, ConversationStartEvent):
                    return 0
                elif isinstance(event, (UserMessageEvent, LLMResponseEvent)):
                    return 1
                elif isinstance(event, StateUpdateEvent):
                    return 2
                else:
                    return 3

            # Sort by timestamp first, then by priority
            events.sort(key=lambda x: (x.timestamp, get_event_priority(x)))

            # Prepare export data
            export_data = {
                "version": "1.0",
                "export_type": "training_session",
                "exported_at": datetime.utcnow().isoformat(),
                "export_metadata": {
                    "export_version": "1.0",
                    "system": "Training Module Export",
                    "original_master_id": master_id,
                    "original_student_id": student_id,
                    "event_count": len(events)
                },
                "master_config": {
                    "master_id": master_id,
                    "system_prompt": master_config.get("system_prompt", ""),
                    "learning_path": master_config.get("learning_path", ""),
                    "analyzer_prompt": master_config.get("analyzer_prompt", ""),
                    "merging_prompt": master_config.get("merging_prompt", ""),
                    "created_at": master_config.get("created_at", datetime.utcnow().isoformat()),
                    "updated_at": master_config.get("updated_at", datetime.utcnow().isoformat()),
                    "metadata": master_config.get("metadata", {})
                },
                "student_info": {
                    "student_id": student_id,
                    "student_name": student.get("name", "Unknown"),
                    "master_id": master_id,
                    "created_at": student.get("created_at", datetime.utcnow().isoformat())
                },
                "training_session": []
            }

            # Convert events to dictionaries
            for event in events:
                event_dict = asdict(event)

                # Remove empty/null values for readability
                event_dict = {k: v for k, v in event_dict.items()
                            if v not in (None, "", [], {}) and v is not None}

                # Remove metadata if empty
                if "metadata" in event_dict and not event_dict["metadata"]:
                    del event_dict["metadata"]

                export_data["training_session"].append(event_dict)

            # Convert to YAML
            yaml_data = yaml.dump(
                export_data,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
                indent=2
            )

            log("info", f"Exported training session for student {student_id} with {len(events)} events")
            return yaml_data

        except Exception as e:
            log("error", f"Failed to export training session: {e}", exc_info=True)
            return None

    @staticmethod
    def save_to_file(yaml_data: str, file_path: str) -> bool:
        """Save YAML data to file."""
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(yaml_data)
            log("info", f"Saved training export to {file_path}")
            return True
        except Exception as e:
            log("error", f"Failed to save training export: {e}")
            return False


class TrainingSessionProcessor:
    """Base class for processing training sessions chronologically."""

    def __init__(self, process_mode: str = "import"):
        """
        Initialize processor.

        Args:
            process_mode: "import" (preserve original) or "replay" (regenerate)
        """
        self.process_mode = process_mode
        self.training_manager = get_training_manager()
        self.conv_manager = get_conversation_manager()
        self.user_manager = get_user_manager()

    def _sort_events_chronologically(self, events: List[Dict]) -> List[Dict]:
        """Sort events in chronological order with proper dependencies."""
        def get_event_priority(event):
            event_type = event.get("event_type", "")
            if event_type == "conversation_start":
                return 0
            elif event_type == "user_message":
                return 1
            elif event_type == "llm_response":
                return 2
            elif event_type == "state_update":
                return 3
            else:
                return 4

        # Sort by timestamp then priority
        return sorted(events, key=lambda x: (
            x.get("timestamp", ""),
            get_event_priority(x)
        ))

    def _process_conversation_start(self, event: Dict, target_student_id: str) -> Optional[str]:
        """Process conversation start event."""
        conv_id = self.conv_manager.create_conversation(
            user_id=target_student_id,
            title=event.get("title", f"{self.process_mode.capitalize()} Conversation"),
            system_prompt=event.get("system_prompt"),
            llm_config=event.get("llm_config", {})
        )

        if conv_id:
            log("debug", f"Created conversation {conv_id} for {self.process_mode}")
            return conv_id

        return None

    def _process_user_message(self, event: Dict, conv_id: str) -> Dict[str, Any]:
        """Process user message event."""
        try:
            # Parse timestamp
            timestamp_str = event.get("timestamp")
            if timestamp_str:
                timestamp = datetime.fromisoformat(timestamp_str)
            else:
                timestamp = datetime.utcnow()

            from shared.common import Message

            message = Message(
                role="user",
                content=event.get("content", ""),
                timestamp=timestamp,
                llm_id=None,
                metadata={
                    **event.get("metadata", {}),
                    f"{self.process_mode}_original_id": event.get("message_id"),
                    f"{self.process_mode}_type": "original_user_message"
                }
            )

            message_id = self.conv_manager.add_message(conv_id, message)
            return {
                "success": True,
                "message": message,
                "message_key": f"{conv_id}_{timestamp.timestamp()}",
                "conversation_id": conv_id
            }

        except Exception as e:
            log("error", f"Failed to add user message: {e}")
            return {"success": False, "error": str(e)}

    async def _process_llm_response(self, event: Dict, conv_id: str,
                                   conversation_messages: List) -> Dict[str, Any]:
        """Process LLM response event."""
        try:
            if self.process_mode == "import":
                # Import mode: preserve original response
                return self._import_llm_response(event, conv_id)
            else:
                # Replay mode: regenerate with current LLM
                return await self._replay_llm_response(event, conv_id, conversation_messages)
        except Exception as e:
            log("error", f"Failed to process LLM response: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def _import_llm_response(self, event: Dict, conv_id: str) -> Dict[str, Any]:
        """Import original LLM response."""
        timestamp_str = event.get("timestamp")
        if timestamp_str:
            timestamp = datetime.fromisoformat(timestamp_str)
        else:
            timestamp = datetime.utcnow()

        from shared.common import Message

        message = Message(
            role=event.get("role", "assistant"),
            content=event.get("content", ""),
            timestamp=timestamp,
            llm_id=event.get("llm_id"),
            metadata={
                **event.get("metadata", {}),
                "import_original_id": event.get("message_id"),
                "import_type": "original_response"
            }
        )

        message_id = self.conv_manager.add_message(conv_id, message)
        return {
            "success": True,
            "message": message,
            "message_key": f"{conv_id}_{timestamp.timestamp()}",
            "conversation_id": conv_id,
            "regenerated": False
        }

    async def _replay_llm_response(self, event: Dict, conv_id: str,
                                  conversation_messages: List) -> Dict[str, Any]:
        """Replay LLM response with current LLM."""
        # Get conversation history up to this point
        messages_for_llm = [
            {"role": msg.role, "content": msg.content}
            for msg in conversation_messages
        ]

        # Get the last user message (which triggered this response)
        last_user_message = None
        for msg in reversed(conversation_messages):
            if msg.role == "user":
                last_user_message = msg.content
                break

        if not last_user_message:
            return {"success": False, "error": "No user message found to trigger response"}

        log("info", f"Regenerating LLM response for: {last_user_message[:50]}...")

        # Generate new response with current LLM
        new_response = await llm_generate(
            last_user_message,
            conversation_history=messages_for_llm
        )

        # Add regenerated response
        timestamp_str = event.get("timestamp")
        if timestamp_str:
            timestamp = datetime.fromisoformat(timestamp_str)
        else:
            timestamp = datetime.utcnow()

        from shared.common import Message

        response_message = Message(
            role="assistant",
            content=new_response,
            timestamp=timestamp,
            llm_id=get_current_llm_id(),
            metadata={
                **event.get("metadata", {}),
                "replay_original_id": event.get("message_id"),
                "replay_type": "regenerated_response",
                "original_content": event.get("content", "")[:500]
            }
        )

        message_id = self.conv_manager.add_message(conv_id, response_message)
        return {
            "success": True,
            "message": response_message,
            "message_key": f"{conv_id}_{timestamp.timestamp()}",
            "conversation_id": conv_id,
            "regenerated": True
        }

    async def _process_state_update(self, event: Dict, target_master_id: str,
                                  target_student_id: str, conversation_messages: Dict[str, List],
                                  current_state: str) -> Tuple[bool, str, int]:
        """Process state update event."""
        if self.process_mode == "import":
            return self._import_state_update(event, target_master_id, target_student_id)
        else:
            return await self._replay_state_update(event, target_master_id, target_student_id,
                                                  conversation_messages, current_state)

    def _import_state_update(self, event: Dict, target_master_id: str,
                           target_student_id: str) -> Tuple[bool, str, int]:
        """Import original state update."""
        try:
            with self.training_manager.db.get_session() as session:
                state_id = str(uuid.uuid4())

                # Parse timestamp
                timestamp_str = event.get("timestamp")
                if timestamp_str:
                    created_at = datetime.fromisoformat(timestamp_str)
                else:
                    created_at = datetime.utcnow()

                state_entry = StudentStateHistoryTable(
                    id=state_id,
                    master_id=target_master_id,
                    student_id=target_student_id,
                    previous_state=event.get("previous_state", ""),
                    new_state=event.get("new_state", ""),
                    change_reason=f"Imported: {event.get('change_reason', 'State update')}",
                    analyzed_message_count=event.get("analyzed_message_count", 0),
                    created_at=created_at,
                    llm_id=event.get("llm_id"),
                    history_metadata={
                        **event.get("metadata", {}),
                        "imported": True,
                        "original_state_id": event.get("state_history_id"),
                        "imported_at": datetime.utcnow().isoformat(),
                        "analyzed_message_ids": event.get("analyzed_message_ids", [])
                    }
                )
                session.add(state_entry)

                # No analyzed message records for import (we don't have the mapping)

                session.commit()
                log("info", f"Imported state update for {target_student_id}")
                return True, event.get("new_state", ""), 1

        except Exception as e:
            log("error", f"Failed to import state update: {e}", exc_info=True)
            return False, "", 0

    async def _replay_state_update(self, event: Dict, target_master_id: str,
                                 target_student_id: str, conversation_messages: Dict[str, List],
                                 current_state: str) -> Tuple[bool, str, int]:
        """Replay state update with current LLM."""
        # Collect all unanalyzed messages up to this point
        unanalyzed_messages = []
        analyzed_ids = event.get("analyzed_message_ids", [])

        for conv_id, messages in conversation_messages.items():
            for msg in messages:
                if msg.role == "user":
                    message_key = f"{conv_id}_{msg.timestamp.timestamp()}"

                    # Check if this message was analyzed in the original
                    original_msg_id = msg.metadata.get("replay_original_id", "")
                    if (original_msg_id in analyzed_ids or
                        message_key in analyzed_ids):
                        unanalyzed_messages.append({
                            "conversation_id": conv_id,
                            "message": msg.content,
                            "timestamp": msg.timestamp,
                            "role": msg.role,
                            "message_key": message_key
                        })

        if not unanalyzed_messages:
            log("warning", f"No messages to analyze for state update")
            return False, current_state, 0

        try:
            # Get master config for analyzer/merging prompts
            config = self.training_manager.get_master_config(target_master_id)

            # Prepare messages for analysis
            messages_text = "\n\n".join([
                f"[{msg['timestamp'].strftime('%Y-%m-%d %H:%M')}] Student: {msg['message']}"
                for msg in unanalyzed_messages
            ])

            # Use analyzer prompt from config or default
            from shared.common import get_prompt
            analyzer_prompt_to_use = ""
            if config and config.get("analyzer_prompt"):
                analyzer_prompt_to_use = config["analyzer_prompt"]
            else:
                analyzer_prompt_to_use = get_prompt("training.training.analyzer_prompt_default", "ERROR")

            # Create analysis prompt
            analysis_prompt_template = get_prompt(
                "training.training.analysis_prompt_template", "ERROR"
            )

            analysis_prompt = analysis_prompt_template.format(
                current_state=current_state,
                messages_text=messages_text,
                analyzer_instructions=analyzer_prompt_to_use
            )

            # Generate analysis with current LLM
            analysis_result = await llm_generate(analysis_prompt)

            # Use merging prompt
            merging_prompt_to_use = ""
            if config and config.get("merging_prompt"):
                merging_prompt_to_use = config["merging_prompt"]
            else:
                merging_prompt_to_use = get_prompt(
                    "training.training.merging_prompt_default",
                    "ERROR"
                )

            merging_prompt_template = get_prompt(
                "training.training.merging_prompt_template",
                "ERROR"
            )

            merging_prompt = merging_prompt_template.format(
                current_state=current_state,
                analysis_result=analysis_result,
                merging_instructions=merging_prompt_to_use
            )

            # Generate new state
            new_state = await llm_generate(merging_prompt)

            # Record state history entry
            with self.training_manager.db.get_session() as session:
                state_id = str(uuid.uuid4())

                # Parse timestamp
                timestamp_str = event.get("timestamp")
                if timestamp_str:
                    created_at = datetime.fromisoformat(timestamp_str)
                else:
                    created_at = datetime.utcnow()

                state_entry = StudentStateHistoryTable(
                    id=state_id,
                    master_id=target_master_id,
                    student_id=target_student_id,
                    previous_state=event.get("previous_state", ""),
                    new_state=new_state,
                    change_reason=f"Replay: {event.get('change_reason', 'State update')}",
                    analyzed_message_count=len(unanalyzed_messages),
                    created_at=created_at,
                    llm_id=get_current_llm_id(),
                    history_metadata={
                        **event.get("metadata", {}),
                        "replay_original_id": event.get("state_history_id"),
                        "replay_type": "regenerated_state",
                        "analysis_result": analysis_result[:500] if analysis_result else "",
                        "original_state": event.get("new_state", "")[:500],
                        "analyzed_message_ids": [msg["message_key"] for msg in unanalyzed_messages]
                    }
                )
                session.add(state_entry)

                # Create analyzed message records
                for msg in unanalyzed_messages:
                    analyzed_msg = AnalyzedMessageTable(
                        id=str(uuid.uuid4()),
                        student_id=target_student_id,
                        message_id=msg["message_key"],
                        conversation_id=msg["conversation_id"],
                        analyzed_at=created_at,
                        analysis_summary=analysis_result[:500] if analysis_result else "",
                        state_history_id=state_id,
                        message_metadata={
                            **msg,
                            "replay_original_id": msg.get("message_key"),
                            "replay_type": "regenerated_analysis"
                        }
                    )
                    session.add(analyzed_msg)

                session.commit()
                log("info", f"Regenerated state update with {len(unanalyzed_messages)} messages")
                return True, new_state, 1

        except Exception as e:
            log("error", f"Failed to regenerate state update: {e}", exc_info=True)
            return False, current_state, 0


class BaseTrainingSessionProcessor:
    """Base class for processing training sessions chronologically."""

    @staticmethod
    def load_from_file(file_path: str) -> Optional[str]:
        """Load YAML data from file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            log("error", f"Failed to load file {file_path}: {e}")
            return None

    def _sort_events_chronologically(self, events: List[Dict]) -> List[Dict]:
        """Sort events in chronological order with proper dependencies."""
        def get_event_priority(event):
            event_type = event.get("event_type", "")
            if event_type == "conversation_start":
                return 0
            elif event_type == "user_message":
                return 1
            elif event_type == "llm_response":
                return 2
            elif event_type == "state_update":
                return 3
            else:
                return 4

        # Sort by timestamp then priority
        return sorted(events, key=lambda x: (
            x.get("timestamp", ""),
            get_event_priority(x)
        ))

    def _process_conversation_start(self, event: Dict, target_student_id: str) -> Optional[str]:
        """Process conversation start event."""
        conv_manager = get_conversation_manager()
        conv_id = conv_manager.create_conversation(
            user_id=target_student_id,
            title=event.get("title", "Processed Conversation"),
            system_prompt=event.get("system_prompt"),
            llm_config=event.get("llm_config", {})
        )

        if conv_id:
            log("debug", f"Created conversation {conv_id}")
            return conv_id

        return None

    def _process_user_message(self, event: Dict, conv_id: str, process_mode: str) -> Dict[str, Any]:
        """Process user message event."""
        try:
            # Parse timestamp
            timestamp_str = event.get("timestamp")
            if timestamp_str:
                timestamp = datetime.fromisoformat(timestamp_str)
            else:
                timestamp = datetime.utcnow()

            from shared.common import Message

            message = Message(
                role="user",
                content=event.get("content", ""),
                timestamp=timestamp,
                llm_id=None,
                metadata={
                    **event.get("metadata", {}),
                    f"{process_mode}_original_id": event.get("message_id"),
                    f"{process_mode}_type": "original_user_message"
                }
            )

            conv_manager = get_conversation_manager()
            message_id = conv_manager.add_message(conv_id, message)
            return {
                "success": True,
                "message": message,
                "message_key": f"{conv_id}_{timestamp.timestamp()}",
                "conversation_id": conv_id
            }

        except Exception as e:
            log("error", f"Failed to add user message: {e}")
            return {"success": False, "error": str(e)}

    async def _process_llm_response(self, event: Dict, conv_id: str,
                                   conversation_messages: List, process_mode: str) -> Dict[str, Any]:
        """Process LLM response event."""
        try:
            if process_mode == "import":
                # Import mode: preserve original response
                return self._import_llm_response(event, conv_id)
            else:
                # Replay mode: regenerate with current LLM
                return await self._replay_llm_response(event, conv_id, conversation_messages)
        except Exception as e:
            log("error", f"Failed to process LLM response: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def _import_llm_response(self, event: Dict, conv_id: str) -> Dict[str, Any]:
        """Import original LLM response."""
        timestamp_str = event.get("timestamp")
        if timestamp_str:
            timestamp = datetime.fromisoformat(timestamp_str)
        else:
            timestamp = datetime.utcnow()

        from shared.common import Message

        message = Message(
            role=event.get("role", "assistant"),
            content=event.get("content", ""),
            timestamp=timestamp,
            llm_id=event.get("llm_id"),
            metadata={
                **event.get("metadata", {}),
                "import_original_id": event.get("message_id"),
                "import_type": "original_response"
            }
        )

        conv_manager = get_conversation_manager()
        message_id = conv_manager.add_message(conv_id, message)
        return {
            "success": True,
            "message": message,
            "message_key": f"{conv_id}_{timestamp.timestamp()}",
            "conversation_id": conv_id,
            "regenerated": False
        }

    async def _replay_llm_response(self, event: Dict, conv_id: str,
                                  conversation_messages: List) -> Dict[str, Any]:
        """Replay LLM response with current LLM."""
        # Get conversation history up to this point
        messages_for_llm = [
            {"role": msg.role, "content": msg.content}
            for msg in conversation_messages
        ]

        # Get the last user message (which triggered this response)
        last_user_message = None
        for msg in reversed(conversation_messages):
            if msg.role == "user":
                last_user_message = msg.content
                break

        if not last_user_message:
            return {"success": False, "error": "No user message found to trigger response"}

        log("info", f"Regenerating LLM response for: {last_user_message[:50]}...")

        # Generate new response with current LLM
        new_response = await llm_generate(
            last_user_message,
            conversation_history=messages_for_llm
        )

        # Add regenerated response
        timestamp_str = event.get("timestamp")
        if timestamp_str:
            timestamp = datetime.fromisoformat(timestamp_str)
        else:
            timestamp = datetime.utcnow()

        from shared.common import Message

        response_message = Message(
            role="assistant",
            content=new_response,
            timestamp=timestamp,
            llm_id=get_current_llm_id(),
            metadata={
                **event.get("metadata", {}),
                "replay_original_id": event.get("message_id"),
                "replay_type": "regenerated_response",
                "original_content": event.get("content", "")[:500]
            }
        )

        conv_manager = get_conversation_manager()
        message_id = conv_manager.add_message(conv_id, response_message)
        return {
            "success": True,
            "message": response_message,
            "message_key": f"{conv_id}_{timestamp.timestamp()}",
            "conversation_id": conv_id,
            "regenerated": True
        }

    async def _process_state_update(self, event: Dict, target_master_id: str,
                                  target_student_id: str, conversation_messages: Dict[str, List],
                                  current_state: str, process_mode: str) -> Tuple[bool, str, int]:
        """Process state update event."""
        if process_mode == "import":
            return self._import_state_update(event, target_master_id, target_student_id)
        else:
            return await self._replay_state_update(event, target_master_id, target_student_id,
                                                  conversation_messages, current_state)

    def _import_state_update(self, event: Dict, target_master_id: str,
                           target_student_id: str) -> Tuple[bool, str, int]:
        """Import original state update."""
        try:
            training_manager = get_training_manager()

            with training_manager.db.get_session() as session:
                state_id = str(uuid.uuid4())

                # Parse timestamp
                timestamp_str = event.get("timestamp")
                if timestamp_str:
                    created_at = datetime.fromisoformat(timestamp_str)
                else:
                    created_at = datetime.utcnow()

                state_entry = StudentStateHistoryTable(
                    id=state_id,
                    master_id=target_master_id,
                    student_id=target_student_id,
                    previous_state=event.get("previous_state", ""),
                    new_state=event.get("new_state", ""),
                    change_reason=f"Imported: {event.get('change_reason', 'State update')}",
                    analyzed_message_count=event.get("analyzed_message_count", 0),
                    created_at=created_at,
                    llm_id=event.get("llm_id"),
                    history_metadata={
                        **event.get("metadata", {}),
                        "imported": True,
                        "original_state_id": event.get("state_history_id"),
                        "imported_at": datetime.utcnow().isoformat(),
                        "analyzed_message_ids": event.get("analyzed_message_ids", [])
                    }
                )
                session.add(state_entry)
                session.commit()

                log("info", f"Imported state update for {target_student_id}")
                return True, event.get("new_state", ""), 1

        except Exception as e:
            log("error", f"Failed to import state update: {e}", exc_info=True)
            return False, "", 0

    async def _replay_state_update(self, event: Dict, target_master_id: str,
                                 target_student_id: str, conversation_messages: Dict[str, List],
                                 current_state: str) -> Tuple[bool, str, int]:
        """Replay state update with current LLM."""
        # Collect all unanalyzed messages up to this point
        unanalyzed_messages = []
        analyzed_ids = event.get("analyzed_message_ids", [])

        for conv_id, messages in conversation_messages.items():
            for msg in messages:
                if msg.role == "user":
                    message_key = f"{conv_id}_{msg.timestamp.timestamp()}"

                    # Check if this message was analyzed in the original
                    original_msg_id = msg.metadata.get("replay_original_id", "")
                    if (original_msg_id in analyzed_ids or
                        message_key in analyzed_ids):
                        unanalyzed_messages.append({
                            "conversation_id": conv_id,
                            "message": msg.content,
                            "timestamp": msg.timestamp,
                            "role": msg.role,
                            "message_key": message_key
                        })

        if not unanalyzed_messages:
            log("warning", f"No messages to analyze for state update")
            return False, current_state, 0

        try:
            training_manager = get_training_manager()

            # Get master config for analyzer/merging prompts
            config = training_manager.get_master_config(target_master_id)

            # Prepare messages for analysis
            messages_text = "\n\n".join([
                f"[{msg['timestamp'].strftime('%Y-%m-%d %H:%M')}] Student: {msg['message']}"
                for msg in unanalyzed_messages
            ])

            # Use analyzer prompt from config or default
            from shared.common import get_prompt
            analyzer_prompt_to_use = ""
            if config and config.get("analyzer_prompt"):
                analyzer_prompt_to_use = config["analyzer_prompt"]
            else:
                analyzer_prompt_to_use = get_prompt("training.training.analyzer_prompt_default", "ERROR")

            # Create analysis prompt
            analysis_prompt_template = get_prompt(
                "training.training.analysis_prompt_template", "ERROR"
            )

            analysis_prompt = analysis_prompt_template.format(
                current_state=current_state,
                messages_text=messages_text,
                analyzer_instructions=analyzer_prompt_to_use
            )

            # Generate analysis with current LLM
            analysis_result = await llm_generate(analysis_prompt)

            # Use merging prompt
            merging_prompt_to_use = ""
            if config and config.get("merging_prompt"):
                merging_prompt_to_use = config["merging_prompt"]
            else:
                merging_prompt_to_use = get_prompt(
                    "training.training.merging_prompt_default",
                    "ERROR"
                )

            merging_prompt_template = get_prompt(
                "training.training.merging_prompt_template",
                "ERROR"
            )

            merging_prompt = merging_prompt_template.format(
                current_state=current_state,
                analysis_result=analysis_result,
                merging_instructions=merging_prompt_to_use
            )

            # Generate new state
            new_state = await llm_generate(merging_prompt)

            # Record state history entry
            with training_manager.db.get_session() as session:
                state_id = str(uuid.uuid4())

                # Parse timestamp
                timestamp_str = event.get("timestamp")
                if timestamp_str:
                    created_at = datetime.fromisoformat(timestamp_str)
                else:
                    created_at = datetime.utcnow()

                state_entry = StudentStateHistoryTable(
                    id=state_id,
                    master_id=target_master_id,
                    student_id=target_student_id,
                    previous_state=event.get("previous_state", ""),
                    new_state=new_state,
                    change_reason=f"Replay: {event.get('change_reason', 'State update')}",
                    analyzed_message_count=len(unanalyzed_messages),
                    created_at=created_at,
                    llm_id=get_current_llm_id(),
                    history_metadata={
                        **event.get("metadata", {}),
                        "replay_original_id": event.get("state_history_id"),
                        "replay_type": "regenerated_state",
                        "analysis_result": analysis_result[:500] if analysis_result else "",
                        "original_state": event.get("new_state", "")[:500],
                        "analyzed_message_ids": [msg["message_key"] for msg in unanalyzed_messages]
                    }
                )
                session.add(state_entry)

                # Create analyzed message records
                for msg in unanalyzed_messages:
                    analyzed_msg = AnalyzedMessageTable(
                        id=str(uuid.uuid4()),
                        student_id=target_student_id,
                        message_id=msg["message_key"],
                        conversation_id=msg["conversation_id"],
                        analyzed_at=created_at,
                        analysis_summary=analysis_result[:500] if analysis_result else "",
                        state_history_id=state_id,
                        message_metadata={
                            **msg,
                            "replay_original_id": msg.get("message_key"),
                            "replay_type": "regenerated_analysis"
                        }
                    )
                    session.add(analyzed_msg)

                session.commit()
                log("info", f"Regenerated state update with {len(unanalyzed_messages)} messages")
                return True, new_state, 1

        except Exception as e:
            log("error", f"Failed to regenerate state update: {e}", exc_info=True)
            return False, current_state, 0


class TrainingSessionImporter(BaseTrainingSessionProcessor):
    """Handles importing training sessions from YAML format."""

    async def import_training_session(self, yaml_data: str, target_master_id: str,
                                    target_student_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Import a training session from YAML.

        Args:
            yaml_data: YAML string containing training session
            target_master_id: Master to import under
            target_student_id: Optional specific student ID to import to

        Returns:
            Dictionary with import results
        """
        try:
            # Parse YAML
            data = yaml.safe_load(yaml_data)

            if not data or data.get("export_type") != "training_session":
                return {"success": False, "error": "Invalid training session format"}

            # Get original student info
            original_student_info = data.get("student_info", {})
            original_master_id = data.get("master_config", {}).get("master_id")

            # Determine target student
            user_manager = get_user_manager()
            if not target_student_id:
                # Create new student for this master
                student_name = original_student_info.get("student_name", "Imported Student")
                base_name = student_name
                counter = 1

                while True:
                    existing = user_manager.get_user_by_name(student_name)
                    if not existing:
                        break
                    student_name = f"{base_name} ({counter})"
                    counter += 1

                # Create new student
                target_student_id = user_manager.create_user(
                    name=student_name,
                    role="NORMAL",
                    parent_id=target_master_id
                )

                if not target_student_id:
                    return {"success": False, "error": "Failed to create student"}

            # Import master config
            master_config = data.get("master_config", {})
            training_manager = get_training_manager()

            config_id = training_manager.save_master_config(
                target_master_id,
                master_config.get("system_prompt", ""),
                master_config.get("learning_path", ""),
                master_config.get("analyzer_prompt", ""),
                master_config.get("merging_prompt", "")
            )

            # Process events
            events = data.get("training_session", [])

            # Sort events chronologically
            events = self._sort_events_chronologically(events)

            # Track created conversations and messages
            conversations = {}
            conversation_messages = {}
            state_updates_processed = 0
            llm_responses_processed = 0

            # Process events in chronological order
            for event in events:
                event_type = event.get("event_type")

                if event_type == "conversation_start":
                    conv_id = self._process_conversation_start(event, target_student_id)
                    if conv_id:
                        conversations[event["conversation_id"]] = conv_id
                        conversation_messages[conv_id] = []

                elif event_type == "user_message":
                    original_conv_id = event.get("conversation_id")
                    conv_id = conversations.get(original_conv_id)

                    if conv_id:
                        result = self._process_user_message(event, conv_id, "import")
                        if result["success"]:
                            conversation_messages[conv_id].append(result["message"])

                elif event_type == "llm_response":
                    original_conv_id = event.get("conversation_id")
                    conv_id = conversations.get(original_conv_id)

                    if conv_id:
                        result = await self._process_llm_response(
                            event, conv_id, conversation_messages.get(conv_id, []), "import"
                        )
                        if result["success"]:
                            conversation_messages[conv_id].append(result["message"])
                            llm_responses_processed += 1

                elif event_type == "state_update":
                    success, new_state, count = await self._process_state_update(
                        event, target_master_id, target_student_id,
                        conversation_messages, "", "import"
                    )
                    if success:
                        state_updates_processed += 1

            return {
                "success": True,
                "master_id": target_master_id,
                "student_id": target_student_id,
                "student_name": original_student_info.get("student_name", "Imported Student"),
                "conversations_created": len(conversations),
                "llm_responses_imported": llm_responses_processed,
                "state_updates_imported": state_updates_processed,
                "events_processed": len(events)
            }

        except Exception as e:
            log("error", f"Failed to import training session: {e}", exc_info=True)
            return {"success": False, "error": str(e)}


class TrainingSessionReplayer(BaseTrainingSessionProcessor):
    """Handles replaying training sessions with current LLM."""

    async def replay_training_session(self, yaml_data: str, target_master_id: str,
                                    target_student_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Replay a training session using current LLM.

        Regenerates:
        1. LLM responses (assistant messages)
        2. State updates (analysis results)

        Args:
            yaml_data: YAML string containing training session
            target_master_id: Master to replay under
            target_student_id: Optional specific student ID to replay to

        Returns:
            Dictionary with replay results
        """
        try:
            # Parse YAML
            data = yaml.safe_load(yaml_data)

            if not data or data.get("export_type") != "training_session":
                return {"success": False, "error": "Invalid training session format"}

            # Get original student info
            original_student_info = data.get("student_info", {})
            original_master_id = data.get("master_config", {}).get("master_id")

            # Determine target student
            user_manager = get_user_manager()
            if not target_student_id:
                # Create new student for this master
                student_name = f"Replay: {original_student_info.get('student_name', 'Imported Student')}"
                base_name = student_name
                counter = 1

                while True:
                    existing = user_manager.get_user_by_name(student_name)
                    if not existing:
                        break
                    student_name = f"{base_name} ({counter})"
                    counter += 1

                # Create new student
                target_student_id = user_manager.create_user(
                    name=student_name,
                    role="NORMAL",
                    parent_id=target_master_id
                )

                if not target_student_id:
                    return {"success": False, "error": "Failed to create student"}

            # Import master config (for context)
            master_config = data.get("master_config", {})
            training_manager = get_training_manager()

            config_id = training_manager.save_master_config(
                target_master_id,
                master_config.get("system_prompt", ""),
                master_config.get("learning_path", ""),
                master_config.get("analyzer_prompt", ""),
                master_config.get("merging_prompt", "")
            )

            # Process events
            events = data.get("training_session", [])

            # Sort events chronologically
            events = self._sort_events_chronologically(events)

            # Initialize tracking structures
            conversations = {}
            conversation_messages = {}
            state_updates_processed = 0
            llm_responses_regenerated = 0
            current_state = ""

            # Replay events in chronological order
            for event in events:
                event_type = event.get("event_type")

                if event_type == "conversation_start":
                    conv_id = self._process_conversation_start(event, target_student_id)
                    if conv_id:
                        conversations[event["conversation_id"]] = conv_id
                        conversation_messages[conv_id] = []

                elif event_type == "user_message":
                    original_conv_id = event.get("conversation_id")
                    conv_id = conversations.get(original_conv_id)

                    if conv_id:
                        result = self._process_user_message(event, conv_id, "replay")
                        if result["success"]:
                            conversation_messages[conv_id].append(result["message"])

                elif event_type == "llm_response":
                    original_conv_id = event.get("conversation_id")
                    conv_id = conversations.get(original_conv_id)

                    if conv_id:
                        result = await self._process_llm_response(
                            event, conv_id, conversation_messages.get(conv_id, []), "replay"
                        )
                        if result["success"]:
                            conversation_messages[conv_id].append(result["message"])
                            if result.get("regenerated", False):
                                llm_responses_regenerated += 1

                elif event_type == "state_update":
                    success, new_state, count = await self._process_state_update(
                        event, target_master_id, target_student_id,
                        conversation_messages, current_state, "replay"
                    )
                    if success:
                        current_state = new_state
                        state_updates_processed += count

            return {
                "success": True,
                "master_id": target_master_id,
                "student_id": target_student_id,
                "student_name": f"Replay: {original_student_info.get('student_name', 'Imported Student')}",
                "conversations_created": len(conversations),
                "llm_responses_regenerated": llm_responses_regenerated,
                "state_updates_regenerated": state_updates_processed,
                "events_processed": len(events),
                "replay_type": "regenerated"
            }

        except Exception as e:
            log("error", f"Failed to replay training session: {e}", exc_info=True)
            return {"success": False, "error": str(e)}


# Global instances for easy access
training_exporter = TrainingSessionExporter()
training_importer = TrainingSessionImporter()
training_replayer = TrainingSessionReplayer()

def export_training_session_to_file(master_id: str, student_id: str, file_path: str) -> bool:
    """Convenience function to export training session to file."""
    yaml_data = training_exporter.export_training_session(master_id, student_id)
    if yaml_data:
        return training_exporter.save_to_file(yaml_data, file_path)
    return False


async def import_training_session_from_file(file_path: str, target_master_id: str,
                                          target_student_id: Optional[str] = None) -> Dict[str, Any]:
    """Convenience function to import training session from file."""
    yaml_data = training_importer.load_from_file(file_path)
    if yaml_data:
        return await training_importer.import_training_session(yaml_data, target_master_id, target_student_id)
    return {"success": False, "error": "Failed to load file"}


async def replay_training_session_from_file(file_path: str, target_master_id: str,
                                          target_student_id: Optional[str] = None) -> Dict[str, Any]:
    """Convenience function to replay training session from file."""
    yaml_data = training_importer.load_from_file(file_path)
    if yaml_data:
        return await training_replayer.replay_training_session(yaml_data, target_master_id, target_student_id)
    return {"success": False, "error": "Failed to load file"}
