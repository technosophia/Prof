"""
Training context management for the trainer module.
Provides access to training program and other contextual information.
"""

from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from shared.common import get_prompt, log


@dataclass
class TrainingContext:
    """
    Training context containing program information and other metadata.
    This context is passed to plugins to provide training-related information.
    """
    trainer_id: str
    training_program: str = ""
    _additional_data: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Initialize with default training program if not provided."""
        if not self.training_program:
            self.training_program = get_prompt('trainer.teacher.training_program')

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get additional context data by key.

        Args:
            key: The key to look up
            default: Default value if key not found

        Returns:
            The value associated with the key, or default
        """
        return self._additional_data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """
        Set additional context data.

        Args:
            key: The key to set
            value: The value to store
        """
        self._additional_data[key] = value

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert context to dictionary for export.

        Returns:
            Dictionary representation of the context
        """
        return {
            'training_program': self.training_program,
            **self._additional_data
        }

    @classmethod
    def from_dict(cls, trainer_id: str, data: Dict[str, Any]) -> 'TrainingContext':
        """
        Create context from dictionary (for import).

        Args:
            trainer_id: The trainer's ID
            data: Dictionary containing context data

        Returns:
            New TrainingContext instance
        """
        # Extract known fields
        training_program = data.pop('training_program', '')

        # Create context with remaining data as additional
        context = cls(
            trainer_id=trainer_id,
            training_program=training_program
        )

        # Add remaining data as additional context
        for key, value in data.items():
            if key != 'training_program':  # Already handled
                context.set(key, value)

        return context


# Global context cache - could be expanded to database storage if needed
_context_cache: Dict[str, TrainingContext] = {}


def get_training_context(trainer_id: str) -> TrainingContext:
    """
    Get the training context for a trainer.
    Creates a new context if one doesn't exist.

    Args:
        trainer_id: The trainer's ID

    Returns:
        TrainingContext instance for the trainer
    """
    if trainer_id not in _context_cache:
        _context_cache[trainer_id] = TrainingContext(trainer_id=trainer_id)
    return _context_cache[trainer_id]


def set_training_program(trainer_id: str, program: str) -> None:
    """
    Set the training program for a trainer.

    Args:
        trainer_id: The trainer's ID
        program: The training program text
    """
    context = get_training_context(trainer_id)
    context.training_program = program
    log("info", f"Updated training program for trainer {trainer_id}")


def export_training_context(trainer_id: str) -> Dict[str, Any]:
    """
    Export training context for YAML serialization.

    Args:
        trainer_id: The trainer's ID

    Returns:
        Dictionary representation of the context
    """
    context = get_training_context(trainer_id)
    return context.to_dict()


def import_training_context(trainer_id: str, data: Dict[str, Any]) -> bool:
    """
    Import training context from YAML data.

    Args:
        trainer_id: The trainer's ID
        data: Dictionary containing context data

    Returns:
        True if import successful
    """
    try:
        context = TrainingContext.from_dict(trainer_id, data)
        _context_cache[trainer_id] = context
        log("info", f"Imported training context for trainer {trainer_id}")
        return True
    except Exception as e:
        log("error", f"Failed to import training context: {e}")
        return False
