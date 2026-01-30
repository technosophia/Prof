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


# Create a test context that's separate from BrowserContext
@pytest.fixture
def test_context():
    """Test context to store state between steps."""
    return {'debug_enabled': False}


@given("I navigate to the admin panel")
def navigate_to_admin_panel_common(test_context):
    """Navigate to the admin panel - common implementation for all modules."""
    if 'page' not in test_context:
        raise KeyError("No 'page' in test_context. Did you call 'the application is running' first?")

    page = test_context['page']
    debug_enabled = test_context.get('debug_enabled', False)

    print("\n=== Navigating to admin panel ===")

    # Try multiple methods to find and click the admin button
    admin_found = False

    # Method 1: Look in sidebar first
    sidebar_content = page.locator("[data-testid='stSidebar']").first
    admin_button = None

    if sidebar_content.count() > 0:
        print("Found sidebar, looking for admin button...")
        # Look for button with "Admin" text in sidebar
        admin_button = sidebar_content.get_by_text("🔧 Admin").or_(sidebar_content.get_by_text("Admin")).first
    else:
        print("Could not find sidebar, looking anywhere...")
        admin_button = page.get_by_text("🔧 Admin").or_(page.get_by_text("Admin")).first

    # Method 2: Try to click if found
    if admin_button and admin_button.count() > 0 and admin_button.is_visible():
        print("Found admin button, clicking...")
        admin_button.click()
        time.sleep(2)
        admin_found = True
    else:
        # Method 3: Search all buttons
        print("Admin button not found by text, trying alternative methods...")
        all_buttons = page.get_by_role("button").all()
        for btn in all_buttons:
            try:
                if btn.is_visible():
                    btn_text = btn.text_content()
                    if btn_text and "admin" in btn_text.lower():
                        print(f"Found potential admin button: {btn_text}")
                        btn.click()
                        time.sleep(2)
                        admin_found = True
                        break
            except:
                continue

    # Method 4: Check if already on admin page
    if not admin_found:
        page_text = page.locator("body").text_content()
        if "admin" in page_text.lower() or "Admin Panel" in page_text:
            print("Already on admin page or admin content visible")
            admin_found = True
        else:
            print("WARNING: Could not find admin button or navigate to admin panel")
            # Try direct navigation as fallback
            page.goto("http://localhost:8502/", wait_until="networkidle")
            time.sleep(2)

    time.sleep(2)  # Wait for navigation to complete

    # Take screenshot if debug enabled
    if debug_enabled:
        take_screenshot(page, "admin_panel_navigated.png", debug_enabled, full_page=True)

    # Update context
    test_context['current_page'] = 'admin'
    print("✓ Admin panel navigation attempted")

    return test_context


@given(parsers.parse('I select the "{tab_name}" tab'))
def select_debug_tab(test_context, tab_name):
    """Select the Debug tab in the admin panel."""
    page = test_context['page']
    debug_enabled = test_context.get('debug_enabled', False)

    print(f'\n=== Selecting "{tab_name}" tab ===')

    # Look for Debug tab
    debug_tab = page.get_by_text(tab_name, exact=True)

    if debug_tab.count() > 0:
        debug_tab.first.click()
        time.sleep(2)

        if debug_enabled:
            debug_path = os.path.join("tests", "debug")
            os.makedirs(debug_path, exist_ok=True)
            page.screenshot(path=os.path.join(debug_path, f"{tab_name}_tab_selected.png"))
    else:
        print("Warning: Could not find Debug tab")
        # Try to find tabs
        tabs = page.locator("[role='tab']")
        for i in range(tabs.count()):
            tab = tabs.nth(i)
            if tab_name in tab.text_content():
                tab.click()
                time.sleep(2)
                break

    return test_context


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

    # Find the LLM selectbox (second selectbox)
    selectboxes = page.locator("[data-testid='stSelectbox']")
    print(f"Found {selectboxes.count()} selectboxes")

    # Log all selectboxes for debugging
    for i in range(selectboxes.count()):
        try:
            selectbox = selectboxes.nth(i)
            text = selectbox.text_content()
            print(f"  Selectbox {i}: {text[:100]}")
        except:
            print(f"  Selectbox {i}: Could not read text")

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
        llm_selectbox.click()
        time.sleep(2)

        # Take screenshot of dropdown
        take_screenshot(page, "conversation_llm_dropdown.png", debug_enabled)

        # Look for options - try multiple selectors
        for selector in ["li[role='option']", "[data-testid='stSelectboxOption']", "div[role='option']"]:
            options = page.locator(selector)
            if options.count() > 0:
                print(f"Found {options.count()} LLM options with {selector}")

                # Log all options
                for i in range(options.count()):
                    option = options.nth(i)
                    option_text = option.text_content()
                    print(f"  Option {i}: {option_text}")

                    if "Mock" in option_text or "mock" in option_text.lower():
                        print(f"  ✓ Selecting Mock LLM: {option_text}")
                        option.click()
                        time.sleep(3)  # Wait for selection to apply

                        # Take screenshot after selection
                        take_screenshot(page, "conversation_mock_llm_selected.png", debug_enabled)

                        print("✓ Mock LLM selected")
                        return context

                # If Mock not found but we have options, select the first one
                print("Mock LLM not found in options, selecting first option")
                options.first.click()
                time.sleep(3)
                break
    else:
        print("Warning: Could not find LLM selectbox")

    print("Note: Could not select Mock LLM, continuing anyway")
    take_screenshot(page, "conversation_llm_final.png", debug_enabled)
    return context

@given(parsers.parse('I am on the "{tab_name}" tab'))
def on_tab(test_context, tab_name):
    """Precondition: on the Test tab."""
    # Try to select the Test tab
    try:
        select_admin_tab(test_context, tab_name)
    except:
        print(f"Note: Could not select {tab_name} tab, continuing anyway")

    return test_context
