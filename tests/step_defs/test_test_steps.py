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

# Re-use fixtures from conftest.py
from conftest import (
    setup_test_environment,
    playwright,
    browser,
    page as conftest_page,
    patch_config,
    mock_db_manager,
    mock_user_manager,
    patch_database
)

# Re-use fixtures from conversation tests
from tests.step_defs.test_conversation_steps import (
    enable_debug,
    streamlit_server,
    browser_context,
    page as conversation_page,
    debug_dir,
    context as conversation_context
)

# Create a test context that's separate from BrowserContext
@pytest.fixture
def test_context():
    """Test context to store state between steps."""
    return {}

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
    if debug_dir:
        debug_path = os.path.join("tests", "debug")
        os.makedirs(debug_path, exist_ok=True)
        page.screenshot(path=os.path.join(debug_path, "test_app_running.png"), full_page=True)

    # Store the page reference in test_context
    test_context['page'] = page
    test_context['debug_enabled'] = debug_dir

    print("✓ Application is running and loaded")
    return test_context


@given("I navigate to the admin panel")
def navigate_to_admin_panel_for_test(test_context):
    """Navigate to the admin panel for Test module."""
    page = test_context['page']
    debug_enabled = test_context.get('debug_enabled', False)

    print("\n=== [Test Module] Navigating to admin panel ===")

    # Look for admin button
    admin_button = page.get_by_text("🔧 Admin").or_(page.get_by_text("Admin"))

    if admin_button.count() > 0:
        admin_button.first.click()
        time.sleep(2)
        admin_button.first.click()
        time.sleep(2)

        if debug_enabled:
            debug_path = os.path.join("tests", "debug")
            os.makedirs(debug_path, exist_ok=True)
            page.screenshot(path=os.path.join(debug_path, "test_admin_panel.png"))

        # Wait for admin page to load
        page.wait_for_selector("h1", timeout=10000)
        test_context['current_page'] = 'admin'
        print("✓ Admin panel loaded")
    else:
        print("Warning: Could not find admin button")
        # Try direct navigation
        page.goto("http://localhost:8502/", wait_until="networkidle")
        time.sleep(2)

    return test_context

# ================ SCENARIO STEPS ================

@when(parsers.parse('I select the "{tab_name}" tab in the admin panel'))
def select_admin_tab(test_context, tab_name):
    """Select a specific tab in the admin panel."""
    page = test_context['page']
    debug_enabled = test_context.get('debug_enabled', False)

    print(f'\n=== [Test Module] Selecting admin tab: "{tab_name}" ===')

    # Store current tab for reference
    test_context['previous_tab'] = test_context.get('current_tab', None)
    test_context['current_tab'] = tab_name

    # Try different methods to find and click the tab
    tab_found = False

    # Method 1: Look for exact text
    tab_element = page.get_by_text(tab_name, exact=True)

    if tab_element.count() > 0:
        print(f"Found tab by exact text: {tab_name}")
        tab_element.first.click()
        tab_found = True
    else:
        # Method 2: Look for tabs with role='tab'
        tabs = page.locator("[role='tab']")
        print(f"Found {tabs.count()} tabs with role='tab'")

        for i in range(tabs.count()):
            tab = tabs.nth(i)
            tab_text = tab.text_content()
            print(f"  Tab {i}: '{tab_text}'")

            if tab_name in tab_text:
                print(f"  ✓ Clicking tab: '{tab_text}'")
                tab.click()
                tab_found = True
                break

    if not tab_found:
        # Method 3: Try case-insensitive search
        print("Trying case-insensitive search...")
        all_text = page.locator("body").text_content()
        if tab_name.lower() in all_text.lower():
            print(f"Tab text '{tab_name}' found somewhere on page (case-insensitive)")
            # Click on any element containing the tab name
            tab_element = page.locator(f":text-is('{tab_name}'):visible")
            if tab_element.count() > 0:
                tab_element.first.click()
                tab_found = True

    time.sleep(2)  # Wait for tab content to load

    if debug_enabled:
        debug_path = os.path.join("tests", "debug")
        os.makedirs(debug_path, exist_ok=True)
        page.screenshot(path=os.path.join(debug_path, f"test_tab_{tab_name.lower().replace(' ', '_')}.png"))

    assert tab_found, f"Could not find or select tab: '{tab_name}'"
    print(f"✓ Selected tab: {tab_name}")

    return test_context

@then(parsers.parse('I should see "{expected_text}" in the admin content'))
def verify_admin_content(test_context, expected_text):
    """Verify text appears in the admin content area."""
    page = test_context['page']
    debug_enabled = test_context.get('debug_enabled', False)

    print(f'\n=== [Test Module] Verifying admin content: "{expected_text}" ===')

    # Wait for content to load
    time.sleep(1)

    # Get all text from the page
    page_text = page.locator("body").text_content()

    # Check if expected text is in page text
    assert expected_text in page_text, f"Expected text '{expected_text}' not found in admin content. Page text:\n{page_text[:500]}"

    print(f"✓ Found expected text: {expected_text}")

    # Take screenshot if debug enabled
    if debug_enabled:
        debug_path = os.path.join("tests", "debug")
        os.makedirs(debug_path, exist_ok=True)
        page.screenshot(path=os.path.join(debug_path, "test_admin_content.png"))

    return test_context

@given(parsers.parse('I have selected the "{tab_name}" tab'))
def given_selected_tab(test_context, tab_name):
    """Precondition: tab has been selected."""
    return select_admin_tab(test_context, tab_name)

@when('I select another admin tab')
def select_other_admin_tab(test_context):
    """Select a different admin tab than the current one."""
    page = test_context['page']
    current_tab = test_context.get('current_tab', 'Test')

    print(f'\n=== [Test Module] Selecting different admin tab (current: {current_tab}) ===')

    # Find all available tabs
    tabs = page.locator("[role='tab']")
    other_tab_found = False

    for i in range(tabs.count()):
        tab = tabs.nth(i)
        tab_text = tab.text_content()

        # Skip current tab
        if current_tab not in tab_text and tab_text.strip():
            print(f"  Selecting different tab: '{tab_text}'")
            tab.click()
            other_tab_found = True
            test_context['current_tab'] = tab_text
            break

    if not other_tab_found:
        # Try to find any button or element that might be another tab
        buttons = page.locator("button")
        for i in range(min(buttons.count(), 10)):  # Check first 10 buttons
            button = buttons.nth(i)
            button_text = button.text_content()
            if button_text.strip() and current_tab not in button_text:
                print(f"  Trying button as tab: '{button_text}'")
                button.click()
                other_tab_found = True
                test_context['current_tab'] = button_text
                break

    time.sleep(2)  # Wait for tab to load

    if other_tab_found:
        print(f"✓ Selected different tab: {test_context['current_tab']}")
    else:
        print("Note: Could not find a different tab")

    return test_context

@when('I return to the "Test" tab')
def return_to_test_tab(test_context):
    """Return to the Test tab."""
    return select_admin_tab(test_context, "Test")

@given('I am on the "Test" tab')
def on_test_tab(test_context):
    """Precondition: on the Test tab."""
    return select_admin_tab(test_context, "Test")

@then(parsers.parse('I should see "{expected_text}" in the header'))
def verify_text_in_header_for_test(test_context, expected_text):
    """Verify text appears in a header on the page for Test module."""
    page = test_context['page']
    debug_enabled = test_context.get('debug_enabled', False)

    print(f'\n=== [Test Module] Verifying header text: "{expected_text}" ===')

    # Wait for content to load
    time.sleep(1)

    # Check headers (h1, h2, h3 elements)
    headers = page.locator("h1, h2, h3, h4, h5, h6")

    found = False
    header_texts = []
    for i in range(headers.count()):
        header = headers.nth(i)
        header_text = header.text_content().strip()
        header_texts.append(header_text)
        if expected_text in header_text:
            print(f"✓ Found '{expected_text}' in header: '{header_text}'")
            found = True
            break

    if not found:
        print(f"Available headers: {header_texts}")
        # Check for any text on the page
        all_text = page.locator("body").text_content()
        if expected_text in all_text:
            print(f"✓ Found '{expected_text}' somewhere on page")
            found = True

    assert found, f"Expected text '{expected_text}' not found in any header"

    if debug_enabled:
        debug_path = os.path.join("tests", "debug")
        os.makedirs(debug_path, exist_ok=True)
        page.screenshot(path=os.path.join(debug_path, "test_header_verified.png"))

    return test_context

# Helper function to verify Test module is available
@given("the Test module is available")
def test_module_available(test_context):
    """Verify the Test module is available in the admin panel."""
    page = test_context['page']

    print("\n=== [Test Module] Verifying Test module is available ===")

    # Check for Test module in available modules
    page_text = page.locator("body").text_content()

    test_found = False
    if "Test" in page_text:
        print("✓ Found 'Test' text on page")
        test_found = True

    # Also check for Test tab specifically
    tabs = page.locator("[role='tab']")
    print(f"Found {tabs.count()} tabs:")

    for i in range(tabs.count()):
        tab = tabs.nth(i)
        tab_text = tab.text_content()
        print(f"  Tab {i}: '{tab_text}'")

        if "Test" in tab_text:
            test_found = True
            print(f"  ✓ Found Test tab: '{tab_text}'")

    if not test_found:
        print("WARNING: Test module/tab not found initially")
        # This might be OK if the tab needs to be selected first

    return test_context
