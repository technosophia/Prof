# modules/rag_bench/rag_bench_models.py
"""
Shared data classes for RAG benchmark modules.
Imported by rag_bench_run_tab, rag_bench_report — no circular deps.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional

FIXABLE_LEVELS = {1, 2, 3, 4}
PARTIAL_LEVELS = {5, 6, 7, 8, 9}
ENGINE_LEVELS  = {10, 11}

LEVEL_LABELS = {
    1: "Direct Keyword Match",    2: "Keyword in Dense Context",
    3: "Temporal/Sequential",     4: "Adversarial Distractor",
    5: "Semantic Paraphrase",     6: "Negation/Absence",
    7: "Numerical/Comparative",   8: "Multi-Chunk Synthesis",
    9: "Sparse Signal",           10: "Cross-Document",
    11: "Ambiguous/Broad",
}

ANOMALY_CATEGORIES = {
    "bad_test":      "🔴 Bad test case (YAML issue, not engine issue)",
    "chunking":      "🟠 Chunking strategy problem",
    "threshold":     "🟡 Threshold miscalibration",
    "embedding":     "🔵 Embedding model weakness",
    "engine_rank":   "🟣 Engine ranking/ordering problem",
    "contradiction": "⚪ Contradictory signals (investigate manually)",
}


@dataclass
class TestCase:
    id: str
    level: int
    question: str
    reference_answer: str
    expected_keywords: List[str]       = field(default_factory=list)
    expected_sources: List[str]        = field(default_factory=list)
    all_required_sources: List[str]    = field(default_factory=list)
    negation_keywords: List[str]       = field(default_factory=list)
    distractor_source: Optional[str]   = None
    distractor_description: Optional[str] = None
    min_score_threshold: float         = 0.65
    required_rank: Optional[int]       = None
    scoring_method: str                = "deterministic"
    notes: str                         = ""


@dataclass
class CaseResult:
    case_id: str
    level: int
    engine: str
    question: str
    gauge: float
    threshold: float
    score_details: Dict
    retrieved_chunks: List[Dict]
    error: Optional[str]  = None
    judge_reasoning: str  = ""

    @property
    def passed(self) -> bool:
        return self.gauge >= self.threshold

    @property
    def delta(self) -> float:
        return self.gauge - self.threshold


@dataclass
class LevelSummary:
    level: int
    engine: str
    total: int
    gauge_sum: float = 0.0

    def __post_init__(self):
        self._passed = 0

    @property
    def avg_gauge(self) -> float:
        return self.gauge_sum / self.total if self.total > 0 else 0.0

    @property
    def passed(self) -> int:
        return self._passed

    @passed.setter
    def passed(self, v: int):
        self._passed = v


def aggregate_results(results: List[CaseResult], engines: List[str]) -> Dict[int, Dict[str, LevelSummary]]:
    agg: Dict[int, Dict[str, LevelSummary]] = {}
    for r in results:
        agg.setdefault(r.level, {})
        if r.engine not in agg[r.level]:
            agg[r.level][r.engine] = LevelSummary(level=r.level, engine=r.engine, total=0)
        s = agg[r.level][r.engine]
        s.total     += 1
        s.gauge_sum += r.gauge
        if r.passed:
            s.passed += 1
    return agg
