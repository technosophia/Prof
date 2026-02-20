<!-- /AGENTS.md -->

This is the main entry point for agents, it helps to find autonomously the information needed to build the correct context. 

# Where to find information ?
The project is structured this way : 
/AGENTS.md : this file, help to navigate the project doc and code
/SPECS.md : functional specificiations, the goal of the project
/META.md : how to write .md files to document the project
/VERIFIER.md : detailled instructions to check the code quality

Anywhre in a directory : 
AGENTS.md : help find information for agents in that directory
CODE.md : global principle to apply when coding, technical specifications
API.md and API_xxx.md : automatically generated from docstrings - the goal is to avoid reading all the .py as much as possible. Function signature and doc.

# How is the project organized ?
The main goal is modularity.

The modularity rule : files are organized so that deleting a directory delete a "unit" of things related to each other. If a functionnality is deleted, deleting the directory delete also : code, but also doc, translations, tests, and so on. It's the fundamental principle of modularity.

The goal of a module is to implement one functionnal unity. It's a semantic closure (kind of markov blanket). 

# Special directories and files
/prof.py is the main application.
/translations : contains translations en.json, fr.json and so on, related to the parent directory.
/tests : contains unit tests. 
config.json : contains configuration
test_config.json : contains overrides for testing purposes
local_config.json : contains overrides for the local environement (prod/dev/preprod)
/core : contains meta code that help to develop. They could be used in any project, their purpose is observability and agility (to change the behaviaviour of the code) for agents and humans. It help debug and evole code itself. 
/shared : the functional code that is used by any modules. This is kind of module that cannot be deactivated. It deals with users, conversations, llm calling and module handling.
/modules : contains all the module, the real functionnalities for the user of the application
