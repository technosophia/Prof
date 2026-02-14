class StudentMemory(Base):
    """Store pedagogical memory for each student with version history."""
    __tablename__ = 'trainer_student_memories'
    __table_args__ = {'extend_existing': True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)  # Student ID
    trainer_id = Column(String, nullable=False, index=True)  # Trainer/Master ID
    content = Column(Text, default="")  # The memory content
    version = Column(Integer, default=1)  # Version number
    is_current = Column(Integer, default=1)  # 1 for current version, 0 for history
    source = Column(String, nullable=False)  # 'auto' or 'manual' or 'llm:llm_id'
    last_analyzed_at = Column(DateTime, nullable=True)  # Timestamp of last conversation analysis
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    memory_metadata = Column(JSON, default={})  # For stats like messages analyzed, etc.
