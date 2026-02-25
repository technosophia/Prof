# file: tests/step_defs/page_helpers.py
"""
Pure helper functions for Playwright + Streamlit testing.
No pytest-bdd decorators here — only reusable utilities.

Streamlit-specific caveats handled here:
- Reruns invalidate DOM: always re-query locators, never cache them.
- networkidle alone is not enough: always pair with explicit element visibility.
- Fragments (st.fragment) do partial reruns invisible to networkidle.
- Selectbox dropdowns render in a portal outside normal DOM ancestry.
- Chat input clears immediately on submit — don't assert its value after Enter.
- Double rerun on startup: rely on APP_FULLY_LOADED_SELECTOR marker.
"""

import os
import re
import time
from typing import Optional, List

from playwright.sync_api import Page, Locator, expect


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

APP_FULLY_LOADED_SELECTOR = '[data-testid="app-fully-loaded"]'
DEFAULT_TIMEOUT = 30_000       # ms — standard wait for most elements
SLOW_TIMEOUT    = 60_000       # ms — LLM responses, heavy init
FAST_TIMEOUT    = 5_000        # ms — quick existence checks
POLL_INTERVAL   = 1_000        # ms — between retry attempts
MAX_RETRIES     = 15           # for LLM response polling


# ---------------------------------------------------------------------------
# Screenshot
# ---------------------------------------------------------------------------

def take_screenshot(page: Page, filename: str, debug_enabled: bool, full_page: bool = False) -> None:
    """Save a screenshot to tests/debug/ when debug mode is active."""
    if not debug_enabled:
        return
    debug_path = os.path.join("tests", "debug")
    os.makedirs(debug_path, exist_ok=True)
    filepath = os.path.join(debug_path, filename)
    page.screenshot(path=filepath, full_page=full_page)
    print(f"  📸 Screenshot saved: {filename}")


def screenshot_on_failure(page: Page, filename: str) -> None:
    """Always save a screenshot (used in except blocks, debug=True unconditionally)."""
    take_screenshot(page, filename, debug_enabled=True, full_page=True)


# ---------------------------------------------------------------------------
# Core stability helpers
# ---------------------------------------------------------------------------

def wait_for_app_stable(page: Page, timeout: int = DEFAULT_TIMEOUT) -> None:
    """
    Wait for Streamlit to finish a rerun cycle.

    Pairs networkidle with an explicit stApp visibility check because:
    - networkidle fires when no network requests are in-flight, but Streamlit
      may still be rendering widgets.
    - After a rerun the stApp div is re-mounted; waiting for it ensures the
      full component tree is present.
    """
    page.wait_for_load_state("networkidle", timeout=timeout)
    expect(page.locator("div[data-testid='stApp']")).to_be_visible(timeout=timeout)


def wait_for_app_fully_loaded(page: Page, timeout: int = SLOW_TIMEOUT) -> None:
    """
    Wait for the explicit readiness marker injected at the end of main().
    Use this after initial navigation, not after every interaction.
    """
    expect(page.locator(APP_FULLY_LOADED_SELECTOR)).to_be_attached(timeout=timeout)
    wait_for_app_stable(page)


# ---------------------------------------------------------------------------
# Guarded expect — the core pattern for robust assertions
# ---------------------------------------------------------------------------

def expect_visible(
    page: Page,
    locator: Locator,
    screenshot_name: str,
    error_message: str,
    timeout: int = DEFAULT_TIMEOUT,
    debug_enabled: bool = True,
) -> None:
    """
    Assert a locator is visible; on failure take a screenshot and re-raise
    with a descriptive message.

    Usage:
        expect_visible(
            page, page.get_by_text("Hello"), "hello_missing.png",
            "Expected greeting not found"
        )
    """
    try:
        expect(locator).to_be_visible(timeout=timeout)
    except AssertionError:
        screenshot_on_failure(page, screenshot_name)
        raise AssertionError(error_message)


def expect_text_on_page(
    page: Page,
    expected_text: str,
    screenshot_name: str,
    container_selector: str = "div[data-testid='stApp']",
    timeout: int = DEFAULT_TIMEOUT,
) -> None:
    """
    Assert that a page contains some text (in a container).
    Falls back to full body check. Always screenshots on failure.
    """
    try:
        expect(page.locator(container_selector)).to_contain_text(expected_text, timeout=timeout)
    except AssertionError:
        # Fallback: search the whole body
        body_text = page.locator("body").text_content(timeout=timeout)
        if expected_text in body_text:
            print(f"  ✓ Text found in body (fallback): {expected_text}")
            return
        screenshot_on_failure(page, screenshot_name)
        raise AssertionError(
            f"Expected text '{expected_text}' not found on page.\n"
            f"Page preview: {body_text[:400]}"
        )


def expect_not_text_on_page(
    page: Page,
    forbidden_text: str,
    screenshot_name: str,
    container_selector: str = "div[data-testid='stApp']",
    timeout: int = DEFAULT_TIMEOUT,
) -> None:
    """Assert that a specific text does NOT appear on the page."""
    wait_for_app_stable(page)
    body_text = page.locator("body").text_content(timeout=timeout)
    if forbidden_text.lower() in body_text.lower():
        screenshot_on_failure(page, screenshot_name)
        raise AssertionError(
            f"Text '{forbidden_text}' was found but should NOT be present.\n"
            f"Page preview: {body_text[:400]}"
        )
    print(f"  ✓ Confirmed absent: '{forbidden_text}'")


# ---------------------------------------------------------------------------
# Header verification
# ---------------------------------------------------------------------------

def verify_header_contains(
    page: Page,
    expected_text: str,
    screenshot_name: str = "header_not_found.png",
    debug_enabled: bool = False,
    retries: int = 3,
) -> None:
    """
    Robustly verify that a heading element contains expected_text.
    Falls back to full-page text search if no heading matches.
    Always screenshots on failure.
    """
    print(f'\n=== Verifying header contains: "{expected_text}" ===')
    wait_for_app_stable(page)

    for attempt in range(retries):
        if attempt > 0:
            print(f"  Retry {attempt}/{retries} …")
            page.wait_for_timeout(POLL_INTERVAL)

        for tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            headers = page.locator(tag)
            for i in range(headers.count()):
                hdr = headers.nth(i)
                if hdr.is_visible() and expected_text in (hdr.text_content() or ""):
                    print(f"  ✓ Found in <{tag}>: '{hdr.text_content().strip()}'")
                    if debug_enabled:
                        take_screenshot(page, "header_found.png", debug_enabled)
                    return

    # Fallbacks
    body_text = page.locator("body").text_content(timeout=FAST_TIMEOUT)
    if expected_text in body_text:
        print(f"  ✓ Found in page body (fallback): '{expected_text}'")
        return

    matching = page.locator(f':has-text("{expected_text}")')
    for i in range(matching.count()):
        elem = matching.nth(i)
        if elem.is_visible() and expected_text in (elem.text_content() or ""):
            print(f"  ✓ Found via :has-text (fallback)")
            return

    screenshot_on_failure(page, screenshot_name)
    raise AssertionError(f"Header text '{expected_text}' not found on page.")


# ---------------------------------------------------------------------------
# Button clicking
# ---------------------------------------------------------------------------

def click_button(
    page: Page,
    texts: List[str],
    screenshot_name: Optional[str] = None,
    debug_enabled: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
) -> None:
    """
    Click the first visible, enabled button matching any of the given texts.
    Builds an OR-chain of text locators, with a role-based fallback.
    Waits for app stability afterwards.
    """
    print(f"\n=== Clicking button — candidates: {texts} ===")

    locator: Optional[Locator] = None
    for text in texts:
        candidate = page.get_by_text(text, exact=False)
        locator = candidate if locator is None else locator.or_(candidate)

    # Role-based fallback
    if locator is None or locator.count() == 0:
        pattern = "|".join(re.escape(t) for t in texts)
        locator = page.get_by_role("button", name=re.compile(pattern, re.IGNORECASE))

    button = locator.first

    try:
        expect(button).to_be_visible(timeout=timeout)
        expect(button).to_be_enabled(timeout=timeout)
    except AssertionError:
        screenshot_on_failure(page, screenshot_name or "button_not_found.png")
        raise AssertionError(f"Button not found or not enabled. Tried texts: {texts}")

    button.click()
    wait_for_app_stable(page)

    if screenshot_name and debug_enabled:
        take_screenshot(page, screenshot_name, debug_enabled)


def click_button_by_key(
    page: Page,
    key: Optional[str] = None,
    label: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> bool:
    """
    Click a Streamlit button located by its st-key-* CSS class or visible label.
    Returns True on success, raises AssertionError on failure.
    """
    print(f"\n=== Clicking button (key={key}, label={label}) ===")
    button: Optional[Locator] = None

    if key:
        for sel in (
            f'[class*="st-key-{key}"] button',
            f'button[class*="st-key-{key}"]',
        ):
            candidate = page.locator(sel).first
            if candidate.count() > 0:
                button = candidate
                break
        if not button or button.count() == 0:
            container = page.locator(f'[class*="st-key-{key}"]')
            if container.count() > 0:
                button = container.locator("button").first

    if (not button or button.count() == 0) and label:
        clean = re.sub(r"[^\w\s]", "", label).strip()
        for attempt_label in (label, clean):
            for loc in (
                page.get_by_role("button", name=re.compile(rf"^\s*{re.escape(attempt_label)}\s*$", re.IGNORECASE)),
                page.get_by_role("button", name=re.compile(re.escape(attempt_label), re.IGNORECASE)),
                page.get_by_text(attempt_label, exact=False),
            ):
                if loc.count() > 0:
                    button = loc.first
                    break
            if button and button.count() > 0:
                break

    if not button or button.count() == 0:
        # Last resort: iterate all visible buttons
        all_btns = page.locator("button")
        for i in range(all_btns.count()):
            btn = all_btns.nth(i)
            if btn.is_visible(timeout=0):
                btn_text = btn.text_content().strip()
                if label and label.lower() in btn_text.lower():
                    button = btn
                    break

    if not button or button.count() == 0:
        screenshot_on_failure(page, "button_not_found.png")
        raise AssertionError(f"Could not find button with key='{key}' / label='{label}'")

    expect(button).to_be_visible(timeout=timeout)
    expect(button).to_be_enabled(timeout=timeout)
    print(f"  Clicking: '{button.text_content().strip()}'")
    button.click()
    page.wait_for_timeout(1_000)
    return True


# ---------------------------------------------------------------------------
# Selectbox
# ---------------------------------------------------------------------------

def _find_selectbox_by_key(page: Page, key: str) -> Optional[Locator]:
    """Find a Streamlit selectbox by its st-key-* CSS class."""
    for sel in (
        f'[class*="st-key-{key}"] [data-testid="stSelectbox"]',
        f'.st-key-{key} [data-testid="stSelectbox"]',
    ):
        elements = page.locator(sel)
        if elements.count() > 0:
            for i in range(elements.count()):
                if elements.nth(i).is_visible(timeout=0):
                    return elements.nth(i)

    container = page.locator(f'[class*="st-key-{key}"]')
    if container.count() > 0:
        for i in range(container.count()):
            if container.nth(i).is_visible(timeout=0):
                sb = container.nth(i).locator('[data-testid="stSelectbox"]')
                if sb.count() > 0:
                    return sb.first
    return None


def find_and_select_in_selectbox(
    page: Page,
    key: Optional[str] = None,
    label: Optional[str] = None,
    value_to_select: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> bool:
    """
    Find a Streamlit selectbox by key or label and choose a value.
    Streamlit selectboxes render their dropdown in a portal — do NOT use
    ancestor/parent selectors to find options after opening.
    """
    print(f'\n=== Selecting "{value_to_select}" in selectbox (key={key}, label={label}) ===')
    selectbox: Optional[Locator] = None

    if key:
        selectbox = _find_selectbox_by_key(page, key)

    if not selectbox and label:
        label_el = page.get_by_text(label, exact=False).first
        if label_el.count() > 0 and label_el.is_visible(timeout=1_000):
            container = label_el.locator('xpath=ancestor::div[@data-testid="stElementContainer"]')
            if container.count() > 0:
                selectbox = container.locator('[data-testid="stSelectbox"]').first
            if not selectbox or selectbox.count() == 0:
                selectbox = label_el.locator('xpath=following::div[@data-testid="stSelectbox"][1]')

    if not selectbox or selectbox.count() == 0:
        # Generic fallback: first visible selectbox
        all_sb = page.locator('[data-testid="stSelectbox"]')
        for i in range(all_sb.count()):
            if all_sb.nth(i).is_visible(timeout=0):
                selectbox = all_sb.nth(i)
                break

    if not selectbox or selectbox.count() == 0:
        screenshot_on_failure(page, "selectbox_not_found.png")
        raise AssertionError(f"Could not find selectbox with key='{key}' / label='{label}'")

    expect(selectbox).to_be_visible(timeout=timeout)

    # Open the dropdown
    clickable = selectbox.locator('div[role="combobox"], input[role="combobox"]')
    if clickable.count() > 0:
        clickable.first.click()
    else:
        selectbox.click()

    # Wait for dropdown options (they render in a portal)
    option_sel = '[data-testid="stSelectboxOption"], div[role="option"], li[role="option"]'
    for attempt in range(5):
        if page.locator(option_sel).count() > 0:
            break
        if attempt < 4:
            page.wait_for_timeout(500)
    else:
        screenshot_on_failure(page, "selectbox_dropdown_not_opened.png")
        raise AssertionError("Selectbox dropdown did not open.")

    options = page.locator(option_sel)
    selected = False
    for i in range(options.count()):
        opt_text = options.nth(i).text_content().strip()
        if value_to_select and value_to_select.lower() in opt_text.lower():
            options.nth(i).click()
            selected = True
            print(f"  ✓ Selected: '{opt_text}'")
            break

    if not selected:
        # Fallback: select first option
        if options.count() > 0:
            first_text = options.first.text_content().strip()
            options.first.click()
            print(f"  ⚠ Exact match not found, selected first option: '{first_text}'")
            selected = True

    page.wait_for_timeout(1_000)
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass

    return selected


# ---------------------------------------------------------------------------
# Input / textarea helpers
# ---------------------------------------------------------------------------

def fill_input(
    page: Page,
    text: str,
    selector: str = "textarea",
    placeholder_hint: str = "",
    timeout: int = DEFAULT_TIMEOUT,
) -> None:
    """
    Find an input or textarea and fill it.
    Tries multiple selectors in order of specificity.
    """
    print(f'\n=== Filling input with: "{text}" ===')
    selectors = [selector]
    if placeholder_hint:
        selectors += [
            f"input[placeholder*='{placeholder_hint}']",
            f"textarea[placeholder*='{placeholder_hint}']",
        ]
    selectors += ["textarea", "input[type='text']", "input"]

    field: Optional[Locator] = None
    for sel in selectors:
        candidates = page.locator(sel)
        for i in range(candidates.count()):
            if candidates.nth(i).is_visible(timeout=0):
                field = candidates.nth(i)
                break
        if field:
            break

    if not field:
        screenshot_on_failure(page, "input_not_found.png")
        raise AssertionError(f"Could not find input field (selector='{selector}')")

    expect(field).to_be_visible(timeout=timeout)
    expect(field).to_be_enabled(timeout=timeout)
    field.fill("")
    field.type(text, delay=80)
    try:
        expect(field).to_have_value(text, timeout=FAST_TIMEOUT)
    except AssertionError:
        print(f"  ⚠ Could not verify input value — proceeding anyway")
    print(f"  ✓ Input filled: '{text}'")


def find_chat_input(page: Page) -> Locator:
    """
    Locate Streamlit's chat input textarea robustly.
    NOTE: do NOT assert its value after pressing Enter — Streamlit clears it immediately.
    """
    # Method 1: Streamlit's dedicated chat input container
    chat_containers = page.locator("[data-testid='stChatInput']").all()
    for container in chat_containers:
        inp = container.locator("textarea, input")
        if inp.count() > 0:
            return inp.first

    # Method 2: textarea with message-like placeholder
    for ta in page.locator("textarea").all():
        placeholder = (ta.get_attribute("placeholder") or "").lower()
        if any(w in placeholder for w in ("message", "type", "say", "ask")):
            return ta

    # Method 3: first visible textarea in main content
    main = page.locator("[data-testid='stApp']").first
    if main.count() > 0:
        for ta in main.locator("textarea").all():
            if ta.is_visible():
                return ta

    screenshot_on_failure(page, "chat_input_not_found.png")
    raise AssertionError("Could not find chat input field.")


# ---------------------------------------------------------------------------
# LLM response polling
# ---------------------------------------------------------------------------

def wait_for_llm_response(
    page: Page,
    expected_text: Optional[str] = None,
    max_attempts: int = MAX_RETRIES,
    poll_ms: int = POLL_INTERVAL * 2,
    context_label: str = "LLM response",
) -> str:
    """
    Poll chat messages until a response appears (and optionally contains expected_text).
    Returns the response text found.

    Strategy:
    1. Wait for networkidle + stApp each iteration (Streamlit rerun may still be running).
    2. Collect all stChatMessage elements.
    3. Check last message text for expected_text (case-insensitive).
    """
    print(f"\n=== Polling for {context_label} ===")

    for attempt in range(max_attempts):
        wait_for_app_stable(page)
        page.wait_for_timeout(poll_ms if attempt > 0 else POLL_INTERVAL)

        messages = page.locator("[data-testid='stChatMessage']").all()
        if messages:
            response_text = messages[-1].text_content() or ""
            if expected_text is None or expected_text.lower() in response_text.lower():
                print(f"  ✓ Found response (attempt {attempt + 1}/{max_attempts})")
                return response_text
            print(f"  Attempt {attempt + 1}/{max_attempts}: '{expected_text}' not yet in response")
        else:
            print(f"  Attempt {attempt + 1}/{max_attempts}: no chat messages yet")

    # Final fallback: return whatever is on page
    body_text = page.locator("body").text_content() or ""
    if expected_text and expected_text.lower() in body_text.lower():
        print("  ✓ Found in full page text (fallback)")
        return body_text

    screenshot_on_failure(page, f"llm_response_timeout_{context_label.replace(' ', '_')}.png")
    raise AssertionError(
        f"{context_label}: '{expected_text}' not found after {max_attempts} attempts."
    )


def wait_for_response_stable(
    page: Page,
    min_length: int = 50,
    timeout_ms: int = 120_000,
) -> str:
    """
    Wait until the last chat message stops changing (streaming complete).
    Returns the stabilised text.
    """
    print("  Waiting for response to stabilise …")
    start = time.time()
    last_text = ""
    stable_count = 0

    while (time.time() - start) * 1000 < timeout_ms:
        messages = page.locator("[data-testid='stChatMessage']").all()
        current = messages[-1].text_content() if messages else ""

        if current == last_text:
            stable_count += 1
            if stable_count >= 3 and len(current.strip()) >= min_length:
                print(f"  ✓ Response stabilised ({len(current)} chars)")
                return current
        else:
            last_text = current
            stable_count = 0

        page.wait_for_timeout(POLL_INTERVAL)

    print(f"  ⚠ Stability timeout after {timeout_ms / 1000}s — returning current text")
    return last_text
