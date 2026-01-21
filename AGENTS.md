<a id="app"></a>

# app

[agent]
# Technical Specifications
The technical specifications are as follows:
- Code and comments are exclusively in English.
- The application is multilingual (French/English), managed via gettext.
- Function or class names are explicit.
- Standalone utility functions are grouped by theme in a "lib" directory.
- To determine if a function is a utility, ask the following question: Could it be useful in a completely different program, unrelated to the current specs? If yes, it's a utility function; if not, it belongs to a module.
- All configuration is stored in a JSON file separate from the code.
- Any value that can be changed without modifying the code and is not user data is placed in the configuration.
- All user data is stored in a database.
- Any key or information that should not be in the git repository is stored in a .env file, loaded at startup.
- Provide shell instructions for launching.
- All prompts are stored in a YAML file.
- The requirements.txt file does not contain version numbers.

Tests:
- Each main function from the specs has a non-regression test for its workflow.
- An initialization function creates a starting test dataset that is reset before running tests.

Modules:
- Every module is designed to be scalable and plug-and-play: the application must be able to run, even if diminished, if the module is absent.
- A module is a directory containing ALL files necessary for its operation (tests, configuration, prompts).
- A module injects into the application through injection points what allows it to function.
- The architecture is modular and scalable; all modules are in a "modules" directory.
- A module groups what is needed to code a semantic unit or a functional unit that uses semantic units.
- Each module contains a specification in its header.
- Each module has associated unit tests.
- A module contains: its translations (JSON), its prompts (YAML), its configuration (JSON), its tests (pytest), its display, its business logic, its libraries. Files are always the same from one module to another.
- A module must be independent of other modules, except for common functionalities.
- A module can have sub-modules and its own injection points, but the only dependencies are the parent module and the application's common functionalities. There must be no module that depends on multiple modules. It is a tree structure.

Common:
- Shared modules are in a dedicated "shared" directory to clearly separate them from removable modules; these modules cannot be disabled.
- The application provides injection points for modules for: translations, prompts and LLM calls, configuration, tests, display (side bar, main page, settings tab, user config).
- Everything common comes with a Mock for tests.

Planned Features:
- Base: multi-user, multilingual, multi-LLM, multi-conversation.
- MVP Features:
- RAG with different RAG engines, means to compare and debug them.
- Token stats: monitoring token usage per user.
- Learning path, level assessment through discussion rather than questionnaires.
- Additional Features:
- Retrieval of YouTube playlists and PDFs for importing RAG content.
- Metadata for RAG if necessary for the learning path.

<a id="shared.database"></a>

# shared.database

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

<a id="shared.database.DatabaseManager"></a>

## DatabaseManager Objects

```python
class DatabaseManager()
```

Manages database connections and operations.

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

<a id="shared.database.DatabaseManager.is_initialized"></a>

#### is\_initialized

```python
def is_initialized()
```

Check if database is initialized.

[agent]
Returns True if database is ready for use.

Returns:
    bool: True if database engine is initialized

<a id="shared.database.DatabaseManager.get_session"></a>

#### get\_session

```python
@contextmanager
def get_session() -> Session
```

Get a database session with context manager.

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

<a id="shared.database.init_database"></a>

#### init\_database

```python
def init_database(use_memory: bool = False, db_path: Optional[str] = None)
```

Initialize the database.

[agent]
Initialize database connection. Must be called before any database operations.

Args:
    use_memory: Use in-memory database for testing (default: False)
    db_path: Path to database file (default: from config or "data/app.db")

Returns:
    DatabaseManager: Initialized database manager

Example:
    # At application startup
    init_database(use_memory=False, db_path="data/myapp.db")

