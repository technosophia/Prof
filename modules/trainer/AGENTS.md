<!-- /modules/trainer/AGENTS.md -->

# Trainer module architecture
This module "trainer" is special, it uses plugins, which is basically modules for modules.

Plugins are automatically discovered in /modules/trainer/plugins directory.

# Plugins

Plugins must herit from TrainerPlugin in plugin_base.py
Plugins can interact with the application like a regular module, they can use common API and injection points, callbacks, translations and prompts, users, conversations.

Their are defined by a plugin.json file.

See API_PLUGIN_BASE.md for details of plugin implementation
