<!-- /TODO.md -->

# Module caching
I have a new problem for recent change in caching policie.
from st_shared.cached get_active_modules => create a regression 
  FAILED tests/step_defs/rag_steps.py::test_rag_disabled_conversation - AssertionError: RAG information leakage detected: '1 place du Louvre, place du Louvre' found when RAG was disabled
but caching modules should be desirable for performance
