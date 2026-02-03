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

from tests.step_defs.common_steps import _wait_for_app_stable, _click_button_by_texts, _robust_header_verification


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
