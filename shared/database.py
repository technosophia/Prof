"""
Unified database management with SQLAlchemy.
Supports both in-memory (for testing) and persistent storage.
"""
import os
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from contextlib import contextmanager

from shared.config import get_config
from shared.logging import log

Base = declarative_base()


class DatabaseManager:
    """Manages database connections and operations."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
            cls._instance._engine = None
            cls._instance._session_factory = None
            cls._instance._in_memory = False
        return cls._instance

    def __init__(self):
        # Don't reinitialize if already done
        pass

    def is_initialized(self):
        """Check if database is initialized."""
        return self._engine is not None

    def initialize(self, use_memory: bool = False, db_path: Optional[str] = None):
        """Initialize the database connection."""
        if self._engine is not None:
            return

        if use_memory:
            # In-memory database for testing
            self._engine = create_engine('sqlite:///:memory:', echo=False)
            self._in_memory = True
            log("info", "Initialized in-memory database for testing")
        else:
            # Persistent database
            if db_path is None:
                # Use config or default path
                db_dir = get_config().get("database.path", "data")
                db_path = os.path.join(db_dir, "app.db")

            # Ensure directory exists
            db_dir = os.path.dirname(db_path)
            if db_dir:  # Not empty string
                try:
                    Path(db_dir).mkdir(parents=True, exist_ok=True)
                    log("debug", f"Ensured directory exists: {db_dir}")
                except Exception as e:
                    log("error", f"Failed to create directory {db_dir}: {e}")
                    raise

            db_url = f'sqlite:///{db_path}'
            try:
                self._engine = create_engine(db_url, echo=False)
                self._in_memory = False
                log("info", f"Initialized database at {db_path}")
            except Exception as e:
                log("error", f"Failed to create database at {db_path}: {e}")
                raise

        # Create session factory
        try:
            self._session_factory = sessionmaker(bind=self._engine)
            log("info", "Database session factory created successfully")
        except Exception as e:
            log("error", f"Failed to create database session factory: {e}")
            self._engine = None
            self._session_factory = None
            raise

    @contextmanager
    def get_session(self) -> Session:
        """Get a database session with context manager."""
        if self._engine is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")

        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            log("error", f"Database error: {e}", exc_info=True)
            raise
        finally:
            session.close()

    def create_tables(self, *table_classes):
        """Create tables for the given table classes."""
        if self._engine is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")

        try:
            for table_class in table_classes:
                table_class.__table__.create(bind=self._engine, checkfirst=True)
                log("debug", f"Created table: {table_class.__tablename__}")
        except Exception as e:
            log("error", f"Failed to create tables: {e}")
            raise

    def create_all_tables(self):
        """Create all tables registered with Base."""
        if self._engine is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")

        try:
            Base.metadata.create_all(self._engine)
            log("info", "All database tables created successfully")
        except Exception as e:
            log("error", f"Failed to create database tables: {e}")
            raise


# Global database manager instance
db_manager = DatabaseManager()


def init_database(use_memory: bool = False, db_path: Optional[str] = None):
    """Initialize the database.

    Args:
        use_memory: Use in-memory database for testing
        db_path: Path to database file (for persistent storage)
    """
    db_manager.initialize(use_memory=use_memory, db_path=db_path)
    return db_manager


def get_db():
    """Get the database manager instance."""
    return db_manager
