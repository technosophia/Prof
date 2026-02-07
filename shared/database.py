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
from sqlalchemy.sql import text
from contextlib import contextmanager

from shared.logging import log

Base = declarative_base()

MEMDB = 'sqlite:///:memory:'  # Changed to true in-memory database

class DatabaseManager:
    """Manages database connections and operations.

    [agent]
    Singleton class providing database services. Use the global db_manager instance.
    Other modules should inject this service rather than creating their own connections.

    Public methods:
    - get_session(): Primary method for database access
    - is_initialized(): Check if database is ready
    - empty_all_tables(): Remove all records from all tables (preserves table structure)

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

    def dispose(self):
        """Dispose of database connections and reset manager state.

        [agent]
        Properly closes all database connections and resets the manager.
        Critical for test isolation - call between tests to prevent file locks.

        Usage:
            # Between tests
            if db_manager.is_initialized():
                db_manager.dispose()
        """
        if self._engine is not None:
            try:
                # Close all connections in the pool
                self._engine.dispose()
                log("info", "Database connections disposed")
            except Exception as e:
                log("error", f"Error disposing database engine: {e}")

            # CRITICAL: Reset all state so is_initialized() returns False
            self._engine = None
            self._session_factory = None
            self._tables_created = False
            self._in_memory = False
            # Note: _initialized is derived from _engine, so no need to set it

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
                raise ValueError("Database path must be specified for persistent database")

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

    def empty_all_tables(self):
        """Remove all records from all tables while preserving table structure.

        [agent]
        Useful for testing or resetting application state. This method deletes all
        data from every table but keeps the tables themselves intact.

        Warning: This is a destructive operation and should be used with caution.
        Not recommended for production use unless absolutely necessary.

        Returns:
            bool: True if successful, False otherwise

        Example:
            # Reset database for testing
            db_manager.empty_all_tables()
        """
        if not self.is_initialized():
            log("error", "Database not initialized. Cannot empty tables.")
            return False

        try:
            with self.get_session() as session:
                # Get all table names
                result = session.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
                )
                table_names = [row[0] for row in result.fetchall()]

                if not table_names:
                    log("debug", "No tables found to empty")
                    return True

                # Disable foreign key constraints for SQLite
                if self._in_memory or 'sqlite' in str(self._engine.url):
                    session.execute(text("PRAGMA foreign_keys = OFF"))

                # Delete all records from each table
                deleted_counts = {}
                for table_name in table_names:
                    try:
                        result = session.execute(text(f"DELETE FROM {table_name}"))
                        deleted_counts[table_name] = result.rowcount
                        log("debug", f"Deleted {result.rowcount} records from table: {table_name}")
                    except Exception as e:
                        log("warning", f"Failed to delete from table {table_name}: {e}")

                # Re-enable foreign key constraints for SQLite
                if self._in_memory or 'sqlite' in str(self._engine.url):
                    session.execute(text("PRAGMA foreign_keys = ON"))

                session.commit()

                total_deleted = sum(deleted_counts.values())
                log("info", f"Successfully emptied all tables. Total records deleted: {total_deleted}")
                log("debug", f"Details: {deleted_counts}")

                return True

        except Exception as e:
            log("error", f"Failed to empty all tables: {e}", exc_info=True)
            # Try to re-enable foreign key constraints in case of error
            try:
                if self._in_memory or 'sqlite' in str(self._engine.url):
                    with self._engine.connect() as conn:
                        conn.execute(text("PRAGMA foreign_keys = ON"))
            except:
                pass
            return False


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


def get_db_manager():
    return DatabaseManager()
