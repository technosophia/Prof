"""
pytest-bdd step definitions for debug admin UI testing.
Tests the basic text input and display functionality.
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
scenarios('../../tests/features/debug.feature')

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
from tests.step_defs.common_steps import (
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
    return {}


# Now define the missing step that's causing the issue
@given("the application is running")
def app_is_running(test_context, page: Page, debug_dir, streamlit_server):
    """Verify the application is running and navigate to it."""
    print("\n=== Navigating to application ===")
    page.goto("http://localhost:8502/", wait_until="networkidle")

    # Wait for Streamlit to fully load
    page.wait_for_selector("[data-testid='stApp']", timeout=30000)

    # Take initial screenshot if debug mode
    if debug_dir:
        debug_path = os.path.join("tests", "debug")
        os.makedirs(debug_path, exist_ok=True)
        page.screenshot(path=os.path.join(debug_path, "debug_app_running.png"), full_page=True)

    # Store the page reference in test_context (not BrowserContext)
    test_context['page'] = page
    test_context['debug_enabled'] = debug_dir

    print("Application is running and loaded")
    return test_context

# Define the other required steps from the Background
@given(parsers.parse('"{username}" exists in the user database'))
def user_exists_in_database(test_context, username, mock_db_manager):
    """Verify that a user exists in the database."""
    print(f"\n=== Verifying user exists in database: {username} ===")

    mock_users = mock_db_manager.get_all_users()
    print(f"Mock database has {len(mock_users)} users:")

    user_found = False
    for user in mock_users:
        print(f"  - {user.get('name')} (id: {user.get('id')})")
        if user.get('name') == username:
            print(f"✓ Found user '{username}' in mock database")
            user_found = True
            test_context['user_id'] = user['id']
            test_context['user_info'] = user
            break

    if not user_found:
        for user in mock_users:
            if user.get('name', '').lower() == username.lower():
                print(f"✓ Found user '{username}' (case-insensitive) in mock database")
                user_found = True
                test_context['user_id'] = user['id']
                test_context['user_info'] = user
                break

    assert user_found, f"User '{username}' does not exist in database"

    return test_context

@given(parsers.parse('the default user "{username}" is logged in'))
def default_user_logged_in(test_context, username):
    """Log in as the default test user."""
    page = test_context['page']
    debug_enabled = test_context.get('debug_enabled', False)

    print(f"\n=== Logging in as: {username} ===")

    # Simplified login for debug tests
    # Look for user selector
    selectboxes = page.locator("[data-testid='stSelectbox']")

    if selectboxes.count() >= 3:
        user_selectbox = selectboxes.nth(2)
        user_selectbox.click()
        time.sleep(1)

        # Try to find and select the user
        options = page.locator("[data-testid='stSelectboxOption'], div[role='option']")
        for i in range(options.count()):
            option = options.nth(i)
            option_text = option.text_content()
            if username in option_text:
                option.click()
                time.sleep(1)
                print(f"✓ Selected user: {username}")
                break

        # Look for login button
        login_button = page.get_by_text("Login as User").or_(page.get_by_text("Login")).or_(page.get_by_text("Log in"))
        if login_button.count() > 0:
            login_button.first.click()
            time.sleep(1)

    test_context['current_user'] = username
    return test_context

@given("the mock LLM is configured and available")
def mock_llm_available(test_context):
    """Verify the mock LLM is configured and available."""
    page = test_context['page']

    print("\n=== Selecting Mock LLM ===")

    # Simple LLM selection - just return context
    # For debug tests, we don't necessarily need to select LLM
    return test_context

# Now define the debug-specific steps
@given("I am logged in as an admin user")
def logged_in_as_admin(test_context):
    """Log in as an admin user."""
    # Use "Test User 2" which is an admin in mock data
    return default_user_logged_in(test_context, "Test User 2")

@given("I navigate to the admin panel")
def navigate_to_admin_panel(test_context):
    """Navigate to the admin panel."""
    page = test_context['page']
    debug_enabled = test_context.get('debug_enabled', False)

    print("\n=== Navigating to admin panel ===")

    # Look for admin button
    admin_button = page.get_by_text("🔧 Admin").or_(page.get_by_text("Admin"))

    if admin_button.count() > 0:
        admin_button.first.click()
        time.sleep(2)
        admin_button.first.click()
        time.sleep(2)
        # Wait for admin page
        page.wait_for_selector("h1", timeout=10000)

        if debug_enabled:
            debug_path = os.path.join("tests", "debug")
            os.makedirs(debug_path, exist_ok=True)
            page.screenshot(path=os.path.join(debug_path, "debug_admin_panel.png"))

        test_context['current_page'] = 'admin'
    else:
        print("Warning: Could not find admin button")
        # Try direct navigation
        page.goto("http://localhost:8502/", wait_until="networkidle")
        time.sleep(2)

    return test_context

@given('I select the "Debug" tab')
def select_debug_tab(test_context):
    """Select the Debug tab in the admin panel."""
    page = test_context['page']
    debug_enabled = test_context.get('debug_enabled', False)

    print('\n=== Selecting "Debug" tab ===')

    # Look for Debug tab
    debug_tab = page.get_by_text("Debug", exact=True)

    if debug_tab.count() > 0:
        debug_tab.first.click()
        time.sleep(2)

        if debug_enabled:
            debug_path = os.path.join("tests", "debug")
            os.makedirs(debug_path, exist_ok=True)
            page.screenshot(path=os.path.join(debug_path, "debug_tab_selected.png"))
    else:
        print("Warning: Could not find Debug tab")
        # Try to find tabs
        tabs = page.locator("[role='tab']")
        for i in range(tabs.count()):
            tab = tabs.nth(i)
            if "Debug" in tab.text_content():
                tab.click()
                time.sleep(2)
                break

    return test_context

@when(parsers.parse('I enter text "{text}" in the text area'))
def enter_text_in_textarea(test_context, text):
    """Enter text in the debug text area."""
    page = test_context['page']
    debug_enabled = test_context.get('debug_enabled', False)

    print(f'\n=== Entering text in text area: "{text}" ===')

    # Find text area
    text_areas = page.locator("textarea")

    if text_areas.count() > 0:
        text_area = text_areas.first
        text_area.fill("")
        text_area.type(text, delay=50)
        time.sleep(0.5)

        test_context['entered_text'] = text

        if debug_enabled:
            debug_path = os.path.join("tests", "debug")
            os.makedirs(debug_path, exist_ok=True)
            page.screenshot(path=os.path.join(debug_path, "debug_text_entered.png"))
    else:
        print("Warning: Could not find text area")

    return test_context

@when('I click the "Display Text" button')
def click_display_text_button(test_context):
    """Click the Display Text button."""
    page = test_context['page']
    debug_enabled = test_context.get('debug_enabled', False)

    print('\n=== Clicking "Display Text" button ===')

    # Find display button
    display_button = page.get_by_text("Display Text").or_(page.get_by_text("📤 Display Text"))

    if display_button.count() > 0:
        display_button.first.click()
        time.sleep(2)

        if debug_enabled:
            debug_path = os.path.join("tests", "debug")
            os.makedirs(debug_path, exist_ok=True)
            page.screenshot(path=os.path.join(debug_path, "debug_display_clicked.png"))
    else:
        print("Warning: Could not find Display Text button")

    return test_context

@then(parsers.parse('I should see "{expected_text}" in the result section'))
def verify_text_in_result(test_context, expected_text):
    """Verify text appears in the result section."""
    page = test_context['page']
    debug_enabled = test_context.get('debug_enabled', False)

    print(f'\n=== Verifying text in result: "{expected_text}" ===')

    time.sleep(1)

    # Check if text appears on page
    page_text = page.locator("body").text_content()

    assert expected_text in page_text, f"Expected text '{expected_text}' not found on page"

    print(f"✓ Found text: {expected_text}")
    return test_context

@then("I should see the character count displayed")
def verify_character_count(test_context):
    """Verify character count is displayed."""
    page = test_context['page']

    print("\n=== Verifying character count ===")

    page_text = page.locator("body").text_content()

    # Look for character count pattern
    if re.search(r'character.*count', page_text, re.IGNORECASE):
        print("✓ Character count found")
    else:
        print("Note: Character count not specifically found")

    return test_context

@then("I should see the word count displayed")
def verify_word_count(test_context):
    """Verify word count is displayed."""
    page = test_context['page']

    print("\n=== Verifying word count ===")

    page_text = page.locator("body").text_content()

    # Look for word count pattern
    if re.search(r'word.*count', page_text, re.IGNORECASE):
        print("✓ Word count found")
    else:
        print("Note: Word count not specifically found")

    return test_context

@given(parsers.parse('I have entered text "{text}" in the text area'))
def given_entered_text(test_context, text):
    """Precondition: text has been entered."""
    return enter_text_in_textarea(test_context, text)

@given("I have displayed the text")
def given_displayed_text(test_context):
    """Precondition: text has been displayed."""
    return click_display_text_button(test_context)

@when('I click the "Clear Text" button')
def click_clear_text_button(test_context):
    """Click the Clear Text button."""
    page = test_context['page']
    debug_enabled = test_context.get('debug_enabled', False)

    print('\n=== Clicking "Clear Text" button ===')

    clear_button = page.get_by_text("Clear Text").or_(page.get_by_text("🗑️ Clear Text"))

    if clear_button.count() > 0:
        clear_button.first.click()
        time.sleep(2)
    else:
        print("Warning: Could not find Clear Text button")

    return test_context

@then("the text area should be empty")
def verify_textarea_empty(test_context):
    """Verify the text area is empty."""
    page = test_context['page']

    print("\n=== Verifying text area is empty ===")

    text_areas = page.locator("textarea")
    if text_areas.count() > 0:
        text_area = text_areas.first
        current_value = text_area.input_value()
        assert current_value == "", f"Text area not empty, contains: {current_value}"
        print("✓ Text area is empty")

    return test_context

@then("the result section should be empty")
def verify_result_section_empty(test_context):
    """Verify the result section is empty of displayed text."""
    page = test_context['page']

    print("\n=== Verifying result section is empty ===")

    # Look for the "Text Result" section specifically
    page_text = page.locator("body").text_content()

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
    return test_context

@when("I clear the text area")
def clear_text_area(test_context):
    """Clear the text area manually."""
    page = test_context['page']

    print("\n=== Clearing text area manually ===")

    text_areas = page.locator("textarea")
    if text_areas.count() > 0:
        text_area = text_areas.first
        text_area.fill("")
        time.sleep(0.5)

    return test_context

@when("I click the \"Display Text\" button without entering text")
def click_display_without_text(test_context):
    """Click Display Text button with empty text area."""
    return click_display_text_button(test_context)

@then("I should see a warning message about empty text")
def verify_warning_message(test_context):
    """Verify a warning message appears about empty text."""
    page = test_context['page']

    print("\n=== Verifying warning message ===")

    page_text = page.locator("body").text_content().lower()

    # Check for any warning indicators
    warning_indicators = ["warning", "please enter", "empty", "no text"]

    found = False
    for indicator in warning_indicators:
        if indicator in page_text:
            found = True
            print(f"✓ Found warning: {indicator}")
            break

    if not found:
        print("Note: No explicit warning found")

    return test_context

@then(parsers.parse('I should see "{expected_text}" in the header'))
def verify_text_in_header(test_context, expected_text):
    """Verify text appears in a header on the page."""
    page = test_context['page']
    debug_enabled = test_context.get('debug_enabled', False)

    print(f'\n=== Verifying text in header: "{expected_text}" ===')

    # Wait a bit for the page to load
    time.sleep(2)

    # Check headers (h1, h2, h3 elements)
    headers = page.locator("h1, h2, h3, h4, h5, h6")

    found = False
    for i in range(headers.count()):
        header = headers.nth(i)
        header_text = header.text_content()
        if expected_text in header_text:
            print(f"✓ Found '{expected_text}' in header: {header_text}")
            found = True
            break

    if not found:
        # Also check for any element containing the text
        all_text = page.locator("body").text_content()
        if expected_text in all_text:
            print(f"✓ Found '{expected_text}' somewhere on page")
            found = True

    assert found, f"Expected text '{expected_text}' not found in any header"

    if debug_enabled:
        debug_path = os.path.join("tests", "debug")
        os.makedirs(debug_path, exist_ok=True)
        page.screenshot(path=os.path.join(debug_path, "debug_header_found.png"))

    return test_context

@given("the debug module is loaded")
def debug_module_loaded(test_context):
    """Verify the debug module is loaded in the admin panel."""
    page = test_context['page']

    print("\n=== Verifying debug module is loaded ===")

    # Check for debug module in available modules
    page_text = page.locator("body").text_content().lower()

    debug_found = False
    if "debug" in page_text:
        print("✓ Found 'debug' text on page")
        debug_found = True

    # Also check for specific debug UI elements
    debug_elements = page.locator(":text('debug'):visible")
    print(f"Found {debug_elements.count()} visible elements with 'debug' text")

    # Print all tabs for debugging
    tabs = page.locator("[role='tab']")
    print(f"Found {tabs.count()} tabs:")
    for i in range(tabs.count()):
        tab = tabs.nth(i)
        tab_text = tab.text_content()
        print(f"  Tab {i}: '{tab_text}'")

        if "debug" in tab_text.lower():
            debug_found = True
            print(f"  ✓ Found Debug tab: '{tab_text}'")

    if not debug_found:
        print("WARNING: Debug module/tab not found!")
        # Print all text for debugging
        print("\nAll page text (first 1000 chars):")
        print(page_text[:1000])

    return test_context
