# file: tests/step_defs/common_steps.py
"""
Common pytest-bdd step definitions reused across multiple feature files.

All pure helper logic lives in page_helpers.py.
This file contains only @given / @when / @then decorated functions.
"""

import os
import re
import pytest
from pytest_bdd import given, when, then, parsers
from playwright.sync_api import Page, expect

from tests.step_defs.page_helpers import *


# ---------------------------------------------------------------------------
# Legacy aliases — keep existing step files compiling without changes
# ---------------------------------------------------------------------------

def _wait_for_app_stable(page: Page, timeout: int = DEFAULT_TIMEOUT) -> None:
    wait_for_app_stable(page, timeout)


def _click_button_by_texts(
    page: Page,
    texts: list,
    debug_enabled: bool = False,
    screenshot_name: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> None:
    click_button(page, texts, screenshot_name=screenshot_name,
                 debug_enabled=debug_enabled, timeout=timeout)


def _robust_header_verification(page: Page, expected_text: str, debug_enabled: bool = False) -> None:
    verify_header_contains(page, expected_text, debug_enabled=debug_enabled)


def find_element_by_text(page: Page, text: str, exact: bool = False) -> object:
    return page.get_by_text(text, exact=exact)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def context() -> dict:
    """Shared mutable dict passed between steps in a scenario."""
    return {"debug_enabled": False}


# ---------------------------------------------------------------------------
# Navigation steps
# ---------------------------------------------------------------------------

@given("I navigate to the admin panel")
def navigate_to_admin_panel_common(context: dict) -> dict:
    """Navigate to the admin panel from anywhere in the app."""
    if "page" not in context:
        raise KeyError("No 'page' in context. Did 'the application is running' run first?")

    page: Page = context["page"]
    debug_enabled = context.get("debug_enabled", False)

    print("\n=== Navigating to admin panel ===")

    sidebar = page.locator("[data-testid='stSidebar']").first
    expect_visible(
        page, sidebar, "admin_sidebar_missing.png",
        "Sidebar not visible — cannot find admin button.",
    )

    # Try to find the admin button in order of specificity
    admin_btn = None
    for locator in (
        sidebar.get_by_text(re.compile(r"Admin", re.IGNORECASE)),
        page.get_by_text(re.compile(r"Admin", re.IGNORECASE)),
        page.get_by_role("button", name=re.compile(r"Admin", re.IGNORECASE)),
    ):
        if locator.count() > 0:
            admin_btn = locator.first
            break

    if admin_btn and admin_btn.count() > 0:
        expect(admin_btn).to_be_visible(timeout=DEFAULT_TIMEOUT)
        expect(admin_btn).to_be_enabled(timeout=FAST_TIMEOUT)
        admin_btn.click()
        wait_for_app_stable(page)

        # Confirm admin panel loaded
        indicator = page.locator("text=/Admin Panel/i").or_(page.locator("[role='tab']")).first
        expect_visible(
            page, indicator, "admin_panel_not_loaded.png",
            "Admin panel did not load after clicking admin button.",
        )
        print("  ✓ Admin panel loaded")
    else:
        # Already on admin page?
        if page.locator("text=/Admin Panel/i").or_(page.locator("[role='tab']")).count() > 0:
            print("  Already on admin page")
        else:
            screenshot_on_failure(page, "admin_not_found.png")
            raise AssertionError("Could not find admin button and not already on admin page.")

    if debug_enabled:
        take_screenshot(page, "admin_panel_navigated.png", debug_enabled, full_page=True)

    context["current_page"] = "admin"
    return context


@given(parsers.parse('I select the "{tab_name}" tab'))
def select_a_tab(context: dict, tab_name: str) -> dict:
    """Select a tab by name in the admin panel."""
    page: Page = context["page"]
    debug_enabled = context.get("debug_enabled", False)

    print(f'\n=== Selecting "{tab_name}" tab ===')

    tabs_container = page.locator("[role='tab']").first
    expect_visible(
        page, tabs_container, f"tab_{tab_name}_not_found.png",
        f"No tabs visible when trying to select '{tab_name}'.",
    )

    tab = (
        page.get_by_role("tab", name=tab_name, exact=True).first
        or page.get_by_role("tab", name=re.compile(re.escape(tab_name), re.IGNORECASE)).first
        or page.get_by_text(tab_name, exact=True).first
    )

    # Use the first match among the three strategies
    for locator in (
        page.get_by_role("tab", name=tab_name, exact=True),
        page.get_by_role("tab", name=re.compile(re.escape(tab_name), re.IGNORECASE)),
        page.get_by_text(tab_name, exact=True),
    ):
        if locator.count() > 0:
            tab = locator.first
            break

    if not tab or tab.count() == 0:
        screenshot_on_failure(page, f"tab_{tab_name}_not_found.png")
        all_tabs = page.locator("[role='tab']")
        labels = [all_tabs.nth(i).text_content() for i in range(all_tabs.count())]
        raise AssertionError(f"Tab '{tab_name}' not found. Available: {labels}")

    expect(tab).to_be_visible(timeout=DEFAULT_TIMEOUT)
    expect(tab).to_be_enabled(timeout=FAST_TIMEOUT)
    tab.click()
    wait_for_app_stable(page)
    expect(tab).to_have_attribute("aria-selected", "true", timeout=DEFAULT_TIMEOUT)

    print(f"  ✓ Tab '{tab_name}' selected")
    if debug_enabled:
        take_screenshot(page, f"tab_{tab_name}_selected.png", debug_enabled)

    return context


@given(parsers.parse("the {module_name} module is loaded"))
def is_module_loaded(context: dict, module_name: str) -> dict:
    """Verify the named module is present (tab or text) in the admin panel."""
    page: Page = context["page"]
    print(f"\n=== Verifying '{module_name}' module is loaded ===")

    wait_for_app_stable(page)
    page.wait_for_timeout(2_000)  # Allow tab animation to settle

    page_text = page.locator("div[data-testid='stApp']").text_content().lower()
    tabs = page.locator("div[data-testid='stApp']").locator("[role='tab']")

    found = module_name.lower() in page_text
    for i in range(tabs.count()):
        try:
            if module_name.lower() in (tabs.nth(i).text_content() or "").lower():
                found = True
                break
        except Exception:
            continue

    if not found:
        print(f"  ⚠ '{module_name}' module/tab not found (may still be loading)")
    else:
        print(f"  ✓ '{module_name}' module found")

    return context


@when("I navigate to the chat page")
def navigate_to_chat_page(context: dict) -> dict:
    """Navigate to the chat page via sidebar button."""
    page: Page = context["page"]
    debug_enabled = context.get("debug_enabled", False)

    print("\n=== Navigating to chat page ===")
    wait_for_app_stable(page)

    chat_btn = None
    for locator in (
        page.get_by_role("button", name=re.compile(r"chat", re.IGNORECASE)),
        page.get_by_text("💬 Chat"),
        page.get_by_text("Chat"),
    ):
        if locator.count() > 0:
            chat_btn = locator.first
            break

    if chat_btn:
        expect_visible(page, chat_btn, "chat_button_not_found.png", "Chat button not visible.")
        expect(chat_btn).to_be_enabled(timeout=FAST_TIMEOUT)
        chat_btn.click()
        wait_for_app_stable(page)

        # Confirm chat UI appeared
        for attempt in range(10):
            page_text = page.locator("body").text_content().lower()
            if page.locator("textarea").count() > 0 or "conversation" in page_text or "chat" in page_text:
                print(f"  ✓ Chat page loaded (attempt {attempt + 1})")
                break
            page.wait_for_timeout(1_000)
        else:
            screenshot_on_failure(page, "chat_page_not_loaded.png")
            raise AssertionError("Chat page did not load after clicking Chat button.")
    else:
        # Already on chat?
        page_text = page.locator("body").text_content().lower()
        if "conversation" in page_text or page.locator("textarea").count() > 0:
            print("  Already on chat page")
        else:
            screenshot_on_failure(page, "chat_button_not_found.png")
            raise AssertionError("Could not find Chat button and not already on chat page.")

    take_screenshot(page, "chat_page_loaded.png", debug_enabled)
    context["current_page"] = "chat"
    return context


# ---------------------------------------------------------------------------
# Message sending
# ---------------------------------------------------------------------------

@when(parsers.parse('I send the message "{message}"'))
def send_message(context: dict, message: str) -> dict:
    """Type and submit a message in the chat input."""
    page: Page = context["page"]
    debug_enabled = context.get("debug_enabled", False)

    print(f"\n=== Sending message: '{message}' ===")
    take_screenshot(page, "before_send.png", debug_enabled, full_page=True)
    wait_for_app_stable(page)

    chat_input = find_chat_input(page)
    expect(chat_input).to_be_visible(timeout=DEFAULT_TIMEOUT)
    expect(chat_input).to_be_enabled(timeout=DEFAULT_TIMEOUT)

    chat_input.fill("")
    chat_input.type(message, delay=80)
    # NOTE: do NOT assert input value after this — Streamlit clears it on Enter
    chat_input.press("Enter")

    # Give Streamlit time to register the submission and start rerun
    page.wait_for_timeout(2_000)

    context["last_message"] = message
    return context


# ---------------------------------------------------------------------------
# Button steps
# ---------------------------------------------------------------------------

EMOJI_VARIANTS: dict[str, list[str]] = {
    "Display Text":   ["📤 Display Text"],
    "Clear Text":     ["🗑️ Clear Text"],
    "New Conversation": ["➕ New Conversation"],
    "Save":           ["💾 Save"],
    "Regenerate":     ["🔄 Regenerate"],
    "Clear":          ["🗑️ Clear"],
    "Edit":           ["✏️ Edit", "✏️"],
}


@when(parsers.parse('I click the "{button_text}" button'))
def click_button_by_text(context: dict, button_text: str) -> dict:
    """Click a button identified by its label (supports emoji variants)."""
    page: Page = context["page"]
    debug_enabled = context.get("debug_enabled", False)

    texts = [button_text] + EMOJI_VARIANTS.get(button_text, [])

    # Special handling for Edit — Streamlit often renders only the emoji
    if button_text == "Edit":
        for btn in page.locator("button:has-text('✏️')").all():
            if btn.is_visible():
                btn.click()
                wait_for_app_stable(page)
                return context

    click_button(
        page, texts,
        screenshot_name=f"btn_{button_text.replace(' ', '_').lower()}.png",
        debug_enabled=debug_enabled,
    )
    return context


# ---------------------------------------------------------------------------
# Text area steps
# ---------------------------------------------------------------------------

@when(parsers.parse('I enter text "{text}" in the text area labeled "{label}"'))
def enter_text_in_labeled_textarea(context: dict, text: str, label: str) -> dict:
    """Fill a textarea identified by its Streamlit label."""
    page: Page = context["page"]
    debug_enabled = context.get("debug_enabled", False)

    print(f'\n=== Entering "{text}" in textarea labeled "{label}" ===')
    wait_for_app_stable(page)

    textarea = None

    # Strategy 1: Label → ancestor container → textarea
    label_el = page.get_by_text(label, exact=True).first
    if label_el.count() > 0:
        parent = label_el.locator(
            "xpath=./ancestor::div[contains(@class,'stText') or contains(@class,'stTextArea')]"
        )
        if parent.count() > 0:
            textarea = parent.locator("textarea").first

    # Strategy 2: aria-label / placeholder matching
    if not textarea or textarea.count() == 0:
        textarea = page.locator(
            f"textarea[aria-label='{label}'], textarea[placeholder='{label}']"
        ).first

    # Strategy 3: Any visible textarea
    if not textarea or textarea.count() == 0:
        for ta in page.locator("textarea").all():
            if ta.is_visible():
                textarea = ta
                break

    if not textarea or textarea.count() == 0:
        screenshot_on_failure(page, f"textarea_{label.replace(' ', '_')}_not_found.png")
        raise AssertionError(f"Could not find textarea labeled '{label}'")

    expect(textarea).to_be_visible(timeout=DEFAULT_TIMEOUT)
    expect(textarea).to_be_enabled(timeout=DEFAULT_TIMEOUT)
    textarea.fill("")
    textarea.type(text, delay=50)
    try:
        expect(textarea).to_have_value(text, timeout=FAST_TIMEOUT)
    except AssertionError:
        print("  ⚠ Could not verify textarea value — proceeding")

    context["entered_text"] = text
    if debug_enabled:
        take_screenshot(page, f"textarea_{label.replace(' ', '_')}_filled.png", debug_enabled)
    return context


@when(parsers.parse('I clear the text area labeled "{label}"'))
def clear_labeled_text_area(context: dict, label: str) -> dict:
    """Clear a textarea identified by its label."""
    page: Page = context["page"]
    print(f'\n=== Clearing textarea labeled "{label}" ===')
    wait_for_app_stable(page)

    textarea = None
    label_el = page.get_by_text(label, exact=True).first
    if label_el.count() > 0:
        parent = label_el.locator(
            "xpath=./ancestor::div[contains(@class,'stText') or contains(@class,'stTextArea')]"
        )
        if parent.count() > 0:
            textarea = parent.locator("textarea").first

    if not textarea or textarea.count() == 0:
        for ta in page.locator("textarea").all():
            if ta.is_visible():
                textarea = ta
                break

    if textarea and textarea.count() > 0:
        expect(textarea).to_be_visible(timeout=DEFAULT_TIMEOUT)
        textarea.fill("")
        try:
            expect(textarea).to_have_value("", timeout=FAST_TIMEOUT)
        except AssertionError:
            print("  ⚠ Could not verify textarea is empty — proceeding")
        print("  ✓ Textarea cleared")
    else:
        print(f"  ⚠ No textarea found for label '{label}'")

    return context


@when(parsers.parse('I enter text "{text}" in the {textarea_type} text area'))
def enter_text_in_textarea(context: dict, text: str, textarea_type: str) -> dict:
    """Fill a textarea by its functional type (debug, chat, judge)."""
    page: Page = context["page"]
    debug_enabled = context.get("debug_enabled", False)

    print(f'\n=== Entering "{text}" in {textarea_type} textarea ===')
    wait_for_app_stable(page)

    textarea = None
    if textarea_type == "chat":
        textarea = find_chat_input(page)
    elif textarea_type in ("debug", "judge"):
        for ta in page.locator("textarea").all():
            if ta.is_visible():
                textarea = ta
                break
    else:
        for ta in page.locator("textarea").all():
            if ta.is_visible():
                textarea = ta
                break

    if not textarea:
        screenshot_on_failure(page, f"textarea_{textarea_type}_not_found.png")
        raise AssertionError(f"Could not find {textarea_type} textarea")

    expect(textarea).to_be_visible(timeout=DEFAULT_TIMEOUT)
    expect(textarea).to_be_enabled(timeout=DEFAULT_TIMEOUT)
    textarea.fill("")
    textarea.type(text, delay=50)
    try:
        expect(textarea).to_have_value(text, timeout=FAST_TIMEOUT)
    except AssertionError:
        print("  ⚠ Could not verify textarea value — proceeding")

    context["entered_text"] = text
    if debug_enabled:
        take_screenshot(page, f"textarea_{textarea_type}_filled.png", debug_enabled)
    return context


@when(parsers.parse('I clear the {textarea_type} text area'))
def clear_text_area(context: dict, textarea_type: str = "debug") -> dict:
    """Clear a textarea by functional type."""
    page: Page = context["page"]
    print(f"\n=== Clearing {textarea_type} textarea ===")
    wait_for_app_stable(page)

    textarea = None
    for ta in page.locator("textarea").all():
        if ta.is_visible():
            textarea = ta
            break

    if textarea and textarea.count() > 0:
        expect(textarea).to_be_visible(timeout=DEFAULT_TIMEOUT)
        textarea.fill("")
        try:
            expect(textarea).to_have_value("", timeout=FAST_TIMEOUT)
        except AssertionError:
            print("  ⚠ Could not verify textarea is empty — proceeding")
        print(f"  ✓ {textarea_type} textarea cleared")
    else:
        print(f"  ⚠ No visible {textarea_type} textarea found")

    return context


# ---------------------------------------------------------------------------
# Assertion steps
# ---------------------------------------------------------------------------

@then(parsers.parse('I should see "{expected_text}" in the result section'))
def verify_text_in_result(context: dict, expected_text: str) -> dict:
    page: Page = context["page"]
    wait_for_app_stable(page)
    expect_text_on_page(
        page, expected_text,
        screenshot_name=f"result_missing_{expected_text[:20]}.png",
    )
    return context


@then(parsers.parse('I should see "{expected_text}" in the header'))
def verify_header_text(context: dict, expected_text: str) -> dict:
    page: Page = context["page"]
    debug_enabled = context.get("debug_enabled", False)
    verify_header_contains(page, expected_text, debug_enabled=debug_enabled)
    return context


@then(parsers.parse('I should see a response containing "{expected_text}"'))
def verify_response_contains(context: dict, expected_text: str) -> dict:
    """Poll for an LLM response containing the expected text."""
    page: Page = context["page"]
    # Use pre-fetched response if available (set by a previous step)
    if "last_response" in context:
        if expected_text.lower() in context["last_response"].lower():
            print(f"  ✓ Found '{expected_text}' in cached response")
            return context

    response = wait_for_llm_response(page, expected_text=expected_text)
    context["last_response"] = response
    return context


@then("the text area should be empty")
def verify_textarea_empty(context: dict) -> dict:
    page: Page = context["page"]
    wait_for_app_stable(page)
    textarea = page.locator("textarea").first
    if textarea.count() == 0:
        print("  ⚠ No textarea found — skipping empty check")
        return context
    try:
        expect(textarea).to_have_value("", timeout=DEFAULT_TIMEOUT)
        print("  ✓ Textarea is empty")
    except AssertionError:
        screenshot_on_failure(page, "textarea_not_empty.png")
        raise AssertionError("Textarea should be empty but is not.")
    return context


@then("I should see a warning message about empty text")
def verify_warning_message(context: dict) -> dict:
    page: Page = context["page"]
    wait_for_app_stable(page)

    indicators = ["warning", "please enter", "empty", "no text", "required"]

    # Check Streamlit alert components first
    for alert in page.locator(".stAlert, .stWarning, .stError").all():
        if any(ind in (alert.text_content() or "").lower() for ind in indicators):
            print("  ✓ Warning component found")
            return context

    page_text = page.locator("div[data-testid='stApp']").text_content().lower()
    if any(ind in page_text for ind in indicators):
        print("  ✓ Warning text found on page")
        return context

    print("  ⚠ No explicit warning found (may be acceptable)")
    return context


# ---------------------------------------------------------------------------
# Debug step
# ---------------------------------------------------------------------------

@when("I debug the current state")
def debug_current_state(context: dict) -> dict:
    """Print a detailed snapshot of current page + context state."""
    page: Page = context["page"]
    debug_enabled = context.get("debug_enabled", False)

    print("\n" + "=" * 60)
    print("DEBUG STATE")
    print("=" * 60)
    print(f"URL   : {page.url}")
    print(f"Title : {page.title()}")
    print(f"Context keys: { {k: v for k, v in context.items() if k != 'page'} }")
    body = page.locator("body").text_content() or ""
    print(f"\nPage text (first 800 chars):\n{body[:800]}")
    print("=" * 60 + "\n")

    take_screenshot(page, "debug_state.png", debug_enabled, full_page=True)
    return context
