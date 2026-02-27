"""Pedagogical memory plugin entrypoints."""

from modules.trainer.plugins.pedagogical_memory.core import PedagogicalMemoryPluginCore
from modules.trainer.plugins.pedagogical_memory.ui import PedagogicalMemoryPluginUI

plugin_core = PedagogicalMemoryPluginCore
plugin_ui = PedagogicalMemoryPluginUI
plugin = PedagogicalMemoryPluginCore
