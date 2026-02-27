"""Memory plugin entrypoints."""

from modules.trainer.plugins.memory.core import MemoryPluginCore
from modules.trainer.plugins.memory.ui import MemoryPluginUI

plugin_core = MemoryPluginCore
plugin_ui = MemoryPluginUI
plugin = MemoryPluginCore
