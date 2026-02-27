"""Suggest plugin entrypoints."""

from modules.trainer.plugins.suggest.core import SuggestPluginCore
from modules.trainer.plugins.suggest.ui import SuggestPluginUI

plugin_core = SuggestPluginCore
plugin_ui = SuggestPluginUI
plugin = SuggestPluginCore
