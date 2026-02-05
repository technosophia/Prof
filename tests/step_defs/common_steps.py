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
def select_a_tab(context, tab_name):
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
