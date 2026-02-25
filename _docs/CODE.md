<!-- /_docs/CODE.md -->

# Coding Rules

The technical specifications are as follows:
- Code and comments are exclusively in English.
- Parts of the application is multilingual (French/English), managed via gettext.
- Function or class names are explicit.
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
cf /modules/AGENTS.md

# STREAMLIT

- Becareful to not use duplicate key for visual elements
- Becareful to use session_state for chained interaction, because streamlit use rerun() after button click for example, and all flow of the app restart
- Use ressource_cache for ressources loaded once and for all to make the app faster
