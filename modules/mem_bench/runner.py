"""Business logic for memory benchmarking runs."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import shutil
from typing import Dict, List, Optional

import yaml

from core.logging import capture_log_end, capture_log_start, log
from modules.mem_bench.evaluators import get_evaluators
from modules.mem_bench.evaluators.base import EvalResult
from shared.common import Message, _get_service, get_conversation_manager, get_driver, get_user_manager


@dataclass
class MemBenchCheck:
    """Single expected memory check result."""

    term: str
    found: bool
    score: float = 1.0
    check_type: str = "contains"


@dataclass
class RoundResult:
    round_index: int
    description: str
    conversation_id: str
    memory_content: str
    checks: List[MemBenchCheck]
    success: bool
    conversation: List[Dict] = field(default_factory=list)


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
    trace_logs: List[str]
    cleared_conversation_count: int
    scenario_path: str = ""
    rounds: List[RoundResult] = field(default_factory=list)
    eval_results: Dict[str, EvalResult] = field(default_factory=dict)
    rubric_path: Optional[str] = None
    is_cumulative: bool = False


class MemBenchRunner:
    """Replay scripted conversations and trigger memory analysis."""

    REQUIRED_SCENARIO_SECTIONS = {"setup", "conversation", "expected_memory_contains"}
    RECOMMENDED_SCENARIO_SECTIONS = {"meta", "yamlmeta"}

    def __init__(self, driver=None, config=None):
        self.driver = driver or get_driver()
        app_config = config or _get_service("config")
        if app_config is None:
            raise RuntimeError("mem_bench: 'config' service not available")
        self.config = app_config.get("mem_bench", {})
        self.scenarios_dir = self.config.get("scenarios_dir", "data/mem_bench/scenarios")
        log("info", f"mem_bench: scenarios_dir={self.scenarios_dir}")

    @property
    def scenarios_directory(self) -> str:
        return self.scenarios_dir

    def run(
        self,
        scenario_path: str,
        memory_backend_option: str,
        rubric_path: Optional[str] = None,
        formation_dir: Optional[str] = None,
        capture_trace: bool = False,
    ) -> MemBenchResult:
        log("info", f"mem_bench.run: received formation_dir='{formation_dir}'")
        if capture_trace:
            capture_log_start("INFO", max_messages=1000)
        scenario = self._load_scenario(scenario_path)
        scenario_name = scenario.get("yamlmeta", {}).get("name", os.path.basename(scenario_path))
        setup = dict(scenario.get("setup") or {})
        training_program = str(setup.get("training_program") or "").strip()
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
                trace_logs=self._consume_logs() if capture_trace else [],
                cleared_conversation_count=0,
                scenario_path=scenario_path,
                rubric_path=rubric_path,
                is_cumulative=bool(scenario.get("rounds")),
            )

        created_users: List[str] = []
        cleared_conversation_count = 0
        round_results: List[RoundResult] = []
        try:
            users = self._ensure_test_users(setup)
            created_users = users["created_user_ids"]
            student_id = users["student_id"]
            trainer_id = users["trainer_id"]

            # IMPORTANT: Configure the trainer with formation BEFORE any plugin operations
            if formation_dir:
                log("info", f"mem_bench: Configuring trainer {trainer_id} with formation dir {formation_dir}")
                self._configure_trainer_with_formation(trainer_id, formation_dir)
                self._refresh_plugin_trainer_managers(trainer_id)
            else:
                log("warning", "mem_bench: No formation_dir provided")

            # Now set the driver context and proceed
            cleared_conversation_count = self._delete_user_conversations(student_id)

            self.driver.set_context(student_id=student_id, trainer_id=trainer_id)
            self.driver.switch_option("memory_backend", memory_backend_option)

            # If training program is specified in the scenario, use it
            if training_program:
                self.driver.do_action("set_training_program", content=training_program)

            rounds, is_cumulative = self._normalize_rounds(scenario)
            for idx, round_item in enumerate(rounds, start=1):
                one = self._execute_round(
                    scenario_name=scenario_name,
                    scenario_round=round_item,
                    round_index=idx,
                    student_id=student_id,
                    trainer_id=trainer_id,
                )
                round_results.append(one)

            final_round = round_results[-1] if round_results else None
            final_memory = final_round.memory_content if final_round else ""
            top_checks = final_round.checks if final_round else []
            scenario_for_eval = dict(scenario)
            if final_round:
                eval_ref = rounds[-1]
                scenario_for_eval["expected_memory_contains"] = list(eval_ref.get("expected_memory_contains") or [])
                scenario_for_eval["expected_memory_excludes"] = list(eval_ref.get("expected_memory_excludes") or [])

            rubric = self._load_rubric(rubric_path) if rubric_path else None
            eval_results = self._run_evaluators(
                memory_content=final_memory,
                scenario=scenario_for_eval,
                training_program=training_program,
                rubric=rubric,
                rounds=round_results,
            )

            success = bool(round_results and all(r.success for r in round_results) and final_memory.strip())
            return MemBenchResult(
                scenario_name=scenario_name,
                memory_backend=memory_backend_option,
                memory_content=final_memory,
                success=success,
                error=None if success else "Memory analysis did not return content.",
                expected_contains=self._expected_terms(scenario_for_eval),
                checks=top_checks,
                trace_logs=self._consume_logs() if capture_trace else [],
                cleared_conversation_count=cleared_conversation_count,
                scenario_path=scenario_path,
                rounds=round_results if is_cumulative else [],
                eval_results=eval_results,
                rubric_path=rubric_path,
                is_cumulative=is_cumulative,
            )
        except Exception as exc:
            log("error", f"mem_bench: run failed: {exc}", stacktrace=True)
            return MemBenchResult(
                scenario_name=scenario_name,
                memory_backend=memory_backend_option,
                memory_content="",
                success=False,
                error=str(exc),
                expected_contains=self._expected_terms(scenario),
                checks=[],
                trace_logs=self._consume_logs() if capture_trace else [],
                cleared_conversation_count=cleared_conversation_count,
                scenario_path=scenario_path,
                rounds=round_results if scenario.get("rounds") else [],
                rubric_path=rubric_path,
                is_cumulative=bool(scenario.get("rounds")),
            )
        finally:
            if self.config.get("cleanup_after_run", False):
                self._cleanup_users(created_users)

    def _execute_round(self, scenario_name: str, scenario_round: Dict, round_index: int, student_id: str, trainer_id: str) -> RoundResult:
        conversation_id = get_conversation_manager().create_conversation(
            user_id=student_id,
            title=f"MemBench {scenario_name} R{round_index}",
            metadata={"created_via": "mem_bench", "round": round_index},
        )
        self.driver.set_context(student_id=student_id, trainer_id=trainer_id, conversation_id=conversation_id)

        for turn in scenario_round.get("conversation", []):
            role = str(turn.get("role") or "").strip()
            content = str(turn.get("content") or "")
            if role not in {"user", "assistant", "system"}:
                raise ValueError(f"Unsupported role in conversation: {role}")
            if not content.strip():
                raise ValueError("Conversation message content cannot be empty")
            get_conversation_manager().add_message(
                conversation_id,
                Message(role=role, content=content, metadata={"created_via": "mem_bench", "replayed": True, "round": round_index}),
            )

        action_result = self.driver.do_action("trigger_memory_analysis")
        memory_content = self._extract_memory_content(action_result)
        checks = self._build_checks(
            memory_content,
            [str(x) for x in (scenario_round.get("expected_memory_contains") or [])],
            [str(x) for x in (scenario_round.get("expected_memory_excludes") or [])],
        )
        success = bool(action_result.get("success") and memory_content.strip() and all(c.found for c in checks))
        return RoundResult(
            round_index=round_index,
            description=str(scenario_round.get("description") or f"Round {round_index}"),
            conversation_id=conversation_id,
            memory_content=memory_content,
            checks=checks,
            success=success,
            conversation=list(scenario_round.get("conversation") or []),
        )

    def _run_evaluators(
        self,
        memory_content: str,
        scenario: Dict,
        training_program: str,
        rubric: Optional[Dict],
        rounds: List[RoundResult],
    ) -> Dict[str, EvalResult]:
        results: Dict[str, EvalResult] = {}
        for evaluator in get_evaluators():
            try:
                results[evaluator.id] = evaluator.evaluate(
                    memory_content,
                    scenario,
                    {
                        "training_program": training_program,
                        "rubric": rubric,
                        "round_index": rounds[-1].round_index if rounds else 0,
                        "all_rounds_memory": [r.memory_content for r in rounds],
                    },
                )
            except Exception as exc:
                log("error", f"mem_bench evaluator '{evaluator.id}' failed: {exc}", stacktrace=True)
        return results

    def _refresh_plugin_trainer_managers(self, trainer_id: str) -> None:
        """Force all plugins to refresh their trainer manager reference."""
        try:
            from modules.trainer.plugin_base import get_plugin_manager
            plugin_manager = get_plugin_manager()

            # Get the trainer manager
            from modules.trainer.manager import get_trainer_manager
            trainer_manager = get_trainer_manager()

            # Set the trainer manager on the plugin manager
            plugin_manager.set_trainer_manager(trainer_manager)

            log("info", f"mem_bench: Refreshed plugin manager with trainer manager for trainer {trainer_id}")
        except Exception as e:
            log("warning", f"mem_bench: Failed to refresh plugin trainer managers: {e}")

    def _configure_trainer_with_formation(self, trainer_id: str, formation_dir: str) -> None:
        """Configure a trainer with the selected formation directory."""
        try:
            # Get the trainer manager
            from modules.trainer.manager import get_trainer_manager
            trainer_manager = get_trainer_manager()

            log("info", f"mem_bench: Configuring trainer {trainer_id} with formation_dir: {formation_dir}")

            # Check if this is already a relative path (just the formation name)
            # The MaterialLoader will add the 'material/' prefix automatically
            if '/' not in formation_dir and '\\' not in formation_dir:
                # This is likely just a formation name like "attention"
                log("info", f"mem_bench: Using relative formation name: {formation_dir}")

                # Verify the formation exists by checking if we can get the program
                try:
                    program = trainer_manager.get_program(trainer_id)
                    if program:
                        log("info", f"mem_bench: Successfully verified formation {formation_dir}")
                except Exception as e:
                    log("warning", f"mem_bench: Could not verify formation {formation_dir}: {e}")

            # Set the formation directory for the trainer
            success = trainer_manager.set_formation_dir(trainer_id, formation_dir)
            if success:
                log("info", f"mem_bench: SUCCESS - configured trainer {trainer_id} with formation dir {formation_dir}")
            else:
                log("warning", f"mem_bench: FAILED - could not set formation dir for trainer {trainer_id}")

        except Exception as e:
            log("warning", f"mem_bench: failed to configure trainer with formation: {e}", stacktrace=True)

    def run_matrix(
        self,
        scenario_paths: List[str],
        backends: List[str],
        rubric_path: Optional[str] = None,
        formation_dir: Optional[str] = None,  # This will be the scenario directory
        capture_trace: bool = False,
    ) -> List[MemBenchResult]:
        matrix_results: List[MemBenchResult] = []
        for scenario_path in scenario_paths:
            for backend in backends:
                run_result = self.run(
                    scenario_path=scenario_path,
                    memory_backend_option=backend,
                    rubric_path=rubric_path,
                    formation_dir=formation_dir,  # Pass the scenario directory
                    capture_trace=capture_trace,
                )
                run_result.scenario_path = scenario_path
                matrix_results.append(run_result)
        return matrix_results

    def ensure_default_scenarios(self) -> None:
        os.makedirs(self.scenarios_dir, exist_ok=True)
        source_dir = os.path.join(os.path.dirname(__file__), "scenarios")
        for file_name in os.listdir(source_dir):
            if not file_name.endswith(".yaml"):
                continue
            src = os.path.join(source_dir, file_name)
            dst = os.path.join(self.scenarios_dir, file_name)
            if not os.path.exists(dst):
                shutil.copyfile(src, dst)

    def is_valid_scenario(self, file_path: str) -> bool:
        if not os.path.isfile(file_path) or not (file_path.endswith('.yaml') or file_path.endswith('.yml')):
            return False
        try:
            data = self._load_scenario(file_path)
            if not isinstance(data, dict) or "setup" not in data:
                return False

            rounds = data.get("rounds")
            if isinstance(rounds, list):
                if not rounds:
                    return False
                return all(self._is_valid_round(item) for item in rounds)

            has_required = all(section in data for section in self.REQUIRED_SCENARIO_SECTIONS)
            if not has_required:
                return False
            return self._is_valid_round(data)
        except (yaml.YAMLError, Exception):
            return False

    @staticmethod
    def _is_valid_round(data: Dict) -> bool:
        conversation = data.get('conversation', [])
        if not isinstance(conversation, list) or len(conversation) == 0:
            return False
        for turn in conversation:
            if not isinstance(turn, dict):
                return False
            if 'role' not in turn or 'content' not in turn:
                return False
            if turn['role'] not in {'user', 'assistant', 'system'}:
                return False
        expected_terms = data.get('expected_memory_contains', [])
        if not isinstance(expected_terms, list) or len(expected_terms) == 0:
            return False
        excludes = data.get('expected_memory_excludes', [])
        if excludes is not None and not isinstance(excludes, list):
            return False
        return True

    def list_scenario_files(self) -> List[str]:
        if not os.path.isdir(self.scenarios_dir):
            return []
        valid_scenarios = []
        for root, _, files in os.walk(self.scenarios_dir):
            for file in files:
                if file.endswith(('.yaml', '.yml')):
                    file_path = os.path.join(root, file)
                    if self.is_valid_scenario(file_path):
                        valid_scenarios.append(file_path)
        return sorted(valid_scenarios)

    def get_relative_scenario_path(self, absolute_path: str) -> str:
        try:
            return os.path.relpath(absolute_path, self.scenarios_dir)
        except ValueError:
            return os.path.basename(absolute_path)

    @staticmethod
    def _load_scenario(scenario_path: str) -> Dict:
        with open(scenario_path, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}

    @staticmethod
    def _load_rubric(path: Optional[str]) -> Optional[Dict]:
        if not path:
            return None
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
                return data if isinstance(data, dict) else None
        except Exception as exc:
            log("error", f"mem_bench: failed loading rubric from {path}: {exc}")
            return None

    @staticmethod
    def _normalize_rounds(scenario: Dict) -> tuple[list[Dict], bool]:
        rounds = scenario.get("rounds")
        if isinstance(rounds, list) and rounds:
            return rounds, True
        return [
            {
                "round": 1,
                "description": "Single round",
                "conversation": scenario.get("conversation") or [],
                "expected_memory_contains": scenario.get("expected_memory_contains") or [],
                "expected_memory_excludes": scenario.get("expected_memory_excludes") or [],
                "is_final": True,
            }
        ], False

    @staticmethod
    def _expected_terms(scenario: Dict) -> List[str]:
        return [str(item) for item in (scenario.get("expected_memory_contains") or [])]

    @staticmethod
    def _build_checks(memory_content: str, expected_terms: List[str], excluded_terms: Optional[List[str]] = None) -> List[MemBenchCheck]:
        lowered = (memory_content or "").lower()
        checks = [MemBenchCheck(term=term, found=term.lower() in lowered, score=1.0 if term.lower() in lowered else 0.0, check_type="contains") for term in expected_terms]
        for term in excluded_terms or []:
            passed = term.lower() not in lowered
            checks.append(MemBenchCheck(term=term, found=passed, score=1.0 if passed else 0.0, check_type="excludes"))
        return checks

    @staticmethod
    def _extract_memory_content(action_result: Dict) -> str:
        details = action_result.get("details") if isinstance(action_result, dict) else None
        if isinstance(details, dict):
            for plugin_result in details.values():
                if isinstance(plugin_result, dict) and plugin_result.get("memory_content"):
                    return str(plugin_result.get("memory_content"))
        return ""

    @staticmethod
    def _ensure_test_users(setup: Dict) -> Dict[str, object]:
        created_user_ids: List[str] = []
        user_manager = get_user_manager()
        trainer_name = setup.get("trainer_id")
        student_name = setup.get("student_id")

        trainer = None
        student = None

        # Handle trainer creation/retrieval
        if trainer_name:
            trainer = user_manager.get_user_by_name(trainer_name)
            if trainer is None:
                trainer_id, _ = user_manager.create_user(name=trainer_name, role="master")
                created_user_ids.append(trainer_id)
                trainer = user_manager.get_user(trainer_id)
            else:
                # NEW: Clear any existing formation_dir for this test trainer
                try:
                    from modules.trainer.manager import get_trainer_manager
                    trainer_manager = get_trainer_manager()
                    # Set to empty string to clear any previous formation
                    trainer_manager.set_formation_dir(trainer["id"], "")
                    log("info", f"mem_bench: Cleared existing formation_dir for trainer {trainer_name}")
                except Exception as e:
                    log("warning", f"mem_bench: Could not clear trainer formation_dir: {e}")

        # Handle student creation/retrieval
        if student_name and trainer:
            student = user_manager.get_user_by_name(student_name)
            if student is None:
                student_id, _ = user_manager.create_user(name=student_name, role="normal", parent_id=trainer["id"])
                created_user_ids.append(student_id)
                student = user_manager.get_user(student_id)

        # Verify both users exist
        if not trainer or not student:
            # Log what went wrong for debugging
            missing = []
            if trainer_name and not trainer:
                missing.append(f"trainer '{trainer_name}'")
            if student_name and not student:
                missing.append(f"student '{student_name}'")
            raise ValueError(f"mem_bench: failed to provision test users - missing: {', '.join(missing)}")

        return {
            "created_user_ids": created_user_ids,
            "trainer_id": trainer["id"],
            "student_id": student["id"]
        }

    @staticmethod
    def _delete_user_conversations(user_id: str) -> int:
        manager = get_conversation_manager()
        conversations = manager.get_user_conversations(user_id, include_inactive=True)
        cleared = 0
        for conversation in conversations:
            conversation_id = conversation.get("id")
            if conversation_id and manager.delete_conversation(conversation_id):
                cleared += 1
        return cleared

    @staticmethod
    def _consume_logs() -> List[str]:
        logs = capture_log_end()
        if not logs:
            return []
        flat_logs: List[str] = []
        for entry in logs:
            if isinstance(entry, list):
                flat_logs.extend(str(item) for item in entry)
            else:
                flat_logs.append(str(entry))
        return flat_logs

    @staticmethod
    def _cleanup_users(user_ids: List[str]) -> None:
        if not user_ids:
            return
        user_manager = get_user_manager()
        for user_id in reversed(user_ids):
            user = user_manager.get_user(user_id)
            if user:
                user_manager.delete_user(user_id)
