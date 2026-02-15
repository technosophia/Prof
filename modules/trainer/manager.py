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
    log, _, get_prompt
)
from modules.trainer.plugin_base import get_plugin_manager


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

    def get_all_contexts(self, student_id: str) -> Dict[str, Dict[str, str]]:
        """
        Get all context information for a student from all active plugins.

        This method aggregates context from all active plugins for the trainer
        who owns this student, and includes the training program at the top.

        Args:
            student_id: The student's ID

        Returns:
            Dictionary with plugin IDs as keys and their context dictionaries as values,
            plus a special 'training_program' key at the top.
        """
        # Get the student's trainer (parent)
        student = self.user_manager.get_user(student_id)
        if not student:
            log("error", f"Student {student_id} not found")
            return {}

        trainer_id = student.get('parent_id')
        if not trainer_id:
            log("error", f"Student {student_id} has no trainer assigned")
            return {}

        # Start with training program context
        contexts = {
            'Training Program': {
                'Training Program': get_prompt('trainer.teacher.training_program')
            }
        }

        # Get all active plugins for this trainer
        plugin_manager = get_plugin_manager()
        active_plugins = plugin_manager.get_active_plugins(trainer_id)

        # Collect context from each plugin
        for plugin in active_plugins:
            plugin_context = plugin.get_context(student_id)
            if plugin_context:  # Only add if plugin returned non-empty context
                contexts[plugin.manifest.name] = plugin_context

        return contexts

    def export_configuration(self, trainer_id: str) -> str:
        """Export trainer and plugins configuration as YAML."""
        from .plugin_base import get_plugin_manager

        # Get the actual system prompt, not just the key
        system_prompt = get_prompt('trainer.teacher.system_prompt')

        config = {
            'trainer': {
                'exported_at': datetime.utcnow().isoformat(),
                'trainer_id': trainer_id,
                'system_prompt': system_prompt,  # Export the actual prompt, not the key
                'training_program': get_prompt('trainer.teacher.training_program'),
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

            # Import training program if present
            trainer_config = config.get('trainer', {})

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
        Uses concise format with student info in preamble and minimal events.
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

        # Build student info map for the preamble
        student_info = {}
        for student in students:
            if student:
                student_info[student['id']] = {
                    'name': student.get('name', 'Unknown'),
                    'email': student.get('email', '')
                }

        # Add conversation events for each student
        for student in students:
            if not student:
                continue

            conversations = self.conversation_manager.get_user_conversations(student['id'])

            for conv in conversations:
                full_conv = self.conversation_manager.get_conversation(conv["id"])
                if full_conv and full_conv.messages:
                    for msg in full_conv.messages:
                        # Minimal event - only essential fields
                        event = {
                            'timestamp': msg.timestamp.isoformat() if msg.timestamp else datetime.utcnow().isoformat(),
                            'type': 'user_message' if msg.role == 'user' else 'assistant_message',
                            'conversation_id': conv["id"],
                            'content': msg.content,
                        }

                        # Only add conversation title if it's not the default
                        if conv.get('title') and conv.get('title') != 'Untitled' and conv.get('title') != 'New Conversation':
                            event['conversation_title'] = conv['title']

                        # Only add message metadata if present
                        if hasattr(msg, 'metadata') and msg.metadata:
                            event['metadata'] = msg.metadata
                        elif hasattr(msg, 'msg_metadata') and msg.msg_metadata:
                            event['metadata'] = msg.msg_metadata

                        events.append(event)

        # Add plugin events
        plugin_manager = get_plugin_manager()
        active_plugins = plugin_manager.get_active_plugins(trainer_id)

        for plugin in active_plugins:
            plugin_events = plugin.export_history(trainer_id, student_id)
            if plugin_events:
                events.extend(plugin_events)

        # Sort events chronologically
        events.sort(key=lambda x: x.get('timestamp', ''))

        # Get configuration export
        config_yaml = self.export_configuration(trainer_id)
        config_data = yaml.safe_load(config_yaml)

        # Build complete export structure with student info in preamble
        export_data = {
            'exported_at': datetime.utcnow().isoformat(),
            'trainer_id': trainer_id,
            'student_id': student_id,
            'export_type': 'full_history_with_config',
            'version': '2.0',  # New version for concise format
            'configuration': config_data,
            'students': student_info,  # Student info in preamble
            'event_count': len(events),
            'events': events
        }

        import re
        yaml_str = yaml.dump(export_data, default_flow_style=False, allow_unicode=True, sort_keys=False)

        # Add empty lines between events for readability
        yaml_str = re.sub(r'^(- )', r'\n\1', yaml_str, flags=re.MULTILINE)
        # Remove the first extra newline
        yaml_str = yaml_str.lstrip('\n')

        return yaml_str

    def import_history(self, trainer_id: str, yaml_content: str) -> bool:
        """
        Import complete history including configuration and events.
        Handles both legacy and v2 concise formats.
        """
        from .plugin_base import get_plugin_manager

        try:
            config = yaml.safe_load(yaml_content)

            if not config:
                log("error", "Invalid history export: empty file")
                return False

            # Check export version
            export_version = config.get('version', '1.0')
            student_info = config.get('students', {})

            # Check if this is a full history export with configuration
            if 'configuration' in config:
                log("info", f"Importing full history with configuration (version {export_version})")

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

            # For v2 format, we need to reconstruct the full event data
            if export_version == '2.0' and student_info:
                events = self._expand_minimal_events(events, student_info)

            # Group events by plugin for processing
            plugin_events = {}
            conversation_events = []

            for event in events:
                plugin_id = event.get('plugin_id', 'core.conversation')

                if plugin_id == 'core.conversation':
                    conversation_events.append(event)
                else:
                    if plugin_id not in plugin_events:
                        plugin_events[plugin_id] = []
                    plugin_events[plugin_id].append(event)

            # Process conversation events
            if conversation_events:
                # Group by conversation
                conversations = {}
                for event in conversation_events:
                    conv_id = event.get('conversation_id')
                    if not conv_id:
                        continue

                    if conv_id not in conversations:
                        conversations[conv_id] = {
                            'title': event.get('conversation_title', 'Imported Conversation'),
                            'student_id': event.get('student_id'),
                            'messages': []
                        }

                    # Add message to conversation
                    conversations[conv_id]['messages'].append({
                        'role': 'user' if event.get('type') == 'user_message' else 'assistant',
                        'content': event.get('content', ''),
                        'timestamp': event.get('timestamp'),
                        'metadata': event.get('metadata', {})
                    })

                # TODO: Implement conversation import
                for conv_id, conv_data in conversations.items():
                    # Sort messages by timestamp
                    conv_data['messages'].sort(key=lambda x: x.get('timestamp', ''))
                    log("info", f"Would import conversation {conv_id} for student {conv_data['student_id']} with {len(conv_data['messages'])} messages")

            # Process plugin events
            plugin_manager = get_plugin_manager()
            for plugin_id, plugin_evts in plugin_events.items():
                plugin = plugin_manager.get_plugin(plugin_id)
                if plugin:
                    # Sort events chronologically for this plugin
                    plugin_evts.sort(key=lambda x: x.get('timestamp', ''))
                    if not plugin.import_history(trainer_id, plugin_evts, student_info):
                        log("warning", f"Plugin {plugin_id} failed to import some events")
                else:
                    log("warning", f"Plugin {plugin_id} not found, skipping {len(plugin_evts)} events")

            return True

        except Exception as e:
            log("error", f"Failed to import history: {e}", exc_info=True)
            return False

    def _expand_minimal_events(self, events: List[Dict], student_info: Dict) -> List[Dict]:
        """
        Expand minimal events (v2 format) to full events for processing.
        Reconstructs missing fields from student_info and defaults.
        """
        expanded_events = []

        for event in events:
            expanded = event.copy()

            # Add student info if needed
            if 'student_id' not in expanded:
                # Try to infer from conversation_id? Not possible, so we'll need to handle this case
                log("warning", f"Event missing student_id: {event.get('type')}")
            else:
                student_id = expanded['student_id']
                if student_id in student_info:
                    # Add student_name if missing (though we might not need it for processing)
                    if 'student_name' not in expanded:
                        expanded['student_name'] = student_info[student_id]['name']

            # For conversation events, ensure they have required fields
            if expanded.get('plugin_id') == 'core.conversation' or 'conversation_id' in expanded:
                if 'type' not in expanded:
                    # Try to infer type from content? Not safe
                    pass

            expanded_events.append(expanded)

        return expanded_events

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
