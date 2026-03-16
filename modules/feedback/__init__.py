"""Feedback module lifecycle."""

from modules.feedback.feedback_core import feedback_on_module_activated, feedback_on_module_deactivated


def on_module_activated(services) -> None:
    feedback_on_module_activated(services)


def on_module_deactivated() -> None:
    feedback_on_module_deactivated()
