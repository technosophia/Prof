"""
[api]

This module provides the foundation for the data layer of Trainer plugins.
All plugins must have a core class that inherits from TrainerPluginCore and
implements the required abstract methods.

Architecture — Two-layer design with separate core and UI classes:
─────────────────────────────────────────────────────────────────────────────
  CORE CLASS (data layer) — plugins/<id>/core.py
    Methods: initialize(), on_activate(), on_deactivate(), get_context(),
             export_history(), import_history(), and any private helpers
    Rules:
      - MUST use self.<service> attributes set in initialize(services)
      - MUST NOT import from st_shared.cached
      - MUST NOT import streamlit
      - MUST be callable headless (no Streamlit process)
      - Inherits from TrainerPluginCore

  UI CLASS (presentation layer) — plugins/<id>/ui.py
    Methods: render_student_widgets(), render_dashboard_widgets(),
             render_student_header_widgets(), render_get_admin_tabs()
    Rules:
      - MUST only call self._core.<data_method>() for all data access
      - MAY import and use streamlit freely
      - MUST NOT call st_shared.cached or database code directly
      - Inherits from TrainerPluginUI

  ENTRY POINTS — plugins/<id>/__init__.py
    - Exports plugin_core and plugin_ui classes for PluginManager discovery

The key invariant: deleting all ui.py files must leave a fully functional
headless system. All data methods work without Streamlit.

Lifecycle:
1. Plugin discovered — PluginManager loads core and (if Streamlit available) UI
2. initialize(services) called on core at startup with ServiceLocator
3. For each trainer, on_activate() called when plugin enabled
4. Plugin hooks called when relevant UI rendered (UI methods route to core)
5. When trainer disables plugin, on_deactivate() called for cleanup

Service attributes (set in initialize, used by data methods):
    self.db              — db_manager
    self.user_manager    — user_manager
    self.conversation_manager — conversation_manager
    self.llm_manager     — llm_manager (if needed)
    self.config          — config (if needed)
"""


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
