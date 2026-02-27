from abc import ABC
from typing import Dict, List, Callable

from .plugin_base_core import TrainerPluginCore


class TrainerPluginUI(ABC):
    """UI layer base class for Trainer plugins."""

    def __init__(self, core: TrainerPluginCore):
        self._core = core

    def __getattr__(self, name):
        return getattr(self._core, name)

    def render_get_admin_tabs(self, trainer_id: str) -> List[tuple]:
        return []

    def get_admin_tabs(self, trainer_id: str) -> List[tuple]:
        return self.render_get_admin_tabs(trainer_id)

    def render_dashboard_widgets(self, trainer_id: str, students: List[Dict]) -> List[Callable]:
        return []

    def render_student_header_widgets(self, trainer_id: str, student: Dict) -> List[Callable]:
        return []

    def render_student_widgets(self, trainer_id: str, student: Dict) -> List[Callable]:
        return []
