import json
import sys
import types
from pathlib import Path

from modules.rag_manager.rag_engines.rag_pageindex import PageIndexRAGEngine


class FakePageIndexClient:
    init_kwargs = []
    index_kwargs = []

    def __init__(self, workspace):
        FakePageIndexClient.init_kwargs.append({"workspace": workspace})
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)

    def index(self, path, **kwargs):
        self.indexed_path = Path(path)
        FakePageIndexClient.index_kwargs.append(kwargs)
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


class FakeLLMManager:
    current_llm = "mock-prof-llm"

    def __init__(self, response=None):
        self.calls = []
        self.response = response or json.dumps(
            {
                "results": [
                    {
                        "node_id": "0002",
                        "title": "Breathing practice",
                        "page_range": "2-3",
                        "reason": "The node is about calming breathwork.",
                        "score": 0.91,
                    }
                ]
            }
        )

    async def internal_response(self, llm_id, messages, response_format=None):
        self.calls.append(
            {
                "llm_id": llm_id,
                "messages": messages,
                "response_format": response_format,
            }
        )
        return self.response


def install_fake_pageindex(monkeypatch):
    FakePageIndexClient.init_kwargs.clear()
    FakePageIndexClient.index_kwargs.clear()
    fake = types.ModuleType("pageindex")
    fake.PageIndexClient = FakePageIndexClient
    monkeypatch.setitem(sys.modules, "pageindex", fake)


def make_engine(tmp_path, **overrides):
    config = {
        "index_path": str(tmp_path / "indexes"),
        "pageindex_root": str(tmp_path / "missing_pageindex"),
        "max_results": 3,
        "llm_id": "configured-prof-llm",
        "if_add_node_summary": False,
        "if_add_doc_description": False,
        **overrides,
    }
    return PageIndexRAGEngine(config=config, engine_id="pageindex_test")


def test_pageindex_config_is_enabled_by_default():
    config = json.loads(Path("modules/rag_manager/config.json").read_text(encoding="utf-8"))
    pageindex = config["rag_manager"]["engines"]["pageindex"]
    assert pageindex["enabled"] is True
    assert config["rag_manager"]["default_engine"] != "pageindex"
    assert pageindex["llm_id"] is None
    assert pageindex["if_add_node_summary"] is False
    assert pageindex["if_add_doc_description"] is False


def test_pageindex_engine_contract(tmp_path):
    engine = make_engine(tmp_path)
    assert PageIndexRAGEngine.ENGINE_TYPE == "pageindex"
    assert engine.engine_type == "pageindex"
    assert engine.engine_id == "pageindex_test"
    assert engine.get_config()["max_results"] == 3
    assert engine.get_config()["llm_id"] == "configured-prof-llm"


def test_pageindex_engine_unavailable_without_dependency(tmp_path, monkeypatch):
    monkeypatch.delitem(sys.modules, "pageindex", raising=False)
    engine = make_engine(tmp_path)
    assert engine.is_available() is False


def test_pageindex_index_search_and_delete_uses_prof_llm(tmp_path, monkeypatch):
    install_fake_pageindex(monkeypatch)
    source = tmp_path / "lesson.md"
    source.write_text("# Breathing\nSlow breathing calms students.", encoding="utf-8")
    engine = make_engine(tmp_path)
    fake_llm = FakeLLMManager()
    monkeypatch.setattr(engine, "_get_llm_manager", lambda: fake_llm)

    assert engine.is_available() is True
    assert engine.index_document("user-1", "lesson.md", str(source)) is True
    assert FakePageIndexClient.init_kwargs == [{"workspace": engine._document_workspace("user-1", "lesson.md")}]
    assert FakePageIndexClient.index_kwargs[0]["if_add_node_summary"] is False
    assert FakePageIndexClient.index_kwargs[0]["if_add_doc_description"] is False

    indexed = engine.get_indexed_documents("user-1")
    assert len(indexed) == 1
    assert indexed[0]["doc_id"] == "doc-1"

    results = engine.search("user-1", "How does breathing calm students?", limit=2)
    assert len(results) == 1
    assert results[0]["filename"] == "lesson.md"
    assert results[0]["score"] == 0.91
    assert "breathing" in results[0]["content"].lower()
    assert results[0]["metadata"]["node_id"] == "0002"
    assert results[0]["metadata"]["llm_id"] == "configured-prof-llm"
    assert fake_llm.calls[0]["llm_id"] == "configured-prof-llm"
    assert fake_llm.calls[0]["response_format"] == "json"

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


def test_pageindex_search_falls_back_when_prof_llm_json_is_invalid(tmp_path, monkeypatch):
    install_fake_pageindex(monkeypatch)
    source = tmp_path / "lesson.md"
    source.write_text("# Breathing\nSlow breathing calms students.", encoding="utf-8")
    engine = make_engine(tmp_path, fallback_search_mode="structure_keyword")
    fake_llm = FakeLLMManager(response="not json")
    monkeypatch.setattr(engine, "_get_llm_manager", lambda: fake_llm)

    assert engine.index_document("user-1", "lesson.md", str(source)) is True
    results = engine.search("user-1", "breathing", limit=2)

    assert len(results) >= 1
    assert results[0]["metadata"]["reason"] == "keyword fallback"
    assert fake_llm.calls


def test_pageindex_clear_user_index(tmp_path, monkeypatch):
    install_fake_pageindex(monkeypatch)
    source = tmp_path / "lesson.md"
    source.write_text("# Lesson", encoding="utf-8")
    engine = make_engine(tmp_path)
    assert engine.index_document("user-1", "lesson.md", str(source)) is True
    assert engine.clear_user_index("user-1") is True
    assert engine.get_indexed_documents("user-1") == []
