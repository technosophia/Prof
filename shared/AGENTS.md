<!-- /shared/AGENTS.md -->

# Shared code

This code implements functionnalities shared across the app. No other module have meaning without it. It would have no purpose.

/shared contains common functionnalities of the app : users, conversations, llm, prompts, settings, and module handling.

It gives "managers", which are singletons objects that handle the app's data and logic.
Managers are python classes, but they are cached in common.py as a streamlit resource.
If needed in strategic points, the shared code provide callbacks (internal), and special callbacks for UI : injection points.

/shared/API.md describe the API that other modules can use to interact with the shared code.
/shared/CODE.md describe the coding rules
