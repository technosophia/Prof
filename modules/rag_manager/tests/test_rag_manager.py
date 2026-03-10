"""
Tests for RAG Manager module — uses injected dependencies.

The core RAGManager accepts config and user_manager at construction time,
so tests never need to patch st_shared.cached.

New in this version
-------------------
- Two-configuration isolation tests: verify that two SimpleRAGEngine instances
  built from *different* configs behave differently (context_size, similarity_
  threshold, max_results).
- ENGINE_TYPE constant test: engine-type slug is discoverable without regex.
- engine_id propagation test: named instances carry the right id.
- get_config / update_config round-trip tests.
- Runtime update_config tests: mutating a live engine changes its behaviour.
- Existing tests preserved and de-duplicated.
"""

import importlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

import modules.rag_manager.rag_engines.rag_simple as rag_simple_module
from modules.rag_manager.rag_manager import RAGManager
from modules.rag_manager.rag_engines.rag_simple import SimpleRAGEngine

rag_manager_module = importlib.import_module("modules.rag_manager.rag_manager")


# ===========================================================================
# Shared test doubles
# ===========================================================================

_mock_user_info = {"id": "test_user", "name": "Test User", "role": "admin"}


def _mock_get_user(user_id):
    return _mock_user_info


mock_user_manager = Mock()
mock_user_manager.get_user = Mock(side_effect=_mock_get_user)
mock_user_manager.get_children = Mock(return_value=[])
mock_user_manager.register_before_delete_callback = Mock()
mock_user_manager.db = Mock()
mock_user_manager.db.is_initialized = Mock(return_value=True)


# ===========================================================================
# Config helpers
# ===========================================================================

class _DictConfig:
    """Minimal dict-like config object with dot-notation support."""

    def __init__(self, data: dict):
        self._data = data

    def get(self, key, default=None):
        if key in self._data:
            return self._data[key]
        parts = key.split(".")
        val = self._data
        for part in parts:
            if isinstance(val, dict) and part in val:
                val = val[part]
            else:
                return default
        return val


def _make_test_config(data_dir: Path) -> _DictConfig:
    return _DictConfig(
        {
            "rag_manager": {
                "data_directory": str(data_dir),
                "allowed_extensions": [".txt", ".md"],
                "max_file_size_mb": 10,
                "default_engine": "simple",
                "engines": {
                    "simple": {
                        "index_path": str(data_dir / "simple_indexes"),
                        "enabled": True,
                    },
                    "classic": {
                        "index_path": str(data_dir / "classic_indexes"),
                        "enabled": True,
                    },
                    "faiss_hierarchical": {
                        "index_path": str(data_dir / "hierarchical_indexes"),
                        "enabled": True,
                    },
                },
            }
        }
    )


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def temp_dir(tmp_path):
    return tmp_path


@pytest.fixture
def temp_rag_manager(temp_dir):
    """RAGManager with injected test config and user manager."""
    data_dir = temp_dir / "rag"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "metadata.json").write_text("{}")
    config = _make_test_config(data_dir)

    with patch.object(rag_simple_module, "get_config", lambda: config, create=True):
        manager = RAGManager(config=config, user_manager=mock_user_manager)
        manager.documents.clear()
        manager._save_metadata()
        yield manager


@pytest.fixture
def test_user_id():
    return "test_user"


# ===========================================================================
# Helpers shared across multiple tests
# ===========================================================================

def _write_tmp_txt(content: str) -> str:
    """Write *content* to a temp .txt file; caller must unlink."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
    f.write(content)
    f.close()
    return f.name


def _make_simple_engine(tmp_path, **config_overrides) -> SimpleRAGEngine:
    """Build an isolated SimpleRAGEngine whose indices live under *tmp_path*."""
    cfg = {"index_path": str(tmp_path), **config_overrides}
    return SimpleRAGEngine(config=cfg)


# ===========================================================================
# Part 1 — SimpleRAGEngine: class-level contracts
# ===========================================================================

class TestSimpleRAGEngineClass:
    """Structural / contract tests that don't require file I/O."""

    def test_engine_type_constant(self):
        """ENGINE_TYPE class constant must equal 'simple'."""
        assert SimpleRAGEngine.ENGINE_TYPE == "simple"

    def test_engine_type_on_instance(self):
        engine = SimpleRAGEngine()
        assert engine.engine_type == "simple"

    def test_default_engine_id_equals_engine_type(self):
        """When engine_id is not provided it defaults to the engine_type slug."""
        engine = SimpleRAGEngine()
        assert engine.engine_id == "simple"

    def test_custom_engine_id_is_stored(self, tmp_path):
        engine = SimpleRAGEngine(
            config={"index_path": str(tmp_path)}, engine_id="simple_alt"
        )
        assert engine.engine_id == "simple_alt"

    def test_is_available(self):
        assert SimpleRAGEngine().is_available() is True


# ===========================================================================
# Part 2 — SimpleRAGEngine: get_config / update_config
# ===========================================================================

class TestSimpleRAGEngineConfig:
    """Tests for the live config-override API."""

    def test_get_config_returns_defaults(self, tmp_path):
        engine = _make_simple_engine(tmp_path)
        cfg = engine.get_config()
        assert cfg["context_size"] == 200
        assert cfg["similarity_threshold"] == 0.0
        assert cfg["max_results"] == 5

    def test_get_config_reflects_constructor_values(self, tmp_path):
        engine = _make_simple_engine(
            tmp_path, context_size=50, similarity_threshold=2.0, max_results=3
        )
        cfg = engine.get_config()
        assert cfg["context_size"] == 50
        assert cfg["similarity_threshold"] == 2.0
        assert cfg["max_results"] == 3

    def test_update_config_context_size(self, tmp_path):
        engine = _make_simple_engine(tmp_path)
        engine.update_config({"context_size": 99})
        assert engine.context_size == 99
        assert engine.get_config()["context_size"] == 99

    def test_update_config_similarity_threshold(self, tmp_path):
        engine = _make_simple_engine(tmp_path)
        engine.update_config({"similarity_threshold": 3.0})
        assert engine.similarity_threshold == 3.0

    def test_update_config_max_results(self, tmp_path):
        engine = _make_simple_engine(tmp_path)
        engine.update_config({"max_results": 1})
        assert engine.max_results == 1

    def test_update_config_partial_override(self, tmp_path):
        """Only specified keys must change; others keep their values."""
        engine = _make_simple_engine(
            tmp_path, context_size=80, similarity_threshold=1.0, max_results=4
        )
        engine.update_config({"context_size": 120})
        assert engine.context_size == 120
        assert engine.similarity_threshold == 1.0  # unchanged
        assert engine.max_results == 4              # unchanged

    def test_update_config_unknown_key_is_ignored(self, tmp_path):
        """Passing an unknown key must not raise."""
        engine = _make_simple_engine(tmp_path)
        engine.update_config({"nonexistent_key": "value"})  # should not raise

    def test_index_path_not_overridable_via_update_config(self, tmp_path):
        """index_path must be excluded from update_config to protect loaded indices."""
        engine = _make_simple_engine(tmp_path)
        original_path = engine.index_path
        engine.update_config({"index_path": "/some/other/path"})
        assert engine.index_path == original_path


# ===========================================================================
# Part 3 — TWO-CONFIGURATION ISOLATION
#
# Core requirement: two SimpleRAGEngine instances built from different configs
# must behave *differently* when searching the same corpus.
# ===========================================================================

class TestSimpleRAGEngineTwoConfigurations:
    """
    Build two engine instances with distinct configs and assert that the
    behavioural difference is observable.

    Config A — lenient / verbose
        context_size         = 300  (wide context window)
        similarity_threshold = 0    (keep all matching docs)
        max_results          = 5

    Config B — strict / narrow
        context_size         = 30   (tight context window → shorter snippets)
        similarity_threshold = 5    (filters out low-score docs)
        max_results          = 1    (hard cap of one result)

    Corpus keyword scores for query "attention focus":
        doc_high.txt   → attention×6 + focus×3 = 9  (passes threshold=5)
        doc_medium.txt → attention×1 + focus×2 = 3  (blocked by threshold=5)
        doc_low.txt    → 0                           (blocked by both engines)
    """

    # The corpus has THREE documents; only one scores highly on the query.
    CORPUS = {
        "doc_high.txt": (
            "attention attention attention focus focus focus "
            "The ability to sustain attention is crucial for learning. "
            "Attention is the cognitive process of selectively concentrating. "
            "Sustained attention requires effort and practice."
        ),
        "doc_medium.txt": "This document mentions attention once and focus twice focus.",
        "doc_low.txt":    "Completely unrelated content about cooking recipes.",
    }
    QUERY = "attention focus"

    @pytest.fixture
    def indexed_engines(self, tmp_path):
        """
        Returns ``(engine_a, engine_b)`` sharing the same indexed content
        but built with very different configs.
        """
        dir_a = tmp_path / "engine_a"
        dir_b = tmp_path / "engine_b"
        doc_dir = tmp_path / "docs"
        doc_dir.mkdir()

        # Write corpus files.
        for fname, content in self.CORPUS.items():
            (doc_dir / fname).write_text(content, encoding="utf-8")

        engine_a = _make_simple_engine(
            dir_a,
            context_size=300,
            similarity_threshold=0,
            max_results=5,
        )
        engine_b = _make_simple_engine(
            dir_b,
            context_size=30,
            similarity_threshold=5,  # doc_high scores 9 (passes), doc_medium scores 3 (blocked)
            max_results=1,
        )

        user = "u1"
        for fname, content in self.CORPUS.items():
            fp = str(doc_dir / fname)
            engine_a.index_document(user, fname, fp, content=content)
            engine_b.index_document(user, fname, fp, content=content)

        return engine_a, engine_b

    # --- max_results ---

    def test_engine_a_returns_multiple_results(self, indexed_engines):
        engine_a, _ = indexed_engines
        results = engine_a.search("u1", self.QUERY)
        real = [r for r in results if not r.get("no_results")]
        assert len(real) > 1, (
            f"Engine A (max_results=5, threshold=0) should return >1 result; "
            f"got {len(real)}"
        )

    def test_engine_b_returns_at_most_one_result(self, indexed_engines):
        _, engine_b = indexed_engines
        results = engine_b.search("u1", self.QUERY)
        real = [r for r in results if not r.get("no_results")]
        assert len(real) <= 1, (
            f"Engine B (max_results=1) must return ≤1 result; got {len(real)}"
        )

    # --- similarity_threshold ---

    def test_engine_a_returns_low_score_document(self, indexed_engines):
        """Engine A (threshold=0) must include doc_medium which has score > 0."""
        engine_a, _ = indexed_engines
        results = engine_a.search("u1", self.QUERY)
        filenames = {r["filename"] for r in results if not r.get("no_results")}
        assert "doc_medium.txt" in filenames, (
            f"Engine A should include doc_medium.txt; got {filenames}"
        )

    def test_engine_b_filters_out_low_score_document(self, indexed_engines):
        """Engine B (threshold=5) must discard doc_medium whose score is 3."""
        _, engine_b = indexed_engines
        results = engine_b.search("u1", self.QUERY)
        filenames = {r["filename"] for r in results if not r.get("no_results")}
        assert "doc_medium.txt" not in filenames, (
            f"Engine B should filter out doc_medium.txt; got {filenames}"
        )

    def test_engine_b_filters_out_unrelated_document(self, indexed_engines):
        """Engine B must not return doc_low (score = 0, well below threshold)."""
        _, engine_b = indexed_engines
        results = engine_b.search("u1", self.QUERY)
        filenames = {r["filename"] for r in results if not r.get("no_results")}
        assert "doc_low.txt" not in filenames

    # --- context_size ---

    def test_engine_a_context_is_wider_than_engine_b(self, indexed_engines):
        """
        With the same document, Engine A must produce a longer context snippet
        than Engine B because its context_size is 10× larger.
        """
        engine_a, engine_b = indexed_engines
        res_a = [r for r in engine_a.search("u1", self.QUERY) if r.get("filename") == "doc_high.txt"]
        res_b = [r for r in engine_b.search("u1", self.QUERY) if r.get("filename") == "doc_high.txt"]

        assert res_a, "Engine A should find doc_high.txt"
        assert res_b, "Engine B should find doc_high.txt (score 9 is above threshold=5)"

        len_a = len(res_a[0]["content"])
        len_b = len(res_b[0]["content"])
        assert len_a > len_b, (
            f"Engine A context ({len_a} chars) should be longer than "
            f"Engine B context ({len_b} chars)"
        )

    # --- result ranking is identical across configs ---

    def test_top_result_is_highest_scoring_document_for_both_engines(self, indexed_engines):
        """Both engines must rank doc_high.txt first (it scores highest)."""
        engine_a, engine_b = indexed_engines
        for engine, label in ((engine_a, "A"), (engine_b, "B")):
            results = [r for r in engine.search("u1", self.QUERY) if not r.get("no_results")]
            assert results, f"Engine {label} must return at least one result"
            assert results[0]["filename"] == "doc_high.txt", (
                f"Engine {label}: expected doc_high.txt first, got {results[0]['filename']}"
            )

    # --- runtime update_config changes behaviour ---

    def test_runtime_threshold_increase_suppresses_results(self, tmp_path):
        """
        Start with threshold=0 (two docs match).
        Raise threshold at runtime → previously visible docs disappear.
        """
        doc_dir = tmp_path / "docs"
        doc_dir.mkdir()
        engine = _make_simple_engine(tmp_path / "eng", similarity_threshold=0)

        (doc_dir / "rich.txt").write_text("cat cat cat cat cat", encoding="utf-8")
        (doc_dir / "poor.txt").write_text("cat", encoding="utf-8")
        engine.index_document("u", "rich.txt", str(doc_dir / "rich.txt"), content="cat cat cat cat cat")
        engine.index_document("u", "poor.txt", str(doc_dir / "poor.txt"), content="cat")

        before = [r for r in engine.search("u", "cat") if not r.get("no_results")]
        assert len(before) == 2, f"Expected 2 results before threshold change, got {len(before)}"

        # Raise threshold so "poor.txt" (score=1) is filtered out.
        engine.update_config({"similarity_threshold": 2})

        after = [r for r in engine.search("u", "cat") if not r.get("no_results")]
        assert len(after) == 1
        assert after[0]["filename"] == "rich.txt"

    def test_runtime_max_results_shrinks_result_set(self, tmp_path):
        """Lowering max_results at runtime should reduce the returned count."""
        doc_dir = tmp_path / "docs"
        doc_dir.mkdir()
        engine = _make_simple_engine(tmp_path / "eng", max_results=5, similarity_threshold=0)

        for i in range(4):
            content = f"keyword " * (i + 1)
            fname = f"doc_{i}.txt"
            (doc_dir / fname).write_text(content, encoding="utf-8")
            engine.index_document("u", fname, str(doc_dir / fname), content=content)

        full = [r for r in engine.search("u", "keyword") if not r.get("no_results")]
        assert len(full) == 4

        engine.update_config({"max_results": 2})
        trimmed = [r for r in engine.search("u", "keyword") if not r.get("no_results")]
        assert len(trimmed) == 2


# ===========================================================================
# Part 4 — RAGManager: two named 'simple' engine instances in one manager
# ===========================================================================

class TestRAGManagerTwoSimpleInstances:
    """
    Declare two SimpleRAGEngine instances (simple_strict, simple_lenient) in the
    manager's config and verify they are independently instantiated with their
    own settings.
    """

    CORPUS_CONTENT = (
        "attention attention attention focus focus "
        "The ability to sustain attention is crucial for learning."
    )
    QUERY = "attention focus"

    @pytest.fixture
    def dual_manager(self, tmp_path):
        data_dir = tmp_path / "rag"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "metadata.json").write_text("{}")

        config = _DictConfig(
            {
                "rag_manager": {
                    "data_directory": str(data_dir),
                    "allowed_extensions": [".txt"],
                    "max_file_size_mb": 10,
                    "default_engine": "simple_lenient",
                    "engines": {
                        # Lenient: low threshold, large context, up to 5 results.
                        "simple_lenient": {
                            "type": "simple",
                            "enabled": True,
                            "index_path": str(data_dir / "idx_lenient"),
                            "context_size": 300,
                            "similarity_threshold": 0,
                            "max_results": 5,
                            "description": "Simple lenient",
                        },
                        # Strict: high threshold, small context, 1 result max.
                        "simple_strict": {
                            "type": "simple",
                            "enabled": True,
                            "index_path": str(data_dir / "idx_strict"),
                            "context_size": 30,
                            "similarity_threshold": 100,
                            "max_results": 1,
                            "description": "Simple strict",
                        },
                    },
                }
            }
        )

        with patch.object(rag_simple_module, "get_config", lambda: config, create=True):
            manager = RAGManager(config=config, user_manager=mock_user_manager)
            manager.documents.clear()
            manager._save_metadata()
            yield manager

    def test_both_engines_instantiated(self, dual_manager):
        ids = dual_manager.get_engine_ids()
        assert "simple_lenient" in ids
        assert "simple_strict" in ids

    def test_engine_ids_are_set_correctly(self, dual_manager):
        assert dual_manager.get_engine("simple_lenient").engine_id == "simple_lenient"
        assert dual_manager.get_engine("simple_strict").engine_id == "simple_strict"

    def test_engines_have_distinct_configs(self, dual_manager):
        lenient = dual_manager.get_engine("simple_lenient")
        strict  = dual_manager.get_engine("simple_strict")

        assert lenient.context_size > strict.context_size
        assert lenient.similarity_threshold < strict.similarity_threshold
        assert lenient.max_results > strict.max_results

    def test_lenient_returns_results_strict_does_not(self, dual_manager, tmp_path):
        """
        After indexing the corpus document, the lenient engine must find it
        while the strict engine (threshold=100, far above any realistic score)
        must return no results.
        """
        tmp_file = tmp_path / "corpus.txt"
        tmp_file.write_text(self.CORPUS_CONTENT, encoding="utf-8")

        fn = dual_manager.upload_document(str(tmp_file), "corpus.txt", user_id="test_user")
        assert fn is not None

        dual_manager.index_document(fn, "simple_lenient", "test_user")
        dual_manager.index_document(fn, "simple_strict", "test_user")

        lenient_results = dual_manager.search(
            "test_user", self.QUERY, engine_type="simple_lenient"
        )
        strict_results = dual_manager.search(
            "test_user", self.QUERY, engine_type="simple_strict"
        )

        lenient_real = [
            r for r in lenient_results.get("simple_lenient", [])
            if not r.get("no_results")
        ]
        strict_real = [
            r for r in strict_results.get("simple_strict", [])
            if not r.get("no_results")
        ]

        assert len(lenient_real) >= 1, "Lenient engine must find the corpus document"
        assert len(strict_real) == 0, (
            f"Strict engine (threshold=100) must return nothing; got {strict_real}"
        )

    def test_get_config_reflects_manager_config(self, dual_manager):
        lenient = dual_manager.get_engine("simple_lenient")
        cfg = lenient.get_config()
        assert cfg["context_size"] == 300
        assert cfg["similarity_threshold"] == 0
        assert cfg["max_results"] == 5


# ===========================================================================
# Part 5 — RAGManager: existing functional tests (preserved + hardened)
# ===========================================================================

class TestRAGManagerCore:

    def test_init_data_directory(self, temp_rag_manager):
        assert temp_rag_manager.data_dir.exists()
        engines = temp_rag_manager.get_available_engines()
        assert len(engines) > 0
        assert any(e["type"] == "simple" for e in engines)

    def test_upload_document(self, temp_rag_manager, test_user_id):
        tmp = _write_tmp_txt("This is a test document.")
        try:
            filename = temp_rag_manager.upload_document(tmp, "test.txt", user_id=test_user_id)
            assert filename is not None
            assert filename in temp_rag_manager.documents
            doc_info = temp_rag_manager.documents[filename]
            assert doc_info["uploaded_by"] == test_user_id
            assert doc_info["original_filename"] == "test.txt"
        finally:
            os.unlink(tmp)

    def test_delete_document(self, temp_rag_manager, test_user_id):
        tmp = _write_tmp_txt("Document to delete.")
        try:
            filename = temp_rag_manager.upload_document(tmp, "delete_test.txt", user_id=test_user_id)
            assert filename is not None
            assert temp_rag_manager.delete_document(filename, user_id=test_user_id) is True
            assert filename not in temp_rag_manager.documents
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def test_get_user_documents(self, temp_rag_manager, test_user_id):
        paths = []
        for i in range(3):
            p = _write_tmp_txt(f"Test document {i}")
            paths.append(p)
            temp_rag_manager.upload_document(p, f"test_{i}.txt", user_id=test_user_id)
        try:
            documents = temp_rag_manager.get_user_documents(test_user_id)
            assert len(documents) == 3
            assert {d["original_filename"] for d in documents} == {
                "test_0.txt", "test_1.txt", "test_2.txt"
            }
        finally:
            for p in paths:
                if os.path.exists(p):
                    os.unlink(p)

    def test_file_validation_valid(self, temp_rag_manager):
        tmp = _write_tmp_txt("Small file")
        try:
            is_valid, error = temp_rag_manager.is_valid_file(tmp)
            assert is_valid is True
            assert error == ""
        finally:
            os.unlink(tmp)

    def test_file_validation_invalid_extension(self, temp_rag_manager):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".exe", delete=False) as f:
            f.write("Invalid extension")
            tmp = f.name
        try:
            is_valid, error = temp_rag_manager.is_valid_file(tmp)
            assert is_valid is False
            assert "Unsupported" in error
        finally:
            os.unlink(tmp)

    def test_metadata_persistence(self, temp_dir, test_user_id):
        data_dir = temp_dir / "rag_persist"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "metadata.json").write_text("{}")
        config = _make_test_config(data_dir)

        with patch.object(rag_simple_module, "get_config", lambda: config, create=True):
            manager = RAGManager(config=config, user_manager=mock_user_manager)
            tmp = _write_tmp_txt("Metadata test")
            try:
                filename = manager.upload_document(tmp, "meta_test.txt", user_id=test_user_id)
                assert filename is not None
                manager._save_metadata()
                with open(manager.metadata_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                assert filename in saved
                assert saved[filename]["uploaded_by"] == test_user_id
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)

    def test_rag_engine_functionality(self, temp_rag_manager, test_user_id):
        engine = temp_rag_manager.get_engine("simple")
        assert engine is not None

        tmp = _write_tmp_txt(
            "This document contains information about artificial intelligence "
            "and machine learning."
        )
        try:
            filename = temp_rag_manager.upload_document(tmp, "ai_doc.txt", user_id=test_user_id)
            assert filename is not None
            assert temp_rag_manager.index_document(filename, "simple", user_id=test_user_id) is True

            results = temp_rag_manager.search(
                test_user_id, "artificial intelligence", engine_type="simple"
            )
            assert "simple" in results
            assert len(results["simple"]) > 0

            context = temp_rag_manager.get_rag_context(
                test_user_id, "What is artificial intelligence?", engine_type="simple"
            )
            assert context != ""
            assert "Relevant context" in context or "From document" in context
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def test_engine_discovery(self, temp_rag_manager):
        engines = temp_rag_manager.get_available_engines()
        assert len(engines) >= 2
        types = [e["type"] for e in engines]
        assert "simple" in types
        assert "classic" in types

    def test_document_indexing_status(self, temp_rag_manager, test_user_id):
        tmp = _write_tmp_txt("Test indexing status.")
        try:
            filename = temp_rag_manager.upload_document(tmp, "index_test.txt", user_id=test_user_id)
            assert filename is not None

            docs = temp_rag_manager.get_user_documents(test_user_id)
            doc = next(d for d in docs if d["filename"] == filename)
            assert doc.get("indexed_in", []) == []

            temp_rag_manager.index_document(filename, "simple", test_user_id)
            docs = temp_rag_manager.get_user_documents(test_user_id)
            doc = next(d for d in docs if d["filename"] == filename)
            assert "simple" in doc.get("indexed_in", [])
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def test_clear_all_documents(self, temp_rag_manager, test_user_id):
        paths = []
        for i in range(3):
            p = _write_tmp_txt(f"Document {i}")
            paths.append(p)
            temp_rag_manager.upload_document(p, f"clear_test_{i}.txt", user_id=test_user_id)
        try:
            assert len(temp_rag_manager.get_user_documents(test_user_id)) == 3
            assert temp_rag_manager.clear_all_documents(test_user_id) is True
            assert len(temp_rag_manager.get_user_documents(test_user_id)) == 0
        finally:
            for p in paths:
                if os.path.exists(p):
                    os.unlink(p)

    def test_get_rag_context_returns_query_when_no_result(self, temp_rag_manager, test_user_id):
        query = "unfindable routeforge token"
        context = temp_rag_manager.get_rag_context(test_user_id, query, engine_type="simple")
        assert context == f"No result found for : '{query}'"

    def test_search_returns_empty_when_rag_disabled(self, temp_rag_manager, test_user_id):
        tmp = _write_tmp_txt("Kevin lives at 1 place du Louvre, Paris")
        try:
            filename = temp_rag_manager.upload_document(tmp, "disabled_doc.txt", user_id=test_user_id)
            assert filename is not None
            assert temp_rag_manager.index_document(filename, "simple", test_user_id) is True

            temp_rag_manager._config._data["rag_manager"]["enabled"] = False
            results = temp_rag_manager.search(test_user_id, "Kevin", engine_type="simple")
            assert results == {}
            context = temp_rag_manager.get_rag_context(test_user_id, "Kevin", engine_type="simple")
            assert context == ""
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
            temp_rag_manager._config._data["rag_manager"].pop("enabled", None)

    def test_get_rag_context_returns_empty_when_engine_disabled(self, temp_rag_manager, test_user_id):
        tmp = _write_tmp_txt("Kevin lives at 1 place du Louvre, Paris")
        try:
            filename = temp_rag_manager.upload_document(tmp, "engine_disabled_doc.txt", user_id=test_user_id)
            assert filename is not None
            assert temp_rag_manager.index_document(filename, "simple", test_user_id) is True
            temp_rag_manager._config._data["rag_manager"]["engines"]["simple"]["enabled"] = False
            context = temp_rag_manager.get_rag_context(
                test_user_id, "Where does Kevin live?", engine_type="simple"
            )
            assert context == ""
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
            temp_rag_manager._config._data["rag_manager"]["engines"]["simple"].pop("enabled", None)

    def test_search_all_flag_queries_all_engines(self, temp_rag_manager):
        with patch.object(
            temp_rag_manager,
            "get_user_documents",
            return_value=[{
                "filename": "doc1",
                "uploaded_by": "owner1",
                "uploaded_at": "2026-01-01T00:00:00",
                "file_size_mb": 0.1,
                "file_extension": ".txt",
                "is_public": False,
                "indexed_in": [],
            }],
        ):
            simple_engine = Mock()
            simple_engine.search.return_value = []
            simple_engine.get_indexed_documents.return_value = []
            classic_engine = Mock()
            classic_engine.search.return_value = []
            classic_engine.get_indexed_documents.return_value = []

            with patch.object(
                temp_rag_manager,
                "engines",
                {"simple": simple_engine, "classic": classic_engine},
            ):
                with patch.object(
                    temp_rag_manager,
                    "get_engine",
                    side_effect=lambda et: {
                        "simple": simple_engine,
                        "classic": classic_engine,
                    }.get(et),
                ):
                    results = temp_rag_manager.search("requester", "query", search_all=True)

        assert "simple" in results
        assert "classic" in results

    def test_check_user_permission_normal_to_master(self, temp_rag_manager):
        original = temp_rag_manager._user_manager.get_user.side_effect
        try:
            with patch.object(rag_manager_module, "user_manager", create=True):
                temp_rag_manager._user_manager.get_user.side_effect = [
                    {"id": "student_1", "role": "normal", "parent_id": "master_1"},
                    {"id": "master_1", "role": "master"},
                ]
                allowed = temp_rag_manager._check_user_permission("student_1", "master_1")
            assert allowed is True
        finally:
            temp_rag_manager._user_manager.get_user.side_effect = original


# ===========================================================================
# Part 6 — SimpleRAGEngine: direct unit tests (backwards-compat suite)
# ===========================================================================

class TestSimpleRAGEngineDirect:

    def test_direct_engine_lifecycle(self, tmp_path):
        engine = SimpleRAGEngine(config={"index_path": str(tmp_path)})
        engine.indices.clear()

        tmp = _write_tmp_txt("Test content for engine testing.")
        try:
            assert engine.index_document("user1", "engine_test.txt", tmp) is True
            docs = engine.get_indexed_documents("user1")
            assert len(docs) == 1
            assert docs[0]["filename"] == "engine_test.txt"

            results = engine.search("user1", "test content")
            assert len(results) == 1
            assert results[0]["score"] > 0

            assert engine.delete_document("user1", "engine_test.txt") is True
            assert len(engine.get_indexed_documents("user1")) == 0
        finally:
            os.unlink(tmp)

    def test_backward_compatibility_no_args(self):
        """SimpleRAGEngine() with no args must not raise."""
        engine = SimpleRAGEngine()
        assert engine.is_available() is True

    def test_stats_include_config_fields(self, tmp_path):
        engine = _make_simple_engine(
            tmp_path, context_size=42, similarity_threshold=1.5, max_results=3
        )
        stats = engine.get_stats()
        assert stats["context_size"] == 42
        assert stats["similarity_threshold"] == 1.5
        assert stats["max_results"] == 3
        assert stats["engine_id"] == "simple"

    def test_stats_with_custom_engine_id(self, tmp_path):
        engine = SimpleRAGEngine(
            config={"index_path": str(tmp_path)}, engine_id="simple_custom"
        )
        stats = engine.get_stats()
        assert stats["engine_id"] == "simple_custom"

    def test_no_results_sentinel_includes_threshold(self, tmp_path):
        """When search returns the no_results sentinel it must carry threshold_used."""
        engine = _make_simple_engine(tmp_path, similarity_threshold=5.0)
        results = engine.search("ghost_user", "anything")
        assert results[0].get("no_results") is True
        assert results[0]["threshold_used"] == 5.0

    def test_backward_compatibility_old_metadata(self, temp_rag_manager, test_user_id):
        """Documents without uploaded_by should not appear in user listings."""
        old_metadata = {
            "old_doc.txt": {
                "original_filename": "old_doc.txt",
                "uploaded_at": "2024-01-01T00:00:00",
                "file_size_mb": 0.1,
                "file_extension": ".txt",
                "file_path": str(temp_rag_manager.data_dir / "old_doc.txt"),
            }
        }
        with open(temp_rag_manager.metadata_file, "w") as f:
            json.dump(old_metadata, f)
        old_file = temp_rag_manager.data_dir / "old_doc.txt"
        old_file.write_text("Old document content")
        try:
            temp_rag_manager.documents = temp_rag_manager._load_metadata()
            docs = temp_rag_manager.get_user_documents(test_user_id)
            assert all(d["filename"] != "old_doc.txt" for d in docs)
        finally:
            if old_file.exists():
                old_file.unlink()
