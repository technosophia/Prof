"""SQLite persistence via SQLModel. Deduplicates on response_id to handle Tally retries."""

import os
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel, Session, create_engine, select

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        db_path = os.environ.get("DATABASE_PATH", "./data/autodiag.db")
        _engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    return _engine


class DiagResponse(SQLModel, table=True):
    __tablename__ = "responses"

    id: Optional[int] = Field(default=None, primary_key=True)
    response_id: str = Field(unique=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    email: str
    situation: str
    felt_constraint: str
    score_energie: int
    score_attention: int
    score_liens: int
    score_moyens: int
    score_total: int
    profile_key: str
    is_rationalisateur: bool
    raw_payload: str  # JSON text


def init_db() -> None:
    SQLModel.metadata.create_all(get_engine())


def save_response(record: DiagResponse) -> bool:
    """Insert record. Returns False if response_id already exists (retry guard)."""
    with Session(get_engine()) as session:
        existing = session.exec(
            select(DiagResponse).where(DiagResponse.response_id == record.response_id)
        ).first()
        if existing:
            return False
        session.add(record)
        session.commit()
        return True
