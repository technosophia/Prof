"""
[api] Trainer Plugin Base Module

This module provides the foundation for creating Trainer plugins.
Plugins extend the functionality of the Trainer module by adding custom
features, UI components, and data processing capabilities.

Goal: Enable developers to create modular, disposable features that can be
quickly implemented and tested with users.

Principles:
- Keep plugins focused on a single responsibility
- Minimize coupling between plugins
- Use provided hooks instead of modifying core code
- Store only essential data in history exports
- Follow bio-coding: make plugins easy to create and discard

Architecture — two-layer design (enforced by convention, future: two classes):
─────────────────────────────────────────────────────────────────────────────
  DATA LAYER  (below the line)
    Methods: get_context(), export_history(), import_history(), on_activate(),
             on_deactivate(), export_config(), import_config(), and any private
             helpers they call.
    Rules:
      - MUST use self.<service> attributes set in initialize(services)
      - MUST NOT import from st_shared.cached
      - MUST NOT import streamlit
      - MUST be callable headless (no Streamlit process)

  UI LAYER  (above the line)
    Methods: render_student_widgets(), render_dashboard_widgets(),
             render_student_header_widgets(), render_get_admin_tabs()
    Rules:
      - MUST only call self.<data_method>() for all data access
      - MAY import and use streamlit freely
      - MUST NOT call st_shared.cached or database code directly

  Future split: when two-class separation is needed, data methods move to
  PluginLogic and render methods move to PluginUI. The only change in render
  methods will be: self.xxx() → self._logic.xxx(). No logic rewrite needed.
─────────────────────────────────────────────────────────────────────────────

How to create a new plugin:
1. Create a directory in /modules/trainer/plugins/ with your plugin ID
2. Add plugin.json manifest (see example below)
3. Create __init__.py with your plugin class inheriting from TrainerPlugin
4. Implement required abstract methods
5. Call super().__init__(manifest) and set service attributes in initialize()
6. Override hooks as needed, respecting the data/UI layer rules above

Plugin manifest example (plugin.json):
{
    "id": "my_plugin",
    "name": "My Plugin",
    "version": "1.0.0",
    "description": "Does something useful",
    "author": "Your Name",
    "enabled_by_default": true,
    "category": "analytics"
}

See PLUGIN_MIGRATE.md for step-by-step migration of existing plugins.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Callable, Protocol
from dataclasses import dataclass
import json
import yaml
from pathlib import Path
import importlib.util
import inspect


from core.logging import log, set_log_module_level


@dataclass
class PluginManifest:
    """Plugin metadata from plugin.json."""
    id: str
    name: str
    version: str
    description: str
    author: str
    enabled_by_default: bool = True
    category: str = "general"


class TrainerPlugin(ABC):
    """
    [api] Base class for all Trainer plugins.

    All plugins must inherit from this class and implement the abstract methods.
    Override the optional methods to add functionality at specific hooks.

    Lifecycle:
    1. Plugin is discovered — initialize(services) called once at startup.
       services is a ServiceLocator or None (legacy / Streamlit-cached fallback).
    2. For each trainer, on_activate() called when plugin is enabled.
    3. Plugin hooks are called when relevant UI is rendered.
    4. When trainer disables plugin, on_deactivate() called for cleanup.
    5. On export/import, history methods are called.

    Service attributes (set in initialize, used by data methods):
        self.db              — db_manager
        self.user_manager    — user_manager
        self.conversation_manager — conversation_manager
        self.llm_manager     — llm_manager (if needed)
        self.config          — config (if needed)

    Plugins that have not yet been migrated may still use st_shared.cached
    inside initialize() as a fallback when services is None. See PLUGIN_MIGRATE.md.
    """

    def __init__(self, manifest: PluginManifest):
        """
        Initialize the plugin with its manifest.

        Args:
            manifest: PluginManifest object with plugin metadata
        """
        self.manifest = manifest
        self.id = manifest.id
        self._is_active: bool = False

        # Service attributes — set in initialize(services).
        # Data methods must use these; never call st_shared.cached directly.
        self.db = None
        self.user_manager = None
        self.conversation_manager = None
        self.llm_manager = None
        self.config = None

    # ─────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────

    def _mark_active(self) -> None:
        """Called by the trainer module when this plugin is activated."""
        self._is_active = True

    def _mark_inactive(self) -> None:
        """Called by the trainer module when this plugin is deactivated."""
        self._is_active = False

    def is_active(self) -> bool:
        """Return True if this plugin is currently the active backend."""
        return self._is_active

    def _resolve_services(self, services=None) -> None:
        """
        Resolve and store service references from ServiceLocator or st_shared.cached.

        Called at the top of initialize(). Migrated plugins pass a real services
        object; legacy plugins pass None and fall back to st_shared.cached.

        This is the ONLY place in the plugin where st_shared.cached is permitted
        (as a fallback), and only until the plugin is fully migrated.
        """
        if services is not None:
            self.db = services.get("db_manager")
            self.user_manager = services.get("user_manager")
            self.conversation_manager = services.get("conversation_manager")
            self.llm_manager = services.get("llm_manager")
            self.config = services.get("config")
        else:
            # Legacy fallback — allowed only during migration
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

    # ─────────────────────────────────────────────────────────────────────
    # Lifecycle — DATA LAYER
    # ─────────────────────────────────────────────────────────────────────

    @abstractmethod
    def initialize(self, services=None) -> bool:
        """
        [api] Initialize the plugin. Called once at module startup.

        Pattern for migrated plugins:
            def initialize(self, services=None) -> bool:
                self._resolve_services(services)
                # one-time setup: create DB tables, register callbacks, etc.
                return True

        Args:
            services: ServiceLocator passed by PluginManager, or None (legacy).

        Returns:
            bool: True if initialization successful, False otherwise.
        """
        pass

    def on_activate(self, trainer_id: str) -> None:
        """
        [api] Called when the plugin is activated for a specific trainer.

        DATA LAYER — no st.* calls allowed here.

        Args:
            trainer_id: The trainer's ID
        """
        pass

    def on_deactivate(self, trainer_id: str) -> None:
        """
        [api] Called when the plugin is deactivated for a specific trainer.

        DATA LAYER — no st.* calls allowed here.

        Args:
            trainer_id: The trainer's ID
        """
        pass

    def get_context(self, student_id: str) -> Dict[str, str]:
        """
        [api] Get plugin-specific context information for a student.

        DATA LAYER — use self.<service> attributes only.

        Returns:
            Dictionary of context strings (key: label, value: context data)
        """
        return {}

    def export_config(self, trainer_id: str) -> Optional[Dict]:
        """
        [api] Export plugin configuration for YAML export.

        DATA LAYER — use self.<service> attributes only.

        Returns:
            Dictionary of configuration data or None
        """
        return None

    def import_config(self, trainer_id: str, config: Dict) -> bool:
        """
        [api] Import plugin configuration from YAML.

        DATA LAYER — use self.<service> attributes only.
        """
        return True

    @abstractmethod
    def export_history(self, trainer_id: str, student_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        [api] Export plugin-specific history events in minimal format.

        DATA LAYER — use self.<service> attributes only.

        Each event must contain at minimum:
        - timestamp: ISO format datetime
        - type: event type (e.g., 'plugin.score_update')
        - plugin_id: this plugin's ID

        Returns:
            List of minimal event dictionaries
        """
        return []

    @abstractmethod
    def import_history(self, trainer_id: str, events: List[Dict[str, Any]],
                       student_info: Dict = None) -> bool:
        """
        [api] Import plugin-specific history events.

        DATA LAYER — use self.<service> attributes only.

        Returns:
            True if import successful, False otherwise
        """
        return True

    # ─────────────────────────────────────────────────────────────────────
    # UI LAYER — render methods
    # Rules: call self.<data_method>() for data; use st.* freely; no db/cache.
    # When splitting into two classes, self.xxx() becomes self._logic.xxx().
    # ─────────────────────────────────────────────────────────────────────

    def render_get_admin_tabs(self, trainer_id: str) -> List[tuple]:
        """
        [api] Return list of admin UI tabs for this plugin.

        UI LAYER — may use st.*; must call self.<data_method>() for data.

        Returns:
            List of (tab_name, render_function) tuples
        """
        return []

    def render_dashboard_widgets(self, trainer_id: str, students: List[Dict]) -> List[Callable]:
        """
        [api] Return list of render functions for dashboard widgets.

        UI LAYER — may use st.*; must call self.<data_method>() for data.

        Returns:
            List of callable render functions
        """
        return []

    def render_student_widgets(self, trainer_id: str, student: Dict) -> List[Callable]:
        """
        [api] Return list of render functions for student-specific widgets.

        UI LAYER — may use st.*; must call self.<data_method>() for data.

        Returns:
            List of callable render functions
        """
        return []

    def render_student_header_widgets(self, student_id: str, trainer_id: str) -> List[Callable]:
        """
        [api] Return list of render functions for student header area.

        UI LAYER — may use st.*; must call self.<data_method>() for data.

        Returns:
            List of callable render functions
        """
        return []


class PluginManager:
    """Manages plugin discovery, loading, and lifecycle."""

    def __init__(self):
        self.plugins: Dict[str, TrainerPlugin] = {}
        self.plugin_paths: Dict[str, Path] = {}
        self._services = None  # Set by set_services() before discover
        self.discover_plugins()

    def set_services(self, services) -> None:
        """
        Provide the ServiceLocator to the plugin manager.

        Must be called before discover_plugins() to ensure plugins receive
        injected services during initialize(). In practice, call this from
        the TrainerManager or module __init__ before the manager is used.
        """
        self._services = services

    def discover_plugins(self):
        """Discover all plugins in the plugins directory."""
        plugins_dir = Path(__file__).parent / "plugins"
        if not plugins_dir.exists():
            return

        for plugin_dir in plugins_dir.iterdir():
            if not plugin_dir.is_dir():
                continue

            manifest_file = plugin_dir / "plugin.json"
            init_file = plugin_dir / "__init__.py"

            if manifest_file.exists() and init_file.exists():
                try:
                    self._load_plugin(plugin_dir, manifest_file)
                except Exception as e:
                    log("error", f"Failed to load plugin {plugin_dir.name}: {e}")

    def _load_plugin(self, plugin_dir: Path, manifest_file: Path):
        """Load a single plugin from directory."""
        with open(manifest_file, 'r', encoding='utf-8') as f:
            manifest_data = json.load(f)

        manifest = PluginManifest(
            id=manifest_data['id'],
            name=manifest_data['name'],
            version=manifest_data['version'],
            description=manifest_data['description'],
            author=manifest_data.get('author', 'Unknown'),
            enabled_by_default=manifest_data.get('enabled_by_default', True),
            category=manifest_data.get('category', 'general')
        )

        # Import the plugin module
        spec = importlib.util.spec_from_file_location(
            f"trainer_plugin_{manifest.id}",
            plugin_dir / "__init__.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Find the plugin class
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (inspect.isclass(attr) and
                issubclass(attr, TrainerPlugin) and
                attr != TrainerPlugin):
                plugin_instance = attr(manifest)
                # Pass services to initialize — None is safe for legacy plugins
                try:
                    result = plugin_instance.initialize(self._services)
                except TypeError:
                    # Legacy plugin — initialize() takes no arguments
                    result = plugin_instance.initialize()
                if result:
                    self.plugins[manifest.id] = plugin_instance
                    self.plugin_paths[manifest.id] = plugin_dir
                    log("info", f"Loaded plugin: {manifest.id} v{manifest.version}")
                    break

    def get_plugin(self, plugin_id: str) -> Optional[TrainerPlugin]:
        """Get plugin by ID."""
        return self.plugins.get(plugin_id)

    def get_all_plugins(self) -> List[TrainerPlugin]:
        """Get all discovered plugins."""
        return list(self.plugins.values())

    def get_active_plugins(self, trainer_id: str) -> List[TrainerPlugin]:
        """Get all plugins active for this trainer."""
        from .manager import get_trainer_manager
        trainer_manager = get_trainer_manager()

        active = []
        for plugin in self.plugins.values():
            if trainer_manager.is_plugin_active(trainer_id, plugin.id):
                active.append(plugin)
        return active

    def get_plugins_by_hook(self, trainer_id: str, hook_name: str) -> List[TrainerPlugin]:
        """Get active plugins that implement a specific hook."""
        active_plugins = self.get_active_plugins(trainer_id)
        result = []

        for plugin in active_plugins:
            method = getattr(plugin, hook_name, None)
            if method and callable(method):
                # Check if it's not the base class implementation
                base_method = getattr(TrainerPlugin, hook_name, None)
                if base_method and method.__func__ != base_method:
                    result.append(plugin)

        return result


# Singleton instance
_plugin_manager = None


def get_plugin_manager() -> PluginManager:
    """Get the global PluginManager instance."""
    global _plugin_manager
    if _plugin_manager is None:
        _plugin_manager = PluginManager()
    return _plugin_manager


def reset_plugin_manager() -> None:
    """Reset the singleton (for tests)."""
    global _plugin_manager
    _plugin_manager = None
