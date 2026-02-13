"""
Unified database management with SQLAlchemy and Alembic migrations.
Supports both in-memory (for testing) and persistent storage with automatic schema migrations.

This module provides a singleton DatabaseManager for database operations.
Now with integrated Alembic migration support.

Public interface:
- db_manager: Global DatabaseManager instance
- Base: SQLAlchemy declarative base for models
- init_database(): Initialize database connection and run migrations
- DatabaseManager.get_session(): Get database session (context manager)
- DatabaseManager.check_and_upgrade_schema(): Run pending migrations

[agent]
Unified database management with SQLAlchemy.
BECAREFUL : internal module. Use shared.common for imports, not core.database

This module provides a singleton DatabaseManager and SQLAlchemy declarative Base
for applications to define their own database models that integrate with the main
database system.

===========================================================================
DEFINING CUSTOM TABLES
===========================================================================

1. Import the Base class from this module:

   from core.database import Base

2. Define your model class inheriting from Base:

   class MyTable(Base):
       __tablename__ = 'my_table'

       id = Column(String, primary_key=True)
       name = Column(String, nullable=False)
       # ... other columns

3. Tables are automatically created on application startup via init_database().
   No manual creation or migration handling is needed.

===========================================================================
DATABASE ACCESS
===========================================================================

Get the global database manager and use session context manager:

   from core.database import get_db_manager

   db = get_db_manager()
   with db.get_session() as session:
       result = session.query(MyTable).all()
       session.add(my_object)

The session automatically commits on success, rolls back on error.

===========================================================================
PUBLIC INTERFACE
===========================================================================

- Base: SQLAlchemy declarative base - inherit this for all custom tables
- get_db_manager(): Returns the singleton DatabaseManager instance
- init_database(): Initialize database connection (called by app startup)
- DatabaseManager.get_session(): Context manager for database sessions

===========================================================================
NOTE
===========================================================================

- All tables inheriting from Base are automatically detected and created
- For persistent databases, schema changes are handled via Alembic migrations
- In-memory database (:memory:) is automatically used for testing
- Always use get_session() context manager - never manage sessions manually

"""
import os
from pathlib import Path
from typing import Any, Dict, Optional
import importlib.util

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from contextlib import contextmanager

from core.logging import log

Base = declarative_base()

MEMDB = 'sqlite:///:memory:'


class AlembicMigrationHelper:
    """
    Helper class for Alembic migrations.
    Integrated directly into DatabaseManager to avoid circular imports.
    """

    def __init__(self, db_manager):
        self.db_manager = db_manager
        self._alembic_available = None
        self._alembic_cfg = None

    @property
    def is_alembic_available(self):
        """Check if alembic is installed."""
        if self._alembic_available is None:
            try:
                import alembic
                self._alembic_available = True
            except ImportError:
                self._alembic_available = False
        return self._alembic_available

    def _get_alembic_config(self):
        """Get Alembic configuration."""
        if not self.is_alembic_available:
            return None

        if self._alembic_cfg is None:
            try:
                from alembic.config import Config

                # Find project root (where alembic.ini should be)
                # Start from the directory of this file and go up to find prof.py
                current_dir = Path(__file__).parent
                project_root = current_dir.parent  # core/ is inside project root

                # Verify we have the right directory (prof.py should be there)
                app_py = project_root / "prof.py"
                if not app_py.exists():
                    # Try going up one more level
                    project_root = project_root.parent
                    app_py = project_root / "prof.py"

                alembic_ini = project_root / "alembic.ini"

                if not alembic_ini.exists():
                    log("warning", f"Alembic config not found at {alembic_ini}")
                    return None

                cfg = Config(str(alembic_ini))

                # Set database URL based on current connection
                if self.db_manager._engine:
                    cfg.set_main_option("sqlalchemy.url", str(self.db_manager._engine.url))

                self._alembic_cfg = cfg
            except Exception as e:
                log("error", f"Failed to load Alembic config: {e}")
                return None

        return self._alembic_cfg

    def get_current_revision(self):
        """Get current database revision."""
        if not self.db_manager.is_initialized():
            return None

        cfg = self._get_alembic_config()
        if not cfg:
            return None

        try:
            from alembic.runtime.migration import MigrationContext

            with self.db_manager.get_session() as session:
                context = MigrationContext.configure(session.connection())
                return context.get_current_revision()
        except Exception as e:
            log("error", f"Failed to get current revision: {e}")
            return None

    def get_head_revision(self):
        """Get head revision from migrations."""
        cfg = self._get_alembic_config()
        if not cfg:
            return None

        try:
            from alembic.script import ScriptDirectory

            script = ScriptDirectory.from_config(cfg)
            return script.get_current_head()
        except Exception as e:
            log("error", f"Failed to get head revision: {e}")
            return None

    def needs_upgrade(self):
        """Check if database needs upgrade."""
        current = self.get_current_revision()
        head = self.get_head_revision()
        return current != head

    def upgrade(self, revision="head"):
        """Upgrade database to specified revision."""
        cfg = self._get_alembic_config()
        if not cfg:
            return False

        try:
            from alembic import command

            log("info", f"Running Alembic upgrade to {revision}...")
            command.upgrade(cfg, revision)
            log("info", "Database upgrade completed successfully")
            return True
        except Exception as e:
            log("error", f"Database upgrade failed: {e}", exc_info=True)
            return False

    def stamp(self, revision="head"):
        """Stamp database without running migrations."""
        cfg = self._get_alembic_config()
        if not cfg:
            return False

        try:
            from alembic import command

            command.stamp(cfg, revision)
            log("info", f"Database stamped with revision {revision}")
            return True
        except Exception as e:
            log("error", f"Failed to stamp database: {e}")
            return False

    def create_migration(self, message, autogenerate=True):
        """Create a new migration."""
        cfg = self._get_alembic_config()
        if not cfg:
            return False

        try:
            from alembic import command

            if autogenerate:
                command.revision(cfg, message=message, autogenerate=True)
            else:
                command.revision(cfg, message=message, autogenerate=False)
            log("info", f"Created migration: {message}")
            return True
        except Exception as e:
            log("error", f"Failed to create migration: {e}")
            return False


class DatabaseManager:
    """Manages database connections and operations with Alembic migration support."""

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
        if not hasattr(self, '_migration_helper'):
            self._migration_helper = AlembicMigrationHelper(self)

    def is_initialized(self):
        """Check if database is initialized."""
        return self._engine is not None

    def dispose(self):
        """Dispose of database connections and reset manager state."""
        if self._engine is not None:
            try:
                self._engine.dispose()
                log("info", "Database connections disposed")
            except Exception as e:
                log("error", f"Error disposing database engine: {e}")

            self._engine = None
            self._session_factory = None
            self._tables_created = False
            self._in_memory = False

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
            DatabaseManager._shared_engine = self._engine
            log("info", "Initialized and stored shared in-memory database engine")
        else:
            if db_path is None:
                raise ValueError("Database path must be specified for persistent database")

            db_dir = os.path.dirname(db_path)
            if db_dir:
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

    def _create_all_tables(self):
        """Create all tables registered with Base."""
        if self._engine is None:
            raise RuntimeError("Database not initialized. Call init_database() first.")

        if self._tables_created:
            log("debug", "Database tables already created, skipping")
            return

        try:
            Base.metadata.create_all(self._engine)
            self._tables_created = True
            log("info", "All database tables created successfully")
        except Exception as e:
            log("error", f"Failed to create database tables: {e}")
            raise

    def are_tables_created(self):
        """Check if tables have been created."""
        return self._tables_created

    def empty_all_tables(self):
        """Remove all records from all tables while preserving table structure."""
        if not self.is_initialized():
            log("error", "Database not initialized. Cannot empty tables.")
            return False

        try:
            with self.get_session() as session:
                result = session.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
                )
                table_names = [row[0] for row in result.fetchall()]

                if not table_names:
                    log("debug", "No tables found to empty")
                    return True

                if self._in_memory or 'sqlite' in str(self._engine.url):
                    session.execute(text("PRAGMA foreign_keys = OFF"))

                deleted_counts = {}
                for table_name in table_names:
                    try:
                        result = session.execute(text(f"DELETE FROM {table_name}"))
                        deleted_counts[table_name] = result.rowcount
                        log("debug", f"Deleted {result.rowcount} records from table: {table_name}")
                    except Exception as e:
                        log("warning", f"Failed to delete from table {table_name}: {e}")

                if self._in_memory or 'sqlite' in str(self._engine.url):
                    session.execute(text("PRAGMA foreign_keys = ON"))

                session.commit()

                total_deleted = sum(deleted_counts.values())
                log("info", f"Successfully emptied all tables. Total records deleted: {total_deleted}")
                return True

        except Exception as e:
            log("error", f"Failed to empty all tables: {e}", exc_info=True)
            try:
                if self._in_memory or 'sqlite' in str(self._engine.url):
                    with self._engine.connect() as conn:
                        conn.execute(text("PRAGMA foreign_keys = ON"))
            except:
                pass
            return False

    # ============= ALEMBIC MIGRATION METHODS =============

    def check_and_upgrade_schema(self, revision="head"):
        """
        Check if database schema needs upgrade and run migrations.
        This is the main method to call on application startup.

        Args:
            revision: Target revision (default: "head")

        Returns:
            bool: True if upgrade was successful or not needed, False on error
        """
        if not self.is_initialized():
            log("warning", "Database not initialized, skipping schema upgrade")
            return False

        if self._in_memory:
            log("debug", "In-memory database, skipping schema upgrade")
            return True

        if not self._migration_helper.is_alembic_available:
            log("warning", "Alembic not installed. Install with: pip install alembic")
            return True

        try:
            if self._migration_helper.needs_upgrade():
                log("info", "Database schema needs upgrade, running migrations...")
                return self._migration_helper.upgrade(revision)
            else:
                log("debug", "Database schema is up to date")
                return True
        except Exception as e:
            log("error", f"Failed to check/upgrade schema: {e}", exc_info=True)
            return False

    def create_migration(self, message: str, autogenerate: bool = True):
        """
        Create a new migration file.

        Args:
            message: Migration description
            autogenerate: Auto-detect changes vs create empty migration

        Returns:
            bool: True if migration was created successfully
        """
        if not self._migration_helper.is_alembic_available:
            log("error", "Alembic not installed. Install with: pip install alembic")
            return False

        return self._migration_helper.create_migration(message, autogenerate)

    def get_migration_status(self) -> dict:
        """
        Get current migration status.

        Returns:
            dict: Migration status information
        """
        status = {
            "alembic_available": self._migration_helper.is_alembic_available,
            "database_initialized": self.is_initialized(),
            "in_memory": self._in_memory,
            "current_revision": None,
            "head_revision": None,
            "needs_upgrade": False
        }

        if self.is_initialized() and not self._in_memory:
            status["current_revision"] = self._migration_helper.get_current_revision()
            status["head_revision"] = self._migration_helper.get_head_revision()
            status["needs_upgrade"] = self._migration_helper.needs_upgrade()

        return status

    def stamp_database(self, revision="head"):
        """
        Stamp database without running migrations.

        Args:
            revision: Revision to stamp

        Returns:
            bool: True if stamping was successful
        """
        if not self._migration_helper.is_alembic_available:
            log("error", "Alembic not installed")
            return False

        return self._migration_helper.stamp(revision)


# Global database manager instance
db_manager = DatabaseManager()


def init_database(use_memory: bool = False,
                  db_path: Optional[str] = None,
                  auto_upgrade: bool = True,
                  upgrade_revision: str = "head"):
    """
    Initialize the database with optional automatic migration.

    Args:
        use_memory: Use in-memory database for testing
        db_path: Path to database file (default: from config or "data/app.db")
        auto_upgrade: Automatically run schema migrations on startup
        upgrade_revision: Target revision for upgrade (default: "head")

    Returns:
        DatabaseManager: Initialized database manager
    """
    if db_manager.is_initialized():
        return db_manager

    # If db_path is None, try to get from config
    if db_path is None and not use_memory:
        try:
            from shared.common import get_config
            config = get_config()
            db_path = config.get("database.path", "data")
            db_path = os.path.join(db_path, "app.db")
        except ImportError:
            db_path = "data/app.db"
            log("warning", f"Could not load config, using default path: {db_path}")
        except Exception as e:
            db_path = "data/app.db"
            log("warning", f"Error loading config, using default path: {db_path}")

    db_manager._initialize(use_memory=use_memory, db_path=db_path)

    # Auto-upgrade schema if requested and not in-memory
    if auto_upgrade and not use_memory:
        db_manager.check_and_upgrade_schema(upgrade_revision)

    if not db_manager.are_tables_created():
        db_manager._create_all_tables()

    return db_manager


def get_db_manager():
    """Get the global DatabaseManager instance."""
    return DatabaseManager()
