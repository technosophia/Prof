import yaml

import modules.trainer as trainer_module
from shared.common import get_driver


class FakePlugin:
    def __init__(self, name):
        self.id = name
        self._is_active = False
        self.analysis_called = 0
        self.notes = []

    def _mark_active(self):
        self._is_active = True

    def _mark_inactive(self):
        self._is_active = False

    def on_activate(self, trainer_id):
        return None

    def on_deactivate(self, trainer_id):
        return None

    def get_memory_context(self, user_id, messages):
        if not self._is_active:
            return None
        return (f"ctx-{self.id}", "system", "top")

    def _action_trigger_analysis(self, context, **params):
        self.analysis_called += 1
        if self.id == "student_pad":
            return {"success": False, "reason": "unsupported", "plugin": self.id}
        return {"success": True, "plugin": self.id}

    def add_note(self, student_id, content, topic=""):
        self.notes.append((student_id, content, topic))
        return {"saved": True}


class FakeManager:
    def __init__(self, plugins):
        self.plugins = plugins

    def get_plugin(self, name):
        return self.plugins.get(name)

    def get_all_plugins(self):
        return list(self.plugins.values())


def _setup(monkeypatch):
    driver = get_driver()
    driver._options = {}
    driver._active_options = {}
    driver._actions = {}
    driver.clear_context()

    trainer_module._DRIVER_REGISTRATION_DONE = False

    plugins = {
        "memory": FakePlugin("memory"),
        "pedagogical_memory": FakePlugin("pedagogical_memory"),
        "student_pad": FakePlugin("student_pad"),
    }
    manager = FakeManager(plugins)

    monkeypatch.setattr(trainer_module, "get_plugin_manager", lambda: manager)
    monkeypatch.setattr(trainer_module, "get_db_manager", lambda: object())

    trainer_module.initialize()
    return driver, plugins


def test_memory_backend_options_registered(monkeypatch):
    driver, _ = _setup(monkeypatch)
    names = [opt["name"] for opt in driver.list_options()["memory_backend"]]
    assert "memory" in names
    assert "pedagogical_memory" in names
    assert "student_pad" in names
    assert "pedagogical_memory+student_pad" in names


def test_switch_to_memory_marks_active(monkeypatch):
    driver, plugins = _setup(monkeypatch)
    driver.set_context(trainer_id="t1")
    driver.switch_option("memory_backend", "memory")
    assert plugins["memory"]._is_active is True


def test_switch_away_marks_previous_inactive(monkeypatch):
    driver, plugins = _setup(monkeypatch)
    driver.set_context(trainer_id="t1")
    driver.switch_option("memory_backend", "memory")
    driver.switch_option("memory_backend", "pedagogical_memory")
    assert plugins["memory"]._is_active is False
    assert plugins["pedagogical_memory"]._is_active is True


def test_inactive_plugin_returns_none_from_context(monkeypatch):
    _, plugins = _setup(monkeypatch)
    plugins["memory"]._mark_inactive()
    assert plugins["memory"].get_memory_context("s1", []) is None


def test_active_plugin_injects_context(monkeypatch):
    _, plugins = _setup(monkeypatch)
    plugins["memory"]._mark_active()
    assert plugins["memory"].get_memory_context("s1", []) is not None


def test_switch_to_combination_marks_both_active(monkeypatch):
    driver, plugins = _setup(monkeypatch)
    driver.set_context(trainer_id="t1")
    driver.switch_option("memory_backend", "pedagogical_memory+student_pad")
    assert plugins["pedagogical_memory"]._is_active is True
    assert plugins["student_pad"]._is_active is True


def test_switch_from_combination_marks_both_inactive(monkeypatch):
    driver, plugins = _setup(monkeypatch)
    driver.set_context(trainer_id="t1")
    driver.switch_option("memory_backend", "pedagogical_memory+student_pad")
    driver.switch_option("memory_backend", "memory")
    assert plugins["pedagogical_memory"]._is_active is False
    assert plugins["student_pad"]._is_active is False


def test_trigger_analysis_dispatches_to_active(monkeypatch):
    driver, plugins = _setup(monkeypatch)
    driver.set_context(trainer_id="t1", student_id="s1")
    driver.switch_option("memory_backend", "memory")
    result = driver.do_action("trigger_memory_analysis")
    assert result["details"]["memory"]["plugin"] == "memory"
    assert plugins["memory"].analysis_called == 1


def test_trigger_analysis_combination(monkeypatch):
    driver, plugins = _setup(monkeypatch)
    driver.set_context(trainer_id="t1", student_id="s1")
    driver.switch_option("memory_backend", "pedagogical_memory+student_pad")
    result = driver.do_action("trigger_memory_analysis")
    assert "pedagogical_memory" in result["details"]
    assert "student_pad" in result["details"]
    assert plugins["pedagogical_memory"].analysis_called == 1
    assert plugins["student_pad"].analysis_called == 1


def test_student_pad_trigger_returns_unsupported_not_raises(monkeypatch):
    driver, _ = _setup(monkeypatch)
    driver.set_context(trainer_id="t1", student_id="s1")
    driver.switch_option("memory_backend", "student_pad")
    result = driver.do_action("trigger_memory_analysis")
    assert result["details"]["student_pad"]["reason"] == "unsupported"


def test_add_note_warns_when_pad_not_active(monkeypatch):
    driver, plugins = _setup(monkeypatch)
    driver.set_context(trainer_id="t1", student_id="s1")
    driver.switch_option("memory_backend", "memory")
    result = driver.do_action("add_student_note", content="hello")
    assert result["saved"] is True
    assert result["warned"] is True
    assert plugins["student_pad"].notes


def test_trainer_id_none_in_context_logs_warning(monkeypatch):
    driver, plugins = _setup(monkeypatch)
    warnings = []

    def fake_log(level, message, *args, **kwargs):
        if level == "warning":
            warnings.append(message)

    monkeypatch.setattr(trainer_module, "log", fake_log)
    driver.switch_option("memory_backend", "memory")
    assert plugins["memory"]._is_active is False
    assert any("trainer_id not set" in msg for msg in warnings)


def test_example_basic_scenario_has_no_trainer_actions():
    with open("modules/benchmarker/scenarios/example_basic.yaml", "r", encoding="utf-8") as f:
        scenario = yaml.safe_load(f)

    forbidden = {"set_training_program", "trigger_memory_analysis", "add_student_note"}
    actions = [step.get("action") for step in scenario.get("steps", [])]
    assert not (set(actions) & forbidden)
    assert "training_program" not in (scenario.get("setup") or {})


def test_trainer_ui_initialize_calls_trainer_initialize(monkeypatch):
    import modules.trainer.trainer_ui as trainer_ui

    called = {"count": 0}

    def fake_initialize():
        called["count"] += 1
        return True

    monkeypatch.setattr(trainer_ui, "initialize_trainer", fake_initialize)

    assert trainer_ui.inject_ui_initialize() is True
    assert called["count"] == 1
