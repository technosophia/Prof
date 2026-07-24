import sys
import types
from pathlib import Path

from modules.rag_manager.rag_engines.rag_pageindex import PageIndexRAGEngine


class FakePageIndexClient:
    documents = {}

    def __init__(self, workspace, retrieve_model=None):
        self.workspace = Path(workspace)
        self.retrieve_model = retrieve_model
        self.workspace.mkdir(parents=True, exist_ok=True)

    def index(self, path):
        self.indexed_path = Path(path)
        return "doc-1"

    def get_document_structure(self, doc_id):
        return [
            {
                "title": "Root",
                "summary": "General training content",
                "node_id": "0001",
                "start_index": 1,
                "end_index": 2,
                "nodes": [
                    {
                        "title": "Breathing practice",
                        "summary": "Slow breathing calms the nervous system",
                        "node_id": "0002",
                        "start_index": 2,
                        "end_index": 3,
                    }
                ],
            }
        ]

    def get_page_content(self, doc_id, pages):
        return f"Page content for {pages}: slow breathing details"


def install_fake_pageindex(monkeypatch):
    fake = types.ModuleType("pageindex")
    fake.PageIndexClient = FakePageIndexClient
    monkeypatch.setitem(sys.modules, "pageindex", fake)


def make_engine(tmp_path):
    return PageIndexRAGEngine(
        config={
            "index_path": str(tmp_path / "indexes"),
            "pageindex_root": str(tmp_path / "missing_pageindex"),
            "max_results": 3,
        },
        engine_id="pageindex_test",
    )


def test_pageindex_engine_contract(tmp_path):
    engine = make_engine(tmp_path)
    assert PageIndexRAGEngine.ENGINE_TYPE == "pageindex"
    assert engine.engine_type == "pageindex"
    assert engine.engine_id == "pageindex_test"
    assert engine.get_config()["max_results"] == 3


def test_pageindex_engine_unavailable_without_dependency(tmp_path, monkeypatch):
    monkeypatch.delitem(sys.modules, "pageindex", raising=False)
    engine = make_engine(tmp_path)
    assert engine.is_available() is False


def test_pageindex_index_search_and_delete(tmp_path, monkeypatch):
    install_fake_pageindex(monkeypatch)
    source = tmp_path / "lesson.md"
    source.write_text("# Breathing\nSlow breathing calms students.", encoding="utf-8")
    engine = make_engine(tmp_path)

    assert engine.is_available() is True
    assert engine.index_document("user-1", "lesson.md", str(source)) is True

    indexed = engine.get_indexed_documents("user-1")
    assert len(indexed) == 1
    assert indexed[0]["doc_id"] == "doc-1"

    results = engine.search("user-1", "How does breathing calm students?", limit=2)
    assert len(results) >= 1
    assert results[0]["filename"] == "lesson.md"
    assert "breathing" in results[0]["content"].lower()
    assert results[0]["metadata"]["node_id"] in {"0001", "0002"}

    assert engine.delete_document("user-1", "lesson.md") is True
    assert engine.get_indexed_documents("user-1") == []


def test_pageindex_txt_content_is_converted_to_markdown(tmp_path, monkeypatch):
    install_fake_pageindex(monkeypatch)
    source = tmp_path / "notes.txt"
    source.write_text("plain notes", encoding="utf-8")
    engine = make_engine(tmp_path)

    assert engine.index_document("user-1", "notes.txt", str(source), content="plain notes") is True
    indexed_path = Path(engine.get_indexed_documents("user-1")[0]["indexed_path"])
    assert indexed_path.suffix == ".md"
    assert indexed_path.read_text(encoding="utf-8") == "plain notes"


def test_pageindex_clear_user_index(tmp_path, monkeypatch):
    install_fake_pageindex(monkeypatch)
    source = tmp_path / "lesson.md"
    source.write_text("# Lesson", encoding="utf-8")
    engine = make_engine(tmp_path)
    assert engine.index_document("user-1", "lesson.md", str(source)) is True
    assert engine.clear_user_index("user-1") is True
    assert engine.get_indexed_documents("user-1") == []
