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

        config = {
            'trainer': {
                'exported_at': datetime.utcnow().isoformat(),
                'trainer_id': trainer_id,
                'system_prompt_key': 'teacher.system_prompt'
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
