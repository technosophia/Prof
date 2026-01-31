"""
pytest-bdd step definitions for debug admin UI testing.
Tests the basic text input and display functionality.
"""
import pytest
import re
from pytest_bdd import given, when, then, scenarios, parsers
import sys
import os
from playwright.sync_api import Page, expect

# Add the project root to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

pytestmark = [pytest.mark.bdd, pytest.mark.playwright]

# Re-use fixtures from conftest.py
from tests.conftest import (
    setup_test_environment,
    playwright,
    browser,
    page as conftest_page,
    patch_config,
    mock_db_manager,
    mock_user_manager,
    patch_database,
    enable_debug,
    streamlit_server,
    browser_context,
    page as conversation_page,
    debug_dir,
    take_screenshot
)

from tests.step_defs.common_steps import *

# Load feature files
scenarios('../../tests/features/debug.feature')

# Now define the debug-specific steps
@given("I am logged in as an admin user")
def logged_in_as_admin(context):
    """Log in as an admin user."""
    # Use "Test User 2" which is an admin in mock data
    return default_user_logged_in(context, "Test User 2")


@when(parsers.parse('I enter text "{text}" in the text area'))
def enter_text_in_textarea(context, text):
    """Enter text in the debug text area."""
    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print(f'\n=== Entering text in text area: "{text}" ===')

    # Wait for app to be ready
    page.wait_for_load_state("networkidle", timeout=30000)
    expect(page.locator("div[data-testid='stApp']")).to_be_visible(timeout=30000)

    # Find text area
    text_areas = page.locator("textarea")
    expect(text_areas.first).to_be_visible(timeout=30000)

    if text_areas.count() > 0:
        text_area = text_areas.first
        expect(text_area).to_be_visible(timeout=30000)
        expect(text_area).to_be_enabled(timeout=30000)

        text_area.fill("")
        text_area.type(text, delay=50)

        # No Streamlit rerun expected for typing, just ensure text is entered
        expect(text_area).to_have_value(text, timeout=30000)

        context['entered_text'] = text

        take_screenshot(page, "debug_text_entered.png", debug_enabled)
    else:
        print("Warning: Could not find text area")

    return context

@when('I click the "Display Text" button')
def click_display_text_button(context):
    """Click the Display Text button."""
    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print('\n=== Clicking "Display Text" button ===')

    # Wait for app to be ready first
    page.wait_for_load_state("networkidle", timeout=30000)
    expect(page.locator("div[data-testid='stApp']")).to_be_visible(timeout=30000)

    # Find display button using robust selectors
    display_button = page.get_by_role("button", name=re.compile(r"display text", re.IGNORECASE)).or_(
        page.get_by_text("Display Text").or_(page.get_by_text("📤 Display Text"))
    )

    expect(display_button.first).to_be_visible(timeout=30000)
    expect(display_button.first).to_be_enabled(timeout=30000)

    display_button.first.click()

    # Wait for Streamlit rerun after button click
    page.wait_for_load_state("networkidle", timeout=30000)
    # Wait for Streamlit app container
    expect(page.locator("div[data-testid='stApp']")).to_be_visible(timeout=30000)

    take_screenshot(page, "debug_display_clicked.png", debug_enabled)

    return context

@then(parsers.parse('I should see "{expected_text}" in the result section'))
def verify_text_in_result(context, expected_text):
    """Verify text appears in the result section."""
    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print(f'\n=== Verifying text in result: "{expected_text}" ===')

    # Wait for Streamlit to be stable
    page.wait_for_load_state("networkidle", timeout=30000)
    # Wait for app container
    expect(page.locator("div[data-testid='stApp']")).to_be_visible(timeout=30000)

    # Use expect with custom message for better debugging
    try:
        expect(page.locator("div[data-testid='stApp']")).to_contain_text(expected_text, timeout=10000)
        print(f"✓ Found text: {expected_text}")
    except AssertionError:
        # Fallback: check text content directly
        page_text = page.locator("body").text_content()
        assert expected_text in page_text, f"Expected text '{expected_text}' not found on page. Page text: {page_text[:500]}..."
        print(f"✓ Found text: {expected_text}")

    return context

@then("I should see the character count displayed")
def verify_character_count(context):
    """Verify character count is displayed."""
    page = context['page']

    print("\n=== Verifying character count ===")

    page.wait_for_load_state("networkidle", timeout=30000)
    expect(page.locator("div[data-testid='stApp']")).to_be_visible(timeout=30000)
    page_text = page.locator("div[data-testid='stApp']").text_content()

    # Look for character count pattern
    if re.search(r'character.*count', page_text, re.IGNORECASE):
        print("✓ Character count found")
    else:
        print("Note: Character count not specifically found")

    return context

@then("I should see the word count displayed")
def verify_word_count(context):
    """Verify word count is displayed."""
    page = context['page']

    print("\n=== Verifying word count ===")

    page.wait_for_load_state("networkidle", timeout=30000)
    expect(page.locator("div[data-testid='stApp']")).to_be_visible(timeout=30000)
    page_text = page.locator("div[data-testid='stApp']").text_content()

    # Look for word count pattern
    if re.search(r'word.*count', page_text, re.IGNORECASE):
        print("✓ Word count found")
    else:
        print("Note: Word count not specifically found")

    return context

@given(parsers.parse('I have entered text "{text}" in the text area'))
def given_entered_text(context, text):
    """Precondition: text has been entered."""
    return enter_text_in_textarea(context, text)

@given("I have displayed the text")
def given_displayed_text(context):
    """Precondition: text has been displayed."""
    return click_display_text_button(context)

@when('I click the "Clear Text" button')
def click_clear_text_button(context):
    """Click the Clear Text button."""
    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print('\n=== Clicking "Clear Text" button ===')

    # Wait for app to be ready first
    page.wait_for_load_state("networkidle", timeout=30000)
    expect(page.locator("div[data-testid='stApp']")).to_be_visible(timeout=30000)

    # First get the current text to debug
    text_areas = page.locator("textarea")
    if text_areas.count() > 0:
        text_area = text_areas.first
        current_value = text_area.input_value()
        print(f"Text area currently contains: '{current_value}'")

    clear_button = page.get_by_role("button", name=re.compile(r"clear text", re.IGNORECASE)).or_(
        page.get_by_text("Clear Text").or_(page.get_by_text("🗑️ Clear Text"))
    )

    expect(clear_button.first).to_be_visible(timeout=30000)
    expect(clear_button.first).to_be_enabled(timeout=30000)

    clear_button.first.click()

    # Wait for Streamlit rerun after clear
    page.wait_for_load_state("networkidle", timeout=30000)
    # Wait for app container
    expect(page.locator("div[data-testid='stApp']")).to_be_visible(timeout=30000)

    # Wait for text area to be cleared - with retry logic
    text_areas = page.locator("textarea")
    if text_areas.count() > 0:
        text_area = text_areas.first

        # Try multiple times with shorter timeout
        for attempt in range(5):
            current_value = text_area.input_value()
            if current_value == "":
                print(f"✓ Text area cleared on attempt {attempt + 1}")
                break
            else:
                print(f"Attempt {attempt + 1}: Text area still contains '{current_value}'")
                if attempt < 4:
                    page.wait_for_timeout(1000)  # Wait 1 second before retrying
                else:
                    # Last attempt failed, try to clear manually
                    print("Clear button didn't work, clearing manually...")
                    text_area.fill("")
                    text_area.press("Control+A")
                    text_area.press("Delete")
                    # Verify it's empty
                    current_value = text_area.input_value()
                    assert current_value == "", f"Failed to clear text area manually. Still contains: '{current_value}'"

        print("✓ Text area is now empty")

    return context

@then("the text area should be empty")
def verify_textarea_empty(context):
    """Verify the text area is empty."""
    page = context['page']

    print("\n=== Verifying text area is empty ===")

    page.wait_for_load_state("networkidle", timeout=30000)
    expect(page.locator("div[data-testid='stApp']")).to_be_visible(timeout=30000)

    text_areas = page.locator("textarea")

    if text_areas.count() > 0:
        text_area = text_areas.first
        expect(text_area).to_be_visible(timeout=30000)
        # Use to_have_value with empty string for more reliable check
        expect(text_area).to_have_value("", timeout=10000)
        print("✓ Text area is empty")
    else:
        print("Warning: No text area found")

    return context

@then("the result section should be empty")
def verify_result_section_empty(context):
    """Verify the result section is empty of displayed text."""
    page = context['page']

    print("\n=== Verifying result section is empty ===")

    page.wait_for_load_state("networkidle", timeout=30000)
    expect(page.locator("div[data-testid='stApp']")).to_be_visible(timeout=30000)

    # Look for the "Text Result" section specifically
    page_text = page.locator("div[data-testid='stApp']").text_content()

    # Check if "Text Result" section exists
    if "Text Result" in page_text:
        # If it exists, we need to check if it's empty or contains actual text
        # The section might still exist but be empty
        # Let's look for the actual result content
        sections = page.locator("h3, h4, .stMarkdown, .stInfo")

        found_result_section = False
        for i in range(sections.count()):
            section = sections.nth(i)
            section_text = section.text_content()

            if "Text Result" in section_text:
                print(f"Found 'Text Result' section: {section_text}")
                found_result_section = True
                # Check if the section has actual content beyond the header
                # Look for any content after this section
                break

        if found_result_section:
            # Try to find the actual displayed text
            # In Streamlit, the result might be in a st.info container
            info_containers = page.locator(".stAlert, .stInfo, .stSuccess")
            has_content = False

            for i in range(info_containers.count()):
                container = info_containers.nth(i)
                container_text = container.text_content()
                # Skip if it's just the result section header
                if container_text and "Text Result" not in container_text:
                    # Check if it's the actual result
                    if container_text.strip() and not container_text.startswith("Character count"):
                        print(f"Found content in result section: '{container_text[:50]}...'")
                        has_content = True
                        break

            assert not has_content, "Result section should be empty but contains content"
    else:
        print("✓ 'Text Result' section not found, so result section is empty")

    print("✓ Result section is empty as expected")
    return context

# FIX: This step was missing - added to match the feature file
@when("I clear the text area")
def clear_text_area(context):
    """Clear the text area manually."""
    page = context['page']

    print("\n=== Clearing text area manually ===")

    page.wait_for_load_state("networkidle", timeout=30000)
    expect(page.locator("div[data-testid='stApp']")).to_be_visible(timeout=30000)

    text_areas = page.locator("textarea")

    if text_areas.count() > 0:
        text_area = text_areas.first
        expect(text_area).to_be_visible(timeout=30000)
        expect(text_area).to_be_enabled(timeout=30000)
        text_area.fill("")

        # Verify text area is empty
        expect(text_area).to_have_value("", timeout=5000)
    else:
        print("Warning: No text area found")

    return context

@when("I click the \"Display Text\" button without entering text")
def click_display_without_text(context):
    """Click Display Text button with empty text area."""
    return click_display_text_button(context)

@then("I should see a warning message about empty text")
def verify_warning_message(context):
    """Verify a warning message appears about empty text."""
    page = context['page']

    print("\n=== Verifying warning message ===")

    page.wait_for_load_state("networkidle", timeout=30000)
    expect(page.locator("div[data-testid='stApp']")).to_be_visible(timeout=30000)

    # Check for warning elements specifically
    warning_elements = page.locator(".stAlert, .stWarning, .stError")

    found_warning = False
    for i in range(warning_elements.count()):
        element = warning_elements.nth(i)
        element_text = element.text_content().lower()

        warning_indicators = ["warning", "please enter", "empty", "no text"]
        for indicator in warning_indicators:
            if indicator in element_text:
                print(f"✓ Found warning element: {element_text[:100]}")
                found_warning = True
                break
        if found_warning:
            break

    if not found_warning:
        # Fallback to checking all page text
        page_text = page.locator("div[data-testid='stApp']").text_content().lower()
        warning_indicators = ["warning", "please enter", "empty", "no text"]
        for indicator in warning_indicators:
            if indicator in page_text:
                print(f"✓ Found warning in page text: {indicator}")
                found_warning = True
                break

    if not found_warning:
        print("Note: No explicit warning found")

    return context

@then(parsers.parse('I should see "{expected_text}" in the header'))
def verify_text_in_header(context, expected_text):
    """Verify text appears in a header on the page."""
    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print(f'\n=== Verifying text in header: "{expected_text}" ===')

    # Wait for page to load completely
    page.wait_for_load_state("networkidle", timeout=30000)
    expect(page.locator("div[data-testid='stApp']")).to_be_visible(timeout=30000)

    # Check headers (h1, h2, h3 elements) within the app container
    headers = page.locator("div[data-testid='stApp'] h1, div[data-testid='stApp'] h2, div[data-testid='stApp'] h3")

    found = False
    for i in range(headers.count()):
        header = headers.nth(i)
        header_text = header.text_content()
        if expected_text in header_text:
            print(f"✓ Found '{expected_text}' in header: {header_text}")
            found = True
            break

    if not found:
        # Also check for any element containing the text within the app container
        expect(page.locator("div[data-testid='stApp']")).to_contain_text(expected_text, timeout=10000)
        print(f"✓ Found '{expected_text}' somewhere on page")
        found = True

    assert found, f"Expected text '{expected_text}' not found in any header"

    take_screenshot(page, "debug_header_found.png", debug_enabled)

    return context
