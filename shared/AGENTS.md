<!-- /shared/AGENTS.md -->

# Shared code

This code implements functionnalities shared across the app. No other module have meaning without it. It would have no purpose.

/shared contains common functionnalities of the app : users, conversations, llm, prompts, settings, and module handling.

It gives "managers", which are singletons objects that handle the app's data and logic.
Managers are python classes, but they are cached in common.py as a streamlit resource.
If needed in strategic points, the shared code provide callbacks (internal), and special callbacks for UI : injection points.

/shared/API.md describe the API that other modules can use to interact with the shared code.
/shared/CODE.md describe the coding rules

See : 
- /shared/API_CONVERSATION.md for conversations
- /shared/API_LLM.md for LLM and prompts
- /shared/API_USERS.md for users and user settings
- /shared/API_DRIVER.md for programmatic app driving API (context, options, actions, session log)
Special : 
- /shared/API_MODULE_HANDLER.md for module handling (main app only)
- MODULE.md to get the list of injection points aviable for modules and directory structure

If needed (only special cases, should be avoided unless strictly necessary to access some internals) : 
/core/API.md for logging, database, configuration, translation
This API is replicated in /shared/common.py and this one


# Special case : common.py
Single entry point to import all functional logic of the app, common to all modules

# Special case : cached.py
Contains code to access resources that are cached by streamlit. Can be from core or shared, but it's for performance purpose, to avoid reloading after each rerun() : translations, configuration, user_manager, conversation_manager, prompt_manager, settings
