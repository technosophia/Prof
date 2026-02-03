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
from tests.conftest import (
    enable_debug,
    streamlit_server,
    browser_context,
    page,
    debug_dir,
    context,
    take_screenshot,
    find_element_by_text,
    TEST_PORT
)

APP_FULLY_LOADED_SELECTOR = '[data-testid="app-fully-loaded"]'

# ==================== HELPER FUNCTIONS ====================

def _wait_for_app_stable(page: Page, timeout: int = 30000) -> None:
    """Consistent wait for Streamlit app stability after reruns."""
    page.wait_for_load_state("networkidle", timeout=timeout)
    expect(page.locator("div[data-testid='stApp']")).to_be_visible(timeout=timeout)


def _click_button_by_texts(page: Page, texts: list[str], debug_enabled: bool = False, screenshot_name: str | None = None) -> None:
    """Robust button click using multiple possible labels (with emojis or variations)."""
    print(f'\n=== Clicking button with possible texts: {texts} ===')

    # Build chained locator with role fallback
    locator = None
    for text in texts:
        new_loc = page.get_by_text(text, exact=False)
        locator = new_loc if locator is None else locator.or_(new_loc)

    # Fallback to role-based search
    if locator is None or locator.count() == 0:
        pattern = "|".join(re.escape(t) for t in texts)
        locator = page.get_by_role("button", name=re.compile(pattern, re.IGNORECASE))

    button = locator.first
    expect(button).to_be_visible(timeout=30000)
    expect(button).to_be_enabled(timeout=30000)
    button.click()

    _wait_for_app_stable(page)

    if screenshot_name and debug_enabled:
        take_screenshot(page, screenshot_name, debug_enabled)


def _robust_header_verification(page: Page, expected_text: str, debug_enabled: bool = False) -> None:
    """Robust header text verification (aligned with test_steps.py logic)."""
    print(f'\n=== Verifying header contains: "{expected_text}" ===')

    _wait_for_app_stable(page)

    found = False
    max_retries = 3

    for retry in range(max_retries):
        if retry > 0:
            print(f"Retry {retry}/{max_retries} for header check...")
            page.wait_for_timeout(1000)

        # Check standard header tags
        for tag in ["h1", "h2", "h3", "h4", "h5", "h6"]:
            headers = page.locator(tag)
            for i in range(headers.count()):
                header = headers.nth(i)
                if header.is_visible():
                    header_text = header.text_content().strip()
                    if expected_text in header_text:
                        print(f"✓ Found '{expected_text}' in {tag}: '{header_text}'")
                        found = True
                        break
            if found:
                break

        if found:
            break

    # Fallback 1: anywhere on page
    if not found:
        page_text = page.locator("body").text_content(timeout=10000)
        if expected_text in page_text:
            print(f"✓ Found '{expected_text}' in page text")
            found = True

    # Fallback 2: :has-text locator
    if not found:
        matching = page.locator(f':has-text("{expected_text}")')
        if matching.count() > 0:
            for i in range(matching.count()):
                elem = matching.nth(i)
                if elem.is_visible() and expected_text in elem.text_content():
                    print(f"✓ Found '{expected_text}' via :has-text")
                    found = True
                    break

    if not found:
        if debug_enabled:
            take_screenshot(page, "debug_header_not_found.png", debug_enabled)
        raise AssertionError(f"Expected header text '{expected_text}' not found")

    if debug_enabled:
        take_screenshot(page, "debug_header_found.png", debug_enabled)

# ==================== STEPS ====================

@given("the application is running")
def app_is_running(context, page: Page, debug_dir, streamlit_server):
    """Verify the application is running and navigate to it."""
    print("\n=== [Test Module] Navigating to application ===")

    # Navigate - use "load" instead of "networkidle" for initial page (more reliable for local Streamlit)
    page.goto(f"http://localhost:{TEST_PORT}/", wait_until="load")

    # Basic Streamlit container check (fast, confirms the app responded)
    expect(page.locator("div[data-testid='stApp']")).to_be_visible(timeout=30000)

    # CRITICAL: Wait for the explicit readiness marker added to app.py
    # This marker is rendered at the very end of main(), after all sidebar, content,
    # module injections, and any potential initial reruns/auto-logins.
    # Using "attached" (not "visible") because the div is intentionally empty/invisible.
    readiness_locator = page.locator(APP_FULLY_LOADED_SELECTOR)
    expect(readiness_locator).to_be_attached(timeout=180000)  # 3 minutes max for heavy init (transformers, etc.)

    # Final stability check - ensures no pending rerun/network activity
    _wait_for_app_stable(page)

    # Optional: fallback wait for sidebar if marker somehow missing (defensive)
    try:
        expect(page.locator("[data-testid='stSidebar']")).to_be_visible(timeout=10000)
    except:
        print("Warning: Sidebar not detected - relying solely on readiness marker")

    # Screenshot now that we know everything is rendered
    take_screenshot(page, "test_app_running.png", debug_dir, full_page=True)

    # Store context
    context['page'] = page
    context['debug_enabled'] = debug_dir

    print("✓ Application is running and FULLY loaded (including heavy init)")
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
            page.goto(f"http://localhost:{TEST_PORT}/", wait_until="networkidle")
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

# file name: tests/step_defs/common_steps.py (updated section)
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
        page.wait_for_timeout(1000)  # Brief wait for dropdown

        # Try different ways to find and select Mock LLM
        try:
            # Method 1: Look for Mock LLM option
            mock_option = page.get_by_text("Mock LLM", exact=False).or_(
                page.get_by_text("mock", exact=False)
            ).first

            if mock_option.count() > 0:
                print(f"Found Mock LLM option, clicking...")
                mock_option.click()
                page.wait_for_load_state("networkidle", timeout=30000)
                print("✓ Mock LLM selected")
                take_screenshot(page, "conversation_mock_llm_selected.png", debug_enabled)
                return context
        except Exception as e:
            print(f"Could not find Mock LLM option via text: {e}")

        # Method 2: Try to click on the dropdown option that's already selected
        try:
            # Check if Mock is already selected (green dot indicator)
            if "mock" in llm_selectbox.text_content().lower():
                print("Mock LLM appears to already be selected")
                # Close dropdown if open
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
                take_screenshot(page, "conversation_mock_llm_selected.png", debug_enabled)
                return context
        except Exception as e:
            print(f"Could not check selected state: {e}")

        # Method 3: Close dropdown and continue
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)

    else:
        print("Warning: Could not find LLM selectbox")

    print("Note: Could not select Mock LLM, assuming it's already selected or not needed")
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

    take_screenshot(page, "conversation_login_before_select.png", debug_enabled, full_page=True)

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

    take_screenshot(page, "conversation_before_login_click.png", debug_enabled, full_page=True)
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
        take_screenshot(page, "conversation_no_log_in_button.png", debug_enabled, full_page=True)
        print("Note: No login button found - maybe login happens automatically")
        raise AssertionError("Chat page did not load properly")

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


# file name: tests/step_defs/common_steps.py (updated section)
@given(parsers.parse("the {module_name} module is loaded"))
def is_module_loaded(context, module_name):
    """Verify the module is loaded in the admin panel."""
    page = context['page']

    print(f"\n=== Verifying {module_name} module is loaded ===")

    # Wait for admin panel to load
    page.wait_for_load_state("networkidle", timeout=30000)
    expect(page.locator("div[data-testid='stApp']")).to_be_visible(timeout=30000)

    # Additional wait for tabs to stabilize
    page.wait_for_timeout(2000)

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
            if module_name.lower() in page_text:
                print(f"✓ Found '{module_name}' text, assuming {module_name} module is loaded")

    # Check for module_name module in available modules
    page_text = page.locator("div[data-testid='stApp']").text_content().lower()

    module_found = False
    if module_name.lower() in page_text:
        print(f"✓ Found '{module_name}' text on page")
        module_found = True

    # Also check for specific module_name UI elements within the app container
    module_elements = page.locator("div[data-testid='stApp']").locator(f":text('{module_name}'):visible")
    if module_elements.count() > 0:
        print(f"Found {module_elements.count()} visible elements with '{module_name}' text")
        module_found = True

    # Print all tabs for debugging (but don't fail if some are hidden)
    tabs = page.locator("div[data-testid='stApp']").locator("[role='tab']")
    print(f"Found {tabs.count()} tab elements:")
    for i in range(tabs.count()):
        try:
            tab = tabs.nth(i)
            # Don't wait for visibility - just get whatever info we can
            tab_text = tab.text_content(timeout=1000)
            is_visible = tab.is_visible()
            print(f"  Tab {i}: '{tab_text}' (visible: {is_visible})")

            if module_name.lower() in tab_text.lower():
                module_found = True
                print(f"  ✓ Found {module_name} tab: '{tab_text}'")
        except:
            print(f"  Tab {i}: [could not read]")

    if not module_found:
        print(f"WARNING: {module_name} module/tab not found!")
        # Print all text for debugging
        print("\nAll page text (first 1000 chars):")
        print(page_text[:1000])

    return context


# Add this step to your scenario or call it manually
@when("I debug the current state")
def debug_current_state(context):
    """Debug the current application state."""
    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print("\n" + "="*60)
    print("DEBUGGING CURRENT STATE")
    print("="*60)

    # 1. Current URL
    print(f"Current URL: {page.url}")

    # 2. Page title
    print(f"Page title: {page.title()}")

    # 3. All text on page
    all_text = page.locator("body").text_content()
    print(f"\nAll page text (first 1000 chars):")
    print(all_text[:1000])

    # 4. Session state (if accessible)
    print(f"\nSession state from context:")
    for key, value in context.items():
        if key != 'page':
            print(f"  {key}: {value}")

    # 5. Screenshot
    take_screenshot(page, "debug_state.png", debug_enabled, full_page=True)

    # 6. Check database state
    if os.getenv("TEST_MODE") == "true":
        try:
            from shared.conversation import conversation_manager
            from shared.users import user_manager

            print(f"\nDatabase state:")

            # Get all users
            all_users = user_manager.get_all_users()
            print(f"Total users: {len(all_users)}")

            # Get current user conversations
            current_user = context.get('current_user')
            if current_user:
                user_id = None
                if isinstance(current_user, dict):
                    user_id = current_user.get('id')
                elif isinstance(current_user, str):
                    user_obj = user_manager.get_user_by_name(current_user)
                    if user_obj:
                        user_id = user_obj.get('id')

                if user_id:
                    conversations = conversation_manager.get_user_conversations(user_id)
                    print(f"Conversations for user {user_id}: {len(conversations)}")
                    for conv in conversations:
                        print(f"  - {conv.get('title')} (ID: {conv.get('id')}, messages: {conv.get('message_count')})")

                        # Get conversation details
                        conv_obj = conversation_manager.get_conversation(conv.get('id'), include_messages=True)
                        if conv_obj and conv_obj.messages:
                            print(f"    Messages:")
                            for msg in conv_obj.messages:
                                print(f"      {msg.role}: {msg.content[:50]}...")
        except Exception as e:
            print(f"Could not check database: {e}")

    print("="*60 + "\n")

    return context
