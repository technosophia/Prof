"""
Pedagogical Memory Plugin for Trainer Module.
Maintains structured atomic pedagogical facts with semantic retrieval.

Migration status: COMPLETE
  - initialize() calls self._resolve_services(services)
  - Added legacy fallback for self.config when services=None
  - All data methods use self.db, self.user_manager, self.conversation_manager,
    self.llm_manager, self.config — no st_shared.cached imports elsewhere
  - All render methods call self.<data_method>() only — no db/cache access inline
  - When splitting into two classes: replace self.xxx() with self._logic.xxx()
    in every render method. No logic rewrite needed.
"""

from typing import List, Dict, Any, Optional, Callable, Tuple
from datetime import datetime, timedelta
import uuid
import json
import asyncio

import numpy as np
from sqlalchemy import Column, String, Text, DateTime, JSON, Integer, Float, LargeBinary, desc

from shared.common import get_prompt, register_llm_context_callback, get_current_llm_id, get_embedding
from modules.trainer.plugin_base import PluginManifest
from modules.trainer.plugin_base_core import TrainerPluginCore

from core.logging import log
from core.database import Base

EMBEDDING_DIMENSION = 384


class PedagogicalFact(Base):
    __tablename__ = "trainer_pedagogical_facts"
    __table_args__ = {"extend_existing": True}

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id = Column(String(36), nullable=False, index=True)
    trainer_id = Column(String(36), nullable=False, index=True)
    fact_type = Column(String(64), nullable=False)
    content = Column(Text, default="")
    embedding = Column(LargeBinary, nullable=False)
    embedding_dim = Column(Integer, default=EMBEDDING_DIMENSION)
    confidence = Column(Float, default=1.0)
    is_active = Column(Integer, default=1)
    source_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_reinforced_at = Column(DateTime, nullable=True)
    fact_metadata = Column(JSON, default={})


class PedagogicalAnalysisLog(Base):
    __tablename__ = "trainer_pedagogical_analysis_logs"
    __table_args__ = {"extend_existing": True}

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id = Column(String(36), nullable=False, index=True)
    trainer_id = Column(String(36), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    messages_analyzed = Column(Integer, default=0)
    facts_created = Column(Integer, default=0)
    facts_updated = Column(Integer, default=0)
    facts_discarded = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


def _run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    else:
        return asyncio.run(coro)



class PedagogicalMemoryPluginCore(TrainerPluginCore):

    def initialize(self, services=None) -> bool:
        """
        Initialize the plugin, tables, and context callback.

        Resolves all services via _resolve_services. If still in legacy mode
        (services=None), also loads config from st_shared.cached because the
        base fallback does not set self.config.
        """
        try:
            self._resolve_services(services)

            # Legacy fallback: if config is still None, try to load it directly
            if self.config is None:
                try:
                    from st_shared.cached import get_config
                    self.config = get_config()
                    log("debug", "PedagogicalMemoryPlugin: loaded config from st_shared.cached fallback")
                except ImportError:
                    log("warning", "PedagogicalMemoryPlugin: no config available, using defaults")
                    self.config = {}

            if self.db and self.db.is_initialized() and not self.db._in_memory:
                Base.metadata.create_all(
                    self.db._engine,
                    tables=[PedagogicalFact.__table__, PedagogicalAnalysisLog.__table__],
                    checkfirst=True,
                )
                log("info", "Pedagogical memory tables created/verified")

            register_llm_context_callback(self.get_memory_context)
            return True
        except Exception as e:
            log("error", f"Failed to initialize pedagogical_memory plugin: {e}", exc_info=True)
            return False

    def on_activate(self, trainer_id: str) -> None:
        log("info", f"Pedagogical memory plugin activated for trainer {trainer_id}")

    def on_deactivate(self, trainer_id: str) -> None:
        log("info", f"Pedagogical memory plugin deactivated for trainer {trainer_id}")

    def _get_plugin_config(self) -> Dict[str, Any]:
        """Get plugin runtime configuration from injected config."""
        # self.config is guaranteed to be a dict (or dict-like) after initialize()
        root_config = self.config.get("modules.trainer.plugins.pedagogical_memory", {}) if self.config else {}
        config = root_config.get("pedagogical_memory", root_config)
        return {
            "fact_types": config.get("fact_types", {}),
            "fact_type_colors": config.get("fact_type_colors", {}),
            "similarity_threshold": float(config.get("similarity_threshold", 0.85)),
            "top_k_context": int(config.get("top_k_context", 5)),
            "decay_days": int(config.get("decay_days", 30)),
            "decay_factor": float(config.get("decay_factor", 0.85)),
            "decay_min_confidence": float(config.get("decay_min_confidence", 0.1)),
        }

    def _serialize_embedding(self, embedding: List[float]) -> bytes:
        return np.asarray(embedding, dtype=np.float32).tobytes()

    def _deserialize_embedding(self, embedding_bytes: bytes, dim: int) -> np.ndarray:
        vector = np.frombuffer(embedding_bytes, dtype=np.float32)
        if dim and vector.shape[0] != dim:
            log("warning", f"Embedding dimension mismatch: expected {dim}, got {vector.shape[0]}")
        return vector

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        if a.size == 0 or b.size == 0:
            return 0.0
        norm_a = float(np.linalg.norm(a))
        norm_b = float(np.linalg.norm(b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def _get_last_analysis_date(self, trainer_id: str, student_id: str) -> Optional[datetime]:
        try:
            with self.db.get_session() as session:
                analysis = (
                    session.query(PedagogicalAnalysisLog)
                    .filter_by(trainer_id=trainer_id, student_id=student_id)
                    .order_by(desc(PedagogicalAnalysisLog.version))
                    .first()
                )
                return analysis.created_at if analysis else None
        except Exception as e:
            log("error", f"Failed to read last analysis date: {e}", exc_info=True)
            return None

    def _get_next_analysis_version(self, trainer_id: str, student_id: str) -> int:
        try:
            with self.db.get_session() as session:
                latest = (
                    session.query(PedagogicalAnalysisLog)
                    .filter_by(trainer_id=trainer_id, student_id=student_id)
                    .order_by(desc(PedagogicalAnalysisLog.version))
                    .first()
                )
                return (latest.version + 1) if latest else 1
        except Exception as e:
            log("error", f"Failed to compute analysis version: {e}", exc_info=True)
            return 1

    def _get_new_conversations(self, student_id: str, since: Optional[datetime]) -> List[Dict[str, Any]]:
        new_messages = []
        try:
            conversations = self.conversation_manager.get_user_conversations(student_id)
            for conv in conversations:
                full_conv = self.conversation_manager.get_conversation(conv["id"])
                if not full_conv or not full_conv.messages:
                    continue
                for msg in full_conv.messages:
                    if msg.role not in ["user", "assistant"]:
                        continue
                    msg_time = msg.timestamp
                    if msg_time and (not since or msg_time > since):
                        new_messages.append({
                            "role": msg.role,
                            "content": msg.content,
                            "timestamp": msg_time.isoformat() if msg_time else None,
                            "conversation_id": conv["id"],
                            "conversation_title": conv.get("title", "Untitled"),
                        })
            new_messages.sort(key=lambda x: x.get("timestamp", ""))
        except Exception as e:
            log("error", f"Failed to read conversations: {e}", exc_info=True)
        return new_messages

    def _format_fact_types(self, fact_types: Dict[str, str]) -> str:
        lines = [f"- {key}: {description}" for key, description in fact_types.items()]
        return "\n".join(lines)

    def _find_similar_facts(
        self,
        session,
        trainer_id: str,
        student_id: str,
        candidate_type: str,
        candidate_embedding: np.ndarray,
        top_n: int = 3,
    ) -> List[Tuple[PedagogicalFact, float]]:
        try:
            existing = (
                session.query(PedagogicalFact)
                .filter_by(trainer_id=trainer_id, student_id=student_id, is_active=1, fact_type=candidate_type)
                .all()
            )
            scored = []
            for fact in existing:
                vector = self._deserialize_embedding(fact.embedding, fact.embedding_dim)
                score = self._cosine_similarity(candidate_embedding, vector)
                scored.append((fact, score))
            scored.sort(key=lambda x: x[1], reverse=True)
            return scored[:top_n]
        except Exception as e:
            log("error", f"Failed to search similar facts: {e}", exc_info=True)
            return []

    def _find_similar_facts_in_memory(
        self,
        facts: List[Dict[str, Any]],
        candidate_type: str,
        candidate_embedding: np.ndarray,
        top_n: int = 3,
    ) -> List[Tuple[Dict[str, Any], float]]:
        scored = []
        for fact in facts:
            if fact.get("fact_type") != candidate_type or int(fact.get("is_active", 0)) != 1:
                continue
            vector = self._deserialize_embedding(fact.get("embedding", b""), int(fact.get("embedding_dim", 0)))
            score = self._cosine_similarity(candidate_embedding, vector)
            scored.append((fact, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_n]

    def _run_confidence_decay(self, session, trainer_id: str, student_id: str, cfg: Dict[str, Any]) -> None:
        try:
            cutoff = datetime.utcnow() - timedelta(days=cfg["decay_days"])
            facts = session.query(PedagogicalFact).filter_by(
                trainer_id=trainer_id,
                student_id=student_id,
                is_active=1,
            ).all()
            for fact in facts:
                pivot_date = fact.last_reinforced_at or fact.updated_at or fact.created_at
                if pivot_date and pivot_date < cutoff:
                    fact.confidence = float(fact.confidence) * cfg["decay_factor"]
                    if fact.confidence < cfg["decay_min_confidence"]:
                        fact.is_active = 0
                    fact.updated_at = datetime.utcnow()
        except Exception as e:
            log("error", f"Failed confidence decay: {e}", exc_info=True)

    def _get_active_facts(self, trainer_id: str, student_id: str) -> List[Dict[str, Any]]:
        try:
            with self.db.get_session() as session:
                rows = (
                    session.query(PedagogicalFact)
                    .filter_by(trainer_id=trainer_id, student_id=student_id, is_active=1)
                    .order_by(desc(PedagogicalFact.updated_at))
                    .all()
                )
                return [
                    {
                        "id": fact.id,
                        "student_id": fact.student_id,
                        "trainer_id": fact.trainer_id,
                        "fact_type": fact.fact_type,
                        "content": fact.content,
                        "embedding": fact.embedding,
                        "embedding_dim": fact.embedding_dim,
                        "confidence": float(fact.confidence or 0.0),
                        "is_active": int(fact.is_active or 0),
                        "source_version": int(fact.source_version or 1),
                        "created_at": fact.created_at,
                        "updated_at": fact.updated_at,
                        "last_reinforced_at": fact.last_reinforced_at,
                        "fact_metadata": fact.fact_metadata or {},
                    }
                    for fact in rows
                ]
        except Exception as e:
            log("error", f"Failed to get active facts: {e}", exc_info=True)
            return []

    def get_memory_context(self, user_id: str, messages: List[Dict]) -> Optional[Tuple[str, str, str]]:
        if not self._is_active:
            return None

        try:
            user = self.user_manager.get_user(user_id)
            if not user or not user.get("parent_id"):
                return None

            trainer_id = user["parent_id"]
            cfg = self._get_plugin_config()
            active_facts = self._get_active_facts(trainer_id, user_id)
            if not active_facts:
                return None

            last_user_message = None
            for msg in reversed(messages or []):
                if msg.get("role") == "user" and msg.get("content"):
                    last_user_message = msg.get("content")
                    break

            if not last_user_message:
                return None

            query_vector = np.asarray(get_embedding(last_user_message), dtype=np.float32)
            scored = []
            for fact in active_facts:
                fact_vector = self._deserialize_embedding(fact["embedding"], fact["embedding_dim"])
                similarity = self._cosine_similarity(query_vector, fact_vector)
                score = similarity * float(fact["confidence"])
                scored.append((fact, score))

            scored.sort(key=lambda x: x[1], reverse=True)
            top_facts = scored[: max(1, cfg["top_k_context"])]
            if not top_facts:
                return None

            facts_text = "\n".join(
                [
                    f"- [{fact['fact_type']}] {fact['content']} (confidence={fact['confidence']:.2f})"
                    for fact, _ in top_facts
                ]
            )
            context_prompt = get_prompt("trainer.plugins.pedagogical_memory.context_injection")
            context = context_prompt.format(facts=facts_text)
            return (context, "system", "top")
        except Exception as e:
            log("error", f"Failed to inject pedagogical memory context: {e}", exc_info=True)
            return None

    def get_context(self, student_id: str) -> Dict[str, str]:
        student = self.user_manager.get_user(student_id)
        if not student or not student.get("parent_id"):
            return {}

        trainer_id = student["parent_id"]
        active_facts = self._get_active_facts(trainer_id, student_id)
        if active_facts:
            fact_summary = "\n".join([f"• {fact['fact_type']}: {fact['content']}" for fact in active_facts[:5]])
            if len(active_facts) > 5:
                fact_summary += f"\n... and {len(active_facts) - 5} more facts"
            return {"🧠 Pedagogical Facts": fact_summary}
        return {}

    def _action_trigger_analysis(self, context, **params) -> Dict:
        from shared.common import record_plugin_event

        result = _run_async(self.refresh_memory(context.trainer_id, context.student_id))

        event_data = {
            "success": True,
            "facts_created": result.get("created", 0),
            "facts_updated": result.get("updated", 0),
            "facts_reinforced": result.get("reinforced", 0),
            "facts_discarded": result.get("discarded", 0),
            "messages_analyzed": result.get("messages_analyzed", 0),
        }

        record_plugin_event("pedagogical_memory", "analysis_complete", event_data)
        record_plugin_event("memory", "analysis_complete", event_data)

        return {"success": True, "plugin": "pedagogical_memory", **result, **event_data}

    def export_history(self, trainer_id: str, student_id: Optional[str] = None) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        try:
            with self.db.get_session() as session:
                facts_query = session.query(PedagogicalFact).filter_by(trainer_id=trainer_id)
                logs_query = session.query(PedagogicalAnalysisLog).filter_by(trainer_id=trainer_id)

                if student_id:
                    facts_query = facts_query.filter_by(student_id=student_id)
                    logs_query = logs_query.filter_by(student_id=student_id)

                for fact in facts_query.order_by(PedagogicalFact.created_at.asc()).all():
                    events.append({
                        "timestamp": fact.created_at.isoformat() if fact.created_at else datetime.utcnow().isoformat(),
                        "type": "plugin.pedagogical_memory.fact",
                        "plugin_id": self.id,
                        "id": fact.id,
                        "student_id": fact.student_id,
                        "trainer_id": fact.trainer_id,
                        "fact_type": fact.fact_type,
                        "content": fact.content,
                        "embedding_dim": fact.embedding_dim,
                        "confidence": fact.confidence,
                        "is_active": fact.is_active,
                        "source_version": fact.source_version,
                        "created_at": fact.created_at.isoformat() if fact.created_at else None,
                        "updated_at": fact.updated_at.isoformat() if fact.updated_at else None,
                        "last_reinforced_at": fact.last_reinforced_at.isoformat() if fact.last_reinforced_at else None,
                        "fact_metadata": fact.fact_metadata or {},
                    })

                for analysis in logs_query.order_by(PedagogicalAnalysisLog.created_at.asc()).all():
                    events.append({
                        "timestamp": analysis.created_at.isoformat() if analysis.created_at else datetime.utcnow().isoformat(),
                        "type": "plugin.pedagogical_memory.analysis",
                        "plugin_id": self.id,
                        "id": analysis.id,
                        "student_id": analysis.student_id,
                        "trainer_id": analysis.trainer_id,
                        "version": analysis.version,
                        "messages_analyzed": analysis.messages_analyzed,
                        "facts_created": analysis.facts_created,
                        "facts_updated": analysis.facts_updated,
                        "facts_discarded": analysis.facts_discarded,
                        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
                    })
        except Exception as e:
            log("error", f"Failed to export pedagogical_memory history: {e}", exc_info=True)
        return events
