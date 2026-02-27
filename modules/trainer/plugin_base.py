"""Trainer plugin compatibility layer and plugin manager."""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
import importlib.util
import inspect
import json

from core.logging import log
from .plugin_base_core import TrainerPluginCore
from .plugin_base_ui import TrainerPluginUI


@dataclass
class PluginManifest:
    id: str
    name: str
    version: str
    description: str
    author: str
    enabled_by_default: bool = True
    category: str = "general"


class TrainerPlugin(TrainerPluginCore, TrainerPluginUI):
    """Backward-compatible single-class plugin base."""

    def __init__(self, manifest: PluginManifest, trainer_manager=None):
        TrainerPluginCore.__init__(self, manifest, trainer_manager=trainer_manager)
        TrainerPluginUI.__init__(self, self)


class PluginManager:
    def __init__(self, trainer_manager=None):
        self.plugins: Dict[str, TrainerPluginCore] = {}
        self.ui_plugins: Dict[str, TrainerPluginUI] = {}
        self.plugin_paths: Dict[str, Path] = {}
        self._services = None
        self._trainer_manager = trainer_manager
        self._streamlit_available = self._check_streamlit_available()
        self.discover_plugins()

    @staticmethod
    def _check_streamlit_available() -> bool:
        try:
            import streamlit  # noqa: F401
            return True
        except Exception:
            return False

    def set_trainer_manager(self, trainer_manager) -> None:
        self._trainer_manager = trainer_manager
        for plugin in self.plugins.values():
            plugin.set_trainer_manager(trainer_manager)

    def set_services(self, services) -> None:
        self._services = services

    def discover_plugins(self):
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

    def _make_manifest(self, manifest_file: Path) -> PluginManifest:
        with open(manifest_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return PluginManifest(
            id=data['id'],
            name=data['name'],
            version=data['version'],
            description=data['description'],
            author=data.get('author', 'Unknown'),
            enabled_by_default=data.get('enabled_by_default', True),
            category=data.get('category', 'general'),
        )

    def _load_plugin(self, plugin_dir: Path, manifest_file: Path):
        manifest = self._make_manifest(manifest_file)
        spec = importlib.util.spec_from_file_location(f"trainer_plugin_{manifest.id}", plugin_dir / "__init__.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        core_cls = getattr(module, "plugin_core", None)
        ui_cls = getattr(module, "plugin_ui", None)

        if inspect.isclass(core_cls) and issubclass(core_cls, TrainerPluginCore):
            core_instance = self._instantiate_core(core_cls, manifest)
            if core_instance and self._initialize_plugin(core_instance):
                self.plugins[manifest.id] = core_instance
                self.plugin_paths[manifest.id] = plugin_dir
                if self._streamlit_available and inspect.isclass(ui_cls):
                    self.ui_plugins[manifest.id] = ui_cls(core_instance)
                log("info", f"Loaded plugin: {manifest.id} v{manifest.version}")
                return

        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if inspect.isclass(attr) and issubclass(attr, TrainerPlugin) and attr != TrainerPlugin:
                plugin_instance = self._instantiate_core(attr, manifest)
                if plugin_instance and self._initialize_plugin(plugin_instance):
                    self.plugins[manifest.id] = plugin_instance
                    self.plugin_paths[manifest.id] = plugin_dir
                    if self._streamlit_available:
                        self.ui_plugins[manifest.id] = plugin_instance
                    log("info", f"Loaded plugin: {manifest.id} v{manifest.version}")
                    return

    def _instantiate_core(self, cls, manifest):
        try:
            return cls(manifest, trainer_manager=self._trainer_manager)
        except TypeError:
            instance = cls(manifest)
            if self._trainer_manager is not None:
                instance.set_trainer_manager(self._trainer_manager)
            return instance

    def _initialize_plugin(self, plugin):
        try:
            return plugin.initialize(self._services)
        except TypeError:
            return plugin.initialize()

    def get_plugin(self, plugin_id: str) -> Optional[TrainerPluginCore]:
        return self.plugins.get(plugin_id)

    def get_ui_plugin(self, plugin_id: str) -> Optional[TrainerPluginUI]:
        return self.ui_plugins.get(plugin_id)

    def get_all_plugins(self) -> List[TrainerPluginCore]:
        return list(self.plugins.values())

    def get_all_ui_plugins(self) -> List[TrainerPluginUI]:
        return list(self.ui_plugins.values())

    def get_active_plugins(self, trainer_id: str) -> List[TrainerPluginCore]:
        if self._trainer_manager is None:
            log("warning", "PluginManager.get_active_plugins called without trainer_manager")
            return []
        return [p for p in self.plugins.values() if self._trainer_manager.is_plugin_active(trainer_id, p.id)]

    def get_active_ui_plugins(self, trainer_id: str) -> List[TrainerPluginUI]:
        if self._trainer_manager is None:
            log("warning", "PluginManager.get_active_ui_plugins called without trainer_manager")
            return []
        result = []
        for plugin_id, plugin in self.plugins.items():
            if self._trainer_manager.is_plugin_active(trainer_id, plugin_id):
                ui_plugin = self.ui_plugins.get(plugin_id)
                if ui_plugin is not None:
                    result.append(ui_plugin)
        return result

    def get_plugins_by_hook(self, trainer_id: str, hook_name: str) -> List[TrainerPluginCore]:
        active_plugins = self.get_active_plugins(trainer_id)
        result = []
        for plugin in active_plugins:
            method = getattr(plugin, hook_name, None)
            if method and callable(method):
                base_method = getattr(TrainerPluginCore, hook_name, None)
                if base_method is None or getattr(method, "__func__", method) != base_method:
                    result.append(plugin)
        return result

    def get_ui_plugins_by_hook(self, trainer_id: str, hook_name: str) -> List[TrainerPluginUI]:
        active_plugins = self.get_active_ui_plugins(trainer_id)
        result = []
        for plugin in active_plugins:
            method = getattr(plugin, hook_name, None)
            if method and callable(method):
                base_method = getattr(TrainerPluginUI, hook_name, None)
                if base_method is None or getattr(method, "__func__", method) != base_method:
                    result.append(plugin)
        return result


_plugin_manager = None


def get_plugin_manager(trainer_manager=None) -> PluginManager:
    global _plugin_manager
    if _plugin_manager is None:
        _plugin_manager = PluginManager(trainer_manager=trainer_manager)
    elif trainer_manager is not None:
        _plugin_manager.set_trainer_manager(trainer_manager)
    return _plugin_manager


def reset_plugin_manager() -> None:
    global _plugin_manager
    _plugin_manager = None
