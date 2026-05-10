<!-- /shared/AGENTS.md -->

# Shared code

This code implements functionnalities shared across the app. No other module have meaning without it. It would have no purpose.

/shared contains common functionnalities of the app : users, conversations, llm, prompts, settings, module handling, and external integrations (email).

It gives "managers", which are singletons objects that handle the app's data and logic.
Managers are python classes, but they are cached in common.py.
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
- /shared/MODULE.md to get the list of injection points aviable for modules and directory structure

Email integrations (see env var requirements in modules/payhip_webhook/AGENTS.md):
- `shared/mailer_lite.py` — MailerLite subscriber upsert with group assignment and reset_code field; also exposes `get_groups`, `get_subscriber_by_email`, `remove_subscriber_from_group`
- `shared/transactional_email.py` — MailerSend transactional email (welcome email with reset code link); requires `MAILERSEND_API_KEY`, `MAILERSEND_FROM`, `APP_URL`

If needed (only special cases, should be avoided unless strictly necessary to access some internals) : 
/core/API.md for logging, database, configuration, translation
This API is replicated in /shared/common.py and this one


# Special case : common.py
Single entry point to import all functional logic of the app, common to all modules
