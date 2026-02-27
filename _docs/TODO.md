<!-- /_docs/TODO.md -->

## Concurrency problems
  mutiple times : FAILED pytest 
3 threads in conftest.py : 
* 1 for the orchestrator
* 1 for the streamlit server with the app
* 1 for the browser executing .features
Problem with concurrency in the tests and sqlite database access

# Bad design choice 
- the training program for a teacher is unique for all the app
- the pedagogical memory has only one structure for all the app instead of one for each teacher

# Frontend
decorelate core logic with streamlit => FastAPI + React + shadcn/ui
