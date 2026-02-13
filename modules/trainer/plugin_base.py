"""
Trainer plugin system foundation.
Defines the base classes and manager for plugins.
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
    """Base class for all Trainer plugins."""

    def __init__(self, manifest: PluginManifest):
        self.manifest = manifest
        self.id = manifest.id

    @abstractmethod
    def initialize(self) -> bool:
        """Initialize the plugin. Called once at module startup."""
        pass

    def get_admin_tabs(self, trainer_id: str) -> List[tuple]:
        """
        Return list of (tab_name: str, render_function: callable) for admin UI.
        Called only if plugin is active for this trainer.
        """
        return []

    def render_dashboard_widgets(self, trainer_id: str, students: List[Dict]) -> List[Callable]:
        """Return list of render functions for dashboard widgets."""
        return []

    def render_student_widgets(self, trainer_id: str, student: Dict) -> List[Callable]:
        """Return list of render functions for student-specific widgets."""
        return []

    def render_student_header_widgets(self, student_id: str, trainer_id: str) -> List[Callable]:
        """
        Return list of render functions for student header area.
        Called when a student (normal user) views their own page.
        """
        return []

    def export_config(self, trainer_id: str) -> Optional[Dict]:
        """Export plugin configuration for YAML export."""
        return None

    def import_config(self, trainer_id: str, config: Dict) -> bool:
        """Import plugin configuration from YAML."""
        return True

    def on_activate(self, trainer_id: str) -> bool:
        """Called when plugin is activated for a trainer."""
        return True

    def on_deactivate(self, trainer_id: str) -> bool:
        """Called when plugin is deactivated for a trainer."""
        return True


class PluginDataProvider(Protocol):
    """Protocol for plugins that provide data access methods."""
    def get_data(self, trainer_id: str, key: str, **kwargs) -> Any:
        ...
    def save_data(self, trainer_id: str, key: str, value: Any, **kwargs) -> bool:
        ...


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
