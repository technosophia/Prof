"""
Unified database management with SQLAlchemy.
Supports both in-memory (for testing) and persistent storage.

[agent]
This module provides a singleton DatabaseManager for database operations.
Modules like users.py should inject this service rather than creating their own connections.

Public interface:
- db_manager: Global DatabaseManager instance
- Base: SQLAlchemy declarative base for models
- init_database(): Initialize database connection
- DatabaseManager.get_session(): Get database session (context manager)
- DatabaseManager.is_initialized(): Check if database is ready

Typical usage:
1. Call init_database() at application startup
2. Use db_manager.get_session() for database operations
3. Define models using Base as base class
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

MEMDB = 'sqlite:///tests/test.db'

class DatabaseManager:
    """Manages database connections and operations.

    [agent]
    Singleton class providing database services. Use the global db_manager instance.
    Other modules should inject this service rather than creating their own connections.

    Public methods:
    - get_session(): Primary method for database access
    - is_initialized(): Check if database is ready

    Usage:
        # In another module like users.py
        from shared.database import db_manager

        if db_manager.is_initialized():
            with db_manager.get_session() as session:
                # Perform database operations
    """

    _instance = None
    _shared_engine = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
            cls._instance._engine = None
            cls._instance._session_factory = None
            cls._instance._in_memory = False
            cls._instance._tables_created = False
        return cls._instance

    def __init__(self):
        # Singleton pattern - don't reinitialize
        pass

    def is_initialized(self):
        """Check if database is initialized.

        [agent]
        Returns True if database is ready for use.

        Returns:
            bool: True if database engine is initialized
        """
        return self._engine is not None

    def _initialize(self, use_memory: bool = False, db_path: Optional[str] = None):
        """Initialize the database connection. Called by init_database()."""
        if self._engine is not None:
            return

        if use_memory and DatabaseManager._shared_engine is not None:
            self._engine = DatabaseManager._shared_engine
            self._in_memory = True
            log("debug", "Reusing shared in-memory database engine")
            return

        if use_memory:
            db_url = MEMDB
            self._engine = create_engine(db_url, echo=False)
            self._in_memory = True
            # Store as shared engine
            DatabaseManager._shared_engine = self._engine
            log("info", "Initialized and stored shared in-memory database engine")
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
        """Get a database session with context manager.

        [agent]
        Primary method for database access. Provides automatic session management.
        Commits on success, rolls back on exception.

        Yields:
            sqlalchemy.orm.Session: Database session

        Raises:
            RuntimeError: If database not initialized

        Example (from users.py):
            with db_manager.get_session() as session:
                user = session.query(UserTable).filter_by(id=user_id).first()
        """
        if self._engine is None:
            raise RuntimeError("Database not initialized. Call init_database() first.")

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

    def _create_tables(self, *table_classes):
        """Create tables for given model classes. Internal method."""
        if self._engine is None:
            raise RuntimeError("Database not initialized. Call init_database() first.")

        try:
            for table_class in table_classes:
                table_class.__table__.create(bind=self._engine, checkfirst=True)
                log("debug", f"Created table: {table_class.__tablename__}")
        except Exception as e:
            log("error", f"Failed to create tables: {e}")
            raise

    def _create_all_tables(self):
        """Create all tables registered with Base. Internal method."""
        if self._engine is None:
            raise RuntimeError("Database not initialized. Call init_database() first.")

        # Check if tables already created
        if self._tables_created:
            log("debug", "Database tables already created, skipping")
            return

        try:
            Base.metadata.create_all(self._engine)
            self._tables_created = True  # Mark as created
            log("info", "All database tables created successfully")
        except Exception as e:
            log("error", f"Failed to create database tables: {e}")
            raise

    # Add method to check if tables created
    def are_tables_created(self):
        """Check if tables have been created."""
        return self._tables_created


# Global database manager instance
db_manager = DatabaseManager()



def init_database(use_memory: bool = False, db_path: Optional[str] = None):
    """Initialize the database.

    [agent]
    Initialize database connection. Must be called before any database operations.

    Args:
        use_memory: Use in-memory database for testing (default: False)
        db_path: Path to database file (default: from config or "data/app.db")

    Returns:
        DatabaseManager: Initialized database manager
    """
    # Don't reinitialize if already done
    if db_manager.is_initialized():
        return db_manager

    db_manager._initialize(use_memory=use_memory, db_path=db_path)
    if not db_manager.are_tables_created():
        db_manager._create_all_tables()
    return db_manager


def _get_db():
    """Get database manager instance. Alternative to db_manager global."""
    return db_manager
