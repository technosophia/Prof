from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Callable

from core.logging import log


class TrainerPluginCore(ABC):
    """Core data-layer base class for Trainer plugins."""

    def __init__(self, manifest, trainer_manager=None):
        self.manifest = manifest
        self.id = manifest.id
        self._is_active: bool = False
        self.trainer_manager = trainer_manager

        self.db = None
        self.user_manager = None
        self.conversation_manager = None
        self.llm_manager = None
        self.config = None

    def _mark_active(self) -> None:
        self._is_active = True

    def _mark_inactive(self) -> None:
        self._is_active = False

    def is_active(self) -> bool:
        return self._is_active

    def _resolve_services(self, services=None) -> None:
        if services is not None:
            self.db = services.get("db_manager")
            self.user_manager = services.get("user_manager")
            self.conversation_manager = services.get("conversation_manager")
            self.llm_manager = services.get("llm_manager")
            self.config = services.get("config")
        else:
            try:
                from st_shared.cached import (
                    get_db_manager,
                    get_user_manager,
                    get_conversation_manager,
                    get_llm_manager,
                )
                self.db = get_db_manager()
                self.user_manager = get_user_manager()
                self.conversation_manager = get_conversation_manager()
                self.llm_manager = get_llm_manager()
            except Exception as e:
                log("warning", f"plugin {self.id}: could not resolve services from st_shared.cached: {e}")

    def set_trainer_manager(self, trainer_manager) -> None:
        self.trainer_manager = trainer_manager

    @abstractmethod
    def initialize(self, services=None) -> bool:
        pass

    def on_activate(self, trainer_id: str) -> None:
        pass

    def on_deactivate(self, trainer_id: str) -> None:
        pass

    def get_context(self, user_id: str) -> Dict[str, str]:
        return {}

    def export_history(self, trainer_id: str, student_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return []
