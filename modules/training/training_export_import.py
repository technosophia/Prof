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

from shared.common import log, get_conversation_manager, get_user_manager
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
                """Give conversation_start events higher priority for sorting."""
                if isinstance(event, ConversationStartEvent):
                    return 0  # Highest priority - must come first
                elif isinstance(event, StateUpdateEvent):
                    return 2  # State updates should come after messages
                else:  # UserMessageEvent or LLMResponseEvent
                    return 1  # Messages medium priority

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


class TrainingSessionImporter:
    """Handles importing training sessions from YAML format."""

    @staticmethod
    def import_training_session(yaml_data: str, target_master_id: str,
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
            if not target_student_id:
                # Create new student for this master
                user_manager = get_user_manager()

                # Generate unique student name
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
                    username=f"imported_{uuid.uuid4().hex[:8]}",
                    password=uuid.uuid4().hex[:16],
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

            # IMPORTANT: DO NOT initialize student state here - we'll import the states from the file
            # This prevents creating a default "New student" state that overrides imported states
            log("info", f"Skipping default state initialization for imported student {target_student_id}")

            # Process events
            events = data.get("training_session", [])
            conv_manager = get_conversation_manager()

            # Track created conversations
            conversations = {}
            state_updates = []
            has_state_updates = False

            # First, check if we have state updates in the import
            for event in events:
                if event.get("event_type") == "state_update":
                    has_state_updates = True
                    break

            # If no state updates, we need to create at least one state entry
            # to mark the student as having an initialized state
            if not has_state_updates:
                log("info", "No state updates found in import, creating minimal state entry")
                with training_manager.db.get_session() as session:
                    state_id = str(uuid.uuid4())
                    minimal_state = StudentStateHistoryTable(
                        id=state_id,
                        master_id=target_master_id,
                        student_id=target_student_id,
                        previous_state=None,
                        new_state="Imported student - no learning state data available",
                        change_reason="Imported without state history",
                        analyzed_message_count=0,
                        created_at=datetime.utcnow(),
                        llm_id=None,
                        history_metadata={
                            "imported": True,
                            "import_type": "minimal_state",
                            "imported_at": datetime.utcnow().isoformat()
                        }
                    )
                    session.add(minimal_state)

            # First, ensure events are properly sorted for import
            # Priority: conversation_start > messages > state_update
            def event_sort_key(event):
                """Sort key to ensure proper event processing order."""
                event_type = event.get("event_type", "")
                timestamp = event.get("timestamp", "")

                if event_type == "conversation_start":
                    priority = 0
                elif event_type in ["user_message", "llm_response"]:
                    priority = 1
                elif event_type == "state_update":
                    priority = 2
                else:
                    priority = 3

                return (priority, timestamp)

            # Sort events for proper import order
            events.sort(key=event_sort_key)

            # Process events in order
            for event in events:
                event_type = event.get("event_type")

                if event_type == "conversation_start":
                    # Create conversation
                    conv_id = conv_manager.create_conversation(
                        user_id=target_student_id,
                        title=event.get("title", "Imported Conversation"),
                        system_prompt=event.get("system_prompt"),
                        llm_config=event.get("llm_config", {})
                    )

                    if conv_id:
                        conversations[event["conversation_id"]] = conv_id
                        log("debug", f"Created conversation {conv_id} for import")

                elif event_type in ["user_message", "llm_response"]:
                    # Add message to conversation
                    original_conv_id = event.get("conversation_id")
                    conv_id = conversations.get(original_conv_id)

                    if conv_id:
                        from shared.common import Message

                        try:
                            # Parse timestamp
                            timestamp_str = event.get("timestamp")
                            if timestamp_str:
                                timestamp = datetime.fromisoformat(timestamp_str)
                            else:
                                timestamp = datetime.utcnow()

                            message = Message(
                                role=event.get("role", "user"),
                                content=event.get("content", ""),
                                timestamp=timestamp,
                                llm_id=event.get("llm_id"),
                                metadata=event.get("metadata", {})
                            )

                            message_id = conv_manager.add_message(conv_id, message)
                            log("debug", f"Added message to conversation {conv_id}: {message.role[:20]}...")

                        except Exception as e:
                            log("error", f"Failed to add message: {e}")
                    else:
                        log("warning", f"Conversation {original_conv_id} not found for message: {event.get('content', '')[:50]}...")

                elif event_type == "state_update":
                    # Store state update for later processing
                    state_updates.append(event)

            # Process state updates after all messages are imported
            state_updates_processed = 0
            for state_event in state_updates:
                try:
                    # Create state history entry
                    with training_manager.db.get_session() as session:
                        state_id = str(uuid.uuid4())

                        # Map analyzed message IDs to new conversation IDs
                        analyzed_message_ids = []
                        original_analyzed_ids = state_event.get("analyzed_message_ids", [])

                        for msg_id in original_analyzed_ids:
                            # Extract original conversation ID from message ID
                            parts = msg_id.split("_")
                            if len(parts) >= 2:
                                orig_conv_id = parts[0]
                                new_conv_id = conversations.get(orig_conv_id)
                                if new_conv_id:
                                    # Reconstruct message ID with new conversation ID
                                    new_msg_id = f"{new_conv_id}_{'_'.join(parts[1:])}"
                                    analyzed_message_ids.append(new_msg_id)
                                else:
                                    # Keep original if no mapping found
                                    analyzed_message_ids.append(msg_id)
                                    log("warning", f"No conversation mapping found for original ID: {orig_conv_id}")

                        # Parse timestamp
                        timestamp_str = state_event.get("timestamp")
                        if timestamp_str:
                            created_at = datetime.fromisoformat(timestamp_str)
                        else:
                            created_at = datetime.utcnow()

                        state_entry = StudentStateHistoryTable(
                            id=state_id,
                            master_id=target_master_id,
                            student_id=target_student_id,
                            previous_state=state_event.get("previous_state", ""),
                            new_state=state_event.get("new_state", ""),
                            change_reason=state_event.get("change_reason", "Imported from export"),
                            analyzed_message_count=state_event.get("analyzed_message_count", 0),
                            created_at=created_at,
                            llm_id=state_event.get("llm_id"),
                            history_metadata={
                                **state_event.get("metadata", {}),
                                "imported": True,
                                "original_state_id": state_event.get("state_history_id"),
                                "imported_at": datetime.utcnow().isoformat(),
                                "analyzed_message_ids": analyzed_message_ids
                            }
                        )
                        session.add(state_entry)

                        # Create analyzed message records
                        for msg_id in analyzed_message_ids:
                            # Extract conversation ID from message ID
                            msg_parts = msg_id.split("_")
                            conv_id = msg_parts[0] if msg_parts else "unknown"

                            analyzed_msg = AnalyzedMessageTable(
                                id=str(uuid.uuid4()),
                                student_id=target_student_id,
                                message_id=msg_id,
                                conversation_id=conv_id,
                                analyzed_at=created_at,
                                analysis_summary=state_event.get("metadata", {}).get("analysis_result", "")[:500],
                                state_history_id=state_id,
                                message_metadata={
                                    "imported": True,
                                    "original_message_id": msg_id
                                }
                            )
                            session.add(analyzed_msg)

                        session.commit()
                        state_updates_processed += 1

                except Exception as e:
                    log("error", f"Failed to process state update: {e}", exc_info=True)

            return {
                "success": True,
                "master_id": target_master_id,
                "student_id": target_student_id,
                "student_name": original_student_info.get("student_name", "Imported Student"),
                "conversations_created": len(conversations),
                "state_updates_imported": state_updates_processed,
                "events_processed": len(events)
            }

        except Exception as e:
            log("error", f"Failed to import training session: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    @staticmethod
    def load_from_file(file_path: str) -> Optional[str]:
        """Load YAML data from file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            log("error", f"Failed to load file {file_path}: {e}")
            return None


# Global instances for easy access
training_exporter = TrainingSessionExporter()
training_importer = TrainingSessionImporter()


def export_training_session_to_file(master_id: str, student_id: str, file_path: str) -> bool:
    """Convenience function to export training session to file."""
    yaml_data = training_exporter.export_training_session(master_id, student_id)
    if yaml_data:
        return training_exporter.save_to_file(yaml_data, file_path)
    return False


def import_training_session_from_file(file_path: str, target_master_id: str,
                                     target_student_id: Optional[str] = None) -> Dict[str, Any]:
    """Convenience function to import training session from file."""
    yaml_data = training_importer.load_from_file(file_path)
    if yaml_data:
        return training_importer.import_training_session(yaml_data, target_master_id, target_student_id)
    return {"success": False, "error": "Failed to load file"}
