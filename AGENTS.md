<!-- /AGENTS.md -->

This is the main entry point for agents, it helps to find autonomously the information needed to build the correct context. 

# Where to find information ?
The project is structured this way : 
/AGENTS.md : this file, help to navigate the project doc and code
/_docs : if more docs are needed beside AGENTS.md, regroup them here
/_adr : architectures decision record
/_docs/CODE.md : coding rules to follow when producing code
/_docs/SPECS.md : functional specificiations, the goal of the project
/_docs/META.md : how to write .md files to document the project
/_docs/VERIFIER.md : detailled instructions to check the code quality

Anywhere in a directory : 
AGENTS.md : help find information for agents in that directory
_docs/CODE.md : global principle to apply when coding, technical specifications
_docs/API.md and _docs/API_xxx.md : automatically generated from docstrings - the goal is to avoid reading all the .py as much as possible. Function signature and doc.

# How is the project organized ?
The main goal is modularity.

The modularity rule : files are organized so that deleting a directory delete a "unit" of things related to each other. If a functionnality is deleted, deleting the directory delete also : code, but also doc, translations, tests, and so on. It's the fundamental principle of modularity.

The goal of a module is to implement one functionnal unity. It's a semantic closure (kind of markov blanket). 

prof.py              ← Streamlit entry point (st.run)
core/                ← observability, logging, config (framework-agnostic)
shared/              ← always-on module: users, conversations, LLM, module_handler
modules/             ← pluggable features (each is a semantic unit)
st_shared/           ← Streamlit-specific UI components shared across modules
tests/               ← BDD integration tests (pytest-bdd + .feature files)
tools/               ← dev scripts (API doc generation, migrations)
_docs/               ← docs associated with AGENTS.md

# Special directories and files
*/translations : contains translations en.json, fr.json and so on, related to the parent directory.
*/tests : contains unit tests. 
*/config.json : contains configuration
*/test_config.json : contains overrides for testing purposes
*/local_config.json : contains overrides for the local environement (prod/dev/preprod)

# Commands
streamlit run prof.py              # run the main app
pytest tests/                      # unit tests and BDD tests
python tools/generate_api_docs.py  # regenerate API_*.md
