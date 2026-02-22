<!-- /modules/trainer/AGENTS.md -->

# Trainer module architecture
This module "trainer" is special, it uses plugins, which is basically modules for modules.

Plugins are automatically discovered in /modules/trainer/plugins directory.

# Plugins

Plugins must herit from TrainerPlugin in plugin_base.py
Plugins can interact with the application like a regular module, they can use common API and injection points, callbacks, translations and prompts, users, conversations.

Their are defined by a plugin.json file.

See API_PLUGIN_BASE.md for details of plugin implementation

## Driver integration

### Option group: `memory_backend`
Single-plugin options: `memory`, `pedagogical_memory`, `student_pad`
Combination options: `memory+student_pad`, `pedagogical_memory+student_pad`

Switching is mutually exclusive within the group.
All plugins NOT in the active option are marked inactive via `_mark_inactive()`
and will return None from `get_memory_context` even if their callback
is still registered.

### Actions registered by trainer:
- `trigger_memory_analysis` — dispatches to active backend plugin(s)
- `set_training_program` — saves training program via save_prompt()
- `add_student_note` — delegates to student_pad plugin

### Activation guard (TrainerPlugin base class):
Every plugin has `_is_active: bool`. `get_memory_context` returns None
immediately if `_is_active` is False. This prevents stale plugins from
injecting context after being switched out.

### Registration pattern:
Module registers, plugins implement handler methods.
Plugins never call register_option() or register_action() directly.
