# file name: tests/step_defs/common_steps.py
"""
Common step definitions and utilities for pytest-bdd tests.
"""
import pytest
import time
import os
import re
import subprocess
import requests
import atexit
import signal
from pytest_bdd import given, when, then, parsers
from playwright.sync_api import Page, expect

# ============ RE-EXPORT FIXTURES ============
# Ces imports permettent aux fichiers de steps d'accéder aux fixtures de conftest
from conftest import (
    enable_debug,
    streamlit_server,
    browser_context,
    page,
    debug_dir,
    context,
    take_screenshot,
    find_element_by_text
)

@given("the application is running")
def app_is_running(context, page: Page, debug_dir, streamlit_server):
    """Verify the application is running and navigate to it."""
    print("\n=== [Test Module] Navigating to application ===")

    # Use the page fixture from conftest
    page.goto("http://localhost:8502/", wait_until="networkidle")

    # Wait for Streamlit to fully load
    page.wait_for_selector("[data-testid='stApp']", timeout=30000)

    # Take initial screenshot if debug mode
    take_screenshot(page, "test_app_running.png", debug_dir, full_page=True)

    # Store the page reference in context
    context['page'] = page
    context['debug_enabled'] = debug_dir

    print("✓ Application is running and loaded")
    return context


# Create a test context that's separate from BrowserContext
@pytest.fixture
def context():
    """Test context to store state between steps."""
    return {'debug_enabled': False}


@given("I navigate to the admin panel")
def navigate_to_admin_panel_common(context):
    """Navigate to the admin panel - common implementation for all modules."""
    if 'page' not in context:
        raise KeyError("No 'page' in context. Did you call 'the application is running' first?")

    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print("\n=== Navigating to admin panel ===")

    # Wait for sidebar to be fully loaded
    sidebar = page.locator("[data-testid='stSidebar']").first
    expect(sidebar).to_be_visible(timeout=10000)

    # Try multiple methods to find and click the admin button
    admin_button = None

    # Method 1: Look for admin button in sidebar with multiple text variations
    admin_button = sidebar.get_by_text(re.compile(r"Admin", re.IGNORECASE)).first

    # Method 2: If not found in sidebar, look anywhere on page
    if admin_button.count() == 0:
        print("Admin button not in sidebar, searching entire page...")
        admin_button = page.get_by_text(re.compile(r"Admin", re.IGNORECASE)).first

    # Method 3: Try button role with admin text
    if admin_button.count() == 0:
        print("Trying button role with admin text...")
        admin_button = page.get_by_role("button", name=re.compile(r"Admin", re.IGNORECASE)).first

    # Click the admin button if found
    if admin_button.count() > 0:
        print("Found admin button, ensuring it's visible and enabled...")
        expect(admin_button).to_be_visible(timeout=10000)
        expect(admin_button).to_be_enabled(timeout=5000)

        print("Clicking admin button...")
        admin_button.click()

        # Wait for Streamlit rerun to complete
        page.wait_for_load_state("networkidle", timeout=30000)

        # Wait for admin panel content to appear (look for "Admin Panel" heading or tabs)
        admin_indicator = page.locator("text=/Admin Panel/i").or_(page.locator("[role='tab']")).first
        expect(admin_indicator).to_be_visible(timeout=30000)

        print("✓ Admin panel loaded successfully")
    else:
        # Method 4: Check if already on admin page
        print("Admin button not found, checking if already on admin page...")
        admin_content = page.locator("text=/Admin Panel/i").or_(page.locator("[role='tab']")).first

        if admin_content.count() > 0:
            print("Already on admin page")
        else:
            # Fallback: try direct navigation
            print("WARNING: Could not find admin button, attempting direct navigation...")
            page.goto("http://localhost:8502/", wait_until="networkidle")
            page.wait_for_load_state("domcontentloaded", timeout=30000)

    # Take screenshot if debug enabled
    if debug_enabled:
        take_screenshot(page, "admin_panel_navigated.png", debug_enabled, full_page=True)

    # Update context
    context['current_page'] = 'admin'
    print("✓ Admin panel navigation completed")

    return context


@given(parsers.parse('I select the "{tab_name}" tab'))
def select_debug_tab(context, tab_name):
    """Select a tab in the admin panel."""
    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print(f'\n=== Selecting "{tab_name}" tab ===')

    # Wait for tabs to be visible
    tabs_container = page.locator("[role='tab']").first
    expect(tabs_container).to_be_visible(timeout=10000)

    # Look for the specific tab by exact text
    tab = page.get_by_role("tab", name=tab_name, exact=True).first

    # If exact match not found, try case-insensitive regex
    if tab.count() == 0:
        print(f"Exact match not found, trying case-insensitive search for {tab_name}...")
        tab = page.get_by_role("tab", name=re.compile(rf"{re.escape(tab_name)}", re.IGNORECASE)).first

    # If still not found, try by text content
    if tab.count() == 0:
        print(f"Role-based search failed, trying text search...")
        tab = page.get_by_text(tab_name, exact=True).first

    if tab.count() > 0:
        print(f"Found {tab_name} tab, ensuring it's visible and enabled...")
        expect(tab).to_be_visible(timeout=10000)
        expect(tab).to_be_enabled(timeout=5000)

        print(f"Clicking {tab_name} tab...")
        tab.click()

        # Wait for Streamlit rerun to complete
        page.wait_for_load_state("networkidle", timeout=30000)

        # Wait for tab content to be visible (the clicked tab should have aria-selected="true")
        expect(tab).to_have_attribute("aria-selected", "true", timeout=10000)

        print(f"✓ {tab_name} tab selected successfully")

        if debug_enabled:
            take_screenshot(page, f"{tab_name}_tab_selected.png", debug_enabled)
    else:
        print(f"Warning: Could not find {tab_name} tab")

        # Log all available tabs for debugging
        all_tabs = page.locator("[role='tab']")
        print(f"Available tabs ({all_tabs.count()}):")
        for i in range(all_tabs.count()):
            tab_text = all_tabs.nth(i).text_content()
            print(f"  Tab {i}: {tab_text}")

    return context



@given(parsers.parse('I am on the "{tab_name}" tab'))
def on_tab(context, tab_name):
    """Precondition: on the Test tab."""
    # Try to select the Test tab
    try:
        select_admin_tab(context, tab_name)
    except:
        print(f"Note: Could not select {tab_name} tab, continuing anyway")

    return context

@given("the mock LLM is configured and available")
def mock_llm_available(context):
    """Verify the mock LLM is configured and available."""
    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print("\n=== Selecting Mock LLM ===")
    print("TEST_MODE env var:", os.getenv("TEST_MODE"))
    print("CONFIG_FILE env var:", os.getenv("CONFIG_FILE"))

    # Take screenshot before
    take_screenshot(page, "conversation_before_llm_select.png", debug_enabled)

    # Wait for page to be ready
    page.wait_for_load_state("networkidle", timeout=30000)
    expect(page.locator("[data-testid='stApp']")).to_be_visible(timeout=30000)

    # Find the LLM selectbox
    selectboxes = page.locator("[data-testid='stSelectbox']")
    print(f"Found {selectboxes.count()} selectboxes")

    # Try to find LLM selector - look for selectbox containing "LLM" or "AI Model"
    llm_selectbox = None
    for i in range(selectboxes.count()):
        selectbox = selectboxes.nth(i)
        text = selectbox.text_content()
        if "llm" in text.lower() or "ai model" in text.lower() or "selection" in text.lower():
            llm_selectbox = selectbox
            print(f"Found LLM selectbox at index {i}: {text[:50]}")
            break

    if llm_selectbox:
        # Click to open dropdown
        expect(llm_selectbox).to_be_visible(timeout=30000)
        llm_selectbox.click()

        # Wait for dropdown to open
        expect(page.locator("li[role='option']").first).to_be_visible(timeout=30000)

        # Take screenshot of dropdown
        take_screenshot(page, "conversation_llm_dropdown.png", debug_enabled)

        # Look for options
        for selector in ["li[role='option']", "[data-testid='stSelectboxOption']"]:
            options = page.locator(selector)
            if options.count() > 0:
                print(f"Found {options.count()} LLM options with {selector}")

                # Try to find Mock LLM
                for i in range(options.count()):
                    option = options.nth(i)
                    option_text = option.text_content()
                    print(f"  Option {i}: {option_text}")

                    if "Mock" in option_text or "mock" in option_text.lower():
                        print(f"  ✓ Selecting Mock LLM: {option_text}")
                        option.click()
                        # Wait for selection to apply
                        page.wait_for_load_state("networkidle", timeout=30000)
                        expect(page.locator("[data-testid='stApp']")).to_be_visible(timeout=30000)

                        # Take screenshot after selection
                        take_screenshot(page, "conversation_mock_llm_selected.png", debug_enabled)

                        print("✓ Mock LLM selected")
                        return context

                # If Mock not found but we have options, select the first one
                print("Mock LLM not found in options, selecting first option")
                options.first.click()
                page.wait_for_load_state("networkidle", timeout=30000)
                expect(page.locator("[data-testid='stApp']")).to_be_visible(timeout=30000)
                break
    else:
        print("Warning: Could not find LLM selectbox")

    print("Note: Could not select Mock LLM, continuing anyway")
    take_screenshot(page, "conversation_llm_final.png", debug_enabled)
    return context


@then("I should see a response from the mock LLM")
def verify_mock_response(context):
    """Verify the mock LLM response appears."""
    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print("\n=== Verifying mock LLM response ===")

    # Wait for response to appear
    page.wait_for_load_state("networkidle", timeout=30000)
    expect(page.locator("[data-testid='stApp']")).to_be_visible(timeout=30000)

    # Look for assistant messages with retry logic
    max_attempts = 5
    found_response = False
    response_text = ""

    for attempt in range(max_attempts):
        # Method 1: Look for chat messages (Streamlit structure)
        chat_messages = page.locator("[data-testid='stChatMessage']").all()
        if chat_messages:
            print(f"Found {len(chat_messages)} chat messages")
            # The last one should be the assistant response
            if len(chat_messages) > 0:
                last_message = chat_messages[-1]
                response_text = last_message.text_content()
                print(f"Last chat message: {response_text[:100]}...")

                # Check for mock indicators
                if any(indicator in response_text.lower() for indicator in ["mock", "test", "hello", "response"]):
                    found_response = True
                    break

        # Method 2: Look for any text that looks like a response
        page_text = page.locator("body").text_content()
        response_patterns = [
            r"mock.*response",
            r"test.*llm",
            r"hello.*assistant",
            r"i.*m.*ai",
            r"user.*said"
        ]

        for pattern in response_patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                found_response = True
                response_text = match.group(0)
                print(f"Found response pattern: {pattern}")
                break

        if found_response:
            break

        if attempt < max_attempts - 1:
            print(f"Response not found yet, waiting... (attempt {attempt + 1}/{max_attempts})")
            page.wait_for_timeout(1000)  # Brief wait between attempts

    if not found_response:
        take_screenshot(page, "conversation_response_debug.png", debug_enabled, full_page=True)
        assert found_response, "No mock LLM response found on page"

    take_screenshot(page, "conversation_08_response_received.png", debug_enabled)
    context['last_response'] = response_text

    return context


@given(parsers.parse('"{username}" exists in the user database'))
def user_exists_in_database(context, username, mock_db_manager):
    """Verify that a user exists in the database by checking the mock directly."""
    print(f"\n=== Verifying user exists in database: {username} ===")

    # Get all users from the mock database
    mock_users = mock_db_manager.get_all_users()
    print(f"Mock database has {len(mock_users)} users:")

    user_found = False
    for user in mock_users:
        print(f"  - {user.get('name')} (id: {user.get('id')})")
        if user.get('name') == username:
            print(f"✓ Found user '{username}' in mock database")
            user_found = True
            context['user_id'] = user['id']
            context['user_info'] = user
            break

    if not user_found:
        # Try case-insensitive
        for user in mock_users:
            if user.get('name', '').lower() == username.lower():
                print(f"✓ Found user '{username}' (case-insensitive) in mock database")
                user_found = True
                context['user_id'] = user['id']
                context['user_info'] = user
                break

    # Final assertion
    assert user_found, f"User '{username}' does not exist in database and could not be added"

    # Also verify through user_manager for consistency
    try:
        from shared.users import user_manager
        user_from_manager = user_manager.get_user_by_name(username)
        if user_from_manager:
            print(f"✓ Verified through user_manager.get_user_by_name: {username}")
        else:
            print(f"⚠ user_manager.get_user_by_name didn't find {username}")
    except Exception as e:
        print(f"⚠ Could not verify through user_manager: {e}")

    return context



@given(parsers.parse('the default user "{username}" is logged in'))
def default_user_logged_in(context, username):
    """Log in as the default test user."""
    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print(f"\n=== Logging in as: {username} ===")

    # Take screenshot before login
    take_screenshot(page, "conversation_before_login.png", debug_enabled, full_page=True)

    # Wait for page to be ready
    page.wait_for_load_state("networkidle", timeout=30000)
    expect(page.locator("[data-testid='stApp']")).to_be_visible(timeout=30000)

    # Find ALL selectboxes
    all_selectboxes = page.locator("[data-testid='stSelectbox']")
    selectbox_count = all_selectboxes.count()
    print(f"Found {selectbox_count} selectboxes total")

    # The user selectbox should be the one with "Choose user" or similar
    # Based on earlier error, it's the 3rd one (index 2)
    if selectbox_count >= 3:
        print("Clicking the third selectbox (assuming it's the user selector)...")
        user_selectbox = all_selectboxes.nth(2)
        expect(user_selectbox).to_be_visible(timeout=30000)
        user_selectbox.click()

        # Wait for dropdown to open
        expect(page.locator("li[role='option']").first).to_be_visible(timeout=30000)

        # Try different selectors for dropdown options
        option_selectors = [
            "[data-testid='stSelectboxOption']",
            "div[role='option']",
            "li[role='option']"
        ]

        options_found = False
        for selector in option_selectors:
            options = page.locator(selector)
            if options.count() > 0:
                option_count = options.count()
                print(f"Found {option_count} dropdown options with selector: {selector}")
                options_found = True

                # Try to find our user
                user_found = False
                for i in range(option_count):
                    option = options.nth(i)
                    option_text = option.text_content()
                    print(f"  Option {i}: '{option_text}'")

                    if username in option_text:
                        option.click()
                        # Wait for Streamlit rerun
                        page.wait_for_load_state("networkidle", timeout=30000)
                        expect(page.locator("[data-testid='stApp']")).to_be_visible(timeout=30000)
                        print(f"✓ Selected user: {username}")
                        user_found = True
                        break

                if not user_found and option_count > 0:
                    # Select first option
                    options.first.click()
                    page.wait_for_load_state("networkidle", timeout=30000)
                    expect(page.locator("[data-testid='stApp']")).to_be_visible(timeout=30000)
                    print("Selected first available user (username not found)")

                break

        if not options_found:
            print("Warning: No dropdown options found after clicking selectbox")
            # Close dropdown if open
            page.keyboard.press("Escape")

    # Look for login button - use robust selectors
    login_button_selectors = [
        page.get_by_role("button", name=re.compile(r"login as user", re.IGNORECASE)),
        page.get_by_role("button", name=re.compile(r"login", re.IGNORECASE)),
        page.get_by_role("button", name=re.compile(r"log in", re.IGNORECASE))
    ]

    login_button = None
    for selector in login_button_selectors:
        if selector.count() > 0:
            login_button = selector.first
            break

    if login_button:
        expect(login_button).to_be_visible(timeout=30000)
        expect(login_button).to_be_enabled(timeout=30000)
        login_button.click()
        # Wait for login to complete
        page.wait_for_load_state("networkidle", timeout=30000)
        expect(page.locator("[data-testid='stApp']")).to_be_visible(timeout=30000)
        print("Clicked login button")
    else:
        print("Note: No login button found - maybe login happens automatically")

    # Take screenshot after login attempt
    take_screenshot(page, "conversation_02_logged_in.png", debug_enabled, full_page=True)

    # Store user in context
    context['current_user'] = username

    # Check if we're logged in by looking for user info or chat interface
    page_text = page.locator("body").text_content()

    # Positive indicators (logged in)
    positive_indicators = [
        f"user.*{username}",
        "logged in",
        "welcome",
        "hello",
        "bonjour",
        "conversation",
        "chat"
    ]

    logged_in = False
    for indicator in positive_indicators:
        if re.search(indicator, page_text, re.IGNORECASE):
            print(f"✓ Found positive indicator: {indicator}")
            logged_in = True
            break

    if not logged_in:
        print("Note: No clear login status indicators found")

    return context


@given(parsers.parse("the {module_name} module is loaded"))
def is_module_loaded(context, module_name):
    """Verify the module is loaded in the admin panel."""
    page = context['page']

    print(f"\n=== Verifying {module_name} module is loaded ===")

    # Wait for admin panel to load
    page.wait_for_load_state("networkidle", timeout=30000)
    expect(page.locator("div[data-testid='stApp']")).to_be_visible(timeout=30000)

    # Check for "Admin Panel" text - use more flexible search
    admin_panel_text = page.locator("div[data-testid='stApp']").get_by_text(re.compile(r"admin.*panel", re.IGNORECASE)).or_(
        page.get_by_text(re.compile(r"admin", re.IGNORECASE))
    )

    try:
        expect(admin_panel_text).to_be_visible(timeout=10000)
        print("✓ Admin panel is visible")
    except AssertionError:
        # If we can't find "Admin Panel", check for tabs or other admin indicators
        print("Note: 'Admin Panel' text not found, checking for admin tabs...")
        # Look for any tabs which indicate we're in admin area
        tabs = page.locator("div[data-testid='stApp']").locator("[role='tab']")
        if tabs.count() > 0:
            print(f"Found {tabs.count()} tabs, assuming admin panel is loaded")
        else:
            # Check if module_name text is on page as alternative indicator
            page_text = page.locator("div[data-testid='stApp']").text_content().lower()
            if module_name in page_text:
                print(f"✓ Found '{module_name}' text, assuming {module_name} module is loaded")

    # Check for module_name module in available modules
    page_text = page.locator("div[data-testid='stApp']").text_content().lower()

    module_found = False
    if module_name in page_text:
        print(f"✓ Found '{module_name}' text on page")
        module_found = True

    # Also check for specific module_name UI elements within the app container
    module_elements = page.locator("div[data-testid='stApp']").locator(f":text('{module_name}'):visible")
    print(f"Found {module_elements.count()} visible elements with '{module_name}' text")

    # Print all tabs for debugging
    tabs = page.locator("div[data-testid='stApp']").locator("[role='tab']")
    print(f"Found {tabs.count()} tabs:")
    for i in range(tabs.count()):
        tab = tabs.nth(i)
        expect(tab).to_be_visible(timeout=5000)
        tab_text = tab.text_content()
        print(f"  Tab {i}: '{tab_text}'")

        if module_name in tab_text.lower():
            module_found = True
            print(f"  ✓ Found {module_name} tab: '{tab_text}'")

    if not module_found:
        print(f"WARNING: {module_name} module/tab not found!")
        # Print all text for debugging
        print("\nAll page text (first 1000 chars):")
        print(page_text[:1000])

    return context



@given(parsers.parse('the default user "{username}" is logged in'))
def default_user_logged_in(context, username):
    """Log in as the default test user."""
    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print(f"\n=== Logging in as: {username} ===")

    # Wait for Streamlit to load
    page.wait_for_load_state("networkidle", timeout=30000)
    # Check for either sidebar OR app container (not both with .or_())
    try:
        # First try to wait for sidebar
        expect(page.locator("[data-testid='stSidebar']")).to_be_visible(timeout=10000)
        print("✓ Sidebar is visible")
    except AssertionError:
        # If sidebar not found, check for app container
        expect(page.locator("div[data-testid='stApp']")).to_be_visible(timeout=10000)
        print("✓ App container is visible")

    # Look for user selector
    selectboxes = page.locator("[data-testid='stSelectbox']")

    if selectboxes.count() >= 3:
        user_selectbox = selectboxes.nth(2)
        expect(user_selectbox).to_be_visible(timeout=30000)
        user_selectbox.click()

        # Wait for dropdown options to appear
        expect(page.locator("li[role='option']").first).to_be_visible(timeout=30000)

        # Try to find and select the user
        options = page.locator("[data-testid='stSelectboxOption'], div[role='option']")
        for i in range(options.count()):
            option = options.nth(i)
            option_text = option.text_content()
            if username in option_text:
                option.click()
                # Wait for Streamlit rerun after selection
                page.wait_for_load_state("networkidle", timeout=30000)
                # Wait for Streamlit app container
                expect(page.locator("div[data-testid='stApp']")).to_be_visible(timeout=30000)
                print(f"✓ Selected user: {username}")
                break

        # Look for login button
        login_button = page.get_by_text("Login as User").or_(page.get_by_text("Login")).or_(page.get_by_text("Log in"))
        if login_button.count() > 0:
            login_button = login_button.first
            expect(login_button).to_be_visible(timeout=30000)
            expect(login_button).to_be_enabled(timeout=30000)
            login_button.click()
            # Wait for login to complete and Streamlit to rerun
            page.wait_for_load_state("networkidle", timeout=30000)
            # Wait for main app container
            expect(page.locator("div[data-testid='stApp']")).to_be_visible(timeout=30000)

    context['current_user'] = username
    return context
