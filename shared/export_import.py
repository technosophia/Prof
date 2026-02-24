"""
Conversation Export/Import Module
=================================

Provides functionality to export and import conversations in YAML format.
Supports both individual conversations and bulk operations.
"""

import yaml
import json
import uuid
import os
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path

from shared.common import Message
from shared.cached import get_conversation_manager, get_user_manager
from shared.cached import get_conversation_manager, get_user_manager
# Import the table models directly
from shared.conversation import ConversationTable, MessageTable


from core.logging import log, set_module_level
from shared.cached import _
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
        # For backward compatibility, only include llm_id for assistant messages
        # and only if it's not None
        export_llm_id = None
        if message.role == "assistant":
            export_llm_id = llm_id or message.llm_id

        # Only include fields that have values (except role and content which are required)
        result_data = {
            "role": message.role,
            "content": message.content,
            "timestamp": message.timestamp.isoformat() if message.timestamp else datetime.utcnow().isoformat(),
        }

        if message.tokens is not None:
            result_data["tokens"] = message.tokens

        if export_llm_id:
            result_data["llm_id"] = export_llm_id

        if message.metadata:
            result_data["metadata"] = message.metadata

        return cls(**result_data)

    def to_message(self) -> Message:
        """Convert to Message object."""
        return Message(
            role=self.role,
            content=self.content,
            timestamp=datetime.fromisoformat(self.timestamp),
            tokens=self.tokens,
            llm_id=self.llm_id,
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

            # Clean up messages: remove null/empty fields
            for msg in export_data.get("messages", []):
                # Remove null values
                keys_to_remove = []
                for key, value in msg.items():
                    if value is None or (isinstance(value, dict) and not value):
                        keys_to_remove.append(key)

                for key in keys_to_remove:
                    msg.pop(key, None)

                # For user messages, remove llm_id entirely (it should be None)
                if msg.get("role") == "user" and "llm_id" in msg:
                    msg.pop("llm_id", None)

            # Add export metadata
            export_data["_export_metadata"] = {
                "export_version": "1.1",  # Updated version
                "exported_at": datetime.utcnow().isoformat(),
                "export_type": "single_conversation",
                "source_conversation_id": conversation_id,
                "original_user_id": conversation.user_id,
                "format": "minimal"  # Indicate we're using minimal format
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
            log("debug", f"Import conversation - data type: {type(data)}")

            # Check if this is a bulk export
            if isinstance(data, dict) and "conversations" in data:
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
            log("debug", f"Importing single conversation: {conv_data.get('title', 'Untitled')}")
            log("debug", f"Conversation data keys: {list(conv_data.keys())}")

            manager = get_conversation_manager()

            # Get llm_id from conversation config for backward compatibility
            conversation_llm_id = conv_data.get("llm_config", {}).get("id")
            log("debug", f"Conversation LLM ID from config: {conversation_llm_id}")

            # Prepare metadata for the new conversation
            import_metadata = {
                "imported": True,
                "imported_from": conv_data.get("id"),
                "imported_at": datetime.utcnow().isoformat(),
                "import_format": "v2_with_llm_id" if any(
                    msg.get("llm_id") for msg in conv_data.get("messages", [])
                    if isinstance(msg, dict) and msg.get("role") == "assistant"
                ) else "v1_legacy",
                "created_via": "import"  # Override the default "ui"
            }

            # Create conversation with metadata
            conversation_id = manager.create_conversation(
                user_id=target_user_id,
                title=conv_data["title"],
                system_prompt=conv_data.get("system_prompt"),
                llm_config=conv_data.get("llm_config", {}),
                metadata=import_metadata  # Pass metadata here
            )

            if not conversation_id:
                log("error", "Failed to create conversation during import")
                return None

            log("debug", f"Created conversation with ID: {conversation_id}")

            # Add messages if present
            messages = conv_data.get("messages", [])
            log("debug", f"Adding {len(messages)} messages to conversation")

            for i, msg_data in enumerate(messages):
                # Convert to Message object
                if isinstance(msg_data, dict):
                    log("debug", f"Processing message {i+1}: role={msg_data.get('role')}")

                    # Handle backward compatibility: if llm_id is missing for assistant messages,
                    # use the conversation's llm_config id
                    if msg_data.get("role") == "assistant" and "llm_id" not in msg_data:
                        msg_data["llm_id"] = conversation_llm_id
                        log("debug", f"Added LLM ID from conversation config: {conversation_llm_id}")

                    # Handle old export format where llm_id was in metadata
                    if msg_data.get("role") == "assistant" and not msg_data.get("llm_id"):
                        metadata = msg_data.get("metadata", {})
                        if metadata and metadata.get("llm_id"):
                            msg_data["llm_id"] = metadata["llm_id"]
                            # Remove from metadata to avoid duplication
                            if "metadata" in msg_data:
                                msg_data["metadata"].pop("llm_id", None)
                            log("debug", f"Extracted LLM ID from metadata: {msg_data['llm_id']}")

                    message = Message.from_dict(msg_data)
                else:
                    message = msg_data

                # Add message to conversation
                manager.add_message(conversation_id, message)

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
    log("debug", f"import_conversation_from_file called with: {file_path}, user: {target_user_id}")

    if not os.path.exists(file_path):
        log("error", f"File does not exist: {file_path}")
        return None

    yaml_data = importer.load_from_file(file_path)
    if not yaml_data:
        log("error", f"Failed to load YAML data from {file_path}")
        return None

    # Try as single conversation
    conv_id = importer.import_conversation(yaml_data, target_user_id, preserve_ids=False)
    if conv_id:
        log("info", f"Successfully imported as single conversation: {conv_id}")
        return conv_id

    # If that fails, try as bulk
    log("debug", "Single import failed, trying bulk import")
    imported_ids = importer.import_bulk_conversations(yaml_data, target_user_id, preserve_ids=False)

    if imported_ids:
        log("info", f"Successfully imported {len(imported_ids)} conversations via bulk import")
        return imported_ids[0]

    log("error", "Both single and bulk import attempts failed")
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

def auto_import_conversations_from_config(config: Optional[Dict[str, Any]] = None) -> Dict[str, int]:
    """
    Auto-import conversations from configured YAML files.
    Only runs if there are NO conversations in the database.
    Called during application startup after database and user manager are initialized.

    Args:
        config: Optional configuration dict. If not provided, loads from get_config()

    Returns:
        Dict with counts of imported, skipped, and error conversations
    """

    from shared.cached import get_config
    from shared.users import get_user_manager
    from shared.conversation import get_conversation_manager
    import os

    if config is None:
        config = get_config()

    db_config = config.get("database", {})
    auto_import_config = db_config.get("auto_import_conversations", {})

    if not auto_import_config.get("enabled", False):
        log("debug", "Auto-import conversations is disabled")
        return {"imported": 0, "skipped": 0, "errors": 0}

    files_config = auto_import_config.get("files", [])
    if not files_config:
        log("debug", "No conversation files configured for auto-import")
        return {"imported": 0, "skipped": 0, "errors": 0}

    # Check if there are ANY conversations in the database
    conversation_manager = get_conversation_manager()
    with conversation_manager.db.get_session() as session:
        from shared.conversation import ConversationTable
        conversation_count = session.query(ConversationTable).count()

        if conversation_count > 0:
            log("debug", f"Database already has {conversation_count} conversations, skipping auto-import")
            return {"imported": 0, "skipped": 0, "errors": 0}

    log("info", "No conversations found in database, proceeding with auto-import")

    user_manager = get_user_manager()
    imported_count = 0
    error_count = 0

    for file_config in files_config:
        file_path = file_config.get("file")
        user_id = file_config.get("user_id")
        description = file_config.get("description", "Unnamed conversation")

        log("info", f"Processing auto-import: file={file_path}, user={user_id}")

        if not file_path or not user_id:
            log("warning", f"Skipping auto-import: missing file or user_id in config: {file_config}")
            error_count += 1
            continue

        # Check if file exists
        if not os.path.exists(file_path):
            log("warning", f"Auto-import conversation file not found: {file_path}")
            error_count += 1
            continue

        # Check if user exists
        user = user_manager.get_user(user_id)
        if not user:
            log("warning", f"Auto-import: user {user_id} not found, skipping conversation: {file_path}")
            error_count += 1
            continue

        # Import the conversation
        try:
            log("info", f"Auto-importing conversation from {file_path} for user {user_id}: {description}")

            from shared.export_import import import_conversation_from_file
            conv_id = import_conversation_from_file(file_path, user_id)

            if conv_id:
                imported_count += 1
                log("info", f"Successfully auto-imported conversation {conv_id} from {file_path}")
            else:
                log("error", f"Failed to import conversation from {file_path}")
                error_count += 1

        except Exception as e:
            log("error", f"Error auto-importing conversation from {file_path}: {e}", exc_info=True)
            error_count += 1

    log("info", f"Auto-import conversations completed: {imported_count} imported, {error_count} errors")
    return {
        "imported": imported_count,
        "errors": error_count
    }
