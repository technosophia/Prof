<!-- /modules/trainer/AGENTS.md -->

# Trainer module architecture
This module "trainer" is special, it uses plugins, which is basically modules for modules.

Plugins are automatically discovered in /modules/trainer/plugins directory.

# Plugins

Plugins must herit from TrainerPlugin in plugin_base.py
Plugins can interact with the application like a regular module, they can use common API and injection points, callbacks, translations and prompts, users, conversations.

Their are defined by a plugin.json file.

See _docs/API_PLUGIN_BASE.md for details of plugin implementation
See _docs/PLUGIN_MIGRATE.md for how to migrate plugin to decouple from streamlit

## Driver integration

### Option group: `memory_backend`
Single-plugin options: `memory`, `pedagogical_memory`, `student_pad`
Combination options: `memory+student_pad`, `pedagogical_memory+student_pad`

Switching is mutually exclusive within the group.

### Actions registered by trainer:
- `trigger_memory_analysis` — dispatches to active backend plugin(s)
- `add_student_note` — delegates to student_pad plugin
- `set_formation_dir` — sets the training program directory for the trainer

### LLM Context Callbacks:
- `inject_teacher_system_prompt` — injects system prompt as system at top
- `inject_training_program` — injects trainer's training program as system at top

### Plugin Activation (Database as Source of Truth):
Plugin activation state is stored in the `PluginActivation` table in the database.
Plugin context callbacks check `trainer_manager.is_plugin_active(trainer_id, plugin_id)` 
directly against the database - no in-memory caching.

### Registration pattern:
Module registers, plugins implement handler methods.
Plugins never call register_option() or register_action() directly.
