<!-- modules/trainer/_docs/API_PLUGIN_BASE_CORE.md -->

<!-- GENERATED FILE - do not edit manually -->
<!-- Source: modules/trainer/plugin_base_core.py -->

# API — plugin_base_core

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
