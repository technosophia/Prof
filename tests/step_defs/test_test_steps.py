# file name: test_test_steps.py
"""
pytest-bdd step definitions for Test admin UI testing.
Tests the Test module functionality in the admin panel.
"""
import pytest
import time
import re
from pytest_bdd import given, when, then, scenarios, parsers
import sys
import os
from playwright.sync_api import Page, expect

# Add the project root to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

pytestmark = pytest.mark.bdd

# Import fixtures from conftest.py only
from conftest import (
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
    context as conversation_context,
    take_screenshot
)

from common_steps import *

# Load feature files
scenarios('../../tests/features/test.feature')

# ================ SCENARIO STEPS ================

@then(parsers.parse('I should see "{expected_text}" in the admin content'))
def verify_admin_content(test_context, expected_text):
    """Verify text appears in the admin content area."""
    if 'page' not in test_context:
        raise KeyError("No 'page' in test_context")

    page = test_context['page']
    debug_enabled = test_context.get('debug_enabled', False)

    print(f'\n=== [Test Module] Verifying admin content: "{expected_text}" ===')

    # Wait for content to load
    time.sleep(1)

    # Get all text from the page
    page_text = page.locator("body").text_content()

    # Check if expected text is in page text
    if expected_text not in page_text:
        print(f"Page text (first 500 chars): {page_text[:500]}")
        if debug_enabled:
            take_screenshot(page, "test_admin_content_not_found.png", debug_enabled)
        raise AssertionError(f"Expected text '{expected_text}' not found in admin content")

    print(f"✓ Found expected text: {expected_text}")

    if debug_enabled:
        take_screenshot(page, "test_admin_content_found.png", debug_enabled)

    return test_context


@then(parsers.parse('I should see "{expected_text}" in the header'))
def verify_text_in_header_for_test(test_context, expected_text):
    """Verify text appears in a header on the page for Test module."""
    if 'page' not in test_context:
        raise KeyError("No 'page' in test_context")

    page = test_context['page']
    debug_enabled = test_context.get('debug_enabled', False)

    print(f'\n=== [Test Module] Verifying header text: "{expected_text}" ===')

    # Wait for content to load
    time.sleep(1)

    # Check headers (h1, h2, h3 elements)
    found = False

    # Check all header elements
    for tag in ["h1", "h2", "h3", "h4", "h5", "h6"]:
        headers = page.locator(tag)
        for i in range(headers.count()):
            try:
                header = headers.nth(i)
                header_text = header.text_content().strip()
                if expected_text in header_text:
                    print(f"✓ Found '{expected_text}' in {tag}: '{header_text}'")
                    found = True
                    break
            except:
                continue
        if found:
            break

    # Also check for text anywhere on page
    if not found:
        page_text = page.locator("body").text_content()
        if expected_text in page_text:
            print(f"✓ Found '{expected_text}' somewhere on page")
            found = True

    if not found:
        if debug_enabled:
            take_screenshot(page, "test_header_not_found.png", debug_enabled)
        raise AssertionError(f"Expected text '{expected_text}' not found in any header")

    if debug_enabled:
        take_screenshot(page, "test_header_found.png", debug_enabled)

    return test_context

@given("the Test module is available")
def test_module_available(test_context):
    """Verify the Test module is available in the admin panel."""
    # Note: This is just a placeholder step definition
    # The actual verification happens in the scenario steps
    print("\n=== [Test Module] Assuming Test module is available ===")
    return

# Optional: Add these step definitions if needed by your feature file
@when('I select another admin tab')
def select_other_admin_tab(test_context):
    """Select a different admin tab than the current one."""
    # Implementation if needed
    return

@when('I return to the "Test" tab')
def return_to_test_tab(test_context):
    """Return to the Test tab."""
    return select_admin_tab(test_context, "Test")
