"""Auto-discovery for mem_bench evaluators."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Dict, List, Optional

from .base import MemEvaluator

_EVALUATORS: Dict[str, MemEvaluator] | None = None


def _discover() -> Dict[str, MemEvaluator]:
    found: Dict[str, MemEvaluator] = {}
    for module_info in pkgutil.iter_modules(__path__):
        if not module_info.name.startswith("evaluator_"):
            continue
        module = importlib.import_module(f"{__name__}.{module_info.name}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if obj is MemEvaluator or not issubclass(obj, MemEvaluator):
                continue
            evaluator = obj()
            if evaluator.id:
                found[evaluator.id] = evaluator
    return found


def get_evaluators() -> List[MemEvaluator]:
    global _EVALUATORS
    if _EVALUATORS is None:
        _EVALUATORS = _discover()
    return [item for _, item in sorted(_EVALUATORS.items())]


def get_evaluator(evaluator_id: str) -> Optional[MemEvaluator]:
    global _EVALUATORS
    if _EVALUATORS is None:
        _EVALUATORS = _discover()
    return _EVALUATORS.get(evaluator_id)
