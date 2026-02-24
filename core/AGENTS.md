<!-- /core/AGENTS.md -->

Contains core coding tools, here to help human and agents to deal with the code of the app easier.
It help to observe and change behaviour of the code.
The goal is evolvability (debugging, maintenance, deployment)

see /core/API.md for technical details of the API provided for other modules

* config : allow changing global behavior of the application, provide overrides for prod and test
* logging : allow observability of the application per module
* database : allow persistence of the application data, agnostic of the database technology
* translate : multilingual support
