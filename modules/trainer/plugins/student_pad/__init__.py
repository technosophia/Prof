"""Student pad plugin entrypoints."""

from modules.trainer.plugins.student_pad.core import StudentPadPluginCore
from modules.trainer.plugins.student_pad.ui import StudentPadPluginUI

plugin_core = StudentPadPluginCore
plugin_ui = StudentPadPluginUI
plugin = StudentPadPluginCore
