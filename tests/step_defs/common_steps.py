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
    test_context['current_page'] = 'admin'
    print("✓ Admin panel navigation completed")

    return test_context


@given(parsers.parse('I select the "{tab_name}" tab'))
def select_debug_tab(test_context, tab_name):
    """Select a tab in the admin panel."""
    page = test_context['page']
    debug_enabled = test_context.get('debug_enabled', False)

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

    return test_context



@given(parsers.parse('I am on the "{tab_name}" tab'))
def on_tab(test_context, tab_name):
    """Precondition: on the Test tab."""
    # Try to select the Test tab
    try:
        select_admin_tab(test_context, tab_name)
    except:
        print(f"Note: Could not select {tab_name} tab, continuing anyway")

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
