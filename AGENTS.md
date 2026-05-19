<!-- /AGENTS.md -->

This is the main entry point for agents, it helps to find autonomously the information needed to build the correct context. 

# Purpose
This is a LLM training compagnon application. Basically it's a specialized RAG and Memory agent. The RAG and Memory are adapted to the context of training and to the formation content. The agent can be proactive and have more sophisticated functions, but the core is just that : Training RAG + student conversation memory.

# Essentials
* `streamlit run prof.py` to launch the application backoffice (coach.yoga-pro.xyz:8501)
* `pytest` to run the all (unit and integration) tests using conftest.py
* `uvicorn api:app --host 0.0.0.0 --port 8000 --reload` to run the frontend for endusers (your-app.example.com:8000)
* `cd frontend && npm run build` to rebuild the React SPA after frontend changes (output → frontend_dist/)

The app has agent observability via the configuratble logging system that can be changed in config.json or with FORCE_LOG=level.

# Rules
When coding or documenting :
  - DRY : don't repeat yourself
	- KISS : keep it stupid simple
	- CODE IS LAW : the doc only describe intent, usage, attention point and rules, beside that, the code is the doc
	- FAIL LOUDLY : fail loudly and early, don't silently continue on error
	- LEARN FROM FAILURE : document to avoir repeating the same error
	- AGENTS.md : each directory has AGENTS.md to describe a module. AGENTS.md give instruction on what to know, what to ignore, what to do and not do
	- Modularity : deleting a module (a directory) should keep the rest working. That defines semantic units.
	- Granularity : be maximally granular, better semantics, leaner context
	- Observability : code is data, data is inspectable at will, use logs as a first pass to detect anomalies
	- Provability : code should be provable, i.e. it should be easy to verify its correctness

# Where to find information ?
The project has a nested structure this way : 
/core : code that help coding the rest, meta-code. Depends on nothing.
/shared : all that is shared accross modules. Depends only on core.
/modules : the implementation of the specs. Depends on core and shared. No dependencies between modules.
  The goal of a module is to implement one functionnal unity. If the directory is deleted, everything related with the module is deleted : doc, tests, translations, configuration, code, dependencies. The rest of the app should work without any issue. The module uses injection points for it's ui, and callbacks for it's behavior.
/api : the frontend API, depends on core and shared.
/frontend : the frontend UI, depends on core and shared.


/AGENTS.md : this file, help to navigate the project doc and code
/_docs : if more docs are needed beside AGENTS.md, regroup them here
/_adr : architectures decision record
/_docs/CODE.md : detailled coding rules to follow when producing code
/_docs/SPECS.md : detailled functional specificiations, the goal of the project
/_docs/META.md : how to write .md files to document the project
/_docs/VERIFIER.md : detailled instructions to check the code quality

Anywhere in a directory : 
AGENTS.md : help find information for agents in that directory
_docs/xxx.md : detailled documentation for the project

# Special directories and files
*/translations : contains translations en.json, fr.json and so on, related to the parent directory.
*/tests : contains unit tests. 
*/config.json : contains configuration
*/test_config.json : contains overrides for testing purposes
*/local_config.json : contains overrides for the local environement (prod/dev/preprod)

# Commands
```bash
python tools/generate_api_docs.py  # regenerate API_*.md
tools/restart-frontend.sh to regenerate the frontend
tools/start-tunnel.sh to connect the app to a remote database
```
