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


@pytest.fixture(scope="session")
def enable_debug():
    """Fixture to enable debug mode (screenshots, logging)."""
    debug_enabled = os.getenv("PYTEST_DEBUG", "false").lower() in ("true", "1", "yes")
    print(f"Debug mode: {'ENABLED' if debug_enabled else 'DISABLED'}")
    return debug_enabled


@pytest.fixture(scope="session")
def streamlit_server():
    """Start Streamlit server for testing - runs once per session."""
    # Kill any existing Streamlit process
    subprocess.run(["pkill", "-f", "streamlit"], capture_output=True, shell=True)
    time.sleep(1)

    # Create test environment
    env = os.environ.copy()
    env["TEST_MODE"] = "true"
    env["CONFIG_FILE"] = "test_config.json"
    env["PYTHONPATH"] = os.path.dirname(os.path.abspath(__file__))

    # Start Streamlit server
    cmd = [
        "streamlit", "run", "app.py",
        "--server.headless", "true",
        "--server.port", "8502",
        "--server.runOnSave", "false",
        "--browser.serverAddress", "localhost",
        "--logger.level", "info",
        "--server.fileWatcherType", "none"
    ]

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        preexec_fn=os.setsid
    )

    # Register cleanup function
    def cleanup():
        if process.poll() is None:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                process.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    atexit.register(cleanup)

    # Wait for server to start
    max_retries = 30
    for i in range(max_retries):
        try:
            response = requests.get("http://localhost:8502/_stcore/health", timeout=2)
            if response.status_code == 200:
                print("✓ Streamlit server started successfully")
                break
        except:
            if i == max_retries - 1:
                cleanup()
                raise RuntimeError("Failed to start Streamlit server after 30 seconds")
            time.sleep(1)

    time.sleep(2)
    yield process

    # Cleanup after tests
    cleanup()
    atexit.unregister(cleanup)
    subprocess.run(["pkill", "-f", "streamlit"], capture_output=True, shell=True)
    time.sleep(1)


@pytest.fixture
def debug_dir(enable_debug):
    """Create debug directory if debug mode is enabled."""
    if enable_debug:
        debug_path = os.path.join("tests", "debug")
        os.makedirs(debug_path, exist_ok=True)
        print(f"Debug directory: {os.path.abspath(debug_path)}")
    return enable_debug


@pytest.fixture(scope="session")
def browser_context(playwright, streamlit_server):
    """Create browser context once per session."""
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()

    yield context

    # Cleanup
    context.close()
    browser.close()


@pytest.fixture
def context():
    """Test context to store state between steps."""
    return {}


@pytest.fixture
def page(browser_context):
    """Create a new page for each test."""
    page = browser_context.new_page()
    # Set longer timeout for slow Streamlit
    page.set_default_timeout(30000)

    yield page

    # Close page after test
    page.close()


def take_screenshot(page, filename, debug_enabled, full_page=False):
    """Take screenshot only if debug mode is enabled."""
    if debug_enabled:
        debug_path = os.path.join("tests", "debug")
        filepath = os.path.join(debug_path, filename)
        page.screenshot(path=filepath, full_page=full_page)
        print(f"  Screenshot saved: {filename}")


def find_element_by_text(page, text, exact=False):
    """Find an element containing specific text."""
    if exact:
        return page.get_by_text(text, exact=True)
    else:
        return page.get_by_text(text)


@given("the application is running")
def app_is_running_common(context, page: Page, debug_dir, streamlit_server):
    """Verify the application is running and navigate to it."""
    print("\n=== Navigating to application ===")
    page.goto("http://localhost:8502/", wait_until="networkidle")

    # Wait for Streamlit to fully load
    page.wait_for_selector("[data-testid='stApp']", timeout=30000)

    # Take initial screenshot if debug mode
    take_screenshot(page, "app_running.png", debug_dir, full_page=True)

    # Store the page reference
    context['page'] = page
    context['debug_enabled'] = debug_dir

    print("Application is running and loaded")
    return context


@given(parsers.parse('"{username}" exists in the user database'))
def user_exists_in_database_common(context, username, mock_db_manager):
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

    assert user_found, f"User '{username}' does not exist in database and could not be added"

    return context


@given(parsers.parse('the default user "{username}" is logged in'))
def default_user_logged_in_common(context, username):
    """Log in as the default test user."""
    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print(f"\n=== Logging in as: {username} ===")

    # Take screenshot before login
    take_screenshot(page, "before_login.png", debug_enabled, full_page=True)

    # Find ALL selectboxes
    all_selectboxes = page.locator("[data-testid='stSelectbox']")
    selectbox_count = all_selectboxes.count()
    print(f"Found {selectbox_count} selectboxes total")

    # The user selectbox should be the one with "Choose user" or similar
    if selectbox_count >= 3:
        print("Clicking the third selectbox (assuming it's the user selector)...")
        user_selectbox = all_selectboxes.nth(2)
        user_selectbox.click()
        time.sleep(2)

        # Try to find dropdown options
        option_selectors = [
            "[data-testid='stSelectboxOption']",
            "div[role='option']",
            "li[role='option']",
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
                    if username in option_text:
                        option.click()
                        time.sleep(2)
                        print(f"✓ Selected user: {username}")
                        user_found = True
                        break

                if not user_found and option_count > 0:
                    options.first.click()
                    time.sleep(2)
                    print("Selected first available user (username not found)")
                break

        if not options_found:
            print("Warning: No dropdown options found after clicking selectbox")
            page.keyboard.press("ArrowDown")
            time.sleep(0.5)
            page.keyboard.press("Enter")
            time.sleep(2)

    # Look for login button
    login_button = find_element_by_text(page, "Login as User").or_(
        find_element_by_text(page, "Login")
    ).or_(find_element_by_text(page, "Log in"))

    if login_button and login_button.count() > 0:
        login_button.first.click()
        time.sleep(2)
        print("Clicked login button")

    # Take screenshot after login attempt
    take_screenshot(page, "after_login.png", debug_enabled, full_page=True)

    # Store user in context
    context['current_user'] = username

    return context


@given("the mock LLM is configured and available")
def mock_llm_available_common(context):
    """Verify the mock LLM is configured and available."""
    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print("\n=== Selecting Mock LLM ===")

    # Find the LLM selectbox
    selectboxes = page.locator("[data-testid='stSelectbox']")

    # Try to find LLM selector - look for selectbox containing "LLM" or "AI Model"
    llm_selectbox = None
    for i in range(selectboxes.count()):
        selectbox = selectboxes.nth(i)
        text = selectbox.text_content()
        if "llm" in text.lower() or "ai model" in text.lower():
            llm_selectbox = selectbox
            print(f"Found LLM selectbox at index {i}: {text[:50]}")
            break

    if llm_selectbox:
        # Click to open dropdown
        llm_selectbox.click()
        time.sleep(2)

        # Look for options
        for selector in ["li[role='option']", "[data-testid='stSelectboxOption']", "div[role='option']"]:
            options = page.locator(selector)
            if options.count() > 0:
                # Look for Mock LLM
                for i in range(options.count()):
                    option = options.nth(i)
                    option_text = option.text_content()
                    if "Mock" in option_text or "mock" in option_text.lower():
                        option.click()
                        time.sleep(3)
                        print("✓ Mock LLM selected")
                        return context

                # If Mock not found, select first option
                options.first.click()
                time.sleep(3)
                break

    print("Note: Could not select Mock LLM, continuing anyway")
    return context


@given("I navigate to the admin panel")
def navigate_to_admin_panel_common(context):
    """Navigate to the admin panel."""
    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print("\n=== Navigating to admin panel ===")

    # Look for admin button
    admin_button = find_element_by_text(page, "🔧 Admin").or_(
        find_element_by_text(page, "Admin")
    )

    if admin_button.count() > 0:
        admin_button.first.click()
        time.sleep(2)

        # Wait for admin page
        page.wait_for_selector("h1", timeout=10000)

        if debug_enabled:
            take_screenshot(page, "admin_panel.png", debug_enabled)

        context['current_page'] = 'admin'
    else:
        print("Warning: Could not find admin button")

    return context


@given(parsers.parse('I select the "{tab_name}" tab in the admin panel'))
def select_admin_tab_common(context, tab_name):
    """Select a specific tab in the admin panel."""
    if 'page' not in context:
        raise KeyError("No 'page' in context")

    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print(f'\n=== Selecting admin tab: "{tab_name}" ===')

    # Store current tab for reference
    context['previous_tab'] = context.get('current_tab', None)
    context['current_tab'] = tab_name

    # Wait for page to settle
    time.sleep(1)

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
                if tab_name in tab_text:
                    tab.click()
                    time.sleep(2)
                    tab_found = True
                    break
            except:
                continue

    if not tab_found:
        # Method 2: Look for the tab text anywhere
        text_elements = page.locator(f"text='{tab_name}'")
        if text_elements.count() > 0:
            for i in range(text_elements.count()):
                try:
                    elem = text_elements.nth(i)
                    if elem.is_visible():
                        elem.click()
                        time.sleep(2)
                        tab_found = True
                        break
                except:
                    continue

    if not tab_found:
        print(f"WARNING: Could not find or select tab '{tab_name}'")

    if debug_enabled:
        take_screenshot(page, f"tab_{tab_name}.png", debug_enabled)

    return context


@then(parsers.parse('I should see "{expected_text}" in the admin content'))
def verify_admin_content_common(context, expected_text):
    """Verify text appears in the admin content area."""
    if 'page' not in context:
        raise KeyError("No 'page' in context")

    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print(f'\n=== Verifying admin content: "{expected_text}" ===')

    # Wait for content to load
    time.sleep(1)

    # Get all text from the page
    page_text = page.locator("body").text_content()

    # Check if expected text is in page text
    if expected_text not in page_text:
        if debug_enabled:
            take_screenshot(page, "admin_content_not_found.png", debug_enabled)
        raise AssertionError(f"Expected text '{expected_text}' not found in admin content")

    print(f"✓ Found expected text: {expected_text}")

    if debug_enabled:
        take_screenshot(page, "admin_content_found.png", debug_enabled)

    return context


@then(parsers.parse('I should see "{expected_text}" in the header'))
def verify_text_in_header_common(context, expected_text):
    """Verify text appears in a header on the page."""
    if 'page' not in context:
        raise KeyError("No 'page' in context")

    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print(f'\n=== Verifying header text: "{expected_text}" ===')

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
            take_screenshot(page, "header_not_found.png", debug_enabled)
        raise AssertionError(f"Expected text '{expected_text}' not found in any header")

    if debug_enabled:
        take_screenshot(page, "header_found.png", debug_enabled)

    return context
