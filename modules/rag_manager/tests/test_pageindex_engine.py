import json
from pathlib import Path

from modules.rag_manager.rag_engines.rag_pageindex import PageIndexRAGEngine


class FakeLLMManager:
    current_llm = "mock-prof-llm"

    def __init__(self, response=None):
        self.calls = []
        self.response = response or json.dumps(
            {
                "results": [
                    {
                        "node_id": "0001",
                        "title": "Breathing practice",
                        "page_range": "1",
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


def test_pageindex_engine_available_without_litellm_or_pageindex_dependency(tmp_path, monkeypatch):
    def fail_import(name, *args, **kwargs):
        if name in {"litellm", "pageindex"}:
            raise AssertionError(f"Unexpected import: {name}")
        return original_import(name, *args, **kwargs)

    original_import = __import__
    monkeypatch.setattr("builtins.__import__", fail_import)
    engine = make_engine(tmp_path)
    assert engine.is_available() is True


def test_pageindex_index_search_and_delete_uses_prof_llm_only(tmp_path, monkeypatch):
    source = tmp_path / "lesson.md"
    source.write_text("# Breathing practice\nSlow breathing calms students.", encoding="utf-8")
    engine = make_engine(tmp_path)
    fake_llm = FakeLLMManager()
    monkeypatch.setattr(engine, "_get_llm_manager", lambda: fake_llm)

    assert engine.index_document("user-1", "lesson.md", str(source)) is True
    workspace = engine._document_workspace("user-1", "lesson.md")
    assert (workspace / "structure.json").exists()
    assert (workspace / "pages.json").exists()

    indexed = engine.get_indexed_documents("user-1")
    assert len(indexed) == 1
    assert indexed[0]["doc_id"] == "lesson.md"

    results = engine.search("user-1", "How does breathing calm students?", limit=2)
    assert len(results) == 1
    assert results[0]["filename"] == "lesson.md"
    assert results[0]["score"] == 0.91
    assert "breathing" in results[0]["content"].lower()
    assert results[0]["metadata"]["node_id"] == "0001"
    assert results[0]["metadata"]["llm_id"] == "configured-prof-llm"
    assert fake_llm.calls[0]["llm_id"] == "configured-prof-llm"
    assert fake_llm.calls[0]["response_format"] == "json"

    assert engine.delete_document("user-1", "lesson.md") is True
    assert engine.get_indexed_documents("user-1") == []


def test_pageindex_never_imports_litellm_during_index_or_search(tmp_path, monkeypatch):
    source = tmp_path / "lesson.md"
    source.write_text("# Breathing practice\nSlow breathing calms students.", encoding="utf-8")
    engine = make_engine(tmp_path)
    fake_llm = FakeLLMManager()
    monkeypatch.setattr(engine, "_get_llm_manager", lambda: fake_llm)

    original_import = __import__

    def fail_litellm_import(name, *args, **kwargs):
        if name == "litellm" or name.startswith("litellm."):
            raise AssertionError("LiteLLM must not be imported by PageIndexRAGEngine")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fail_litellm_import)
    assert engine.index_document("user-1", "lesson.md", str(source)) is True
    results = engine.search("user-1", "breathing", limit=1)
    assert results[0]["metadata"]["llm_id"] == "configured-prof-llm"


def test_pageindex_txt_content_is_indexed_locally(tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text("plain notes", encoding="utf-8")
    engine = make_engine(tmp_path)

    assert engine.index_document("user-1", "notes.txt", str(source), content="plain notes") is True
    workspace = engine._document_workspace("user-1", "notes.txt")
    pages = json.loads((workspace / "pages.json").read_text(encoding="utf-8"))
    assert pages["1"] == "plain notes"


def test_pageindex_search_falls_back_when_prof_llm_json_is_invalid(tmp_path, monkeypatch):
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


def test_pageindex_clear_user_index(tmp_path):
    source = tmp_path / "lesson.md"
    source.write_text("# Lesson", encoding="utf-8")
    engine = make_engine(tmp_path)
    assert engine.index_document("user-1", "lesson.md", str(source)) is True
    assert engine.clear_user_index("user-1") is True
    assert engine.get_indexed_documents("user-1") == []
