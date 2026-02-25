<!-- /modules/AGENTS.md -->

# What is a module ?
It's a set of self-related functionalities that can be activated or deactivated independently.

The principle is simple : if a module is deactivated, or deleted, the application should still work, but with less functionnality. Deleting a module cannot break the rest. That's the simple principle that rule the module creation.

Modules must not depend on each other, only interact through /shared code.
If 2 modules depends on each other, that mean shared code must be refactored to avoid that.

A module respects the global architecture of the project.
It uses /shared/common.py to implements it's ui and interact with the application.
Cf /shared/AGENTS.md for more details.
It must respect the global app architecture and file/directory structure, and coding standards.

See /modules/CODE.md for more details on coding principle for modules, how to architecture them.
Se /shared/API.md for implemetantion details.

Module are automatically discovered and loaded by the application provided the are a directory within the /modules directory and that they provide a valide module.json file.

# How to code a module

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

# Module directory structure
/module.json defines the module's metadata, including its name, version, description, and dependencies.
/config.json defines the module's configuration, auto-loaded by the app.
/translations contains translation files : en.json, fr.json
/tests contains unit test files.
/prompt.en.yml, /prompt.fr.yml for the prompts used by the module (automatically loaded)
