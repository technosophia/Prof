#!/usr/bin/env python3
"""
Initialize Alembic for database migrations.
Run this script once to set up Alembic in your project.
"""
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

def init_alembic():
    """Initialize Alembic configuration and environment."""
    from alembic.config import Config
    from alembic import command

    project_root = Path(__file__).parent.parent

    # Check if alembic already initialized
    if (project_root / "alembic").exists() and (project_root / "alembic.ini").exists():
        print("✓ Alembic already initialized")
        return True

    print("Initializing Alembic...")

    # Create alembic directory
    alembic_dir = project_root / "alembic"
    alembic_dir.mkdir(exist_ok=True)
    (alembic_dir / "versions").mkdir(exist_ok=True)

    # Create Alembic config
    cfg = Config()
    cfg.set_main_option("script_location", "alembic")

    # Initialize
    try:
        command.init(cfg, "alembic")
        print("✓ Alembic initialized successfully")

        # Now create our custom env.py
        create_custom_env_py(project_root)

        return True
    except Exception as e:
        print(f"✗ Failed to initialize Alembic: {e}")
        return False


def create_custom_env_py(project_root):
    """Create a custom env.py file with our configuration."""
    env_py_content = '''"""Alembic environment configuration."""
import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Import all models so Alembic can detect them
from core.database import Base
from shared.users import UserTable
from shared.conversation import ConversationTable, MessageTable

# Try to import optional module models
try:
    from modules.rag_manager.rag_simple import DocumentTable, ChunkTable, IndexTable
except ImportError:
    pass

try:
    from modules.llm_monitor.models import LLMRequestTable
except ImportError:
    pass

try:
    from modules.training.training_models import (
        UserProgressionTable,
        SkillAssessmentTable,
        LearningPathTable,
        LearningActivityTable
    )
except ImportError:
    pass

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target metadata
target_metadata = Base.metadata

def get_url():
    """Get database URL from config or use default."""
    db_path = os.environ.get("TEST_DB_PATH", "data/app.db")
    return f"sqlite:///{db_path}"

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # Important for SQLite
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # Important for SQLite
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
'''

    env_py_path = project_root / "alembic" / "env.py"
    with open(env_py_path, "w") as f:
        f.write(env_py_content)

    print("✓ Created custom alembic/env.py")

    # Also create script.py.mako
    create_script_mako(project_root)


def create_script_mako(project_root):
    """Create script.py.mako template."""
    mako_content = '''"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}

def upgrade() -> None:
    ${upgrades if upgrades else "pass"}

def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
'''

    mako_path = project_root / "alembic" / "script.py.mako"
    with open(mako_path, "w") as f:
        f.write(mako_content)

    print("✓ Created alembic/script.py.mako")


def create_alembic_ini(project_root):
    """Create alembic.ini configuration file."""
    ini_content = '''[alembic]
script_location = alembic
prepend_sys_path = .
version_path_separator = os
version_locations = %(here)s/alembic/versions
revision_environment = false

# SQLAlchemy URL - will be overridden by env.py
sqlalchemy.url = sqlite:///data/app.db

[post_write_hooks]
hooks = black
black.type = console_scripts
black.entrypoint = black
black.options = -l 88

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
'''

    ini_path = project_root / "alembic.ini"
    if not ini_path.exists():
        with open(ini_path, "w") as f:
            f.write(ini_content)
        print("✓ Created alembic.ini")


if __name__ == "__main__":
    print("=" * 50)
    print("Alembic Initialization Script")
    print("=" * 50)

    success = init_alembic()

    # Also create alembic.ini
    project_root = Path(__file__).parent.parent
    create_alembic_ini(project_root)

    if success:
        print("\n" + "=" * 50)
        print("✅ Alembic initialized successfully!")
        print("=" * 50)
        print("\nNext steps:")
        print("  1. Create initial migration:")
        print("     python scripts/migrate.py create \"Initial schema\"")
        print("  2. Apply migration:")
        print("     python scripts/migrate.py upgrade")
        sys.exit(0)
    else:
        print("\n❌ Alembic initialization failed")
        sys.exit(1)
