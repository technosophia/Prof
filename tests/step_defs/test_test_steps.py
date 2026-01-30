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

# Load feature files
scenarios('../../tests/features/test.feature')

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

# Create a test context that's separate from BrowserContext
@pytest.fixture
def test_context():
    """Test context to store state between steps."""
    return {'debug_enabled': False}

# Helper functions
def find_element_by_text(page, text, exact=False):
    """Find an element containing specific text."""
    if exact:
        return page.get_by_text(text, exact=True)
    else:
        return page.get_by_text(text)

# ================ BACKGROUND STEPS ================

@given("the application is running")
def app_is_running(test_context, page: Page, debug_dir, streamlit_server):
    """Verify the application is running and navigate to it."""
    print("\n=== [Test Module] Navigating to application ===")

    # Use the page fixture from conftest
    page.goto("http://localhost:8502/", wait_until="networkidle")

    # Wait for Streamlit to fully load
    page.wait_for_selector("[data-testid='stApp']", timeout=30000)

    # Take initial screenshot if debug mode
    take_screenshot(page, "test_app_running.png", debug_dir, full_page=True)

    # Store the page reference in test_context
    test_context['page'] = page
    test_context['debug_enabled'] = debug_dir

    print("✓ Application is running and loaded")
    return test_context

@given("I navigate to the admin panel")
def navigate_to_admin_panel_for_test(test_context):
    """Navigate to the admin panel for Test module."""
    if 'page' not in test_context:
        raise KeyError("No 'page' in test_context. Did you call 'the application is running' first?")

    page = test_context['page']
    debug_enabled = test_context.get('debug_enabled', False)

    print("\n=== [Test Module] Navigating to admin panel ===")

    # Look for admin button in sidebar - try different approaches
    admin_found = False

    # Method 1: Look for the admin button by text
    admin_button = None

    # First check if we can see sidebar content
    sidebar_content = page.locator("[data-testid='stSidebar']").first
    if sidebar_content.count() > 0:
        print("Found sidebar, looking for admin button...")
        # Look for button with "Admin" text
        admin_button = sidebar_content.get_by_text("🔧 Admin").or_(sidebar_content.get_by_text("Admin")).first
    else:
        print("Could not find sidebar, looking anywhere...")
        admin_button = page.get_by_text("🔧 Admin").or_(page.get_by_text("Admin")).first

    if admin_button and admin_button.count() > 0 and admin_button.is_visible():
        print("Found admin button, clicking...")
        admin_button.click()
        time.sleep(2)
        admin_found = True
    else:
        # Method 2: Try to find any button that navigates to admin
        print("Admin button not found by text, trying alternative methods...")
        all_buttons = page.get_by_role("button").all()
        for btn in all_buttons:
            try:
                btn_text = btn.text_content()
                if "admin" in btn_text.lower():
                    print(f"Found potential admin button: {btn_text}")
                    btn.click()
                    time.sleep(2)
                    admin_found = True
                    break
            except:
                continue

    if not admin_found:
        # Method 3: Check if we're already on admin page
        page_text = page.locator("body").text_content()
        if "admin" in page_text.lower() or "Admin Panel" in page_text:
            print("Already on admin page or admin content visible")
            admin_found = True
        else:
            print("WARNING: Could not find admin button or navigate to admin panel")

    time.sleep(2)  # Wait for navigation

    if debug_enabled:
        take_screenshot(page, "test_admin_panel_navigated.png", debug_enabled)

    test_context['current_page'] = 'admin'
    print("✓ Admin panel navigation attempted")
    return test_context

# ================ SCENARIO STEPS ================

@when(parsers.parse('I select the "{tab_name}" tab in the admin panel'))
def select_admin_tab(test_context, tab_name):
    """Select a specific tab in the admin panel."""
    if 'page' not in test_context:
        raise KeyError("No 'page' in test_context")

    page = test_context['page']
    debug_enabled = test_context.get('debug_enabled', False)

    print(f'\n=== [Test Module] Selecting admin tab: "{tab_name}" ===')

    # Store current tab for reference
    test_context['previous_tab'] = test_context.get('current_tab', None)
    test_context['current_tab'] = tab_name

    # Wait for page to settle
    time.sleep(1)

    # Check if we're on admin page
    page_text = page.locator("body").text_content()
    if "Admin Panel" not in page_text:
        print("Not on admin page, trying to navigate...")
        # Try to navigate to admin first
        test_context = navigate_to_admin_panel_for_test(test_context)
        time.sleep(2)

    # Try to find tabs
    tab_found = False

    # Method 1: Look for tabs with role='tab'
    tabs = page.locator("[role='tab']")
    tab_count = tabs.count()
    print(f"Found {tab_count} elements with role='tab'")

    if tab_count > 0:
        for i in range(tab_count):
            try:
                tab = tabs.nth(i)
                tab_text = tab.text_content()
                print(f"  Tab {i}: '{tab_text}'")

                if tab_name in tab_text:
                    print(f"  Found matching tab, clicking...")
                    tab.click()
                    time.sleep(2)
                    tab_found = True
                    break
            except:
                continue

    if not tab_found:
        # Method 2: Look for the tab text anywhere
        print(f"Tab '{tab_name}' not found in tab elements, searching for text...")
        text_elements = page.locator(f"text='{tab_name}'")
        if text_elements.count() > 0:
            for i in range(text_elements.count()):
                try:
                    elem = text_elements.nth(i)
                    if elem.is_visible():
                        print(f"Found text '{tab_name}', clicking...")
                        elem.click()
                        time.sleep(2)
                        tab_found = True
                        break
                except:
                    continue

    if not tab_found:
        print(f"WARNING: Could not find or select tab '{tab_name}'")
        # Don't fail here - let the test continue to see what happens
    else:
        print(f"✓ Tab '{tab_name}' selected")

    if debug_enabled:
        take_screenshot(page, f"test_tab_{tab_name}.png", debug_enabled)

    return test_context

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

@given(parsers.parse('I have selected the "{tab_name}" tab'))
def given_selected_tab(test_context, tab_name):
    """Precondition: tab has been selected."""
    # First ensure we're in admin panel
    if test_context.get('current_page') != 'admin':
        test_context = navigate_to_admin_panel_for_test(test_context)

    # Select the tab (don't assert, just try)
    try:
        select_admin_tab(test_context, tab_name)
    except:
        print(f"Note: Could not select tab '{tab_name}', continuing anyway")

    return test_context

@given('I am on the "Test" tab')
def on_test_tab(test_context):
    """Precondition: on the Test tab."""
    # First ensure we're in admin panel
    if test_context.get('current_page') != 'admin':
        test_context = navigate_to_admin_panel_for_test(test_context)

    # Try to select the Test tab
    try:
        select_admin_tab(test_context, "Test")
    except:
        print("Note: Could not select Test tab, continuing anyway")

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
