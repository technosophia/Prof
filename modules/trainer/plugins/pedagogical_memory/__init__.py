"""
Pedagogical Memory Plugin for Trainer Module.
Maintains structured atomic pedagogical facts with semantic retrieval.
"""

from typing import List, Dict, Any, Optional, Callable, Tuple
import streamlit as st
from datetime import datetime, timedelta
import uuid
import json
import asyncio

import numpy as np
from sqlalchemy import Column, String, Text, DateTime, JSON, Integer, Float, LargeBinary, desc

from shared.common import get_prompt, register_llm_context_callback, get_current_llm_id, get_embedding
from st_shared.cached import get_db_manager, get_conversation_manager, get_llm_manager, get_user_manager, get_config
from modules.trainer.plugin_base import TrainerPlugin
from modules.trainer.manager import get_trainer_manager


from core.logging import log, set_log_module_level
from core.database import Base
EMBEDDING_DIMENSION = 384


class PedagogicalFact(Base):
    """Store atomic pedagogical facts for each student and trainer."""

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
    """Track pedagogical memory analysis runs."""

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
    """
    Run an async coroutine safely regardless of whether there is already
    a running event loop (Streamlit) or not (plain scripts / tests).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # We're inside Streamlit (or another async host).
        # Schedule on the existing loop and block until done.
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    else:
        return asyncio.run(coro)

class PedagogicalMemoryPlugin(TrainerPlugin):
    """Plugin that maintains structured pedagogical fact memory."""

    def initialize(self) -> bool:
        """Initialize the plugin, tables, and context callback."""
        try:
            db = get_db_manager()
            if db.is_initialized() and not db._in_memory:
                Base.metadata.create_all(
                    db._engine,
                    tables=[PedagogicalFact.__table__, PedagogicalAnalysisLog.__table__],
                    checkfirst=True,
                )
                log("info", "Pedagogical memory tables created/verified")

            register_llm_context_callback(self.get_memory_context)
            return True
        except Exception as e:
            log("error", f"Failed to initialize pedagogical_memory plugin: {e}", exc_info=True)
            return False

    def _get_plugin_config(self) -> Dict[str, Any]:
        """Get plugin runtime configuration."""
        root_config = get_config().get("modules.trainer.plugins.pedagogical_memory", {}) or {}
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
        """Serialize embedding vector to bytes."""
        return np.asarray(embedding, dtype=np.float32).tobytes()

    def _deserialize_embedding(self, embedding_bytes: bytes, dim: int) -> np.ndarray:
        """Deserialize embedding bytes to numpy vector."""
        vector = np.frombuffer(embedding_bytes, dtype=np.float32)
        if dim and vector.shape[0] != dim:
            log("warning", f"Embedding dimension mismatch: expected {dim}, got {vector.shape[0]}")
        return vector

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity between 2 vectors."""
        if a.size == 0 or b.size == 0:
            return 0.0

        norm_a = float(np.linalg.norm(a))
        norm_b = float(np.linalg.norm(b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0

        return float(np.dot(a, b) / (norm_a * norm_b))

    def _get_last_analysis_date(self, trainer_id: str, student_id: str) -> Optional[datetime]:
        """Get last analysis timestamp for student."""
        try:
            with get_db_manager().get_session() as session:
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
        """Get next analysis version number for student."""
        try:
            with get_db_manager().get_session() as session:
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
        """Get new student conversation messages since timestamp."""
        new_messages = []
        try:
            conv_manager = get_conversation_manager()
            conversations = conv_manager.get_user_conversations(student_id)

            for conv in conversations:
                full_conv = conv_manager.get_conversation(conv["id"])
                if not full_conv or not full_conv.messages:
                    continue

                for msg in full_conv.messages:
                    if msg.role not in ["user", "assistant"]:
                        continue

                    msg_time = msg.timestamp
                    if msg_time and (not since or msg_time > since):
                        new_messages.append(
                            {
                                "role": msg.role,
                                "content": msg.content,
                                "timestamp": msg_time.isoformat() if msg_time else None,
                                "conversation_id": conv["id"],
                                "conversation_title": conv.get("title", "Untitled"),
                            }
                        )

            new_messages.sort(key=lambda x: x.get("timestamp", ""))
        except Exception as e:
            log("error", f"Failed to read conversations: {e}", exc_info=True)

        return new_messages

    def _format_fact_types(self, fact_types: Dict[str, str]) -> str:
        """Format fact taxonomy for prompts."""
        lines = []
        for key, description in fact_types.items():
            lines.append(f"- {key}: {description}")
        return "\n".join(lines)

    async def _extract_candidate_facts(
        self, trainer_id: str, student_id: str, new_messages: List[Dict[str, Any]], fact_types: Dict[str, str]
    ) -> List[Dict[str, str]]:
        """Call extraction LLM prompt and parse JSON array of candidate facts."""
        try:
            training_program = get_prompt("trainer.teacher.training_program")
            conversations_text = ""
            for msg in new_messages:
                role_symbol = "👤 Student" if msg["role"] == "user" else "🤖 Assistant"
                conversations_text += f"{role_symbol} ({msg['timestamp']}): {msg['content']}\n\n"

            system_prompt = get_prompt("trainer.plugins.pedagogical_memory.extraction_system").format(
                training_program=training_program,
                fact_types=self._format_fact_types(fact_types),
            )
            user_prompt = get_prompt("trainer.plugins.pedagogical_memory.extraction_user").format(
                conversations=conversations_text
            )

            llm_id = get_current_llm_id()
            response = await get_llm_manager().internal_response(
                llm_id,
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )

            if not response or response.startswith("Error"):
                log("error", f"Extraction call failed: {response}")
                return []

            try:
                payload = json.loads(response)
            except Exception as e:
                log("error", f"Failed to parse extraction JSON output: {e}\n {response}", exc_info=True)
                log("info", f"{system_prompt}\n{user_prompt}")
                return []

            if not isinstance(payload, list):
                return []

            allowed_types = set(fact_types.keys())
            filtered = []
            for item in payload:
                if not isinstance(item, dict):
                    continue
                fact_type = str(item.get("fact_type", "")).strip()
                content = str(item.get("content", "")).strip()
                if fact_type in allowed_types and content:
                    filtered.append({"fact_type": fact_type, "content": content})
            return filtered
        except Exception as e:
            log("error", f"Failed to extract candidate facts: {e}", exc_info=True)
            return []

    def _find_similar_facts(
        self,
        session,
        trainer_id: str,
        student_id: str,
        candidate_type: str,
        candidate_embedding: np.ndarray,
        top_n: int = 3,
    ) -> List[Tuple[PedagogicalFact, float]]:
        """Find top-N similar active facts for candidate."""
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

    async def _decide_reconciliation(self, fact_type: str, existing_content: str, candidate_content: str) -> str:
        """Use LLM to decide UPDATE, REINFORCE, or DISCARD."""
        try:
            llm_id = get_current_llm_id()
            system_prompt = get_prompt("trainer.plugins.pedagogical_memory.reconciliation_system")
            user_prompt = get_prompt("trainer.plugins.pedagogical_memory.reconciliation_user").format(
                fact_type=fact_type,
                existing_content=existing_content,
                candidate_content=candidate_content,
            )
            response = await get_llm_manager().internal_response(
                llm_id,
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            decision = (response or "").strip().upper()
            if decision in ["UPDATE", "REINFORCE", "DISCARD"]:
                return decision
            return "DISCARD"
        except Exception as e:
            log("error", f"Failed reconciliation decision: {e}", exc_info=True)
            return "DISCARD"

    def _find_similar_facts_in_memory(
        self,
        facts: List[Dict[str, Any]],
        candidate_type: str,
        candidate_embedding: np.ndarray,
        top_n: int = 3,
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Find top-N similar active facts from an in-memory snapshot."""
        scored: List[Tuple[Dict[str, Any], float]] = []
        for fact in facts:
            if fact.get("fact_type") != candidate_type or int(fact.get("is_active", 0)) != 1:
                continue

            vector = self._deserialize_embedding(fact.get("embedding", b""), int(fact.get("embedding_dim", 0)))
            score = self._cosine_similarity(candidate_embedding, vector)
            scored.append((fact, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_n]

    def _run_confidence_decay(self, session, trainer_id: str, student_id: str, cfg: Dict[str, Any]) -> None:
        """Apply confidence decay to stale facts and soft-delete weak facts."""
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

    async def refresh_memory(self, trainer_id: str, student_id: str) -> Dict[str, int]:
        """Run extraction, reconciliation, and decay for a student."""
        stats = {"created": 0, "updated": 0, "reinforced": 0, "discarded": 0, "messages_analyzed": 0}
        cfg = self._get_plugin_config()
        fact_types = cfg["fact_types"]

        if not fact_types:
            log("warning", "No fact taxonomy configured for pedagogical_memory")
            return stats

        last_analysis = self._get_last_analysis_date(trainer_id, student_id)
        messages = self._get_new_conversations(student_id, last_analysis)
        stats["messages_analyzed"] = len(messages)

        if not messages:
            return stats

        version = self._get_next_analysis_version(trainer_id, student_id)
        candidates = await self._extract_candidate_facts(trainer_id, student_id, messages, fact_types)

        try:
            with get_db_manager().get_session() as session:
                current_facts = (
                    session.query(PedagogicalFact)
                    .filter_by(trainer_id=trainer_id, student_id=student_id, is_active=1)
                    .all()
                )

            fact_snapshot: List[Dict[str, Any]] = [
                {
                    "id": fact.id,
                    "fact_type": fact.fact_type,
                    "content": fact.content,
                    "embedding": fact.embedding,
                    "embedding_dim": fact.embedding_dim,
                    "confidence": float(fact.confidence or 0.0),
                    "is_active": int(fact.is_active or 0),
                    "fact_metadata": fact.fact_metadata or {},
                }
                for fact in current_facts
            ]

            operations: List[Dict[str, Any]] = []
            pending_id = 0

            for candidate in candidates:
                candidate_vector = np.asarray(get_embedding(candidate["content"]), dtype=np.float32)
                similar = self._find_similar_facts_in_memory(
                    fact_snapshot,
                    candidate["fact_type"],
                    candidate_vector,
                    top_n=3,
                )

                if not similar or similar[0][1] < cfg["similarity_threshold"]:
                    operations.append(
                        {
                            "action": "CREATE",
                            "fact_type": candidate["fact_type"],
                            "content": candidate["content"],
                            "vector": candidate_vector,
                        }
                    )
                    stats["created"] += 1
                    pending_id -= 1
                    fact_snapshot.append(
                        {
                            "id": pending_id,
                            "fact_type": candidate["fact_type"],
                            "content": candidate["content"],
                            "embedding": self._serialize_embedding(candidate_vector.tolist()),
                            "embedding_dim": EMBEDDING_DIMENSION,
                            "confidence": 1.0,
                            "is_active": 1,
                            "fact_metadata": {"source": "llm", "reconciliation": "CREATE"},
                        }
                    )
                    continue

                best_fact, _ = similar[0]
                decision = await self._decide_reconciliation(
                    candidate["fact_type"],
                    best_fact["content"],
                    candidate["content"],
                )

                if decision == "UPDATE":
                    operations.append(
                        {
                            "action": "UPDATE",
                            "fact_id": best_fact["id"],
                            "content": candidate["content"],
                            "vector": candidate_vector,
                        }
                    )
                    best_fact["content"] = candidate["content"]
                    best_fact["embedding"] = self._serialize_embedding(candidate_vector.tolist())
                    best_fact["embedding_dim"] = EMBEDDING_DIMENSION
                    best_fact["fact_metadata"] = {
                        **(best_fact.get("fact_metadata") or {}),
                        "source": "llm",
                        "reconciliation": "UPDATE",
                    }
                    stats["updated"] += 1
                elif decision == "REINFORCE":
                    operations.append({"action": "REINFORCE", "fact_id": best_fact["id"]})
                    best_fact["confidence"] = min(1.0, float(best_fact.get("confidence", 0.0)) + 0.05)
                    best_fact["fact_metadata"] = {
                        **(best_fact.get("fact_metadata") or {}),
                        "source": "llm",
                        "reconciliation": "REINFORCE",
                    }
                    stats["reinforced"] += 1
                else:
                    stats["discarded"] += 1

            with get_db_manager().get_session() as session:
                for operation in operations:
                    if operation["action"] == "CREATE":
                        session.add(
                            PedagogicalFact(
                                student_id=student_id,
                                trainer_id=trainer_id,
                                fact_type=operation["fact_type"],
                                content=operation["content"],
                                embedding=self._serialize_embedding(operation["vector"].tolist()),
                                embedding_dim=EMBEDDING_DIMENSION,
                                confidence=1.0,
                                is_active=1,
                                source_version=version,
                                fact_metadata={"source": "llm", "reconciliation": "CREATE"},
                            )
                        )
                        continue

                    db_fact = session.query(PedagogicalFact).filter_by(id=operation["fact_id"]).first()
                    if not db_fact:
                        continue

                    if operation["action"] == "UPDATE":
                        db_fact.content = operation["content"]
                        db_fact.embedding = self._serialize_embedding(operation["vector"].tolist())
                        db_fact.embedding_dim = EMBEDDING_DIMENSION
                        db_fact.updated_at = datetime.utcnow()
                        db_fact.source_version = version
                        db_fact.fact_metadata = {
                            **(db_fact.fact_metadata or {}),
                            "source": "llm",
                            "reconciliation": "UPDATE",
                        }
                    elif operation["action"] == "REINFORCE":
                        db_fact.last_reinforced_at = datetime.utcnow()
                        db_fact.confidence = min(1.0, float(db_fact.confidence) + 0.05)
                        db_fact.updated_at = datetime.utcnow()
                        db_fact.fact_metadata = {
                            **(db_fact.fact_metadata or {}),
                            "source": "llm",
                            "reconciliation": "REINFORCE",
                        }

                self._run_confidence_decay(session, trainer_id, student_id, cfg)

                session.add(
                    PedagogicalAnalysisLog(
                        student_id=student_id,
                        trainer_id=trainer_id,
                        version=version,
                        messages_analyzed=stats["messages_analyzed"],
                        facts_created=stats["created"],
                        facts_updated=stats["updated"],
                        facts_discarded=stats["discarded"],
                    )
                )
                session.commit()
                return stats
        except Exception as e:
            log("error", f"Failed to refresh pedagogical memory: {e}", exc_info=True)
            return stats

    def _get_active_facts(self, trainer_id: str, student_id: str) -> List[Dict[str, Any]]:
        """Get active facts for student as detached-safe dictionaries."""
        try:
            with get_db_manager().get_session() as session:
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
        """Inject top relevant pedagogical facts as LLM context."""
        try:
            user = get_user_manager().get_user(user_id)
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

    def _action_trigger_analysis(self, context, **params) -> Dict:
        import asyncio
        from shared.common import record_plugin_event

        result = _run_async(
            self.refresh_memory(context.trainer_id, context.student_id)
        )

        event_data = {
            "success": True,
            "facts_created": result.get("created", 0),
            "facts_updated": result.get("updated", 0),
            "facts_reinforced": result.get("reinforced", 0),
            "facts_discarded": result.get("discarded", 0),
            "messages_analyzed": result.get("messages_analyzed", 0),
        }

        # Emit canonical plugin id and legacy alias for backward-compatible
        # benchmark scenarios/assertions still matching plugin_id="memory".
        record_plugin_event("pedagogical_memory", "analysis_complete", event_data)
        record_plugin_event("memory", "analysis_complete", event_data)

        return {
            "success": True,
            "plugin": "pedagogical_memory",
            **result,
            **event_data,
        }

    def render_student_widgets(self, trainer_id: str, student: Dict) -> List[Callable]:
        """Render student-level pedagogical memory widget."""

        def render_student_memory():
            student_id = student["id"]
            cfg = self._get_plugin_config()
            fact_types = cfg["fact_types"]
            type_colors = cfg["fact_type_colors"]

            st.markdown("### 🧠 Pedagogical Memory")

            active_facts = self._get_active_facts(trainer_id, student_id)
            last_analysis = self._get_last_analysis_date(trainer_id, student_id)
            with get_db_manager().get_session() as session:
                version_count = (
                    session.query(PedagogicalAnalysisLog)
                    .filter_by(trainer_id=trainer_id, student_id=student_id)
                    .count()
                )

            st.markdown("#### Stats")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Active facts", len(active_facts))
            with col2:
                st.caption(f"Last analysis: {last_analysis.strftime('%Y-%m-%d %H:%M') if last_analysis else 'Never'}")
            with col3:
                st.caption(f"Analysis versions: {version_count}")

            pills = []
            for fact_type in fact_types.keys():
                count = sum(1 for f in active_facts if f["fact_type"] == fact_type)
                if count > 0:
                    pills.append(f"`{fact_type}: {count}`")
            if pills:
                st.markdown(" ".join(pills))

            st.markdown("#### Facts")
            if not active_facts:
                st.info("No active pedagogical facts.")

            for fact in active_facts:
                color = type_colors.get(fact["fact_type"], "#6C757D")
                st.markdown(f"<span style='color:{color};font-weight:700;'>● {fact['fact_type']}</span>", unsafe_allow_html=True)
                edit_key = f"{self.id}_content_{fact['id']}"
                if edit_key not in st.session_state:
                    st.session_state[edit_key] = fact["content"]

                st.text_input("Content", key=edit_key)
                st.progress(max(0.0, min(1.0, float(fact["confidence"]))))
                st.caption(
                    f"Last reinforced: {fact['last_reinforced_at'].strftime('%Y-%m-%d %H:%M') if fact['last_reinforced_at'] else 'Never'}"
                )
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Save", key=f"save_fact_{fact['id']}"):
                        try:
                            new_content = st.session_state.get(edit_key, "").strip()
                            if new_content:
                                with get_db_manager().get_session() as session:
                                    db_fact = session.query(PedagogicalFact).filter_by(id=fact["id"]).first()
                                    if db_fact:
                                        db_fact.content = new_content
                                        db_fact.embedding = self._serialize_embedding(get_embedding(new_content))
                                        db_fact.embedding_dim = EMBEDDING_DIMENSION
                                        db_fact.updated_at = datetime.utcnow()
                                        db_fact.fact_metadata = {**(db_fact.fact_metadata or {}), "source": "manual_edit"}
                                        session.commit()
                                        st.success("Fact updated")
                                        st.rerun()
                        except Exception as e:
                            log("error", f"Failed to save fact edits: {e}", exc_info=True)
                            st.error("Failed to save fact")
                with c2:
                    if st.button("Delete", key=f"delete_fact_{fact['id']}"):
                        try:
                            with get_db_manager().get_session() as session:
                                db_fact = session.query(PedagogicalFact).filter_by(id=fact["id"]).first()
                                if db_fact:
                                    db_fact.is_active = 0
                                    db_fact.updated_at = datetime.utcnow()
                                    session.commit()
                                    st.success("Fact deleted")
                                    st.rerun()
                        except Exception as e:
                            log("error", f"Failed to delete fact: {e}", exc_info=True)
                            st.error("Failed to delete fact")
                st.divider()

            with st.expander("+ Add fact manually"):
                new_type = st.selectbox(
                    "Fact type",
                    options=list(fact_types.keys()),
                    key=f"manual_fact_type_{student_id}",
                )
                new_content = st.text_area("Content", key=f"manual_fact_content_{student_id}")
                if st.button("Save manual fact", key=f"save_manual_fact_{student_id}"):
                    try:
                        content = (new_content or "").strip()
                        if content:
                            with get_db_manager().get_session() as session:
                                session.add(
                                    PedagogicalFact(
                                        student_id=student_id,
                                        trainer_id=trainer_id,
                                        fact_type=new_type,
                                        content=content,
                                        embedding=self._serialize_embedding(get_embedding(content)),
                                        embedding_dim=EMBEDDING_DIMENSION,
                                        confidence=1.0,
                                        is_active=1,
                                        source_version=self._get_next_analysis_version(trainer_id, student_id),
                                        fact_metadata={"source": "manual"},
                                    )
                                )
                                session.commit()
                            st.success("Manual fact added")
                            st.rerun()
                    except Exception as e:
                        log("error", f"Failed to add manual fact: {e}", exc_info=True)
                        st.error("Failed to add manual fact")

            st.markdown("#### Analysis")
            if st.button("🔬 Run Analysis", key=f"run_pedagogical_analysis_{student_id}"):
                with st.spinner("Running pedagogical analysis..."):
                    result = _run_async(self.refresh_memory(trainer_id, student_id))
                st.success(
                    f"Created {result['created']} · Updated {result['updated']} · "
                    f"Reinforced {result['reinforced']} · Discarded {result['discarded']}"
                )
                st.rerun()

            with st.expander("Raw conversation preview"):
                preview = self._get_new_conversations(student_id, last_analysis)
                if not preview:
                    st.caption("No new messages to analyse.")
                for msg in preview:
                    st.caption(f"[{msg['timestamp']}] {msg['role']}: {msg['content']}")

        return [render_student_memory]

    def render_dashboard_widgets(self, trainer_id: str, students: List[Dict]) -> List[Callable]:
        """Render compact dashboard overview for all students."""

        def render_dashboard():
            st.markdown("### 🧠 Pedagogical Memory Overview")

            if st.button("Run all analyses", key=f"{self.id}_run_all"):
                progress = st.progress(0)
                status = st.empty()
                total = len(students)
                for idx, student in enumerate(students):
                    status.caption(f"Running analysis for {student.get('name', student['id'])}...")
                    try:
                        _run_async(self.refresh_memory(trainer_id, student["id"]))
                    except Exception as e:
                        log("error", f"Run-all analysis failed for {student['id']}: {e}", exc_info=True)
                    progress.progress((idx + 1) / max(1, total))
                status.caption("All analyses completed")
                st.rerun()

            for student in students:
                facts = self._get_active_facts(trainer_id, student["id"])
                last_analysis = self._get_last_analysis_date(trainer_id, student["id"])
                top_two = facts[:2]

                with st.container():
                    st.markdown(f"**{student.get('name', student['id'])}**")
                    st.caption(f"Active facts: {len(facts)}")
                    if top_two:
                        for fact in top_two:
                            st.caption(f"- [{fact['fact_type']}] {fact['content'][:120]}")
                    st.caption(
                        f"Last analysis: {last_analysis.strftime('%Y-%m-%d %H:%M') if last_analysis else 'Never'}"
                    )
                    st.divider()

        return [render_dashboard]

    def export_history(self, trainer_id: str, student_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Export facts and analysis logs as plugin events (without embedding bytes)."""
        events: List[Dict[str, Any]] = []

        try:
            with get_db_manager().get_session() as session:
                facts_query = session.query(PedagogicalFact).filter_by(trainer_id=trainer_id)
                logs_query = session.query(PedagogicalAnalysisLog).filter_by(trainer_id=trainer_id)

                if student_id:
                    facts_query = facts_query.filter_by(student_id=student_id)
                    logs_query = logs_query.filter_by(student_id=student_id)

                for fact in facts_query.order_by(PedagogicalFact.created_at.asc()).all():
                    events.append(
                        {
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
                            "last_reinforced_at": (
                                fact.last_reinforced_at.isoformat() if fact.last_reinforced_at else None
                            ),
                            "fact_metadata": fact.fact_metadata or {},
                        }
                    )

                for analysis in logs_query.order_by(PedagogicalAnalysisLog.created_at.asc()).all():
                    events.append(
                        {
                            "timestamp": analysis.created_at.isoformat()
                            if analysis.created_at
                            else datetime.utcnow().isoformat(),
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
                        }
                    )

        except Exception as e:
            log("error", f"Failed to export pedagogical_memory history: {e}", exc_info=True)

        return events

    def import_history(self, trainer_id: str, events: List[Dict[str, Any]], student_info: Dict = None) -> bool:
        """Import pedagogical memory events and recompute embeddings."""
        try:
            with get_db_manager().get_session() as session:
                memory_events = [e for e in events if e.get("plugin_id") == self.id]

                fact_events = [e for e in memory_events if e.get("type") == "plugin.pedagogical_memory.fact"]
                analysis_events = [e for e in memory_events if e.get("type") == "plugin.pedagogical_memory.analysis"]

                for event in fact_events:
                    content = event.get("content", "")
                    fact = PedagogicalFact(
                        id=event.get("id", str(uuid.uuid4())),
                        student_id=event.get("student_id"),
                        trainer_id=trainer_id,
                        fact_type=event.get("fact_type", "knowledge_state"),
                        content=content,
                        embedding=self._serialize_embedding(get_embedding(content)),
                        embedding_dim=int(event.get("embedding_dim", EMBEDDING_DIMENSION)),
                        confidence=float(event.get("confidence", 1.0)),
                        is_active=int(event.get("is_active", 1)),
                        source_version=int(event.get("source_version", 1)),
                        created_at=datetime.fromisoformat(event["created_at"])
                        if event.get("created_at")
                        else datetime.utcnow(),
                        updated_at=datetime.fromisoformat(event["updated_at"])
                        if event.get("updated_at")
                        else datetime.utcnow(),
                        last_reinforced_at=(
                            datetime.fromisoformat(event["last_reinforced_at"])
                            if event.get("last_reinforced_at")
                            else None
                        ),
                        fact_metadata=event.get("fact_metadata", {}),
                    )
                    session.merge(fact)

                for event in analysis_events:
                    analysis = PedagogicalAnalysisLog(
                        id=event.get("id", str(uuid.uuid4())),
                        student_id=event.get("student_id"),
                        trainer_id=trainer_id,
                        version=int(event.get("version", 1)),
                        messages_analyzed=int(event.get("messages_analyzed", 0)),
                        facts_created=int(event.get("facts_created", 0)),
                        facts_updated=int(event.get("facts_updated", 0)),
                        facts_discarded=int(event.get("facts_discarded", 0)),
                        created_at=datetime.fromisoformat(event["created_at"])
                        if event.get("created_at")
                        else datetime.utcnow(),
                    )
                    session.merge(analysis)

                session.commit()
            return True
        except Exception as e:
            log("error", f"Failed to import pedagogical_memory history: {e}", exc_info=True)
            return False


plugin = PedagogicalMemoryPlugin
