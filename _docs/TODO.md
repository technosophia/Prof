<!-- /_docs/TODO.md -->

# Concurrency problems
  mutiple times : FAILED pytest 
3 threads in conftest.py : 
* 1 for the orchestrator
* 1 for the streamlit server with the app
* 1 for the browser executing .features
Problem with concurrency in the tests and sqlite database access

# Bad design choice 
- the pedagogical memory has only one structure for all the app instead of one for each teacher

# Frontend
decorelate core logic with streamlit => FastAPI + React + shadcn/ui

# Evaluation system
how to evaluate the accuracy of a response by the LLM ? The best would be to compare with a real output (mine for example)

# META
AGENTS.md is the entry point. It should have those sections or explain where to find them:
- SPECS : explain the model for the agents. The goal is to help them understand the intent.
- SKILLS : here the goal is to explain how to modify the codebase.
- META : how to update the documentation

# embeddings
    "model_name": "all-MiniLM-L6-v2",
    "model_name": "paraphrase-multilingual-mpnet-base-v2",
