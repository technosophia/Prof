<!-- /_docs/TODO.md -->

# Module caching
I have a new problem for recent change in caching policie.
from st_shared.cached get_active_modules => create a regression 
  FAILED tests/step_defs/rag_steps.py::test_rag_disabled_conversation - AssertionError: RAG information leakage detected: '1 place du Louvre, place du Louvre' found when RAG was disabled
but caching modules should be desirable for performance

## Concurrency problems
  FAILED tests/step_defs/test_steps.py::test_verify_test_module_loads_in_admin_panel - AssertionError: Expected text 'Test module active' not found in admin content
3 threads in conftest.py : 
* 1 for the orchestrator
* 1 for the streamlit server with the app
* 1 for the browser executing .features
Problem with concurrency in the tests and sqlite database access
