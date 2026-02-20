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

How to create a new plugin:
1. Create a directory in /modules/trainer/plugins/ with your plugin ID
2. Add plugin.json manifest (see example below)
3. Create __init__.py with your plugin class inheriting from TrainerPlugin
4. Implement required abstract methods
5. Override hooks as needed

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

See AGENTS.md in the trainer module for more context on plugin architecture.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Callable, Protocol
from dataclasses import dataclass
import json
import yaml
from pathlib import Path
import importlib.util
import inspect

from shared.common import log, _, get_config


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
    1. Plugin is discovered and initialized (initialize() called once)
    2. For each trainer, on_activate() called when plugin is enabled
    3. Plugin hooks are called when relevant UI is rendered
    4. When trainer disables plugin, on_deactivate() called for cleanup
    5. On export/import, history methods are called

    Best practices:
    - Keep initialization lightweight in __init__
    - Use initialize() for heavy setup (DB connections, file creation)
    - Clean up resources in on_deactivate()
    - Return empty lists from hook methods when no content
    - Keep exported history minimal and reconstructable
    """

    def __init__(self, manifest: PluginManifest):
        """
        Initialize the plugin with its manifest.

        Args:
            manifest: PluginManifest object with plugin metadata
        """
        self.manifest = manifest
        self.id = manifest.id

    @abstractmethod
    def initialize(self) -> bool:
        """
        [api] Initialize the plugin. Called once at module startup.

        Use this for one-time setup like creating database tables,
        registering event handlers, or loading resources.

        Returns:
            bool: True if initialization successful, False otherwise
        """
        pass

    def on_activate(self, trainer_id: str) -> None:
        """
        [api] Called when the plugin is activated for a specific trainer.

        Override to perform per-trainer setup when plugin is turned on.
        This is where you might create trainer-specific data structures
        or initialize per-trainer state.

        Args:
            trainer_id: The trainer's ID
        """
        pass

    def on_deactivate(self, trainer_id: str) -> None:
        """
        [api] Called when the plugin is deactivated for a specific trainer.

        Override to perform per-trainer cleanup when plugin is turned off.
        Release resources, close connections, or archive data.

        Args:
            trainer_id: The trainer's ID
        """
        pass

    def get_admin_tabs(self, trainer_id: str) -> List[tuple]:
        """
        [api] Return list of admin UI tabs for this plugin.

        Each tab is a tuple of (tab_name: str, render_function: callable).
        The render function will be called with the request context and
        should return HTML content.

        Args:
            trainer_id: The trainer's ID

        Returns:
            List of (tab_name, render_function) tuples
        """
        return []

    def render_dashboard_widgets(self, trainer_id: str, students: List[Dict]) -> List[Callable]:
        """
        [api] Return list of render functions for dashboard widgets.

        Widgets appear on the trainer's main dashboard. Each render function
        should accept the request context and return HTML.

        Args:
            trainer_id: The trainer's ID
            students: List of student data dictionaries

        Returns:
            List of callable render functions
        """
        return []

    def render_student_widgets(self, trainer_id: str, student: Dict) -> List[Callable]:
        """
        [api] Return list of render functions for student-specific widgets.

        Widgets appear on individual student pages when viewed by trainer.

        Args:
            trainer_id: The trainer's ID
            student: Student data dictionary

        Returns:
            List of callable render functions
        """
        return []

    def render_student_header_widgets(self, student_id: str, trainer_id: str) -> List[Callable]:
        """
        [api] Return list of render functions for student header area.

        Called when a student views their own page. Use this to show
        student-facing information or controls.

        Args:
            student_id: The student's ID
            trainer_id: The trainer's ID

        Returns:
            List of callable render functions
        """
        return []

    def get_context(self, student_id: str) -> Dict[str, str]:
        """
        [api] Get plugin-specific context information for a student.

        This provides key-value pairs for student context display.
        All values must be strings for consistent UI rendering.

        Args:
            student_id: The student's ID

        Returns:
            Dictionary of context strings (key: description, value: context data)
        """
        return {}

    def export_config(self, trainer_id: str) -> Optional[Dict]:
        """
        [api] Export plugin configuration for YAML export.

        Return None if no configuration to export.

        Args:
            trainer_id: The trainer's ID

        Returns:
            Dictionary of configuration data or None
        """
        return None

    def import_config(self, trainer_id: str, config: Dict) -> bool:
        """
        [api] Import plugin configuration from YAML.

        Args:
            trainer_id: The trainer's ID
            config: Dictionary of configuration data

        Returns:
            True if import successful, False otherwise
        """
        return True

    @abstractmethod
    def export_history(self, trainer_id: str, student_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        [api] Export plugin-specific history events in minimal format.

        Each event must contain at minimum:
        - timestamp: ISO format datetime
        - type: event type (e.g., 'plugin.score_update')
        - plugin_id: this plugin's ID

        Additional fields must be kept minimal. Do not include data that
        can be inferred from configuration (like student names). The goal
        is to export only what's necessary for reconstructing history.

        Args:
            trainer_id: The trainer's ID
            student_id: Optional student ID to filter history for a specific student

        Returns:
            List of minimal event dictionaries
        """
        return []

    @abstractmethod
    def import_history(self, trainer_id: str, events: List[Dict[str, Any]], student_info: Dict = None) -> bool:
        """
        [api] Import plugin-specific history events.

        Reconstruct plugin state from minimal event data. Use student_info
        to map IDs to names or other context when needed.

        Args:
            trainer_id: The trainer's ID
            events: List of minimal event dictionaries to import
            student_info: Optional dictionary with student information for reconstruction

        Returns:
            True if import successful, False otherwise
        """
        return True

class PluginManager:
    """Manages plugin discovery, loading, and lifecycle."""

    def __init__(self):
        self.plugins: Dict[str, TrainerPlugin] = {}
        self.plugin_paths: Dict[str, Path] = {}
        self.discover_plugins()

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
                if plugin_instance.initialize():
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
                if method.__func__ != getattr(TrainerPlugin, hook_name, getattr(TrainerPlugin, hook_name, None)):
                    result.append(plugin)

        return result


# Singleton instance
_plugin_manager = None


def get_plugin_manager():
    """Get the global PluginManager instance."""
    global _plugin_manager
    if _plugin_manager is None:
        _plugin_manager = PluginManager()
    return _plugin_manager
