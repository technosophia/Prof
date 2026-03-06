"""
Test RAG system functionality.

RAGManager takes (config, user_manager) by injection — no module-level
get_config / user_manager / UserRole attributes exist in rag_manager.py.
Patching rag_simple_module.get_config is still needed for SimpleRAGEngine.
"""

import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

import modules.rag_manager.rag_engines.rag_simple as rag_simple_module
from modules.rag_manager.rag_manager import RAGManager
from modules.rag_manager.rag_engines.rag_simple import SimpleRAGEngine


# ---------------------------------------------------------------------------
# Helpers — mirrored from test_rag_manager.py
# ---------------------------------------------------------------------------

_mock_user_info = {"id": "test_user", "name": "Test User", "role": "admin"}

_mock_user_manager = Mock()
_mock_user_manager.get_user = Mock(return_value=_mock_user_info)
_mock_user_manager.get_children = Mock(return_value=[])
_mock_user_manager.register_before_delete_callback = Mock()
_mock_user_manager.db = Mock()
_mock_user_manager.db.is_initialized = Mock(return_value=True)


class _DictConfig:
    """Plain dict-like config with dot-notation support."""

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
    return _DictConfig({
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
    })


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_rag_manager(tmp_path):
    """Fully isolated RAGManager using constructor injection."""
    data_dir = tmp_path / "rag"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "metadata.json").write_text("{}")

    config = _make_test_config(data_dir)

    # Only rag_simple_module needs patching — it still calls get_config() internally.
    # rag_manager.py has no module-level get_config; it receives config via __init__.
    with patch.object(rag_simple_module, "get_config", lambda: config, create=True):
        manager = RAGManager(config=config, user_manager=_mock_user_manager)
        manager.documents.clear()
        manager._save_metadata()
        yield manager


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_rag_engine_initialization():
    """SimpleRAGEngine constructs without a Streamlit context."""
    engine = SimpleRAGEngine()
    assert engine.engine_type == "simple"
    assert engine.description != ""
    assert engine.is_available() is True


def test_document_indexing():
    """SimpleRAGEngine indexes and searches in isolation."""
    engine = SimpleRAGEngine()

    # Clear any state persisted from previous runs.
    engine.indices.clear()
    engine._save_user_index("test_user")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(
            "This is a test document about artificial intelligence "
            "and machine learning."
        )
        temp_path = f.name

    try:
        assert engine.index_document("test_user", "test.txt", temp_path) is True

        docs = engine.get_indexed_documents("test_user")
        assert len(docs) == 1, f"Expected 1 doc, got {len(docs)}: {docs}"
        assert docs[0]["filename"] == "test.txt"

        results = engine.search("test_user", "artificial intelligence")
        assert len(results) == 1
        assert results[0]["filename"] == "test.txt"
        assert results[0]["score"] > 0
    finally:
        os.unlink(temp_path)
        engine.indices.pop("test_user", None)
        engine._save_user_index("test_user")


def test_rag_manager_engine_discovery(isolated_rag_manager):
    """RAGManager discovers simple and classic engines."""
    engines = isolated_rag_manager.get_available_engines()
    assert len(engines) > 0

    engine_types = [e["type"] for e in engines]
    assert "simple" in engine_types
    assert "classic" in engine_types

    default = isolated_rag_manager.get_default_engine()
    assert default is not None
    assert default.engine_type in ("simple", "classic", "faiss_hierarchical")


def test_user_permissions(isolated_rag_manager):
    """_check_user_permission is present and callable."""
    assert hasattr(isolated_rag_manager, "_check_user_permission")
    assert callable(isolated_rag_manager._check_user_permission)
