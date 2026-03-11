"""
Trainer module business logic.
Manages students, notes, and plugin coordination.

NO st_shared.cached imports here — all dependencies injected via constructor.
The factory (manager_factory.py) is the only place that bridges st_shared.cached.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from modules.trainer.material_loader import MaterialLoader

from core.logging import log


class TrainerManager:
    """
    Main manager for trainer functionality.

    All dependencies are injected via constructor — no st_shared.cached.
    """

    def __init__(self, db_manager, user_manager, conversation_manager):
        self.db = db_manager
        self.user_manager = user_manager
        self.conversation_manager = conversation_manager

    # ─────────────────────────────────────────────────────────────────────
    # Students
    # ─────────────────────────────────────────────────────────────────────

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
                except Exception:
                    return None
        return None

    # ─────────────────────────────────────────────────────────────────────
    # Context aggregation
    # ─────────────────────────────────────────────────────────────────────

    def get_all_contexts(self, student_id: str) -> Dict[str, Dict[str, str]]:
        """
        Get all context information for a student from all active plugins.

        Aggregates context from all active plugins for the trainer who owns
        this student, and includes the trainer-specific training program at the top.

        Returns:
            Dictionary with plugin names as keys and their context dicts as values,
            plus a 'Training Program' key at the top.
        """
        student = self.user_manager.get_user(student_id)
        if not student:
            log("error", f"Student {student_id} not found")
            return {}

        trainer_id = student.get('parent_id')
        if not trainer_id:
            log("error", f"Student {student_id} has no trainer assigned")
            return {}

        # Get trainer-specific training program
        training_program = self.get_program(trainer_id)

        contexts = {
            'Training Program': {
                'Training Program': training_program
            }
        }

        from .plugin_base import get_plugin_manager
        plugin_manager = get_plugin_manager()
        if hasattr(plugin_manager, "set_trainer_manager"):
            plugin_manager.set_trainer_manager(self)
        active_plugins = plugin_manager.get_active_plugins(trainer_id)

        for plugin in active_plugins:
            plugin_context = plugin.get_context(student_id)
            if plugin_context:
                contexts[plugin.manifest.name] = plugin_context

        return contexts

    # ─────────────────────────────────────────────────────────────────────
    # Plugin activation
    # ─────────────────────────────────────────────────────────────────────

    def is_plugin_active(self, trainer_id: str, plugin_id: str) -> bool:
        """Check if a plugin is active for this trainer."""
        from .models import PluginActivation

        log("debug", f"[PLUGIN_STATE] Checking is_plugin_active(trainer={trainer_id}, plugin={plugin_id})")

        with self.db.get_session() as session:
            activation = session.query(PluginActivation).filter_by(
                trainer_id=trainer_id,
                plugin_id=plugin_id
            ).first()

            result = activation.is_active if activation else False
            log("debug", f"[PLUGIN_STATE] Plugin {plugin_id} for trainer {trainer_id} active = {result}")

            # Si c'est le plugin memory et qu'il est inactif, logguer plus de contexte
            if plugin_id == "memory" and not result:
                # Compter combien d'activations existent pour ce trainer
                count = session.query(PluginActivation).filter_by(trainer_id=trainer_id).count()
                log("debug", f"[PLUGIN_STATE] Trainer {trainer_id} has {count} total plugin activations")

                # Lister tous les plugins de ce trainer
                all_plugins = session.query(PluginActivation).filter_by(trainer_id=trainer_id).all()
                for p in all_plugins:
                    log("debug", f"[PLUGIN_STATE]   - {p.plugin_id}: active={p.is_active}")

            return result

    def set_plugin_active(self, trainer_id: str, plugin_id: str, active: bool) -> bool:
        """Activate or deactivate a plugin for this trainer."""
        from .models import PluginActivation

        log("debug", f"[PLUGIN_STATE] Setting plugin {plugin_id} for trainer {trainer_id} to active={active}")

        try:
            with self.db.get_session() as session:
                activation = session.query(PluginActivation).filter_by(
                    trainer_id=trainer_id,
                    plugin_id=plugin_id
                ).first()

                before_state = activation.is_active if activation else False
                log("debug", f"[PLUGIN_STATE] Before change: active={before_state}")

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

                # Vérification immédiate
                session.refresh(activation)
                after_state = activation.is_active
                log("debug", f"[PLUGIN_STATE] After commit: active={after_state}")

                if after_state != active:
                    error_msg = f"Plugin state mismatch: requested {active} but got {after_state}"
                    log("error", error_msg)
                    raise RuntimeError(error_msg)

                log("info", f"[PLUGIN_STATE] SUCCESS: Plugin {plugin_id} for trainer {trainer_id} set to {active}")
                return True

        except Exception as e:
            log("error", f"Failed to set plugin activation: {e}", stacktrace=True)
            return False

    def _expand_minimal_events(self, events: List[Dict], student_info: Dict) -> List[Dict]:
        """
        Expand minimal events (v2 format) to full events for processing.
        Reconstructs missing fields from student_info and defaults.
        """
        expanded_events = []

        for event in events:
            expanded = event.copy()

            if 'student_id' not in expanded:
                log("warning", f"Event missing student_id: {event.get('type')}")
            else:
                student_id = expanded['student_id']
                if student_id in student_info:
                    if 'student_name' not in expanded:
                        expanded['student_name'] = student_info[student_id]['name']

            expanded_events.append(expanded)

        return expanded_events

    def get_trainer_config(self, trainer_id: str) -> Optional[Dict[str, Any]]:
        """
        Get trainer configuration from database.

        Args:
            trainer_id: The trainer's user ID

        Returns:
            Dictionary with trainer config or None if not found
        """
        from .models import TrainerConfig

        with self.db.get_session() as session:
            config = session.query(TrainerConfig).filter_by(
                trainer_id=trainer_id
            ).first()

            if config:
                return {
                    'id': config.id,
                    'trainer_id': config.trainer_id,
                    'formation_dir': config.formation_dir,
                    'config': config.config,
                    'updated_at': config.updated_at
                }
            return None


    def get_formation_dir(self, trainer_id: str) -> Optional[str]:
        """Get the configured formation directory for a trainer."""
        from .models import TrainerConfig

        with self.db.get_session() as session:
            config = session.query(TrainerConfig).filter_by(trainer_id=trainer_id).first()
            return config.formation_dir if config else None

    def set_formation_dir(self, trainer_id: str, formation_dir: str) -> bool:
        """Set the formation directory for a trainer (upsert)."""
        from .models import TrainerConfig

        try:
            with self.db.get_session() as session:
                config = session.query(TrainerConfig).filter_by(trainer_id=trainer_id).first()
                if config:
                    config.formation_dir = formation_dir
                    config.updated_at = datetime.utcnow()
                else:
                    config = TrainerConfig(trainer_id=trainer_id, formation_dir=formation_dir)
                    session.add(config)
                session.commit()
                log("info", f"Formation dir set to '{formation_dir}' for trainer {trainer_id}")
                return True
        except Exception as e:
            log("error", f"Failed to set formation_dir for trainer {trainer_id}: {e}", stacktrace=True)
            return False

    def get_program(self, trainer_id: str) -> str:
        """
        Get the training program markdown for a trainer.
        Returns empty string if no formation is configured or file not found.
        """
        formation_dir = self.get_formation_dir(trainer_id)
        if not formation_dir:
            log("warning", f"No formation_dir configured for trainer {trainer_id}")
            return ""
        try:
            return MaterialLoader().get_program(formation_dir)
        except Exception as e:
            log("warning", str(e))
            return ""

    def get_rubrics(self, trainer_id: str) -> Dict[str, Any]:
        """
        Get the rubrics dict for a trainer.
        Returns empty dict if no formation is configured or file not found.
        """
        formation_dir = self.get_formation_dir(trainer_id)
        if not formation_dir:
            log("warning", f"No formation_dir configured for trainer {trainer_id}")
            return {}
        try:
            return MaterialLoader().get_rubrics(formation_dir)
        except Exception as e:
            log("warning", str(e))
            return {}


# ─────────────────────────────────────────────────────────────────────────────
# Singleton — managed by factory
# ─────────────────────────────────────────────────────────────────────────────

_trainer_manager: Optional[TrainerManager] = None


def get_trainer_manager() -> TrainerManager:
    """Get the global TrainerManager instance."""
    if _trainer_manager is None:
        raise RuntimeError("trainer: manager is not initialized; activate module first")
    return _trainer_manager


def set_trainer_manager(instance: TrainerManager) -> None:
    """Set the global instance (used by factory / tests)."""
    global _trainer_manager
    _trainer_manager = instance


def reset_trainer_manager() -> None:
    """Reset the singleton (for tests)."""
    global _trainer_manager
    _trainer_manager = None
