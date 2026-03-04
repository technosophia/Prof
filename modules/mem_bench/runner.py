"""Business logic for memory benchmarking runs."""

from __future__ import annotations

from dataclasses import dataclass
import os
import shutil
from typing import Dict, List, Optional

import yaml

from core.logging import log
from shared.common import Message, _get_service, get_conversation_manager, get_driver, get_user_manager


@dataclass
class MemBenchCheck:
    """Single expected memory check result."""

    term: str
    found: bool


@dataclass
class MemBenchResult:
    """Outcome of one memory benchmark execution."""

    scenario_name: str
    memory_backend: str
    memory_content: str
    success: bool
    error: Optional[str]
    expected_contains: List[str]
    checks: List[MemBenchCheck]


class MemBenchRunner:
    """Replay scripted conversations and trigger memory analysis."""

    def __init__(self, driver=None, config=None):
        self.driver = driver or get_driver()
        app_config = config or _get_service("config")
        if app_config is None:
            raise RuntimeError("mem_bench: 'config' service not available")
        self.config = app_config.get("mem_bench", {})

    def run(self, scenario_path: str, memory_backend_option: str) -> MemBenchResult:
        """Execute one scenario and return memory-check output."""
        scenario = self._load_scenario(scenario_path)
        scenario_name = scenario.get("yamlmeta", {}).get("name", os.path.basename(scenario_path))
        setup = dict(scenario.get("setup") or {})
        student_name = str(setup.get("student_id") or "").strip()
        trainer_name = str(setup.get("trainer_id") or "").strip()

        if not student_name.startswith("bench_mem_") or not trainer_name.startswith("bench_mem_"):
            return MemBenchResult(
                scenario_name=scenario_name,
                memory_backend=memory_backend_option,
                memory_content="",
                success=False,
                error="Scenario setup IDs must start with 'bench_mem_'.",
                expected_contains=self._expected_terms(scenario),
                checks=[],
            )

        created_users: List[str] = []
        try:
            created_users = self._ensure_test_users(setup)
            conversation_id = get_conversation_manager().create_conversation(
                user_id=self._require_user_id(student_name),
                title=f"MemBench {scenario_name}",
                metadata={"created_via": "mem_bench"},
            )

            self.driver.set_context(
                student_id=student_name,
                trainer_id=trainer_name,
                conversation_id=conversation_id,
            )
            self.driver.switch_option("memory_backend", memory_backend_option)

            training_program = str(setup.get("training_program") or "").strip()
            if training_program:
                self.driver.do_action("set_training_program", content=training_program)

            for turn in scenario.get("conversation", []):
                role = str(turn.get("role") or "").strip()
                content = str(turn.get("content") or "")
                if role not in {"user", "assistant", "system"}:
                    raise ValueError(f"Unsupported role in conversation: {role}")
                if not content.strip():
                    raise ValueError("Conversation message content cannot be empty")
                get_conversation_manager().add_message(
                    conversation_id,
                    Message(
                        role=role,
                        content=content,
                        metadata={"created_via": "mem_bench", "replayed": True},
                    ),
                )

            action_result = self.driver.do_action("trigger_memory_analysis")
            memory_content = self._extract_memory_content(action_result)
            checks = self._build_checks(memory_content, self._expected_terms(scenario))
            success = bool(action_result.get("success") and memory_content.strip())

            return MemBenchResult(
                scenario_name=scenario_name,
                memory_backend=memory_backend_option,
                memory_content=memory_content,
                success=success,
                error=None if success else "Memory analysis did not return content.",
                expected_contains=self._expected_terms(scenario),
                checks=checks,
            )
        except Exception as exc:
            return MemBenchResult(
                scenario_name=scenario_name,
                memory_backend=memory_backend_option,
                memory_content="",
                success=False,
                error=str(exc),
                expected_contains=self._expected_terms(scenario),
                checks=[],
            )
        finally:
            if self.config.get("cleanup_after_run", False):
                self._cleanup_users(created_users)

    def ensure_default_scenarios(self) -> None:
        """Copy bundled scenarios to configured scenarios directory if missing."""
        target_dir = self.config.get("scenarios_dir", "data/mem_bench/scenarios")
        os.makedirs(target_dir, exist_ok=True)
        source_dir = os.path.join(os.path.dirname(__file__), "scenarios")
        for file_name in os.listdir(source_dir):
            if not file_name.endswith(".yaml"):
                continue
            src = os.path.join(source_dir, file_name)
            dst = os.path.join(target_dir, file_name)
            if not os.path.exists(dst):
                shutil.copyfile(src, dst)

    def list_scenario_files(self) -> List[str]:
        """List available scenario YAML files from configured scenarios directory."""
        scenarios_dir = self.config.get("scenarios_dir", "data/mem_bench/scenarios")
        if not os.path.isdir(scenarios_dir):
            return []
        return sorted(
            os.path.join(scenarios_dir, name)
            for name in os.listdir(scenarios_dir)
            if name.endswith(".yaml") or name.endswith(".yml")
        )

    @staticmethod
    def _load_scenario(scenario_path: str) -> Dict:
        with open(scenario_path, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}

    @staticmethod
    def _expected_terms(scenario: Dict) -> List[str]:
        return [str(item) for item in (scenario.get("expected_memory_contains") or [])]

    @staticmethod
    def _build_checks(memory_content: str, expected_terms: List[str]) -> List[MemBenchCheck]:
        lowered = (memory_content or "").lower()
        return [MemBenchCheck(term=term, found=term.lower() in lowered) for term in expected_terms]

    @staticmethod
    def _extract_memory_content(action_result: Dict) -> str:
        details = action_result.get("details") if isinstance(action_result, dict) else None
        if isinstance(details, dict):
            for plugin_result in details.values():
                if isinstance(plugin_result, dict) and plugin_result.get("memory_content"):
                    return str(plugin_result.get("memory_content"))
        return ""

    @staticmethod
    def _require_user_id(user_name: str) -> str:
        user = get_user_manager().get_user_by_name(user_name)
        if not user:
            raise ValueError(f"User not found: {user_name}")
        return user["id"]

    @staticmethod
    def _ensure_test_users(setup: Dict) -> List[str]:
        created = []
        user_manager = get_user_manager()

        trainer_name = setup.get("trainer_id")
        student_name = setup.get("student_id")

        trainer = user_manager.get_user_by_name(trainer_name) if trainer_name else None
        if trainer is None and trainer_name:
            trainer_id, _ = user_manager.create_user(name=trainer_name, role="master")
            created.append(trainer_id)
            trainer = user_manager.get_user(trainer_id)
            log("info", f"mem_bench: created trainer {trainer_name}")

        student = user_manager.get_user_by_name(student_name) if student_name else None
        if student is None and student_name and trainer:
            student_id, _ = user_manager.create_user(name=student_name, role="normal", parent_id=trainer["id"])
            created.append(student_id)
            log("info", f"mem_bench: created student {student_name}")

        return created

    @staticmethod
    def _cleanup_users(user_ids: List[str]) -> None:
        if not user_ids:
            return
        user_manager = get_user_manager()
        for user_id in reversed(user_ids):
            user = user_manager.get_user(user_id)
            if user and user_manager.delete_user(user_id):
                log("info", f"mem_bench: deleted test user {user.get('name', user_id)}")
