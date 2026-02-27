"""
Trainer module business logic.
Manages students, notes, and plugin coordination.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
import yaml
import json
from shared.common import get_prompt
from st_shared.cached import get_db_manager, get_user_manager, get_conversation_manager
from modules.trainer.plugin_base import get_plugin_manager


from core.logging import log, set_log_module_level

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

    def is_plugin_active(self, trainer_id: str, plugin_id: str) -> bool:
        """Check if a plugin is active for this trainer."""
        from .models import PluginActivation

        with self.db.get_session() as session:
            activation = session.query(PluginActivation).filter_by(
                trainer_id=trainer_id,
                plugin_id=plugin_id
            ).first()

            return activation.is_active if activation else False


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
