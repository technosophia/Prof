"""
Training logic and business rules.
"""
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

from sqlalchemy.orm import Session
from sqlalchemy import desc

from shared.common import get_db_manager
from shared.common import log
from shared.common import get_section
from shared.common import get_user_manager, UserRole
from shared.common import get_conversation_manager, Message
from shared.common import llm_generate, get_current_llm_id
from shared.common import get_prompt

from modules.training.training_models import (
    TrainingMasterConfigTable,
    StudentStateHistoryTable,
    AnalyzedMessageTable
)


@dataclass
class StudentStatus:
    """Data class for student status display."""
    student_id: str
    student_name: str
    current_state: str
    last_analyzed: Optional[datetime]
    unanalyzed_messages: int
    total_conversations: int
    last_activity: Optional[datetime]


@dataclass
class StateHistoryEntry:
    """Data class for state history display."""
    id: str
    previous_state: str
    new_state: str
    change_reason: str
    analyzed_message_count: int
    created_at: datetime
    llm_id: Optional[str]  # NEW: Added llm_id field
    metadata: Dict[str, Any]


class TrainingManager:
    """Manages training operations."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized'):
            self.db = get_db_manager()
            self.user_manager = get_user_manager()
            self.conversation_manager = get_conversation_manager()
            self.config = get_section("training")
            self._initialized = True
            self._ensure_tables_exist()

    def _ensure_tables_exist(self):
        """Ensure training tables exist."""
        if not self.db.is_initialized():
            log("warning", "Database not initialized")
            return False

        try:
            # Tables are automatically created via Base metadata
            # when init_database() is called
            return True
        except Exception as e:
            log("error", f"Failed to ensure training tables exist: {e}")
            return False

    def is_master_user(self, user_id: str) -> bool:
        """Check if user is a master."""
        user = self.user_manager.get_user(user_id)
        return user and user.get("role") == UserRole.MASTER.value

    def is_student_of_master(self, master_id: str, student_id: str) -> bool:
        """Check if student belongs to master."""
        student = self.user_manager.get_user(student_id)
        return student and student.get("parent_id") == master_id

    def get_master_config(self, master_id: str) -> Optional[Dict[str, Any]]:
        """Get master training configuration."""
        if not self.is_master_user(master_id):
            return None

        with self.db.get_session() as session:
            config = session.query(TrainingMasterConfigTable).filter_by(
                master_id=master_id, is_active=True
            ).first()

            if config:
                return {
                    "id": config.id,
                    "master_id": config.master_id,
                    "system_prompt": config.system_prompt or get_prompt("training.system_prompt_default", ""),                    "learning_path": config.learning_path,
                    "analyzer_prompt": config.analyzer_prompt,
                    "merging_prompt": config.merging_prompt,
                    "created_at": config.created_at,
                    "updated_at": config.updated_at,
                    "metadata": config.config_metadata or {}
                }
            return None

    def save_master_config(
        self,
        master_id: str,
        system_prompt: str,
        learning_path: str,
        analyzer_prompt: str,
        merging_prompt: str
    ) -> str:
        """Save or update master training configuration."""
        if not self.is_master_user(master_id):
            raise ValueError("Only master users can save training configuration")

        with self.db.get_session() as session:
            # Check for existing config
            existing = session.query(TrainingMasterConfigTable).filter_by(
                master_id=master_id, is_active=True
            ).first()

            config_id = str(uuid.uuid4())

            if existing:
                # Update existing
                existing.system_prompt = system_prompt
                existing.learning_path = learning_path
                existing.analyzer_prompt = analyzer_prompt
                existing.merging_prompt = merging_prompt
                existing.updated_at = datetime.utcnow()
                config_id = existing.id
            else:
                # Create new
                config = TrainingMasterConfigTable(
                    id=config_id,
                    master_id=master_id,
                    system_prompt=system_prompt,
                    learning_path=learning_path,
                    analyzer_prompt=analyzer_prompt,
                    merging_prompt=merging_prompt,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                    is_active=True,
                    config_metadata={"created_via": "ui"}
                )
                session.add(config)

            log("info", f"Saved training config for master {master_id}")
            return config_id

    def get_student_state(self, master_id: str, student_id: str) -> Optional[Dict[str, Any]]:
        """Get student's current learning state from the most recent history entry."""
        if not self.is_student_of_master(master_id, student_id):
            return None

        with self.db.get_session() as session:
            # Get the most recent history entry for this student
            latest_history = session.query(StudentStateHistoryTable).filter_by(
                master_id=master_id,
                student_id=student_id
            ).order_by(desc(StudentStateHistoryTable.created_at)).first()

            if latest_history:
                return {
                    "id": latest_history.id,
                    "master_id": latest_history.master_id,
                    "student_id": latest_history.student_id,
                    "current_state": latest_history.new_state,
                    "last_analyzed_at": latest_history.created_at if latest_history.analyzed_message_count > 0 else None,
                    "created_at": latest_history.created_at,
                    "updated_at": latest_history.created_at,
                    "llm_id": latest_history.llm_id,
                    "metadata": latest_history.history_metadata or {}
                }
            return None

    def initialize_student_state(self, master_id: str, student_id: str) -> str:
        """Initialize a new student state record."""
        if not self.is_student_of_master(master_id, student_id):
            raise ValueError(f"Student {student_id} does not belong to master {master_id}")

        state_id = str(uuid.uuid4())
        current_llm_id = get_current_llm_id()  # Get current LLM ID

        with self.db.get_session() as session:
            # Create initial history entry
            history_entry = StudentStateHistoryTable(
                id=state_id,
                master_id=master_id,
                student_id=student_id,
                previous_state=None,
                new_state="New student. Learning progress will be tracked here.",
                change_reason="Initial state",
                analyzed_message_count=0,
                analyzed_message_ids=[],
                created_at=datetime.utcnow(),
                llm_id=current_llm_id,
                history_metadata={
                    "initialized_at": datetime.utcnow().isoformat(),
                    "update_type": "initialization"
                }
            )
            session.add(history_entry)

        log("info", f"Initialized student state for {student_id} under master {master_id} with LLM: {current_llm_id}")
        return state_id

    def update_student_state(self, master_id: str, student_id: str, new_state: str,
                           change_reason: str = "Manual update") -> bool:
        """Update student's learning state manually and record history."""
        log("info", f"Updating student state for {student_id} and master {master_id}")

        if not self.is_student_of_master(master_id, student_id):
            log("error", f"Student {student_id} is not a student of master {master_id}")
            return False

        try:
            current_llm_id = get_current_llm_id()

            with self.db.get_session() as session:
                # Get current state (most recent history entry)
                latest_history = session.query(StudentStateHistoryTable).filter_by(
                    master_id=master_id,
                    student_id=student_id
                ).order_by(desc(StudentStateHistoryTable.created_at)).first()

                previous_state = latest_history.new_state if latest_history else ""

                # Record history entry
                history_id = str(uuid.uuid4())
                history_entry = StudentStateHistoryTable(
                    id=history_id,
                    master_id=master_id,
                    student_id=student_id,
                    previous_state=previous_state,
                    new_state=new_state,
                    change_reason=change_reason,
                    analyzed_message_count=0,
                    analyzed_message_ids=[],
                    created_at=datetime.utcnow(),
                    llm_id=current_llm_id,
                    history_metadata={"update_type": "manual"}
                )
                session.add(history_entry)

                session.commit()
                log("info", f"Updated student state for {student_id} with LLM: {current_llm_id}")
                return True

        except Exception as e:
            log("error", f"Failed to update student state: {e}", exc_info=True)
            return False

    def clear_student_state(self, master_id: str, student_id: str) -> bool:
        """Clear student state and reset analyzed messages."""
        if not self.is_student_of_master(master_id, student_id):
            return False

        current_llm_id = get_current_llm_id()

        with self.db.get_session() as session:
            # Get current state before clearing
            latest_history = session.query(StudentStateHistoryTable).filter_by(
                master_id=master_id,
                student_id=student_id
            ).order_by(desc(StudentStateHistoryTable.created_at)).first()

            previous_state = latest_history.new_state if latest_history else ""

            # Record history entry for reset
            history_id = str(uuid.uuid4())
            history_entry = StudentStateHistoryTable(
                id=history_id,
                master_id=master_id,
                student_id=student_id,
                previous_state=previous_state,
                new_state="Learning progress has been reset.",
                change_reason="State reset by master",
                analyzed_message_count=0,
                analyzed_message_ids=[],
                created_at=datetime.utcnow(),
                llm_id=current_llm_id,
                history_metadata={"reset_type": "full"}
            )
            session.add(history_entry)

            # Clear analyzed messages for this student
            session.query(AnalyzedMessageTable).filter_by(
                student_id=student_id
            ).delete()

        log("info", f"Cleared student state for {student_id} with LLM: {current_llm_id}")
        return True

    def get_unanalyzed_messages(self, student_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get unanalyzed messages for a student."""
        with self.db.get_session() as session:
            # Get all analyzed message IDs
            analyzed_ids = [
                msg.message_id for msg in
                session.query(AnalyzedMessageTable.message_id).filter_by(
                    student_id=student_id
                ).all()
            ]

            # Get conversations for this student
            conversations = self.conversation_manager.get_user_conversations(
                student_id, include_inactive=False
            )

            unanalyzed_messages = []
            for conv in conversations:
                # Get conversation with messages
                full_conv = self.conversation_manager.get_conversation(conv["id"])
                if full_conv and full_conv.messages:
                    for msg in full_conv.messages:
                        # Create message key
                        message_key = f"{conv['id']}_{msg.timestamp.timestamp() if hasattr(msg.timestamp, 'timestamp') else msg.timestamp}"

                        # Check if this message has been analyzed
                        if message_key not in analyzed_ids and msg.role == "user":
                            unanalyzed_messages.append({
                                "conversation_id": conv["id"],
                                "message": msg.content,
                                "timestamp": msg.timestamp,
                                "role": msg.role,
                                "message_key": message_key
                            })

                            if len(unanalyzed_messages) >= limit:
                                break

                if len(unanalyzed_messages) >= limit:
                    break

            return unanalyzed_messages

    async def analyze_student_messages(
        self,
        master_id: str,
        student_id: str,
        analyzer_prompt: Optional[str] = None
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Analyze unanalyzed messages and update student state.
        Returns (new_state, analyzed_messages)
        """
        if not self.is_student_of_master(master_id, student_id):
            raise ValueError(f"Student {student_id} does not belong to master {master_id}")

        # Get master config
        config = self.get_master_config(master_id)
        if not config:
            raise ValueError(f"No training configuration found for master {master_id}")

        # Get current student state
        current_state_data = self.get_student_state(master_id, student_id)
        current_state = current_state_data["current_state"] if current_state_data else ""

        # Get unanalyzed messages
        unanalyzed = self.get_unanalyzed_messages(student_id)
        if not unanalyzed:
            return current_state, []

        # Prepare messages for analysis
        messages_text = "\n\n".join([
            f"[{msg['timestamp'].strftime('%Y-%m-%d %H:%M')}] Student: {msg['message']}"
            for msg in unanalyzed
        ])

        # Use provided analyzer prompt, then from config, then default prompt
        if analyzer_prompt:
            analyzer_prompt_to_use = analyzer_prompt
        elif config.get("analyzer_prompt"):
            analyzer_prompt_to_use = config["analyzer_prompt"]
        else:
            # Fallback to default prompt from prompts.yaml
            analyzer_prompt_to_use = get_prompt("training.training.analyzer_prompt_default",
                                                "ERROR")

        # Create analysis prompt using template from prompts.yaml
        analysis_prompt_template = get_prompt(
            "training.training.analysis_prompt_template", "ERROR"
        )

        analysis_prompt = analysis_prompt_template.format(
            current_state=current_state,
            messages_text=messages_text,
            analyzer_instructions=analyzer_prompt_to_use
        )

        # Call LLM for analysis
        analysis_result = await llm_generate(analysis_prompt)

        # Use merging prompt from config or default
        merging_prompt_to_use = config.get("merging_prompt") or get_prompt(
            "training.training.merging_prompt_default",
            "ERROR"
        )

        # Create merging prompt using template from prompts.yaml
        merging_prompt_template = get_prompt(
            "training.training.merging_prompt_template",
            "ERROR"
        )

        merging_prompt = merging_prompt_template.format(
            current_state=current_state,
            analysis_result=analysis_result,
            merging_instructions=merging_prompt_to_use
        )

        # Call LLM for merged state
        new_state = await llm_generate(merging_prompt)

        # Limit state length
        max_length = self.config.get("max_state_length", 2000)
        if len(new_state) > max_length:
            new_state = new_state[:max_length] + "..."

        # Get current LLM ID for tracking
        current_llm_id = get_current_llm_id()

        # Save new state and record history
        with self.db.get_session() as session:
            # Get current state for history
            latest_history = session.query(StudentStateHistoryTable).filter_by(
                master_id=master_id,
                student_id=student_id
            ).order_by(desc(StudentStateHistoryTable.created_at)).first()

            previous_state = latest_history.new_state if latest_history else ""

            # Create history entry
            history_id = str(uuid.uuid4())
            analyzed_message_ids = [msg["message_key"] for msg in unanalyzed]

            history_entry = StudentStateHistoryTable(
                id=history_id,
                master_id=master_id,
                student_id=student_id,
                previous_state=previous_state,
                new_state=new_state,
                change_reason=f"Analyzed {len(unanalyzed)} messages",
                analyzed_message_count=len(unanalyzed),
                created_at=datetime.utcnow(),
                llm_id=current_llm_id,
                history_metadata={
                    "analysis_result": analysis_result[:500] if analysis_result else "",
                    "unanalyzed_count_before": len(unanalyzed),
                    "update_type": "auto_analysis",
                    "analyzed_message_ids": analyzed_message_ids  # Store in metadata
                }
            )
            session.add(history_entry)

            # Mark messages as analyzed, linking to history entry
            for msg in unanalyzed:
                analyzed_msg = AnalyzedMessageTable(
                    id=str(uuid.uuid4()),
                    student_id=student_id,
                    message_id=msg["message_key"],
                    conversation_id=msg["conversation_id"],
                    analyzed_at=datetime.utcnow(),
                    analysis_summary=analysis_result[:500] if analysis_result else "",
                    state_history_id=history_id,
                    message_metadata={
                        "original_message": msg["message"][:200],
                        "timestamp": msg["timestamp"].isoformat()
                    }
                )
                session.add(analyzed_msg)

        log("info", f"Analyzed {len(unanalyzed)} messages for student {student_id} with LLM: {current_llm_id}")
        return new_state, unanalyzed

    def get_student_state_history(self, master_id: str, student_id: str,
                                limit: int = 50) -> List[StateHistoryEntry]:
        """Get state history for a student."""
        if not self.is_student_of_master(master_id, student_id):
            return []

        with self.db.get_session() as session:
            history_entries = session.query(StudentStateHistoryTable).filter_by(
                master_id=master_id,
                student_id=student_id
            ).order_by(desc(StudentStateHistoryTable.created_at)).limit(limit).all()

            return [
                StateHistoryEntry(
                    id=entry.id,
                    previous_state=entry.previous_state or "",
                    new_state=entry.new_state,
                    change_reason=entry.change_reason or "",
                    analyzed_message_count=entry.analyzed_message_count,
                    created_at=entry.created_at,
                    llm_id=entry.llm_id,
                    metadata=entry.history_metadata or {}
                )
                for entry in history_entries
            ]

    def clear_student_state_history(self, master_id: str, student_id: str) -> bool:
        """Clear all state history for a student."""
        if not self.is_student_of_master(master_id, student_id):
            return False

        try:
            with self.db.get_session() as session:
                # Delete all history entries for this student
                session.query(StudentStateHistoryTable).filter_by(
                    master_id=master_id,
                    student_id=student_id
                ).delete()

                # Clear state_history_id references in analyzed messages
                session.query(AnalyzedMessageTable).filter_by(
                    student_id=student_id
                ).update({"state_history_id": None})

                session.commit()
                log("info", f"Cleared state history for student {student_id}")
                return True
        except Exception as e:
            log("error", f"Failed to clear state history: {e}")
            return False

    def revert_to_previous_state(self, master_id: str, student_id: str,
                               history_id: str) -> Tuple[bool, Optional[str]]:
        """
        Revert to a previous state from history.
        This will:
        1. Restore the previous state
        2. Unmark the messages associated with that history entry
        3. Create a new history entry for the reversion
        """
        if not self.is_student_of_master(master_id, student_id):
            return False, None

        try:
            current_llm_id = get_current_llm_id()

            with self.db.get_session() as session:
                # Get the history entry to revert to
                history_entry = session.query(StudentStateHistoryTable).filter_by(
                    id=history_id,
                    master_id=master_id,
                    student_id=student_id
                ).first()

                if not history_entry:
                    log("error", f"History entry {history_id} not found")
                    return False, None

                # Get current state (most recent history entry)
                current_history = session.query(StudentStateHistoryTable).filter_by(
                    master_id=master_id,
                    student_id=student_id
                ).order_by(desc(StudentStateHistoryTable.created_at)).first()

                if not current_history:
                    log("error", f"No current state found for student {student_id}")
                    return False, None

                # Store the state we're reverting from
                reverting_from_state = current_history.new_state

                # Create a new history entry for the reversion
                revert_history_id = str(uuid.uuid4())
                revert_entry = StudentStateHistoryTable(
                    id=revert_history_id,
                    master_id=master_id,
                    student_id=student_id,
                    previous_state=reverting_from_state,
                    new_state=history_entry.previous_state or "",
                    change_reason=f"Reverted to state from {history_entry.created_at.strftime('%Y-%m-%d %H:%M')}",
                    analyzed_message_count=0,
                    analyzed_message_ids=[],
                    created_at=datetime.utcnow(),
                    llm_id=current_llm_id,
                    history_metadata={
                        "reverted_from_history_id": history_id,
                        "reverted_message_count": len(history_entry.analyzed_message_ids or []),
                        "original_llm_id": history_entry.llm_id,
                        "update_type": "revert"
                    }
                )
                session.add(revert_entry)

                # Unmark messages associated with the reverted history entry
                if history_entry.analyzed_message_ids:
                    # Delete analyzed messages linked to this history entry
                    session.query(AnalyzedMessageTable).filter(
                        AnalyzedMessageTable.student_id == student_id,
                        AnalyzedMessageTable.state_history_id == history_id
                    ).delete()

                session.commit()

                log("info", f"Reverted student {student_id} to previous state from {history_entry.created_at} with LLM: {current_llm_id}")
                return True, history_entry.previous_state or ""

        except Exception as e:
            log("error", f"Failed to revert to previous state: {e}", exc_info=True)
            return False, None

    def get_student_status_board(self, master_id: str) -> List[StudentStatus]:
        """Get status board for all students of a master."""
        if not self.is_master_user(master_id):
            return []

        # Get all children (students) of this master
        students = self.user_manager.get_children(master_id)
        if not students:
            return []

        status_list = []

        for student in students:
            student_id = student["id"]

            # Get student state from most recent history
            state_data = self.get_student_state(master_id, student_id)

            # Get unanalyzed message count
            unanalyzed = self.get_unanalyzed_messages(student_id)

            # Get student's conversations
            conversations = self.conversation_manager.get_user_conversations(student_id)

            # Find last activity
            last_activity = None
            if conversations:
                last_conv = max(conversations, key=lambda x: x.get("updated_at", ""))
                last_activity = last_conv.get("updated_at")
                if last_activity:
                    last_activity = datetime.fromisoformat(last_activity.replace('Z', '+00:00'))

            status = StudentStatus(
                student_id=student_id,
                student_name=student["name"],
                current_state=state_data["current_state"] if state_data else "No state initialized",
                last_analyzed=state_data["last_analyzed_at"] if state_data else None,
                unanalyzed_messages=len(unanalyzed),
                total_conversations=len(conversations),
                last_activity=last_activity
            )
            status_list.append(status)

        return status_list

    def get_student_state_for_injection(self, student_id: str) -> str:
        """Get student state for injection into LLM context."""
        # Find the master for this student
        student = self.user_manager.get_user(student_id)
        if not student or not student.get("parent_id"):
            return f"ERROR : user or master not found for student {student_id}"

        master_id = student["parent_id"]
        state_data = self.get_student_state(master_id, student_id)

        if state_data and state_data["current_state"]:
            llm_info = f" (analyzed by LLM: {state_data['llm_id']})" if state_data.get('llm_id') else ""
            return f"\n[Student Learning Context]\nCurrent learning progress{llm_info}: {state_data['current_state']}\n"
        return f"ERROR : no user state found for student {student_id}"

    def cleanup_student_data(self, student_id: str) -> bool:
        """Clean up all training data for a student when they are deleted."""
        try:
            with self.db.get_session() as session:
                # Delete state history
                session.query(StudentStateHistoryTable).filter_by(student_id=student_id).delete()

                # Delete analyzed messages
                session.query(AnalyzedMessageTable).filter_by(student_id=student_id).delete()

                log("info", f"Cleaned up training data for student {student_id}")
                return True
        except Exception as e:
            log("error", f"Failed to cleanup training data: {e}")
            return False

    def cleanup_master_data(self, master_id: str) -> bool:
        """Clean up all training data for a master when they are deleted."""
        try:
            with self.db.get_session() as session:
                # Delete master config
                session.query(TrainingMasterConfigTable).filter_by(master_id=master_id).delete()

                # Delete state history for this master
                session.query(StudentStateHistoryTable).filter_by(master_id=master_id).delete()

                log("info", f"Cleaned up training data for master {master_id}")
                return True
        except Exception as e:
            log("error", f"Failed to cleanup master training data: {e}")
            return False


def get_training_manager():
    return TrainingManager()
