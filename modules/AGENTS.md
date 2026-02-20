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
