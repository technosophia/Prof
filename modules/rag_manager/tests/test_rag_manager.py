"""
Tests for RAG Manager module — uses injected dependencies.

The core RAGManager now accepts config and user_manager at construction time,
so tests no longer need to patch st_shared.cached.
"""

import pytest
import tempfile
import os
import json
import importlib
from pathlib import Path
import shutil
from unittest.mock import Mock, patch

from modules.rag_manager.rag_manager import RAGManager
from modules.rag_manager.rag_engines.rag_simple import SimpleRAGEngine

rag_manager_module = importlib.import_module("modules.rag_manager.rag_manager")
rag_simple_module = importlib.import_module("modules.rag_manager.rag_engines.rag_simple")

# ---------------------------------------------------------------------------
# Shared test doubles
# ---------------------------------------------------------------------------

mock_user_info = {'id': 'test_user', 'name': 'Test User', 'role': 'admin'}

def mock_get_user(user_id):
    """Always return the same user info regardless of how many times called."""
    return mock_user_info

mock_user_manager = Mock()
mock_user_manager.get_user = Mock(side_effect=mock_get_user)  # Use side_effect with function
mock_user_manager.get_children = Mock(return_value=[])
mock_user_manager.register_before_delete_callback = Mock()
mock_user_manager.db = Mock()
mock_user_manager.db.is_initialized = Mock(return_value=True)


def _make_test_config(data_dir: Path) -> dict:
    """Return a plain dict config — no Streamlit caching."""
    cfg = {
        "rag_manager": {
            "data_directory": str(data_dir),
            "allowed_extensions": [".txt", ".md"],
            "max_file_size_mb": 10,
            "default_engine": "simple",
            "engines": {
                "simple": {"index_path": str(data_dir / "simple_indexes"), "enabled": True},
                "classic": {"index_path": str(data_dir / "classic_indexes"), "enabled": True},
                "faiss_hierarchical": {"index_path": str(data_dir / "hierarchical_indexes"), "enabled": True},
            },
        }
    }

    class DictConfig:
        def __init__(self, data):
            self._data = data

        def get(self, key, default=None):
            # Support dot-notation keys
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

    return DictConfig(cfg)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp()
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def temp_rag_manager(temp_dir):
    """RAGManager with injected test config and user manager."""
    data_dir = temp_dir / "rag"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "metadata.json").write_text("{}")

    config = _make_test_config(data_dir)

    # Patch SimpleRAGEngine's st_shared fallback so it uses the test config
    with patch.object(rag_simple_module, "get_config", lambda: config, create=True):
        manager = RAGManager(config=config, user_manager=mock_user_manager)
        manager.documents.clear()
        manager._save_metadata()
        yield manager


@pytest.fixture
def test_user_id():
    return "test_user"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_init_data_directory(temp_rag_manager):
    assert temp_rag_manager.data_dir.exists()
    engines = temp_rag_manager.get_available_engines()
    assert len(engines) > 0
    assert any(e['type'] == 'simple' for e in engines)


def test_upload_document(temp_rag_manager, test_user_id):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("This is a test document.")
        temp_path = f.name
    try:
        filename = temp_rag_manager.upload_document(temp_path, "test.txt", user_id=test_user_id)
        assert filename is not None
        assert filename in temp_rag_manager.documents
        doc_info = temp_rag_manager.documents[filename]
        assert doc_info['uploaded_by'] == test_user_id
        assert doc_info['original_filename'] == "test.txt"
    finally:
        os.unlink(temp_path)


def test_delete_document(temp_rag_manager, test_user_id):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("Document to delete.")
        temp_path = f.name
    try:
        filename = temp_rag_manager.upload_document(temp_path, "delete_test.txt", user_id=test_user_id)
        assert filename is not None
        assert temp_rag_manager.delete_document(filename, user_id=test_user_id) is True
        assert filename not in temp_rag_manager.documents
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def test_get_user_documents(temp_rag_manager, test_user_id):
    for i in range(3):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(f"Test document {i}")
            temp_path = f.name
        try:
            temp_rag_manager.upload_document(temp_path, f"test_{i}.txt", user_id=test_user_id)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    documents = temp_rag_manager.get_user_documents(test_user_id)
    assert len(documents) == 3
    assert {d['original_filename'] for d in documents} == {"test_0.txt", "test_1.txt", "test_2.txt"}


def test_file_validation_valid(temp_rag_manager):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("Small file")
        temp_path = f.name
    try:
        is_valid, error = temp_rag_manager.is_valid_file(temp_path)
        assert is_valid is True
        assert error == ""
    finally:
        os.unlink(temp_path)


def test_file_validation_invalid_extension(temp_rag_manager):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.exe', delete=False) as f:
        f.write("Invalid extension")
        temp_path = f.name
    try:
        is_valid, error = temp_rag_manager.is_valid_file(temp_path)
        assert is_valid is False
        assert "Unsupported" in error
    finally:
        os.unlink(temp_path)


def test_metadata_persistence(temp_dir, test_user_id):
    data_dir = temp_dir / "rag_persist"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "metadata.json").write_text("{}")
    config = _make_test_config(data_dir)

    with patch.object(rag_simple_module, "get_config", lambda: config, create=True):
        manager = RAGManager(config=config, user_manager=mock_user_manager)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Metadata test")
            temp_path = f.name
        try:
            filename = manager.upload_document(temp_path, "meta_test.txt", user_id=test_user_id)
            assert filename is not None
            manager._save_metadata()

            with open(manager.metadata_file, 'r', encoding='utf-8') as f:
                saved = json.load(f)
            assert filename in saved
            assert saved[filename]['uploaded_by'] == test_user_id
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)


def test_rag_engine_functionality(temp_rag_manager, test_user_id):
    engine = temp_rag_manager.get_engine("simple")
    assert engine is not None

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("This document contains information about artificial intelligence and machine learning.")
        temp_path = f.name
    try:
        filename = temp_rag_manager.upload_document(temp_path, "ai_doc.txt", user_id=test_user_id)
        assert filename is not None

        assert temp_rag_manager.index_document(filename, "simple", user_id=test_user_id) is True

        results = temp_rag_manager.search(test_user_id, "artificial intelligence", engine_type="simple")
        assert "simple" in results
        assert len(results["simple"]) > 0

        context = temp_rag_manager.get_rag_context(test_user_id, "What is artificial intelligence?", engine_type="simple")
        assert context != ""
        assert "Relevant context" in context or "From document" in context
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def test_engine_discovery(temp_rag_manager):
    engines = temp_rag_manager.get_available_engines()
    assert len(engines) >= 2
    types = [e['type'] for e in engines]
    assert 'simple' in types
    assert 'classic' in types


def test_document_indexing_status(temp_rag_manager, test_user_id):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("Test indexing status.")
        temp_path = f.name
    try:
        filename = temp_rag_manager.upload_document(temp_path, "index_test.txt", user_id=test_user_id)
        assert filename is not None

        docs = temp_rag_manager.get_user_documents(test_user_id)
        doc = next(d for d in docs if d['filename'] == filename)
        assert doc.get('indexed_in', []) == []

        temp_rag_manager.index_document(filename, "simple", test_user_id)

        docs = temp_rag_manager.get_user_documents(test_user_id)
        doc = next(d for d in docs if d['filename'] == filename)
        assert "simple" in doc.get('indexed_in', [])
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def test_clear_all_documents(temp_rag_manager, test_user_id):
    for i in range(3):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(f"Document {i}")
            temp_path = f.name
        try:
            temp_rag_manager.upload_document(temp_path, f"clear_test_{i}.txt", user_id=test_user_id)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    assert len(temp_rag_manager.get_user_documents(test_user_id)) == 3
    assert temp_rag_manager.clear_all_documents(test_user_id) is True
    assert len(temp_rag_manager.get_user_documents(test_user_id)) == 0


def test_simple_rag_engine_direct():
    """Test SimpleRAGEngine directly with injected config."""
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = SimpleRAGEngine(config={"index_path": tmpdir})
        # Isolate: clear any pre-loaded indices
        engine.indices.clear()

        assert engine.engine_type == "simple"
        assert engine.is_available() is True

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Test content for engine testing.")
            temp_path = f.name
        try:
            assert engine.index_document("user1", "engine_test.txt", temp_path) is True
            docs = engine.get_indexed_documents("user1")
            assert len(docs) == 1
            assert docs[0]['filename'] == "engine_test.txt"

            results = engine.search("user1", "test content")
            assert len(results) == 1
            assert results[0]['score'] > 0

            assert engine.delete_document("user1", "engine_test.txt") is True
            assert len(engine.get_indexed_documents("user1")) == 0
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)


def test_backward_compatibility_no_uploaded_by(temp_rag_manager, test_user_id):
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
    with open(temp_rag_manager.metadata_file, 'w') as f:
        json.dump(old_metadata, f)
    old_file = temp_rag_manager.data_dir / "old_doc.txt"
    old_file.write_text("Old document content")
    try:
        temp_rag_manager.documents = temp_rag_manager._load_metadata()
        docs = temp_rag_manager.get_user_documents(test_user_id)
        assert all(d['filename'] != "old_doc.txt" for d in docs)
    finally:
        if old_file.exists():
            old_file.unlink()


def test_get_rag_context_returns_query_when_no_result(temp_rag_manager, test_user_id):
    query = "unfindable routeforge token"
    context = temp_rag_manager.get_rag_context(test_user_id, query, engine_type="simple")
    assert context == f"No result found for : '{query}'"


def test_search_returns_empty_when_rag_disabled(temp_rag_manager, test_user_id):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("Kevin lives at 1 place du Louvre, Paris")
        temp_path = f.name
    try:
        filename = temp_rag_manager.upload_document(temp_path, "disabled_doc.txt", user_id=test_user_id)
        assert filename is not None
        assert temp_rag_manager.index_document(filename, "simple", test_user_id) is True

        temp_rag_manager._config._data["rag_manager"]["enabled"] = False

        results = temp_rag_manager.search(test_user_id, "Kevin", engine_type="simple")
        assert results == {}

        context = temp_rag_manager.get_rag_context(test_user_id, "Kevin", engine_type="simple")
        assert context == ""
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        temp_rag_manager._config._data["rag_manager"].pop("enabled", None)


def test_search_all_flag_queries_all_engines(temp_rag_manager):
    with patch.object(temp_rag_manager, 'get_user_documents', return_value=[{
        'filename': 'doc1', 'uploaded_by': 'owner1', 'uploaded_at': '2026-01-01T00:00:00',
        'file_size_mb': 0.1, 'file_extension': '.txt', 'is_public': False, 'indexed_in': [],
    }]):
        simple_engine = Mock()
        simple_engine.search.return_value = []
        simple_engine.get_indexed_documents.return_value = []
        classic_engine = Mock()
        classic_engine.search.return_value = []
        classic_engine.get_indexed_documents.return_value = []

        with patch.object(temp_rag_manager, 'engines', {'simple': simple_engine, 'classic': classic_engine}):
            with patch.object(temp_rag_manager, 'get_engine', side_effect=lambda et: {'simple': simple_engine, 'classic': classic_engine}.get(et)):
                results = temp_rag_manager.search('requester', 'query', search_all=True)

    assert 'simple' in results
    assert 'classic' in results


def test_check_user_permission_normal_to_master(temp_rag_manager):
    """NORMAL users should access their master's documents."""
    original_side_effect = temp_rag_manager._user_manager.get_user.side_effect
    try:
        with patch.object(rag_manager_module, 'user_manager', create=True):
            temp_rag_manager._user_manager.get_user.side_effect = [
                {'id': 'student_1', 'role': 'normal', 'parent_id': 'master_1'},
                {'id': 'master_1', 'role': 'master'},
            ]
            allowed = temp_rag_manager._check_user_permission('student_1', 'master_1')
        assert allowed is True
    finally:
        temp_rag_manager._user_manager.get_user.side_effect = original_side_effect

def test_get_rag_context_returns_query_when_no_result(temp_rag_manager, test_user_id):
    """RAG should inject an explicit fallback context with the query when no result exists."""
    query = "unfindable routeforge token"
    context = temp_rag_manager.get_rag_context(test_user_id, query, engine_type="simple")
    assert context == f"No result found for : '{query}'"


def test_search_returns_no_results_when_rag_disabled_in_config(temp_rag_manager, test_user_id):
    """RAG search must be disabled when rag_manager.enabled is false."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("Kevin lives at 1 place du Louvre, Paris")
        temp_path = f.name

    try:
        filename = temp_rag_manager.upload_document(temp_path, "rag_disabled_doc.txt", user_id=test_user_id)
        assert filename is not None
        assert temp_rag_manager.index_document(filename, "simple", test_user_id) is True

        # Disable RAG globally by modifying the underlying config data
        temp_rag_manager._config._data["rag_manager"]["enabled"] = False

        results = temp_rag_manager.search(test_user_id, "Where does Kevin live?", engine_type="simple")
        assert results == {}

        context = temp_rag_manager.get_rag_context(test_user_id, "Where does Kevin live?", engine_type="simple")
        assert context == ""
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        # Restore config (remove the 'enabled' key we added)
        temp_rag_manager._config._data["rag_manager"].pop("enabled", None)


def test_get_rag_context_returns_empty_when_engine_disabled_in_config(temp_rag_manager, test_user_id):
    """RAG context must not be injected when the selected engine is disabled."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("Kevin lives at 1 place du Louvre, Paris")
        temp_path = f.name

    try:
        filename = temp_rag_manager.upload_document(temp_path, "engine_disabled_doc.txt", user_id=test_user_id)
        assert filename is not None
        assert temp_rag_manager.index_document(filename, "simple", test_user_id) is True

        # Disable the 'simple' engine in the underlying config data
        temp_rag_manager._config._data["rag_manager"]["engines"]["simple"]["enabled"] = False

        context = temp_rag_manager.get_rag_context(test_user_id, "Where does Kevin live?", engine_type="simple")
        assert context == ""
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        # Restore engine enabled state (remove the key we set)
        temp_rag_manager._config._data["rag_manager"]["engines"]["simple"].pop("enabled", None)
