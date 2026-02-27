<!-- modules/trainer/_docs/API_PLUGIN_BASE.md -->

<!-- GENERATED FILE - do not edit manually -->
<!-- Source: modules/trainer/plugin_base.py -->

# API — plugin_base

Trainer plugin compatibility layer and plugin manager.


This module provides the PluginManager for discovering and loading Trainer plugins,
and maintains backward compatibility for legacy single-class plugins.

Architecture — Two-class plugin system:
─────────────────────────────────────────────────────────────────────────────
  CORE CLASS (data layer) — plugins/<id>/core.py
    - Inherits from TrainerPluginCore
    - Contains all data methods and business logic
    - No streamlit imports, callable headless

  UI CLASS (presentation layer) — plugins/<id>/ui.py
    - Inherits from TrainerPluginUI
    - Contains all render methods
    - Holds reference to core instance as self._core
    - All data access via self._core.<method>()

  ENTRY POINTS — plugins/<id>/__init__.py
    - Exports plugin_core and plugin_ui classes

PluginManager handles both:
  - New style: separate core + ui classes via entry points
  - Legacy: single class inheriting TrainerPlugin (backward compatible)

Key invariant: deleting all ui.py files must leave a fully functional
headless system. The PluginManager only loads UI classes when Streamlit
is available.

Usage:
    from modules.trainer.plugin_base import get_plugin_manager

    # Get manager (singleton)
    plugin_mgr = get_plugin_manager(trainer_manager)

    # Get core plugin instance
    core = plugin_mgr.get_plugin("memory")

    # Get UI plugin instance (only if Streamlit available)
    ui = plugin_mgr.get_ui_plugin("memory")

    # Get all active UI plugins for a trainer
    active_ui = plugin_mgr.get_active_ui_plugins(trainer_id)
