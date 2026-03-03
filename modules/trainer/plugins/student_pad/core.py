"""
Student Pad Plugin for Trainer Module.
Allows each student to have a personal note-taking pad with version history.
Visible in dashboard and exportable/importable.

Migration status: COMPLETE
  - initialize() calls self._resolve_services(services)
  - Added legacy fallback for when services=None
  - All data methods use self.db, self.user_manager, self.conversation_manager,
    self.llm_manager, self.config — no st_shared.cached imports elsewhere
  - All render methods call self.<data_method>() only — no db/cache access inline
  - When splitting into two classes: replace self.xxx() with self._logic.xxx()
    in every render method. No logic rewrite needed.
"""

from typing import List, Dict, Any, Optional, Callable, Tuple
from datetime import datetime
import uuid

from sqlalchemy import Column, String, Text, DateTime, JSON, Integer, and_

from core.logging import log
from core.database import Base
from shared.common import get_prompt, register_llm_context_callback
from modules.trainer.plugin_base import PluginManifest
from modules.trainer.plugin_base_core import TrainerPluginCore


class StudentNote(Base):
    """Store notes/pad for each student with version history."""
    __tablename__ = 'trainer_student_notes'
    __table_args__ = {'extend_existing': True}

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), nullable=False, index=True)  # Student ID
    trainer_id = Column(String(36), nullable=False, index=True)  # Trainer/Master ID
    content = Column(Text, default="")
    plugin_id = Column(String(36), default="core")  # Which plugin owns this note
    version = Column(Integer, default=1)  # Version number
    is_current = Column(Integer, default=1)  # 1 for current version, 0 for history
    updated_at = Column(DateTime, default=datetime.utcnow)
    note_metadata = Column(JSON, default={})



class StudentPadPluginCore(TrainerPluginCore):

    def initialize(self, services=None) -> bool:
        """Initialize the plugin, tables, and context callbacks."""
        try:
            self._resolve_services(services)

            # Ensure table exists - but don't try to create it in tests
            if self.db and self.db.is_initialized() and not self.db._in_memory:
                Base.metadata.create_all(
                    self.db._engine,
                    tables=[StudentNote.__table__],
                    checkfirst=True
                )
                log("info", "StudentNote table created/verified with version tracking")

            # Register context callbacks
            register_llm_context_callback(self.get_student_notes_context)
            register_llm_context_callback(self.get_teacher_notes_context)
            return True
        except Exception as e:
            log("error", f"Failed to initialize student_pad plugin: {e}", stacktrace=True)
            return False

    def on_activate(self, trainer_id: str) -> None:
        """Called when plugin is activated for a trainer."""
        log("info", f"Student pad plugin activated for trainer {trainer_id}")

    def on_deactivate(self, trainer_id: str) -> None:
        """Called when plugin is deactivated for a trainer."""
        log("info", f"Student pad plugin deactivated for trainer {trainer_id}")

    def _get_student_note(self, student_id: str, trainer_id: str, plugin_id: str = None) -> str:
        """Get current student note directly from database."""
        if plugin_id is None:
            plugin_id = self.id

        with self.db.get_session() as session:
            note = session.query(StudentNote).filter_by(
                user_id=student_id,
                trainer_id=trainer_id,
                plugin_id=plugin_id,
                is_current=1
            ).first()
            return note.content if note else ""

    def _get_note_version_count(self, student_id: str, trainer_id: str, plugin_id: str = None) -> int:
        """Get the number of historical versions."""
        if plugin_id is None:
            plugin_id = self.id

        with self.db.get_session() as session:
            total_count = session.query(StudentNote).filter_by(
                user_id=student_id,
                trainer_id=trainer_id,
                plugin_id=plugin_id
            ).count()
            return max(0, total_count - 1)

    def _save_student_note(self, student_id: str, trainer_id: str, content: str, plugin_id: str = None) -> bool:
        """Save student note with version history."""
        if plugin_id is None:
            plugin_id = self.id

        try:
            with self.db.get_session() as session:
                current_note = session.query(StudentNote).filter_by(
                    user_id=student_id,
                    trainer_id=trainer_id,
                    plugin_id=plugin_id,
                    is_current=1
                ).first()

                # If content hasn't changed, don't create new version
                if current_note and current_note.content == content:
                    return True

                # Mark current note as historical if it exists
                if current_note:
                    current_note.is_current = 0
                    session.add(current_note)

                # Get the next version number
                max_version = session.query(StudentNote.version).filter_by(
                    user_id=student_id,
                    trainer_id=trainer_id,
                    plugin_id=plugin_id
                ).order_by(StudentNote.version.desc()).first()

                next_version = (max_version[0] + 1) if max_version else 1

                # Create new note as current version
                new_note = StudentNote(
                    user_id=student_id,
                    trainer_id=trainer_id,
                    content=content,
                    plugin_id=plugin_id,
                    version=next_version,
                    is_current=1,
                    updated_at=datetime.utcnow()
                )
                session.add(new_note)
                session.commit()
                return True
        except Exception as e:
            log("error", f"Failed to save student note: {e}", stacktrace=True)
            return False

    def _ensure_single_current_note(self, session, student_id: str, trainer_id: str,
                                    plugin_id: str, note_events: List[Dict]):
        """Ensure exactly one note is marked as current after import."""
        current_notes = session.query(StudentNote).filter_by(
            user_id=student_id,
            trainer_id=trainer_id,
            plugin_id=plugin_id,
            is_current=1
        ).all()

        if len(current_notes) > 1:
            # If multiple current notes, keep the most recent one
            current_notes.sort(key=lambda x: x.updated_at or datetime.min, reverse=True)
            for i, note in enumerate(current_notes):
                if i == 0:
                    continue
                note.is_current = 0
        elif len(current_notes) == 0 and note_events:
            # If no current note, set the most recent as current
            most_recent = max(note_events, key=lambda x: x.get('timestamp', ''))
            note_id = most_recent.get('note_id')
            if note_id:
                note = session.query(StudentNote).filter_by(id=note_id).first()
                if note:
                    note.is_current = 1

    def _expand_minimal_event(self, event: Dict, student_info: Dict = None) -> Dict:
        """Expand a minimal event to full event data for import."""
        expanded = event.copy()

        if 'version' not in expanded:
            expanded['version'] = 1
        if 'is_current' not in expanded:
            expanded['is_current'] = False
        if 'metadata' not in expanded:
            expanded['metadata'] = {}

        if 'timestamp' in expanded:
            if 'created_at' not in expanded:
                expanded['created_at'] = expanded['timestamp']
            if 'updated_at' not in expanded:
                expanded['updated_at'] = expanded['timestamp']

        if student_info and expanded.get('student_id') in student_info:
            if 'student_name' not in expanded:
                expanded['student_name'] = student_info[expanded['student_id']]['name']

        return expanded

    def get_student_notes_context(self, user_id: str, messages: List[Dict]) -> Optional[Tuple[str, str, str]]:
        """Context callback for student's personal notes."""
        if not self._is_active:
            return None

        user = self.user_manager.get_user(user_id)
        if not user or not user.get('parent_id'):
            return None

        trainer_id = user['parent_id']
        student_notes = self._get_student_note(user_id, trainer_id)

        if not student_notes:
            return None

        context_prompt = get_prompt('trainer.plugins.student_pad.student_notes_context',
                                   "Student's personal notes:\n{student_notes}")
        context = context_prompt.format(student_notes=student_notes)

        return (context, "system", "top")

    def get_teacher_notes_context(self, user_id: str, messages: List[Dict]) -> Optional[Tuple[str, str, str]]:
        """Context callback for teacher's private notes about the student."""
        if not self._is_active:
            return None

        user = self.user_manager.get_user(user_id)
        if not user or not user.get('parent_id'):
            return None

        trainer_id = user['parent_id']
        teacher_notes = self._get_student_note(user_id, trainer_id, "teacher_notes")

        if not teacher_notes:
            return None

        context_prompt = get_prompt('trainer.plugins.student_pad.teacher_notes_context',
                                   "Teacher's private notes about this student (use this to guide your teaching approach):\n{teacher_notes}")
        context = context_prompt.format(teacher_notes=teacher_notes)

        return (context, "system", "top")

    def get_memory_context(self, user_id: str, messages: List[Dict]) -> Optional[Tuple[str, str, str]]:
        """Legacy callback - delegates to student notes."""
        if not self._is_active:
            return None
        return self.get_student_notes_context(user_id, messages)

    def get_context(self, student_id: str) -> Dict[str, str]:
        """Get plugin-specific context information for a student."""
        user = self.user_manager.get_user(student_id)
        if not user or not user.get('parent_id'):
            return {}

        trainer_id = user['parent_id']
        student_notes = self._get_student_note(student_id, trainer_id)
        teacher_notes = self._get_student_note(student_id, trainer_id, "teacher_notes")

        context = {}
        if student_notes:
            context["📝 Student's Personal Notes"] = student_notes
        if teacher_notes:
            context["👨‍🏫 Teacher's Private Notes"] = teacher_notes

        return context

    def add_note(self, student_id: str, content: str, topic: str = "") -> Dict:
        """Append a note to the student's pad."""
        user = self.user_manager.get_user(student_id)
        if not user or not user.get("parent_id"):
            return {"saved": False, "reason": "trainer_not_found"}

        trainer_id = user["parent_id"]
        existing = self._get_student_note(student_id, trainer_id)
        line = content.strip() if not topic else f"[{topic}] {content.strip()}"
        merged = f"{existing}\n{line}".strip() if existing else line

        saved = self._save_student_note(student_id, trainer_id, merged)
        return {"saved": bool(saved)}

    def _action_trigger_analysis(self, context, **params) -> Dict:
        """Unsupported action."""
        log("warning", "student_pad: trigger_memory_analysis not supported")
        return {"success": False, "reason": "unsupported", "plugin": "student_pad"}

    def export_history(self, trainer_id: str, student_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Export all student pad history events in minimal format."""
        events = []

        with self.db.get_session() as session:
            query = session.query(StudentNote).filter_by(trainer_id=trainer_id)
            if student_id:
                query = query.filter_by(user_id=student_id)

            notes = query.order_by(StudentNote.updated_at).all()

            for note in notes:
                if note.plugin_id == self.id or note.plugin_id == "core":
                    event_type = 'plugin.student_pad.student_note'
                    note_type = 'student'
                elif note.plugin_id == "teacher_notes":
                    event_type = 'plugin.student_pad.teacher_note'
                    note_type = 'teacher'
                else:
                    continue

                event = {
                    'timestamp': note.updated_at.isoformat() if note.updated_at else datetime.utcnow().isoformat(),
                    'type': event_type,
                    'plugin_id': self.id,
                    'student_id': note.user_id,
                    'note_id': note.id,
                    'note_type': note_type,
                    'content': note.content,
                }

                if note.version != 1:
                    event['version'] = note.version
                if note.is_current == 1:
                    event['is_current'] = True
                if note.note_metadata:
                    event['metadata'] = note.note_metadata

                events.append(event)

        return events
