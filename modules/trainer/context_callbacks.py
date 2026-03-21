"""LLM context callbacks for trainer module."""

from typing import List, Dict, Optional, Tuple

from core.logging import log
from shared.common import get_prompt


def _get_trainer_id_for_user(user_id: str) -> Optional[str]:
    """Get trainer_id for a user (returns parent_id for students)."""
    log(
        "debug",
        f"[TRAINER_CALLBACK] _get_trainer_id_for_user called with user_id={user_id}",
    )

    from .manager import get_trainer_manager

    trainer_manager = get_trainer_manager()
    if trainer_manager is None:
        log("warning", "[TRAINER_CALLBACK] trainer_manager not available")
        return None

    try:
        user = trainer_manager.user_manager.get_user(user_id)
        if not user:
            log("debug", f"[TRAINER_CALLBACK] User {user_id} not found")
            return None
        parent_id = user.get("parent_id")
        log("debug", f"[TRAINER_CALLBACK] User {user_id} has parent_id={parent_id}")
        return parent_id
    except Exception as e:
        log("warning", f"trainer: could not get trainer for user {user_id}: {e}")
        return None


def inject_teacher_system_prompt(
    user_id: str, messages: List[Dict]
) -> Optional[Tuple[str, str, str]]:
    """Inject system-wide teacher system prompt as 'system' at 'top'.

    Returns None if user is not a student (no parent_id).
    """
    log(
        "debug",
        f"[TRAINER_CALLBACK] inject_teacher_system_prompt called user_id={user_id}",
    )

    trainer_id = _get_trainer_id_for_user(user_id)
    if not trainer_id:
        log(
            "debug",
            "[TRAINER_CALLBACK] No trainer_id, returning None (user is not a student)",
        )
        return None

    try:
        system_prompt = get_prompt("teacher.system_prompt")
        log(
            "debug",
            f"[TRAINER_CALLBACK] Returning system_prompt for trainer {trainer_id}, len={len(system_prompt)}",
        )
        return (system_prompt, "system", "top")
    except Exception as e:
        log("warning", f"trainer: could not get teacher.system_prompt: {e}")
        return None


def inject_training_program(
    user_id: str, messages: List[Dict]
) -> Optional[Tuple[str, str, str]]:
    """Inject trainer-specific training program as 'system' at 'top'.

    Returns None if user is not a student (no parent_id).
    Returns default message if no training program is configured.
    """
    log("debug", f"[TRAINER_CALLBACK] inject_training_program called user_id={user_id}")

    trainer_id = _get_trainer_id_for_user(user_id)
    if not trainer_id:
        log(
            "debug",
            "[TRAINER_CALLBACK] No trainer_id, returning None (user is not a student)",
        )
        return None

    from .manager import get_trainer_manager

    trainer_manager = get_trainer_manager()
    if trainer_manager is None:
        log(
            "warning",
            "trainer: trainer_manager not available in inject_training_program",
        )
        return None

    try:
        template = get_prompt("teacher.training_program")
        program = trainer_manager.get_program(trainer_id)

        if not program:
            program = "No training program has been configured for this coach."
            log(
                "debug",
                f"[TRAINER_CALLBACK] No program for trainer {trainer_id}, using default",
            )

        formatted = template.format(training_program=program)
        log(
            "debug",
            f"[TRAINER_CALLBACK] Returning training_program for trainer {trainer_id}, total_len={len(formatted)}",
        )
        return (formatted, "system", "top")
    except Exception as e:
        log(
            "warning",
            f"trainer: could not get training program for trainer {trainer_id}: {e}",
        )
        return None
