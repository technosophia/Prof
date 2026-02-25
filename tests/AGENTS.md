<!-- /tests/AGENTS.md -->

# Test Suite — Agent Guidelines

## Stack

- **pytest** + **pytest-bdd** for BDD scenario execution
- **Playwright** (`playwright.sync_api`) for browser automation
- **Streamlit** as the application backend
- Features in `/tests/features/`, step definitions in `/tests/step_defs/`

---

## File layout

| File | Purpose |
|---|---|
| `page_helpers.py` | **Pure helper functions only.** No pytest-bdd decorators. All Playwright/Streamlit utilities live here. |
| `common_steps.py` | `@given`/`@when`/`@then` steps reused across multiple feature files. Imports from `page_helpers.py`. |
| `app_start_steps.py` | App startup / navigation to app. |
| `user_steps.py` | Login / user selection steps. |
| `llm_steps.py` | LLM selection and response verification steps. |
| `conversation_common_steps.py` | Conversation create/select/edit steps. |
| `rag_steps.py` | RAG enable/disable and response verification. |
| `debug_steps.py` | Debug admin UI steps. |
| `test_steps.py` | Test admin UI steps. |
| `st_helpers.py` | Compatibility shim — do not add new code here. |

**Rule:** helper functions → `page_helpers.py`. Step definitions → appropriate `*_steps.py`.

---

## Streamlit-specific caveats

### 1. Every interaction triggers a full rerun
Streamlit reruns the entire Python script on every widget interaction. After any click, form submission, or selectbox change, the entire DOM is rebuilt. **Never cache locators across steps** — always re-query them.

### 2. Always pair `networkidle` with an explicit element check
`page.wait_for_load_state("networkidle")` fires when no network requests are in-flight, but Streamlit may still be rendering widgets. Always follow it with an `expect(...).to_be_visible(...)` on a known element. Use `wait_for_app_stable()` for this.

### 3. `st.fragment` is invisible to `networkidle`
Streamlit `@st.fragment` performs partial reruns that do not trigger network requests. If your feature uses fragments, you must poll for the expected DOM change explicitly.

### 4. Selectbox dropdowns render in a portal
The dropdown list of a `st.selectbox` is appended to `<body>`, **outside** the selectbox's DOM ancestry. Never use `.locator("..")` or ancestor selectors to find options after opening a selectbox. Use a global selector like `[data-testid="stSelectboxOption"]` instead.

### 5. Chat input clears immediately on submit
`st.chat_input` clears its value the instant Enter is pressed (Streamlit handles it before the next render). **Never** assert the input's value after pressing Enter — it will always be empty.

### 6. Double rerun on startup
Streamlit often performs two reruns on initial load (auto-login hooks, session state init, etc.). Always wait for the explicit `[data-testid="app-fully-loaded"]` marker before asserting any page content.

### 7. Stale element references after rerun
Playwright `Locator` objects are lazy and re-query the DOM on each use, so they are generally safe. However, avoid storing `.element_handle()` objects across steps — handles become stale after a rerun.

### 8. Widget key conflicts cause silent failures
If a Streamlit widget key appears twice in the same render cycle, Streamlit raises an error that may surface as a blank or broken page. Check for duplicate keys when debugging unexpected blank pages.

### 9. `aria-label` and `data-testid` are stable; class names are not
Streamlit generates predictable `data-testid` attributes (e.g., `stSelectbox`, `stChatMessage`) and `st-key-*` CSS classes for keyed widgets. Prefer these over positional selectors or auto-generated class names.

---

## Core patterns

### Always use `expect_visible()` — never bare `assert`

```python
# ✅ Correct
expect_visible(
    page,
    page.get_by_text("My heading"),
    screenshot_name="heading_missing.png",
    error_message="Expected heading not found after navigation.",
)

# ❌ Wrong — no screenshot context on failure
assert page.get_by_text("My heading").is_visible()
```

### Always call `wait_for_app_stable()` before querying elements

```python
# ✅ Correct
def my_step(context):
    page = context["page"]
    wait_for_app_stable(page)          # wait for rerun to finish
    expect_visible(page, page.locator("..."), ...)

# ❌ Wrong — query immediately after an action
def my_step(context):
    page = context["page"]
    page.locator("button").click()
    assert page.locator("result").is_visible()  # may be stale
```

### Screenshot on every failure

Every `except AssertionError` block must call `screenshot_on_failure(page, "descriptive_name.png")` before re-raising. The screenshot is always saved regardless of `debug_enabled`.

```python
try:
    expect(some_locator).to_be_visible(timeout=15_000)
except AssertionError:
    screenshot_on_failure(page, "my_element_not_found.png")
    raise AssertionError("My element was not visible after action X.")
```

### Never assert chat input value after Enter

```python
# ✅ Correct
chat_input.type(message, delay=80)
chat_input.press("Enter")
page.wait_for_timeout(2_000)  # let Streamlit register the submit

# ❌ Wrong — Streamlit clears the field immediately
chat_input.press("Enter")
expect(chat_input).to_have_value(message)  # always fails
```

### Use the helper functions — do not duplicate logic

| Need | Use |
|---|---|
| Wait for Streamlit rerun | `wait_for_app_stable(page)` |
| Assert element visible + screenshot | `expect_visible(page, locator, "file.png", "msg")` |
| Assert text on page + screenshot | `expect_text_on_page(page, "text", "file.png")` |
| Assert text absent + screenshot | `expect_not_text_on_page(page, "text", "file.png")` |
| Verify header text | `verify_header_contains(page, "text")` |
| Click a button | `click_button(page, ["Label", "emoji Label"])` |
| Fill a selectbox | `find_and_select_in_selectbox(page, key="my_key", value_to_select="Value")` |
| Find chat input | `find_chat_input(page)` |
| Poll for LLM response | `wait_for_llm_response(page, expected_text="word")` |
| Wait for streaming to finish | `wait_for_response_stable(page)` |

---

## Writing new steps

1. **Check `page_helpers.py` first** — your logic may already exist.
2. Add new helper functions to `page_helpers.py` (no decorators).
3. Add new step definitions to the most specific `*_steps.py` file, or `common_steps.py` if reused by ≥ 2 features.
4. Every step function must:
   - Accept `context: dict` as first argument
   - Call `wait_for_app_stable(page)` before any DOM interaction
   - Use `expect_visible()` / `expect_text_on_page()` (not bare asserts)
   - Call `screenshot_on_failure()` in every `except` block
   - Return `context`

---

## Timeouts reference

| Constant | Value | Use for |
|---|---|---|
| `DEFAULT_TIMEOUT` | 30 000 ms | Standard element visibility |
| `SLOW_TIMEOUT` | 60 000 ms | LLM responses, heavy init |
| `FAST_TIMEOUT` | 5 000 ms | Quick existence checks |
| `POLL_INTERVAL` | 1 000 ms | Between retry attempts |
| `MAX_RETRIES` | 15 | LLM response polling loops |

---

## Debugging failing tests

1. Set `debug_enabled = True` in `context` — every helper will save screenshots.
2. Screenshots land in `tests/debug/`.
3. The `"I debug the current state"` step prints full page text + context to stdout.
4. Check `tests/debug/` for the screenshot taken immediately before the `AssertionError`.
5. If the page is blank or broken, check for duplicate Streamlit widget keys.
6. If `networkidle` never fires, check for `st.fragment` usage — use explicit polling instead.
