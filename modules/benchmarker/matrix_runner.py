"""Matrix execution orchestration for benchmark scenarios."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from typing import Callable, Dict, List, Optional

import yaml

from core.logging import log
from modules.benchmarker.runner import RunResult, ScenarioRunner
from modules.benchmarker.scoring_pipeline import get_scoring_pipeline
from shared.common import get_available_llms, get_driver, _get_service
from modules.benchmarker.benchmarker import BenchmarkRun
from st_shared.cached import get_db_manager

@dataclass
class MatrixCell:
    llm_id: str
    memory_backend: str
    rag_engine: str


@dataclass
class MatrixWarning:
    scenario_path: str
    cell: MatrixCell
    message: str
    blocking: bool


@dataclass
class MatrixCellResult:
    scenario_name: str
    scenario_path: str
    cell: MatrixCell
    run_result: Optional[RunResult]
    session_path: str
    scoring_errors: List[str] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""


@dataclass
class MatrixRunResult:
    cells: List[MatrixCellResult]
    total: int
    completed: int
    failed: int
    skipped: int


class _BatchContainer:
    """No-op container used by scorers in batch mode."""

    def __init__(self):
        self.messages: List[str] = []

    def info(self, text: str) -> None:
        self.messages.append(str(text))

    def warning(self, text: str) -> None:
        self.messages.append(str(text))

    def success(self, text: str) -> None:
        self.messages.append(str(text))

    def error(self, text: str) -> None:
        self.messages.append(str(text))

    def dataframe(self, *args, **kwargs) -> None:  # noqa: ANN002,ANN003
        return


class MatrixRunner:
    """Run scenario × option matrix and auto-score each resulting session."""

    def __init__(self, progress_callback: Optional[Callable[[int, int, str], None]] = None, driver=None, config=None, db_manager=None):
        self.driver = driver or get_driver()
        self.db_manager = db_manager or _get_service("db_manager")
        if self.db_manager is None:
            raise RuntimeError("benchmarker: 'db_manager' service not available")
        self.scenario_runner = ScenarioRunner(driver=self.driver, config=config, db_manager=self.db_manager)
        self.pipeline = get_scoring_pipeline()
        self.progress_callback = progress_callback

    def _cells(self, llm_ids: List[str], memory_backends: List[str], rag_engines: List[str]) -> List[MatrixCell]:
        llm_values = llm_ids or [""]
        memory_values = memory_backends or [""]
        rag_values = rag_engines or [""]
        return [
            MatrixCell(llm_id=llm, memory_backend=memory, rag_engine=rag)
            for llm in llm_values
            for memory in memory_values
            for rag in rag_values
        ]

    def validate_matrix(
        self,
        scenario_paths: List[str],
        llm_ids: List[str],
        memory_backends: List[str],
        rag_engines: List[str],
    ) -> List[MatrixWarning]:
        warnings: List[MatrixWarning] = []
        driver_options = self.driver.list_options()
        memory_names = {opt.get("name") for opt in driver_options.get("memory_backend", [])}
        rag_names = {opt.get("name") for opt in driver_options.get("rag_engine", [])}
        try:
            available_llms = {str(item.get("id", "")) for item in get_available_llms() if item.get("id")}
        except Exception as exc:
            log("warning", f"Unable to fetch available LLMs for matrix validation: {exc}", stacktrace=True)
            available_llms = set()

        for scenario_path in scenario_paths:
            scenario = self._load_yaml(scenario_path)
            for cell in self._cells(llm_ids, memory_backends, rag_engines):
                injected = self._inject_cell(scenario, cell)
                validation_errors = self.scenario_runner.validate_scenario(injected)
                for err in validation_errors:
                    warnings.append(
                        MatrixWarning(
                            scenario_path=scenario_path,
                            cell=cell,
                            message=err,
                            blocking=True,
                        )
                    )

                if cell.memory_backend and cell.memory_backend not in memory_names:
                    warnings.append(
                        MatrixWarning(
                            scenario_path=scenario_path,
                            cell=cell,
                            message=f"Unknown memory_backend option: {cell.memory_backend}",
                            blocking=True,
                        )
                    )

                if cell.rag_engine and cell.rag_engine not in rag_names:
                    warnings.append(
                        MatrixWarning(
                            scenario_path=scenario_path,
                            cell=cell,
                            message=f"Unknown rag_engine option: {cell.rag_engine}",
                            blocking=True,
                        )
                    )

                if cell.llm_id and cell.llm_id not in available_llms:
                    warnings.append(
                        MatrixWarning(
                            scenario_path=scenario_path,
                            cell=cell,
                            message=f"LLM not currently available: {cell.llm_id}",
                            blocking=False,
                        )
                    )

        return warnings

    def run_matrix(
        self,
        scenario_paths: List[str],
        llm_ids: List[str],
        memory_backends: List[str],
        rag_engines: List[str],
        setup_overrides: Dict[str, str],
        auto_score: bool = False,
    ) -> MatrixRunResult:
        cells = self._cells(llm_ids, memory_backends, rag_engines)
        all_pairs = [(scenario_path, cell) for scenario_path in scenario_paths for cell in cells]
        total = len(all_pairs)

        blocking = {
            self._warning_key(w.scenario_path, w.cell)
            for w in self.validate_matrix(scenario_paths, llm_ids, memory_backends, rag_engines)
            if w.blocking
        }

        out: List[MatrixCellResult] = []
        completed = 0
        failed = 0
        skipped = 0

        for idx, (scenario_path, cell) in enumerate(all_pairs, start=1):
            scenario_name = self._scenario_name(scenario_path)
            if self.progress_callback:
                self.progress_callback(idx, total, f"{scenario_name} | {self._label(cell)}")

            if self._warning_key(scenario_path, cell) in blocking:
                skipped += 1
                out.append(
                    MatrixCellResult(
                        scenario_name=scenario_name,
                        scenario_path=scenario_path,
                        cell=cell,
                        run_result=None,
                        session_path="",
                        skipped=True,
                        skip_reason="Blocking pre-flight warning",
                    )
                )
                continue

            option_overrides = {}
            if cell.memory_backend:
                option_overrides["memory_backend"] = cell.memory_backend
            if cell.rag_engine:
                option_overrides["rag_engine"] = cell.rag_engine

            try:
                run_result = self.scenario_runner.run(
                    scenario_path,
                    option_overrides=option_overrides,
                    setup_overrides=setup_overrides,
                    llm_override=cell.llm_id,
                    summary_overrides={"matrix_run": True},
                )
                self._mark_matrix_summary(run_result.session_path)
                scoring_errors = self._score_all(run_result.session_path) if auto_score else []

                if run_result.success:
                    completed += 1
                else:
                    failed += 1

                out.append(
                    MatrixCellResult(
                        scenario_name=run_result.scenario_name,
                        scenario_path=scenario_path,
                        cell=cell,
                        run_result=run_result,
                        session_path=run_result.session_path,
                        scoring_errors=scoring_errors,
                        skipped=False,
                        skip_reason="",
                    )
                )
            except Exception as exc:
                failed += 1
                log("error", f"Matrix run failed for scenario={scenario_path} cell={cell}: {exc}", stacktrace=True)
                out.append(
                    MatrixCellResult(
                        scenario_name=scenario_name,
                        scenario_path=scenario_path,
                        cell=cell,
                        run_result=None,
                        session_path="",
                        scoring_errors=[str(exc)],
                        skipped=False,
                        skip_reason="",
                    )
                )

        return MatrixRunResult(cells=out, total=total, completed=completed, failed=failed, skipped=skipped)

    def _score_all(self, session_path: str) -> List[str]:
        errors: List[str] = []
        if not session_path or not os.path.exists(session_path):
            return [f"Session file not found for scoring: {session_path}"]

        with open(session_path, "r", encoding="utf-8") as handle:
            session = yaml.safe_load(handle) or {}

        available = [item for item in self.pipeline.list_scorers() if item.get("available")]
        automatable = [item for item in available if item.get("id") not in {"manual", "llm_external"}]

        container = _BatchContainer()
        for scorer_item in automatable:
            scorer = self.pipeline.get_scorer(scorer_item["id"])
            if scorer is None:
                errors.append(f"Scorer not found: {scorer_item['id']}")
                continue
            try:
                if scorer_item["id"] == "llm_internal" and hasattr(scorer, "compute_score_all_rubrics"):
                    scorer.compute_score_all_rubrics(
                        session=session,
                        config={"session_path": session_path, "batch_mode": True},
                        container=container,
                    )
                else:
                    scorer.compute_score(
                        session=session,
                        config={"session_path": session_path, "batch_mode": True},
                        container=container,
                    )
            except Exception as exc:
                errors.append(f"Scorer {scorer_item['id']} failed: {exc}")
                log("warning", f"Matrix scoring failed for scorer {scorer_item['id']}: {exc}", stacktrace=True)
        return errors

    @staticmethod
    def _inject_cell(scenario: Dict, cell: MatrixCell) -> Dict:
        injected = dict(scenario)
        options = dict((scenario.get("options") or {}))
        if cell.llm_id:
            options["llm"] = cell.llm_id
            injected["llm"] = cell.llm_id
        if cell.memory_backend:
            options["memory_backend"] = cell.memory_backend
        if cell.rag_engine:
            options["rag_engine"] = cell.rag_engine
        injected["options"] = options
        return injected

    @staticmethod
    def _scenario_name(scenario_path: str) -> str:
        try:
            with open(scenario_path, "r", encoding="utf-8") as handle:
                scenario = yaml.safe_load(handle) or {}
            return scenario.get("meta", {}).get("name", os.path.basename(scenario_path))
        except Exception:
            return os.path.basename(scenario_path)

    @staticmethod
    def _label(cell: MatrixCell) -> str:
        return f"{cell.llm_id or '-'} / {cell.memory_backend or '-'} / {cell.rag_engine or '-'}"

    @staticmethod
    def _warning_key(scenario_path: str, cell: MatrixCell) -> str:
        return "|".join([scenario_path, cell.llm_id, cell.memory_backend, cell.rag_engine])

    @staticmethod
    def _load_yaml(path: str) -> Dict:
        with open(path, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}

    @staticmethod
    def _mark_matrix_summary(session_path: str) -> None:
        if not session_path:
            return
        try:
            with get_db_manager().get_session() as session:
                row = (
                    session.query(BenchmarkRun)
                    .filter(BenchmarkRun.session_file == session_path)
                    .order_by(BenchmarkRun.run_at.desc())
                    .first()
                )
                if row is None:
                    return
                summary = dict(row.summary or {})
                summary["matrix_run"] = True
                row.summary = summary
        except Exception as exc:
            log("warning", f"Failed to tag matrix run summary for {session_path}: {exc}", stacktrace=True)
