"""
Database admin UI for managing migrations.
No circular dependencies - uses DatabaseManager directly.
"""
import streamlit as st
import subprocess
import sys
from pathlib import Path

from core.database import db_manager
from core.logging import log


def inject_ui_admin_tab():
    """Add Database tab to admin panel."""

    def render_database_admin():
        st.header("🗄️ Database Migration Management")

        # Get migration status
        status = db_manager.get_migration_status()

        # Database status
        st.subheader("Status")

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("Alembic Available",
                     "✅" if status['alembic_available'] else "❌")

        with col2:
            current = status['current_revision']
            display_current = current[:8] if current else "None"
            st.metric("Current Revision", display_current)

        with col3:
            head = status['head_revision']
            display_head = head[:8] if head else "None"
            st.metric("Head Revision", display_head)

        with col4:
            st.metric("Needs Upgrade",
                     "⚠️ Yes" if status['needs_upgrade'] else "✅ No")

        # Migration actions
        st.subheader("Migration Actions")

        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button("🔄 Upgrade to Latest", width='stretch',
                        disabled=not status['needs_upgrade']):
                with st.spinner("Running migrations..."):
                    if db_manager.check_and_upgrade_schema():
                        st.success("✅ Database upgraded successfully")
                        st.rerun()
                    else:
                        st.error("❌ Upgrade failed - check logs")

        with col2:
            if st.button("⬇️ Downgrade One Step", width='stretch',
                        disabled=not status['current_revision']):
                with st.spinner("Downgrading..."):
                    # Run downgrade via alembic directly
                    try:
                        project_root = Path(__file__).parent.parent
                        result = subprocess.run(
                            [sys.executable, "scripts/migrate.py", "downgrade", "-1"],
                            cwd=project_root,
                            capture_output=True,
                            text=True
                        )
                        if result.returncode == 0:
                            st.success("✅ Database downgraded successfully")
                            st.rerun()
                        else:
                            st.error(f"❌ Downgrade failed: {result.stderr}")
                    except Exception as e:
                        st.error(f"❌ Error: {e}")

        with col3:
            if st.button("📋 Show Migration History", width='stretch'):
                st.session_state.show_migration_history = True

        # Migration history
        if st.session_state.get("show_migration_history", False):
            st.subheader("Migration History")

            try:
                project_root = Path(__file__).parent.parent
                result = subprocess.run(
                    [sys.executable, "scripts/migrate.py", "history"],
                    cwd=project_root,
                    capture_output=True,
                    text=True
                )
                st.code(result.stdout, language="bash")

                if st.button("Hide History"):
                    del st.session_state.show_migration_history
                    st.rerun()
            except Exception as e:
                st.error(f"Failed to get history: {e}")

        # Create new migration
        st.subheader("Create New Migration")

        migration_message = st.text_input(
            "Migration Description",
            placeholder="e.g., Add user preferences table",
            key="migration_message"
        )

        col1, col2 = st.columns(2)

        with col1:
            if st.button("📝 Auto-Detect Changes", width='stretch',
                        disabled=not migration_message):
                if migration_message:
                    with st.spinner("Creating migration..."):
                        if db_manager.create_migration(migration_message, autogenerate=True):
                            st.success("✅ Migration created successfully!")
                            st.info("Don't forget to review and apply it!")
                        else:
                            st.error("❌ Failed to create migration")
                else:
                    st.warning("Please enter a migration description")

        with col2:
            if st.button("⚙️ Create Empty Migration", width='stretch',
                        disabled=not migration_message):
                if migration_message:
                    with st.spinner("Creating empty migration..."):
                        if db_manager.create_migration(migration_message, autogenerate=False):
                            st.success("✅ Empty migration created!")
                            st.info("Edit the file before applying")
                        else:
                            st.error("❌ Failed to create migration")
                else:
                    st.warning("Please enter a migration description")

        # Database utilities
        st.subheader("Database Utilities")

        col1, col2 = st.columns(2)

        with col1:
            if st.button("💾 Stamp Current Database", width='stretch'):
                with st.spinner("Stamping database..."):
                    if db_manager.stamp_database():
                        st.success("✅ Database stamped with head revision")
                        st.rerun()
                    else:
                        st.error("❌ Failed to stamp database")

        with col2:
            if st.button("📁 Show Migration Files", width='stretch'):
                project_root = Path(__file__).parent.parent
                versions_dir = project_root / "alembic" / "versions"

                if versions_dir.exists():
                    files = list(versions_dir.glob("*.py"))
                    files.sort(key=lambda x: x.stat().st_mtime, reverse=True)

                    st.write(f"**Found {len(files)} migration files:**")
                    for i, f in enumerate(files[:10]):  # Show last 10
                        with st.expander(f"{i+1}. {f.name}"):
                            try:
                                with open(f, 'r') as file:
                                    content = file.read()
                                    # Extract just the docstring and upgrade/downgrade
                                    lines = content.split('\n')
                                    preview = '\n'.join(lines[:20]) + "\n..."
                                    st.code(preview, language="python")
                            except Exception as e:
                                st.error(f"Could not read file: {e}")

                    if len(files) > 10:
                        st.info(f"... and {len(files) - 10} more files")
                else:
                    st.info("No migrations directory found")

        # Warning for in-memory databases
        if status['in_memory']:
            st.warning("⚠️ You are using an in-memory database. Migrations only work with persistent databases.")

    return ("Database", render_database_admin)
