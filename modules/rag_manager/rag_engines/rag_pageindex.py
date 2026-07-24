"""
PageIndex RAG Engine Plugin

Wraps VectifyAI PageIndex as an optional, vectorless RAG engine while keeping
Prof's existing RAGEngine contract and dynamic engine registry.
"""

import importlib
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from core.thread import run_async_safely

from modules.rag_manager.rag_engine import RAGEngine
from core.logging import log


class PageIndexRAGEngine(RAGEngine):
    """RAG engine backed by PageIndex's hierarchical document index."""

    ENGINE_TYPE = "pageindex"
    SUPPORTED_EXTENSIONS = {".pdf", ".md", ".markdown", ".txt"}

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        engine_id: Optional[str] = None,
    ):
        super().__init__(engine_type=self.ENGINE_TYPE, engine_id=engine_id)
        cfg = config or {}

        self.description = cfg.get(
            "description",
            "PageIndex vectorless reasoning-based RAG",
        )
        self.index_path = Path(cfg.get("index_path", "data/pageindex_indexes/default"))
        self.pageindex_root = Path(cfg.get("pageindex_root", "vendor/PageIndex"))
        self.llm_id = cfg.get("llm_id")
        self.agent_max_steps = int(cfg.get("agent_max_steps", 5))
        self.agent_response_format = cfg.get("agent_response_format", "json")
        self.fallback_search_mode = cfg.get("fallback_search_mode", "structure_keyword")
        self.max_results = int(cfg.get("max_results", 5))
        self.content_preview_chars = int(cfg.get("content_preview_chars", 1800))
        self.include_structure_on_empty_query = bool(cfg.get("include_structure_on_empty_query", True))

        self.toc_check_pages = int(cfg.get("toc_check_pages", 20))
        self.max_pages_per_node = int(cfg.get("max_pages_per_node", 10))
        self.max_tokens_per_node = int(cfg.get("max_tokens_per_node", 20000))
        self.if_add_node_id = bool(cfg.get("if_add_node_id", True))
        self.if_add_node_summary = bool(cfg.get("if_add_node_summary", True))
        self.if_add_doc_description = bool(cfg.get("if_add_doc_description", True))
        self.if_add_node_text = bool(cfg.get("if_add_node_text", False))

        self.index_path.mkdir(parents=True, exist_ok=True)
        self._registry: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._pageindex_module_available: Optional[bool] = None
        self._load_registry()

    # ------------------------------------------------------------------
    # Config and availability
    # ------------------------------------------------------------------

    def get_config(self) -> Dict[str, Any]:
        return {
            "index_path": str(self.index_path),
            "pageindex_root": str(self.pageindex_root),
            "llm_id": self.llm_id,
            "agent_max_steps": self.agent_max_steps,
            "agent_response_format": self.agent_response_format,
            "fallback_search_mode": self.fallback_search_mode,
            "max_results": self.max_results,
            "content_preview_chars": self.content_preview_chars,
            "toc_check_pages": self.toc_check_pages,
            "max_pages_per_node": self.max_pages_per_node,
            "max_tokens_per_node": self.max_tokens_per_node,
            "if_add_node_id": self.if_add_node_id,
            "if_add_node_summary": self.if_add_node_summary,
            "if_add_doc_description": self.if_add_doc_description,
            "if_add_node_text": self.if_add_node_text,
        }

    def update_config(self, overrides: Dict[str, Any]) -> None:
        mutable = {
            "llm_id": str,
            "agent_max_steps": int,
            "agent_response_format": str,
            "fallback_search_mode": str,
            "max_results": int,
            "content_preview_chars": int,
            "toc_check_pages": int,
            "max_pages_per_node": int,
            "max_tokens_per_node": int,
            "if_add_node_id": bool,
            "if_add_node_summary": bool,
            "if_add_doc_description": bool,
            "if_add_node_text": bool,
        }
        for key, caster in mutable.items():
            if key in overrides:
                setattr(self, key, caster(overrides[key]))
                log("debug", f"PageIndexRAGEngine [{self.engine_id}]: {key} updated")

    def is_available(self) -> bool:
        return self._load_pageindex_client_class(raise_on_error=False) is not None

    def _load_pageindex_client_class(self, raise_on_error: bool = True):
        if str(self.pageindex_root) not in sys.path and self.pageindex_root.exists():
            sys.path.insert(0, str(self.pageindex_root.resolve()))
        try:
            module = importlib.import_module("pageindex")
            client_class = getattr(module, "PageIndexClient")
            self._pageindex_module_available = True
            return client_class
        except Exception as exc:
            self._pageindex_module_available = False
            message = (
                "PageIndex is not importable. Run: "
                "git submodule update --init --recursive && "
                "python -m pip install -r vendor/PageIndex/requirements.txt"
            )
            if raise_on_error:
                log("error", f"{message}. Original error: {exc}")
                raise RuntimeError(message) from exc
            log("debug", f"{message}. Original error: {exc}")
            return None

    # ------------------------------------------------------------------
    # Paths and registry
    # ------------------------------------------------------------------

    def _safe_name(self, value: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
        return safe or "document"

    def _user_path(self, user_id: str) -> Path:
        path = self.index_path / self.engine_id / self._safe_name(user_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _document_workspace(self, user_id: str, filename: str) -> Path:
        return self._user_path(user_id) / self._safe_name(filename)

    def _registry_path(self) -> Path:
        return self.index_path / self.engine_id / "registry.json"

    def _load_registry(self) -> None:
        path = self._registry_path()
        if not path.exists():
            self._registry = {}
            return
        try:
            self._registry = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            log("error", f"PageIndex: failed to load registry {path}: {exc}")
            self._registry = {}

    def _save_registry(self) -> None:
        path = self._registry_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._registry, indent=2, ensure_ascii=False), encoding="utf-8")

    def _client_for_workspace(self, workspace: Path):
        PageIndexClient = self._load_pageindex_client_class(raise_on_error=True)
        try:
            return PageIndexClient(workspace=workspace)
        except TypeError:
            return PageIndexClient(str(workspace))

    # ------------------------------------------------------------------
    # RAGEngine operations
    # ------------------------------------------------------------------

    def index_document(
        self,
        user_id: str,
        filename: str,
        file_path: str,
        content: Optional[str] = None,
    ) -> bool:
        source_path = Path(file_path)
        suffix = source_path.suffix.lower()
        if suffix not in self.SUPPORTED_EXTENSIONS:
            log("error", f"PageIndex: unsupported file extension for {filename}: {suffix}")
            return False

        workspace = self._document_workspace(user_id, filename)
        workspace.mkdir(parents=True, exist_ok=True)
        index_input = source_path

        if suffix == ".txt":
            if content is None:
                content = source_path.read_text(encoding="utf-8")
            index_input = workspace / f"{source_path.stem or 'document'}.md"
            index_input.write_text(content, encoding="utf-8")

        try:
            client = self._client_for_workspace(workspace)
            doc_id = self._index_with_pageindex(client, index_input)
            metadata = {
                "filename": filename,
                "doc_id": str(doc_id),
                "workspace": str(workspace),
                "source_path": str(source_path),
                "indexed_path": str(index_input),
                "indexed_at": datetime.now().isoformat(),
                "file_size": source_path.stat().st_size,
                "llm_id": self.llm_id,
            }
            self._registry.setdefault(user_id, {})[filename] = metadata
            self._save_registry()
            log("info", f"PageIndex: indexed {filename} for user {user_id} as {doc_id}")
            return True
        except Exception as exc:
            log("error", f"PageIndex: failed to index {filename}: {exc}", stacktrace=True)
            return False


    def _index_with_pageindex(self, client: Any, index_input: Path) -> Any:
        """Build the PageIndex tree while disabling PageIndex LLM enrichment when supported."""
        kwargs = {
            "toc_check_pages": self.toc_check_pages,
            "max_pages_per_node": self.max_pages_per_node,
            "max_tokens_per_node": self.max_tokens_per_node,
            "if_add_node_id": self.if_add_node_id,
            "if_add_node_summary": self.if_add_node_summary,
            "if_add_doc_description": self.if_add_doc_description,
            "if_add_node_text": self.if_add_node_text,
        }
        try:
            return client.index(index_input, **kwargs)
        except TypeError:
            return client.index(index_input)

    def _get_llm_manager(self) -> Any:
        from shared.common import get_llm_manager

        manager = get_llm_manager()
        if manager is None:
            raise RuntimeError("PageIndex: Prof LLM manager is not available")
        return manager

    def _resolve_llm_id(self, manager: Any) -> str:
        llm_id = self.llm_id or getattr(manager, "current_llm", None)
        if not llm_id:
            raise RuntimeError("PageIndex: no Prof LLM is currently configured")
        return str(llm_id)

    def _select_nodes_with_prof_llm(
        self,
        filename: str,
        doc_id: str,
        structure: Any,
        query: str,
    ) -> List[Dict[str, Any]]:
        try:
            manager = self._get_llm_manager()
            llm_id = self._resolve_llm_id(manager)
            prompt = self._selection_prompt(filename, doc_id, structure, query)
            messages = [{"role": "user", "content": prompt}]
            raw = run_async_safely(
                manager.internal_response(
                    llm_id,
                    messages,
                    response_format=self.agent_response_format,
                )
            )
            parsed = self._parse_llm_json(raw)
            results = parsed.get("results", [])
            if not isinstance(results, list):
                return []
            normalized = []
            for item in results:
                if not isinstance(item, dict):
                    continue
                item["source"] = "prof_llm"
                item["llm_id"] = llm_id
                item.setdefault("score", 0.5)
                normalized.append(item)
            return normalized
        except Exception as exc:
            log("warning", f"PageIndex: Prof LLM selection failed for {filename}: {exc}")
            return []

    def _selection_prompt(self, filename: str, doc_id: str, structure: Any, query: str) -> str:
        structure_json = json.dumps(structure, ensure_ascii=False)[:12000]
        return (
            "You are selecting PageIndex document nodes for a RAG retriever.\n"
            "Use only the provided document structure. Do not answer the user.\n"
            "Return strict JSON with this shape: "
            "{\"results\":[{\"node_id\":\"...\",\"title\":\"...\","
            "\"page_range\":\"...\",\"reason\":\"...\",\"score\":0.0}]}.\n"
            f"Document filename: {filename}\n"
            f"Document id: {doc_id}\n"
            f"User query: {query}\n"
            f"Max results: {self.max_results}\n"
            f"Document structure JSON:\n{structure_json}"
        )

    def _parse_llm_json(self, raw: str) -> Dict[str, Any]:
        try:
            return json.loads(raw)
        except Exception:
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                return json.loads(raw[start:end + 1])
            raise

    def _node_lookup(self, nodes: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        lookup = {}
        for node in nodes:
            node_id = node.get("node_id") or node.get("id")
            if node_id is not None:
                lookup[str(node_id)] = node
        return lookup

    def _keyword_select_nodes(self, nodes: List[Dict[str, Any]], query_terms: List[str]) -> List[Dict[str, Any]]:
        scored: List[Tuple[float, Dict[str, Any]]] = []
        for node in nodes:
            node_text = " ".join(str(node.get(key, "")) for key in ("title", "summary", "text", "description"))
            score = self._keyword_score(node_text, query_terms)
            if score > 0 or (not query_terms and self.include_structure_on_empty_query):
                scored.append((score, node))
        if not scored and nodes:
            scored = [(0.1, node) for node in nodes[: self.max_results]]
        selections = []
        for score, node in sorted(scored, key=lambda pair: pair[0], reverse=True):
            selections.append({
                "node_id": node.get("node_id") or node.get("id"),
                "title": node.get("title"),
                "page_range": self._node_pages(node),
                "reason": "keyword fallback",
                "score": score,
                "source": "fallback",
            })
        return selections

    def delete_document(self, user_id: str, filename: str) -> bool:
        try:
            removed = False
            if user_id in self._registry and filename in self._registry[user_id]:
                self._registry[user_id].pop(filename, None)
                if not self._registry[user_id]:
                    self._registry.pop(user_id, None)
                removed = True
            workspace = self._document_workspace(user_id, filename)
            if workspace.exists():
                shutil.rmtree(workspace)
                removed = True
            self._save_registry()
            return removed
        except Exception as exc:
            log("error", f"PageIndex: failed to delete {filename}: {exc}")
            return False

    def search(self, user_id: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        docs = self._registry.get(user_id, {})
        if not docs:
            return [self._no_results(0.0)]

        results: List[Dict[str, Any]] = []
        effective_limit = min(limit, self.max_results)
        for filename, doc in docs.items():
            try:
                results.extend(self._search_document(filename, doc, query))
            except Exception as exc:
                log("error", f"PageIndex: failed to search {filename}: {exc}")

        results.sort(key=lambda item: item.get("score", 0.0), reverse=True)
        if not results:
            return [self._no_results(0.0)]
        max_score = results[0].get("score", 0.0)
        for result in results[:effective_limit]:
            result["max_score_reached"] = max_score
        return results[:effective_limit]

    def _search_document(self, filename: str, doc: Dict[str, Any], query: str) -> List[Dict[str, Any]]:
        workspace = Path(doc["workspace"])
        client = self._client_for_workspace(workspace)
        doc_id = doc["doc_id"]
        structure_text = client.get_document_structure(doc_id)
        structure = json.loads(structure_text) if isinstance(structure_text, str) else structure_text
        nodes = list(self._flatten_nodes(structure))
        query_terms = [term for term in re.findall(r"\w+", query.lower()) if len(term) > 2]

        selections = self._select_nodes_with_prof_llm(filename, doc_id, structure, query)
        if not selections and self.fallback_search_mode == "structure_keyword":
            selections = self._keyword_select_nodes(nodes, query_terms)

        results = []
        node_lookup = self._node_lookup(nodes)
        for selection in selections[: self.max_results]:
            node = node_lookup.get(str(selection.get("node_id", "")), {})
            pages = str(selection.get("page_range") or selection.get("pages") or self._node_pages(node))
            page_content = self._get_page_content(client, doc_id, pages)
            content = self._compose_content(node or selection, page_content)
            results.append(
                {
                    "filename": filename,
                    "score": float(selection.get("score", 0.0)),
                    "content": content[: self.content_preview_chars],
                    "metadata": {
                        **doc,
                        "node_id": selection.get("node_id") or node.get("node_id") or node.get("id"),
                        "title": selection.get("title") or node.get("title"),
                        "pages": pages,
                        "reason": selection.get("reason", ""),
                        "engine": self.engine_id,
                        "llm_id": selection.get("llm_id") or self.llm_id,
                        "agent_steps": 1 if selection.get("source") == "prof_llm" else 0,
                    },
                    "threshold_used": 0.0,
                }
            )
        return results

    def get_indexed_documents(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        docs: List[Dict[str, Any]] = []
        users = [user_id] if user_id else list(self._registry.keys())
        for uid in users:
            for metadata in self._registry.get(uid, {}).values():
                docs.append({**metadata, "user_id": uid})
        return docs

    def clear_user_index(self, user_id: str) -> bool:
        try:
            self._registry.pop(user_id, None)
            user_path = self._user_path(user_id)
            if user_path.exists():
                shutil.rmtree(user_path)
            self._save_registry()
            return True
        except Exception as exc:
            log("error", f"PageIndex: failed to clear user index {user_id}: {exc}")
            return False

    def get_stats(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        docs = self.get_indexed_documents(user_id)
        return {
            "engine_type": self.engine_type,
            "engine_id": self.engine_id,
            "description": self.description,
            "available": self.is_available(),
            "indexed_documents": len(docs),
            "index_path": str(self.index_path),
            "pageindex_root": str(self.pageindex_root),
            "llm_id": self.llm_id,
            "agent_max_steps": self.agent_max_steps,
            "agent_response_format": self.agent_response_format,
            "fallback_search_mode": self.fallback_search_mode,
        }

    # ------------------------------------------------------------------
    # Search helpers
    # ------------------------------------------------------------------

    def _flatten_nodes(self, value: Any) -> Iterable[Dict[str, Any]]:
        if isinstance(value, dict):
            yield value
            for child_key in ("nodes", "children"):
                children = value.get(child_key, [])
                if isinstance(children, list):
                    for child in children:
                        yield from self._flatten_nodes(child)
        elif isinstance(value, list):
            for item in value:
                yield from self._flatten_nodes(item)

    def _keyword_score(self, text: str, terms: List[str]) -> float:
        lowered = text.lower()
        return float(sum(lowered.count(term) for term in terms))

    def _node_pages(self, node: Dict[str, Any]) -> str:
        start = node.get("start_index") or node.get("start_page") or node.get("page") or node.get("line_num")
        end = node.get("end_index") or node.get("end_page") or start
        if start is None:
            return ""
        return str(start) if start == end else f"{start}-{end}"

    def _get_page_content(self, client: Any, doc_id: str, pages: str) -> str:
        if not pages:
            return ""
        try:
            return str(client.get_page_content(doc_id, pages))
        except Exception as exc:
            log("warning", f"PageIndex: could not retrieve page content for {doc_id} pages={pages}: {exc}")
            return ""

    def _compose_content(self, node: Dict[str, Any], page_content: str) -> str:
        parts = []
        title = node.get("title")
        summary = node.get("summary") or node.get("description")
        if title:
            parts.append(f"Title: {title}")
        if summary:
            parts.append(f"Summary: {summary}")
        if page_content:
            parts.append(f"Source excerpt:\n{page_content}")
        return "\n\n".join(parts)

    def _no_results(self, max_score: float) -> Dict[str, Any]:
        return {
            "filename": None,
            "score": 0,
            "content": "",
            "threshold_used": 0.0,
            "max_score_reached": max_score,
            "no_results": True,
        }
