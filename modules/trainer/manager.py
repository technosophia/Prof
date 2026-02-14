"""
Trainer module business logic.
Manages students, notes, and plugin coordination.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
import yaml
import json
from shared.common import (
    get_db_manager, get_user_manager, get_conversation_manager,
    log, _
)


class TrainerManager:
    """Main manager for trainer functionality."""

    def __init__(self):
        self.db = get_db_manager()
        self.user_manager = get_user_manager()
        self.conversation_manager = get_conversation_manager()

    def get_trainer_students(self, trainer_id: str) -> List[Dict[str, Any]]:
        """Get all normal users that have this trainer as parent."""
        return self.user_manager.get_children(trainer_id)

    def get_student_conversation_count(self, trainer_id: str, student_id: str) -> int:
        """Get total number of conversations for a student."""
        conversations = self.conversation_manager.get_user_conversations(student_id)
        return len(conversations)

    def get_student_message_count(self, trainer_id: str, student_id: str) -> int:
        """Get total number of messages from a student."""
        conversations = self.conversation_manager.get_user_conversations(student_id)
        total_messages = 0

        for conv in conversations:
            full_conv = self.conversation_manager.get_conversation(conv["id"])
            if full_conv and full_conv.messages:
                user_messages = [msg for msg in full_conv.messages if msg.role == "user"]
                total_messages += len(user_messages)

        return total_messages

    def get_student_last_active(self, student_id: str) -> Optional[datetime]:
        """Get last activity time for a student."""
        conversations = self.conversation_manager.get_user_conversations(student_id)
        if conversations:
            last_conv = max(conversations, key=lambda x: x.get("updated_at", ""))
            updated_at = last_conv.get("updated_at")
            if updated_at:
                try:
                    return datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                except:
                    return None
        return None

    def export_configuration(self, trainer_id: str) -> str:
        """Export trainer and plugins configuration as YAML."""
        from .plugin_base import get_plugin_manager

        # Get the actual system prompt, not just the key
        from shared.common import get_prompt
        system_prompt = get_prompt('trainer.teacher.system_prompt')

        config = {
            'trainer': {
                'exported_at': datetime.utcnow().isoformat(),
                'trainer_id': trainer_id,
                'system_prompt': system_prompt,  # Export the actual prompt, not the key
            },
            'plugins': {}
        }

        plugin_manager = get_plugin_manager()
        for plugin in plugin_manager.get_active_plugins(trainer_id):
            plugin_config = plugin.export_config(trainer_id)
            if plugin_config:
                config['plugins'][plugin.id] = plugin_config

        return yaml.dump(config, default_flow_style=False, allow_unicode=True)

    def import_configuration(self, trainer_id: str, yaml_content: str) -> bool:
        """Import trainer and plugins configuration from YAML."""
        from .plugin_base import get_plugin_manager

        try:
            config = yaml.safe_load(yaml_content)

            plugin_manager = get_plugin_manager()
            for plugin_id, plugin_config in config.get('plugins', {}).items():
                plugin = plugin_manager.get_plugin(plugin_id)
                if plugin:
                    plugin.import_config(trainer_id, plugin_config)

            return True
        except Exception as e:
            log("error", f"Failed to import configuration: {e}", exc_info=True)
            return False

    def is_plugin_active(self, trainer_id: str, plugin_id: str) -> bool:
        """Check if a plugin is active for this trainer."""
        from .models import PluginActivation

        with self.db.get_session() as session:
            activation = session.query(PluginActivation).filter_by(
                trainer_id=trainer_id,
                plugin_id=plugin_id
            ).first()

            return activation.is_active if activation else False

    def export_history(self, trainer_id: str, student_id: Optional[str] = None) -> str:
        """
        Export complete history including configuration, conversations and plugin events.

        Args:
            trainer_id: The trainer's ID
            student_id: Optional student ID to filter history for a specific student

        Returns:
            YAML string containing configuration and chronologically sorted events
        """
        from .plugin_base import get_plugin_manager

        events = []

        # Get all students for this trainer
        if student_id:
            student = self.user_manager.get_user(student_id)
            if student and student.get('parent_id') == trainer_id:
                students = [student]
            else:
                log("error", f"Student {student_id} not found or not assigned to trainer {trainer_id}")
                students = []
        else:
            students = self.get_trainer_students(trainer_id)

        # Add conversation events for each student
        for student in students:
            if not student:
                continue

            conversations = self.conversation_manager.get_user_conversations(student['id'])

            for conv in conversations:
                full_conv = self.conversation_manager.get_conversation(conv["id"])
                if full_conv and full_conv.messages:
                    for msg in full_conv.messages:
                        event = {
                            'timestamp': msg.timestamp.isoformat() if msg.timestamp else datetime.utcnow().isoformat(),
                            'type': 'user_message' if msg.role == 'user' else 'assistant_message',
                            'student_id': student['id'],
                            'student_name': student.get('name', 'Unknown'),
                            'conversation_id': conv["id"],
                            'conversation_title': conv.get('title', 'Untitled'),
                            'content': msg.content,
                            'plugin_id': 'core.conversation'
                        }

                        # Add message metadata if available
                        if hasattr(msg, 'metadata') and msg.metadata:
                            event['metadata'] = msg.metadata
                        elif hasattr(msg, 'msg_metadata') and msg.msg_metadata:  # Fallback for backward compatibility
                            event['metadata'] = msg.msg_metadata

                        events.append(event)

        # Add plugin events
        plugin_manager = get_plugin_manager()
        active_plugins = plugin_manager.get_active_plugins(trainer_id)

        for plugin in active_plugins:
            plugin_events = plugin.export_history(trainer_id, student_id)
            if plugin_events:
                # Ensure each plugin event has required fields
                for event in plugin_events:
                    if 'timestamp' not in event:
                        event['timestamp'] = datetime.utcnow().isoformat()
                    if 'type' not in event:
                        event['type'] = f'plugin.{plugin.id}.event'
                    if 'plugin_id' not in event:
                        event['plugin_id'] = plugin.id
                events.extend(plugin_events)

        # Sort events chronologically
        events.sort(key=lambda x: x.get('timestamp', ''))

        # Get configuration export
        config_yaml = self.export_configuration(trainer_id)
        config_data = yaml.safe_load(config_yaml)

        # Build complete export structure with configuration as preamble
        export_data = {
            'exported_at': datetime.utcnow().isoformat(),
            'trainer_id': trainer_id,
            'student_id': student_id,
            'export_type': 'full_history_with_config',
            'version': '1.0',
            'configuration': config_data,  # Configuration as preamble
            'event_count': len(events),
            'events': events
        }

        return yaml.dump(export_data, default_flow_style=False, allow_unicode=True)

    def import_history(self, trainer_id: str, yaml_content: str) -> bool:
        """
        Import complete history including configuration and events.

        Args:
            trainer_id: The trainer's ID
            yaml_content: YAML string containing configuration and events to import

        Returns:
            True if import successful, False otherwise
        """
        from .plugin_base import get_plugin_manager

        try:
            config = yaml.safe_load(yaml_content)

            if not config:
                log("error", "Invalid history export: empty file")
                return False

            # Check if this is a full history export with configuration
            if 'configuration' in config:
                log("info", "Importing full history with configuration")

                # First import the configuration
                config_success = self.import_configuration(trainer_id, yaml.dump(config['configuration']))
                if not config_success:
                    log("warning", "Configuration import had issues, continuing with events")

                # Then import events
                events = config.get('events', [])
            else:
                # Legacy format - just events
                log("info", "Importing legacy history format (no configuration)")
                events = config.get('events', []) if 'events' in config else []

            # Group events by plugin for processing
            plugin_events = {}
            conversation_events = []

            for event in events:
                plugin_id = event.get('plugin_id', 'unknown')

                if plugin_id == 'core.conversation':
                    conversation_events.append(event)
                else:
                    if plugin_id not in plugin_events:
                        plugin_events[plugin_id] = []
                    plugin_events[plugin_id].append(event)

            # Process conversation events first
            if conversation_events:
                # Group by student and conversation
                student_conversations = {}
                for event in conversation_events:
                    student_id = event.get('student_id')
                    if not student_id:
                        continue

                    if student_id not in student_conversations:
                        student_conversations[student_id] = {}

                    conv_id = event.get('conversation_id')
                    if conv_id not in student_conversations[student_id]:
                        student_conversations[student_id][conv_id] = {
                            'title': event.get('conversation_title', 'Imported Conversation'),
                            'messages': []
                        }

                    # Add message to conversation
                    student_conversations[student_id][conv_id]['messages'].append({
                        'role': 'user' if event.get('type') == 'user_message' else 'assistant',
                        'content': event.get('content', ''),
                        'timestamp': event.get('timestamp'),
                        'metadata': event.get('metadata', {})
                    })

                # TODO: Implement conversation import in conversation_manager
                # For now, just log
                for student_id, conversations in student_conversations.items():
                    for conv_id, conv_data in conversations.items():
                        # Sort messages by timestamp
                        conv_data['messages'].sort(key=lambda x: x.get('timestamp', ''))
                        log("info", f"Would import conversation {conv_id} for student {student_id} with {len(conv_data['messages'])} messages")

            # Process plugin events
            plugin_manager = get_plugin_manager()
            for plugin_id, plugin_evts in plugin_events.items():
                plugin = plugin_manager.get_plugin(plugin_id)
                if plugin:
                    # Sort events chronologically for this plugin
                    plugin_evts.sort(key=lambda x: x.get('timestamp', ''))
                    if not plugin.import_history(trainer_id, plugin_evts):
                        log("warning", f"Plugin {plugin_id} failed to import some events")
                else:
                    log("warning", f"Plugin {plugin_id} not found, skipping {len(plugin_evts)} events")

            return True

        except Exception as e:
            log("error", f"Failed to import history: {e}", exc_info=True)
            return False


    def set_plugin_active(self, trainer_id: str, plugin_id: str,
                         active: bool) -> bool:
        """Activate or deactivate a plugin for this trainer."""
        from .models import PluginActivation

        try:
            with self.db.get_session() as session:
                activation = session.query(PluginActivation).filter_by(
                    trainer_id=trainer_id,
                    plugin_id=plugin_id
                ).first()

                if activation:
                    activation.is_active = active
                    activation.updated_at = datetime.utcnow()
                else:
                    activation = PluginActivation(
                        trainer_id=trainer_id,
                        plugin_id=plugin_id,
                        is_active=active
                    )
                    session.add(activation)
                session.commit()
                return True
        except Exception as e:
            log("error", f"Failed to set plugin activation: {e}", exc_info=True)
            return False


# Singleton instance
_trainer_manager = None


def get_trainer_manager():
    """Get the global TrainerManager instance."""
    global _trainer_manager
    if _trainer_manager is None:
        _trainer_manager = TrainerManager()
    return _trainer_manager
