# SKILL: Building or extending a module

Reference implementation: `modules/demo/`  
Minimal working example: `modules/test/`

---

## Before you start — read these first

| File | What it tells you |
|------|------------------|
| `modules/AGENTS.md` | What a module is, directory structure, rules |
| `shared/AGENTS.md` | What shared services exist and how to access them |
| `shared/API.md` and `shared/API_*.md` | Full API for each shared service |
| `_docs/CODE.md` | Coding standards, config, prompts, test rules |

Only open `modules/demo/demo_core.py` when you need a concrete calling example.

---

## Mandatory files

```
modules/my_module/
  module.json          ← name, version, enabled_by_default, dependencies: []
  config.json          ← module config (auto-loaded under modules.my_module.*)
  __init__.py          ← wires on_module_activated / on_module_deactivated
  translations/
    en.json            ← UI strings, nested under module name
    fr.json
  prompt.en.yml        ← LLM prompts, nested under module name
  prompt.fr.yml
  tests/
    __init__.py        ← required for pytest discovery
    test_my_module.py
```

UI files (only if the module has a UI):
```
  my_module_ui.py        ← inject_ui_initialize() + inject_ui_main_footer()
  my_module_admin_ui.py  ← inject_ui_admin_tab() → (tab_name, render_fn)
```

Business logic files: use **your module's own structure**, not the shape of shared.  
→ See `modules/demo/demo_core.py` for calling patterns.

---

## UI separation — critical architectural rule

Every module MUST separate core logic from UX so it runs headless.

```
my_module_core.py      ← pure Python, no Streamlit import, testable headless
my_module_ui.py        ← all Streamlit code for the main page
my_module_admin_ui.py  ← all Streamlit code for the admin panel
```

### `my_module_ui.py` has two injection points:

```python
def inject_ui_initialize() -> None:
    """
    Called once at app startup (headless-tolerant).
    ONLY st.session_state initialization here.
    No business logic. No data fetching.
    """
    if "my_module_key" not in st.session_state:
        st.session_state["my_module_key"] = None

def inject_ui_main_footer() -> None:
    """Called each render cycle. All display logic goes here."""
    ...
```

### `my_module_admin_ui.py`:

```python
def inject_ui_admin_tab():
    """Returns (tab_name, render_function) for the admin panel."""
    return ("My Module", _show_admin_content)
```

→ See `modules/demo/demo_ui.py` and `modules/demo/demo_admin_ui.py` for full examples.

---

## Lifecycle (`__init__.py`)

```python
def on_module_activated(services) -> None:
    """Headless-safe. Register callbacks, options, actions here."""
    ...

def on_module_deactivated() -> None:
    """Mirror of on_module_activated. Unregister everything."""
    ...
```

`services` is a `ServiceLocator`. Access: `services.get("user_manager")`.  
→ See `modules/demo/demo_core.py` → `demo_on_module_activated()` for a full example.  
→ See `shared/AGENTS.md` for the list of available services.

---

## Config, translations, prompts

**Config** — values in `config.json` auto-load under `modules.my_module.*`:
```python
config.get("modules.my_module.my_key", default)
```
Make the value in `config.json` **distinct from the code default** so you can see visually whether the file loaded.  
→ See `modules/demo/config.json` and `demo_core.get_demo_config_value()`.

**Translations** — nested JSON, namespace under module name:
```python
_("my_module.my_key")   # in UI: from st_shared.cached import _
```
Add a dedicated check key (not reusing a key shown in the UI label) so you can tell if the file loaded.  
→ See `modules/demo/translations/en.json` → key `demo.check_translation`.

**Prompts** — YAML nested under module name:
```python
prompt_manager.get_prompt("my_module.my_key", "⚠ NOT LOADED", language)
```
Use `"⚠ NOT LOADED"` as default so the UI shows file-not-found visually.  
→ See `modules/demo/prompt.en.yml` and `demo_core.get_demo_prompt()`.

---

## Registering callbacks

All registrations go in `on_module_activated(services)`, **never at import time**.  
All unregistrations go in `on_module_deactivated()` — must mirror exactly.

```python
# LLM context injection (RAG, memory, system prompt additions)
# fn(message: str, history: list) → (system_addition, before_msg, after_msg)
register_llm_context_callback(fn)

# React to any user message (trigger indexing, memory, analytics)
# fn(conversation_id: str, messages: List[Message]) → None
# 'messages' is full history including the new message
register_user_message_callback(fn)

# Driver: feature flags (for Benchmarker / test harness)
register_option(group, name, activate_fn, deactivate_fn, description)

# Driver: testable callable endpoints
register_action(name, handler_fn, description)
```

→ See `modules/demo/demo_core.py` → `demo_on_module_activated()`.

---

## Tests

Tests use the root `conftest.py` — **do not create a local conftest**.  
`conftest.py` calls `register_all_services()` and `module_handler.activate_all()` before tests run.  
Use real services — no mocking of `shared.common`.

**Pattern: inject managers as arguments**
```python
from shared.common import get_user_manager
from modules.my_module.my_core import my_function

def test_something():
    um = get_user_manager()       # real instance from conftest setup
    result = my_function(um, ...) # call core logic directly
    assert ...
```

**Regression imports** — detect shared API changes early:
```python
class TestSharedAPIContract:
    def test_user_manager_importable(self):
        from shared.common import get_user_manager
        assert callable(get_user_manager)
    # one test per symbol your module uses from shared.common
```
→ See `modules/demo/tests/test_demo.py` → `TestSharedCommonAPIContract`.

**ServiceLocator regression**:
```python
from shared.module_handler import module_handler
services = module_handler.get_services()
assert services is not None
assert "user_manager" in services
```
→ See `TestServicesIntrospection` in the demo tests.

---

## Checklist

- [ ] `module.json` with `name`, `dependencies: []`
- [ ] `config.json` — value distinct from code default for visual verification
- [ ] `__init__.py` with `on_module_activated(services)` and `on_module_deactivated()`
- [ ] Core logic file(s): no Streamlit imports, runs headless
- [ ] `translations/en.json` and `fr.json` — include a `check_translation` key
- [ ] `prompt.en.yml` and `fr.yml` — default sentinel `"⚠ NOT LOADED"` in code
- [ ] `inject_ui_initialize()` — only `st.session_state` init, nothing else
- [ ] `inject_ui_main_footer()` — display only
- [ ] `inject_ui_admin_tab()` — returns `(tab_name, render_fn)`
- [ ] All settings namespaced: `"my_module.key_name"`
- [ ] All callbacks registered in `on_module_activated`, unregistered in `on_module_deactivated`
- [ ] `tests/__init__.py` present
- [ ] Tests use real services (no `@patch` on `shared.common`)
- [ ] `TestSharedAPIContract` covers all shared.common symbols used
- [ ] Visual check: run the app → Infrastructure tab shows ✅ for config, translations, prompts → Services tab shows ✅ for all services
