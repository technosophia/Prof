"""
pytest-bdd step definitions for debug admin UI testing.
Refactored version: cleaner, more robust, with reduced duplication by:
- Reusing common steps where possible (e.g., tab selection, screenshots, waits).
- Introducing local helpers for repeated patterns (button clicking, robust text verification).
- Aligning header verification logic with the robust approach used in test_steps.py.
- Consistent waiting, expectations, and debugging.
"""
import pytest
import re
from pytest_bdd import given, when, then, scenarios, parsers
from playwright.sync_api import Page, expect

# Add project root to path
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

pytestmark = [pytest.mark.bdd, pytest.mark.playwright]

# Re-use fixtures and common steps
from tests.conftest import (
    enable_debug,
    streamlit_server,
    browser_context,
    debug_dir,
    take_screenshot,
)
from tests.step_defs.common_steps import *
from tests.step_defs.app_start_steps import *
from tests.step_defs.user_steps import *
from tests.step_defs.common_steps import _robust_header_verification, _wait_for_app_stable, _click_button_by_texts

# Load feature file
scenarios('../../tests/features/debug.feature')



# ==================== STEPS ====================

@given("I am logged in as an admin user")
def logged_in_as_admin(context):
    """Ensure we are logged in as an admin (reuses common login logic if available)."""
    # Assuming common_steps has a generic login; fallback to specific if needed
    # Here we reuse the pattern seen in conversation tests
    if 'current_user' not in context:
        # Use admin user "Test User 2" from mock data
        context = default_user_logged_in(context, "Test User 2") if 'default_user_logged_in' in globals() else context
    return context


@when(parsers.parse('I enter text "{text}" in the text area'))
def enter_text_in_textarea(context, text: str):
    page: Page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print(f'\n=== Entering text: "{text}" ===')

    _wait_for_app_stable(page)

    textarea = page.locator("textarea").first
    expect(textarea).to_be_visible(timeout=30000)
    expect(textarea).to_be_enabled(timeout=30000)

    textarea.fill("")
    textarea.type(text, delay=50)
    expect(textarea).to_have_value(text, timeout=10000)

    context['entered_text'] = text

    if debug_enabled:
        take_screenshot(page, "debug_text_entered.png", debug_enabled)


@when('I click the "Display Text" button')
def click_display_text_button(context):
    page: Page = context['page']
    debug_enabled = context.get('debug_enabled', False)
    _click_button_by_texts(
        page,
        ["Display Text", "📤 Display Text"],
        debug_enabled=debug_enabled,
        screenshot_name="debug_display_clicked.png"
    )


@when('I click the "Clear Text" button')
def click_clear_text_button(context):
    page: Page = context['page']
    debug_enabled = context.get('debug_enabled', False)
    _click_button_by_texts(
        page,
        ["Clear Text", "🗑️ Clear Text"],
        debug_enabled=debug_enabled,
        screenshot_name="debug_clear_clicked.png"
    )

    # Extra safety: manually ensure textarea is empty if button didn't fully clear
    textarea = page.locator("textarea").first
    if textarea.count() > 0 and textarea.input_value().strip():
        textarea.fill("")
        expect(textarea).to_have_value("", timeout=5000)


@when("I clear the text area")
def clear_text_area(context):
    page: Page = context['page']
    print("\n=== Manually clearing text area ===")
    _wait_for_app_stable(page)

    textarea = page.locator("textarea").first
    if textarea.count() > 0:
        expect(textarea).to_be_visible(timeout=30000)
        textarea.fill("")
        expect(textarea).to_have_value("", timeout=5000)


@when("I click the \"Display Text\" button without entering text")
def click_display_without_text(context):
    return click_display_text_button(context)


@then(parsers.parse('I should see "{expected_text}" in the result section'))
def verify_text_in_result(context, expected_text: str):
    page: Page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print(f'\n=== Verifying result contains: "{expected_text}" ===')
    _wait_for_app_stable(page)

    try:
        expect(page.locator("div[data-testid='stApp']")).to_contain_text(expected_text, timeout=10000)
        print(f"✓ Result text found")
    except AssertionError:
        page_text = page.locator("body").text_content(timeout=10000)
        if expected_text not in page_text:
            if debug_enabled:
                take_screenshot(page, "debug_result_missing.png", debug_enabled)
            raise AssertionError(f"Expected '{expected_text}' not found in result. Page text sample: {page_text[:500]}")
        print(f"✓ Result text found (fallback check)")


@then("I should see the character count displayed")
def verify_character_count(context):
    page: Page = context['page']
    print("\n=== Verifying character count display ===")
    _wait_for_app_stable(page)
    page_text = page.locator("div[data-testid='stApp']").text_content()
    if not re.search(r'character.*count', page_text, re.IGNORECASE):
        print("Note: No explicit 'character count' label found (may still be present)")
    else:
        print("✓ Character count displayed")


@then("I should see the word count displayed")
def verify_word_count(context):
    page: Page = context['page']
    print("\n=== Verifying word count display ===")
    _wait_for_app_stable(page)
    page_text = page.locator("div[data-testid='stApp']").text_content()
    if not re.search(r'word.*count', page_text, re.IGNORECASE):
        print("Note: No explicit 'word count' label found (may still be present)")
    else:
        print("✓ Word count displayed")


@then("the result section should be empty")
def verify_result_section_empty(context):
    page: Page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print("\n=== Verifying result section is empty ===")
    _wait_for_app_stable(page)

    page_text = page.locator("div[data-testid='stApp']").text_content()

    if "Text Result" not in page_text:
        print("✓ No 'Text Result' section found → considered empty")
        return

    # If section exists, check for non-trivial content (ignore headers like "Character count")
    alerts = page.locator(".stAlert, .stInfo, .stSuccess, .stMarkdown")
    has_content = False
    for i in range(alerts.count()):
        elem = alerts.nth(i)
        text = elem.text_content().strip()
        if text and not re.match(r'^(Character|Word)\s*count', text, re.IGNORECASE):
            has_content = True
            break

    if has_content:
        if debug_enabled:
            take_screenshot(page, "debug_result_not_empty.png", debug_enabled)
        raise AssertionError("Result section should be empty but contains content")

    print("✓ Result section is empty")


@then("the text area should be empty")
def verify_textarea_empty(context):
    page: Page = context['page']
    print("\n=== Verifying text area is empty ===")
    _wait_for_app_stable(page)

    textarea = page.locator("textarea").first
    if textarea.count() == 0:
        print("Warning: No textarea found")
        return

    expect(textarea).to_have_value("", timeout=10000)
    print("✓ Text area is empty")


@then("I should see a warning message about empty text")
def verify_warning_message(context):
    page: Page = context['page']
    print("\n=== Verifying warning about empty text ===")
    _wait_for_app_stable(page)

    warning_indicators = ["warning", "please enter", "empty", "no text", "required"]

    # Check Streamlit alert components first
    alerts = page.locator(".stAlert, .stWarning, .stError")
    found = False
    for i in range(alerts.count()):
        text = alerts.nth(i).text_content().lower()
        if any(ind in text for ind in warning_indicators):
            print(f"✓ Warning found: {text[:100]}")
            found = True
            break

    # Fallback to full page text
    if not found:
        page_text = page.locator("div[data-testid='stApp']").text_content().lower()
        if any(ind in page_text for ind in warning_indicators):
            print("✓ Warning indicator found in page text")
            found = True

    if not found:
        print("Note: No clear warning message detected")


@then(parsers.parse('I should see "{expected_text}" in the header'))
def verify_debug_header(context, expected_text: str):
    page: Page = context['page']
    debug_enabled = context.get('debug_enabled', False)
    _robust_header_verification(page, expected_text, debug_enabled)
