"""
Conversation Export/Import Module
=================================

Provides functionality to export and import conversations in YAML format.
Supports both individual conversations and bulk operations.
"""

import yaml
import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path

from shared.common import _, log, get_conversation_manager, Message, get_user_manager
from shared.common import get_conversation_manager, get_user_manager
# Import the table models directly
from shared.conversation import ConversationTable, MessageTable


@dataclass
class ExportedMessage:
    """Message structure for export/import."""
    role: str
    content: str
    timestamp: str
    tokens: Optional[int] = None
    llm_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    @classmethod
    def from_message(cls, message: Message, llm_id: Optional[str] = None) -> 'ExportedMessage':
        """Convert a Message object to ExportedMessage."""
        return cls(
            role=message.role,
            content=message.content,
            timestamp=message.timestamp.isoformat() if message.timestamp else datetime.utcnow().isoformat(),
            tokens=message.tokens,
            llm_id=llm_id,
            metadata=message.metadata or {}
        )

    def to_message(self) -> Message:
        """Convert to Message object."""
        return Message(
            role=self.role,
            content=self.content,
            timestamp=datetime.fromisoformat(self.timestamp),
            tokens=self.tokens,
            metadata=self.metadata or {}
        )


@dataclass
class ExportedConversation:
    """Conversation structure for export/import."""
    id: str
    user_id: str
    title: str
    created_at: str
    updated_at: str
    is_active: bool
    metadata: Dict[str, Any]
    system_prompt: Optional[str]
    llm_config: Dict[str, Any]
    messages: List[ExportedMessage]

    @classmethod
    def from_conversation(cls, conversation_data: Dict[str, Any]) -> 'ExportedConversation':
        """Convert conversation data to ExportedConversation."""
        messages = []

        # Extract messages and include llm_id from conversation metadata
        for msg_data in conversation_data.get("messages", []):
            message = Message.from_dict(msg_data) if isinstance(msg_data, dict) else msg_data

            # Get llm_id from conversation metadata or message metadata
            llm_id = None
            if conversation_data.get("llm_config", {}).get("id"):
                llm_id = conversation_data["llm_config"]["id"]
            elif isinstance(msg_data, dict) and msg_data.get("metadata", {}).get("llm_id"):
                llm_id = msg_data["metadata"]["llm_id"]

            messages.append(ExportedMessage.from_message(message, llm_id))

        return cls(
            id=conversation_data["id"],
            user_id=conversation_data["user_id"],
            title=conversation_data["title"],
            created_at=conversation_data["created_at"],
            updated_at=conversation_data["updated_at"],
            is_active=conversation_data["is_active"],
            metadata=conversation_data.get("metadata", {}),
            system_prompt=conversation_data.get("system_prompt"),
            llm_config=conversation_data.get("llm_config", {}),
            messages=messages
        )


class ConversationExporter:
    """Handles exporting conversations to YAML format."""

    @staticmethod
    def export_single_conversation(conversation_id: str) -> Optional[str]:
        """
        Export a single conversation to YAML string.

        Args:
            conversation_id: ID of the conversation to export

        Returns:
            YAML string or None if conversation not found
        """
        try:
            manager = get_conversation_manager()
            conversation = manager.get_conversation(conversation_id, include_messages=True)

            if not conversation:
                log("error", f"Conversation {conversation_id} not found for export")
                return None

            # Convert to dictionary for YAML serialization
            export_data = conversation.to_dict()

            # Add export metadata
            export_data["_export_metadata"] = {
                "export_version": "1.0",
                "exported_at": datetime.utcnow().isoformat(),
                "export_type": "single_conversation",
                "source_conversation_id": conversation_id,
                "original_user_id": conversation.user_id
            }

            # Convert to YAML
            yaml_data = yaml.dump(
                export_data,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False
            )

            log("info", f"Exported conversation: {conversation.title} ({conversation_id})")
            return yaml_data

        except Exception as e:
            log("error", f"Failed to export conversation {conversation_id}: {e}", exc_info=True)
            return None

    @staticmethod
    def export_all_conversations(user_id: str) -> Optional[str]:
        """
        Export all conversations for a user to YAML string.

        Args:
            user_id: ID of the user

        Returns:
            YAML string or None if no conversations found
        """
        try:
            manager = get_conversation_manager()
            conversations_data = manager.get_user_conversations(user_id, include_inactive=True)

            if not conversations_data:
                log("info", f"No conversations found for user {user_id}")
                return None

            # Get full details for each conversation
            full_conversations = []
            for conv_data in conversations_data:
                conversation = manager.get_conversation(conv_data["id"], include_messages=True)
                if conversation:
                    full_conversations.append(conversation.to_dict())

            if not full_conversations:
                log("warning", f"No conversation details could be loaded for user {user_id}")
                return None

            # Prepare export data
            export_data = {
                "version": "1.0",
                "exported_at": datetime.utcnow().isoformat(),
                "user_id": user_id,
                "conversation_count": len(full_conversations),
                "conversations": full_conversations,
                "_export_metadata": {
                    "export_version": "1.0",
                    "exported_at": datetime.utcnow().isoformat(),
                    "export_type": "bulk_conversations",
                    "original_user_id": user_id
                }
            }

            # Convert to YAML
            yaml_data = yaml.dump(
                export_data,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False
            )

            log("info", f"Exported {len(full_conversations)} conversations for user {user_id}")
            return yaml_data

        except Exception as e:
            log("error", f"Failed to export conversations for user {user_id}: {e}", exc_info=True)
            return None

    @staticmethod
    def save_to_file(yaml_data: str, file_path: str) -> bool:
        """
        Save YAML data to file.

        Args:
            yaml_data: YAML string to save
            file_path: Path to save file

        Returns:
            True if successful, False otherwise
        """
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(yaml_data)
            log("info", f"Saved export to {file_path}")
            return True
        except Exception as e:
            log("error", f"Failed to save export to {file_path}: {e}")
            return False


class ConversationImporter:
    """Handles importing conversations from YAML format."""

    @staticmethod
    def import_conversation(yaml_data: str, target_user_id: str,
                           preserve_ids: bool = False) -> Optional[str]:
        """
        Import a conversation from YAML string.

        Args:
            yaml_data: YAML string containing conversation data
            target_user_id: User ID to import conversation for
            preserve_ids: Whether to preserve original conversation ID

        Returns:
            New conversation ID or None if import failed
        """
        try:
            # Parse YAML
            data = yaml.safe_load(yaml_data)

            # Check if this is a bulk export
            if "conversations" in data and isinstance(data["conversations"], list):
                log("warning", "Bulk export detected in single conversation import")
                return None

            # Import single conversation
            conversation_id = ConversationImporter._import_single_conversation(
                data, target_user_id, preserve_ids
            )

            return conversation_id

        except Exception as e:
            log("error", f"Failed to import conversation: {e}", exc_info=True)
            return None

    @staticmethod
    def import_bulk_conversations(yaml_data: str, target_user_id: str,
                                 preserve_ids: bool = False) -> List[str]:
        """
        Import multiple conversations from YAML string.

        Args:
            yaml_data: YAML string containing bulk conversation data
            target_user_id: User ID to import conversations for
            preserve_ids: Whether to preserve original conversation IDs

        Returns:
            List of new conversation IDs
        """
        try:
            # Parse YAML
            data = yaml.safe_load(yaml_data)

            imported_ids = []

            # Check if this is a bulk export
            if "conversations" in data and isinstance(data["conversations"], list):
                # Import each conversation
                for conv_data in data["conversations"]:
                    conv_id = ConversationImporter._import_single_conversation(
                        conv_data, target_user_id, preserve_ids
                    )
                    if conv_id:
                        imported_ids.append(conv_id)

                log("info", f"Imported {len(imported_ids)} conversations for user {target_user_id}")
                return imported_ids
            else:
                # Single conversation
                conv_id = ConversationImporter._import_single_conversation(
                    data, target_user_id, preserve_ids
                )
                if conv_id:
                    imported_ids.append(conv_id)

                return imported_ids

        except Exception as e:
            log("error", f"Failed to import bulk conversations: {e}", exc_info=True)
            return []

    @staticmethod
    def _import_single_conversation(conv_data: Dict[str, Any], target_user_id: str,
                                   preserve_ids: bool = False) -> Optional[str]:
        """Internal method to import a single conversation."""
        try:
            manager = get_conversation_manager()

            # Generate new ID if not preserving
            original_id = conv_data.get("id")
            if preserve_ids and original_id:
                # Check if conversation ID already exists
                existing = manager.get_conversation(original_id, include_messages=False)
                if existing:
                    # Generate new ID to avoid conflict
                    new_id = str(uuid.uuid4())
                else:
                    new_id = original_id
            else:
                new_id = str(uuid.uuid4())

            # Create conversation
            conversation_id = manager.create_conversation(
                user_id=target_user_id,
                title=conv_data["title"],
                system_prompt=conv_data.get("system_prompt"),
                llm_config=conv_data.get("llm_config", {})
            )

            if not conversation_id:
                log("error", "Failed to create conversation during import")
                return None

            # Update conversation ID if we want to use a specific one
            if preserve_ids and original_id and original_id != conversation_id:
                # We need to update the conversation ID in the database
                with manager.db.get_session() as session:
                    # Get the newly created conversation
                    conv = session.query(ConversationTable).filter_by(id=conversation_id).first()
                    if conv:
                        # Update to the original ID
                        conv.id = original_id

                        # Update all related messages
                        session.query(MessageTable).filter_by(conversation_id=conversation_id).update(
                            {"conversation_id": original_id}
                        )

                        session.commit()
                        conversation_id = original_id

            # Add messages if present
            messages = conv_data.get("messages", [])
            for msg_data in messages:
                # Convert to Message object
                if isinstance(msg_data, dict):
                    # Handle exported format
                    if "llm_id" in msg_data and "metadata" not in msg_data:
                        msg_data["metadata"] = {"llm_id": msg_data["llm_id"]}

                    message = Message.from_dict(msg_data)
                else:
                    message = msg_data

                # Add message to conversation
                manager.add_message(conversation_id, message)

            # Update conversation metadata to include import info
            with manager.db.get_session() as session:
                conv = session.query(ConversationTable).filter_by(id=conversation_id).first()
                if conv:
                    metadata = conv.conv_metadata or {}
                    metadata["imported_from"] = original_id
                    metadata["imported_at"] = datetime.utcnow().isoformat()
                    conv.conv_metadata = metadata

            log("info", f"Imported conversation: {conv_data['title']} (ID: {conversation_id})")
            return conversation_id

        except Exception as e:
            log("error", f"Failed to import single conversation: {e}", exc_info=True)
            return None

    @staticmethod
    def load_from_file(file_path: str) -> Optional[str]:
        """
        Load YAML data from file.

        Args:
            file_path: Path to YAML file

        Returns:
            YAML string or None if file not found
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            log("error", f"Failed to load file {file_path}: {e}")
            return None


# Global instances for easy access
exporter = ConversationExporter()
importer = ConversationImporter()


def export_conversation_to_file(conversation_id: str, file_path: str) -> bool:
    """Convenience function to export conversation to file."""
    yaml_data = exporter.export_single_conversation(conversation_id)
    if yaml_data:
        return exporter.save_to_file(yaml_data, file_path)
    return False


def import_conversation_from_file(file_path: str, target_user_id: str) -> Optional[str]:
    """Convenience function to import conversation from file."""
    yaml_data = importer.load_from_file(file_path)
    if yaml_data:
        return importer.import_conversation(yaml_data, target_user_id)
    return None


def export_all_conversations_to_file(user_id: str, file_path: str) -> bool:
    """Convenience function to export all conversations to file."""
    yaml_data = exporter.export_all_conversations(user_id)
    if yaml_data:
        return exporter.save_to_file(yaml_data, file_path)
    return False


def import_bulk_conversations_from_file(file_path: str, target_user_id: str) -> List[str]:
    """Convenience function to import bulk conversations from file."""
    yaml_data = importer.load_from_file(file_path)
    if yaml_data:
        return importer.import_bulk_conversations(yaml_data, target_user_id)
    return []
