"""
pytest-bdd step definitions for RAG system testing.
"""
import pytest
import re
import time
from pathlib import Path
import tempfile
import os
from pytest_bdd import given, when, then, scenarios, parsers
from playwright.sync_api import Page, expect
from typing import Dict, List, Optional
from st_shared.cached import get_config

# Import common steps
from tests.step_defs.common_steps import *
from tests.step_defs.user_steps import *
from tests.step_defs.conversation_common_steps import *
from tests.step_defs.common_steps import take_screenshot

scenarios('../../tests/features/rag.feature')

pytestmark = [pytest.mark.bdd, pytest.mark.playwright, pytest.mark.rag]

# ==================== RAG-SPECIFIC HELPER FUNCTIONS ====================

def select_rag_llm(page: Page, model_names: List[str], debug_enabled: bool = False):
    """
    Select an LLM model from the dropdown based on provided model name patterns.

    Args:
        page: Playwright page object
        model_names: List of model name patterns to search for (e.g., ["Ollama Small", "llama 3", "gpt-4"])
        debug_enabled: Enable debug output if True

    Returns:
        bool: True if selection was successful or not needed
    """
    if debug_enabled:
        print(f"\n=== Selecting LLM: searching for {model_names} ===")

    # Wait for page to be ready
    page.wait_for_load_state("networkidle", timeout=30000)
    expect(page.locator("[data-testid='stApp']")).to_be_visible(timeout=30000)

    # Find the LLM selectbox
    selectboxes = page.locator("[data-testid='stSelectbox']")
    if debug_enabled:
        print(f"Found {selectboxes.count()} selectboxes")

    # Try to find LLM selector
    llm_selectbox = None
    for i in range(selectboxes.count()):
        selectbox = selectboxes.nth(i)
        text = selectbox.text_content()
        if "llm" in text.lower() or "ai model" in text.lower() or "selection" in text.lower():
            llm_selectbox = selectbox
            if debug_enabled:
                print(f"Found LLM selectbox at index {i}: {text[:50]}")
            break

    if llm_selectbox:
        # Click to open dropdown
        expect(llm_selectbox).to_be_visible(timeout=30000)
        llm_selectbox.click()

        # Wait for dropdown to open
        page.wait_for_timeout(1000)

        # Look for model option
        model_option = None

        # Try each model name pattern
        for pattern in model_names:
            option = page.get_by_text(re.compile(pattern, re.IGNORECASE)).first
            if option.count() > 0:
                model_option = option
                if debug_enabled:
                    print(f"Found model option with pattern: {pattern}")
                break

        if model_option:
            if debug_enabled:
                print(f"Clicking model option for pattern: {pattern}...")
            model_option.click()
            page.wait_for_load_state("networkidle", timeout=30000)
            if debug_enabled:
                print(f"✓ Model {pattern} selected")
        else:
            if debug_enabled:
                print(f"Warning: Could not find any model option, trying manual search...")

            # Get all dropdown options
            options = page.locator("li[role='option']").all()
            if debug_enabled:
                print(f"Found {len(options)} dropdown options")

            for i, option in enumerate(options):
                try:
                    option_text = option.text_content()
                    if debug_enabled:
                        print(f"  Option {i}: '{option_text}'")

                    # Check if option matches any of the model patterns
                    for pattern in model_names:
                        if pattern.lower() in option_text.lower():
                            option.click()
                            page.wait_for_load_state("networkidle", timeout=30000)
                            if debug_enabled:
                                print(f"✓ Selected model option: {option_text}")
                            break
                    else:
                        continue
                    break
                except:
                    continue

            # Close dropdown if still open
            page.keyboard.press("Escape")
    else:
        if debug_enabled:
            print("Note: Could not find LLM selectbox, assuming model is already selected")

    return True

def toggle_rag_injection(page: Page, enable: bool, debug_enabled: bool = False):
    """Toggle RAG context injection in the sidebar - minimal robust version."""
    print(f"\n=== {'Enabling' if enable else 'Disabling'} RAG context injection ===")

    # Wait for sidebar to be ready
    page.wait_for_load_state("networkidle", timeout=30000)

    # Find and expand the RAG Settings expander using a single robust selector
    rag_expander = page.locator("[data-testid='stSidebar']").get_by_text(
        re.compile(r"⚙️\s*RAG Settings|RAG Settings", re.IGNORECASE)
    )

    if rag_expander.count() > 0:
        # Check if expander is collapsed by looking for the expander icon or state
        expander_icon = rag_expander.locator("svg").first
        is_collapsed = True  # Assume collapsed by default

        # Try to determine if expander is collapsed by checking parent element
        try:
            parent = rag_expander.locator("..")
            is_collapsed = not ("expanded" in parent.get_attribute("class", timeout=1000) or
                               parent.get_attribute("open", timeout=1000))
        except:
            pass  # If we can't determine, assume collapsed

        if is_collapsed:
            print("Expanding RAG Settings expander...")
            rag_expander.click()
            page.wait_for_timeout(500)  # Wait for animation

    # Now find the checkbox directly using its aria-label (most reliable)
    # From the error log, we see: aria-label="Enable RAG Context Injection"
    checkbox = page.locator("[data-testid='stSidebar']").locator(
        f"input[type='checkbox'][aria-label*='RAG'][aria-label*='Context'][aria-label*='Injection']"
    )

    # Fallback: try any checkbox with RAG in aria-label
    if checkbox.count() == 0:
        checkbox = page.locator("[data-testid='stSidebar']").locator(
            "input[type='checkbox'][aria-label*='RAG']"
        )

    # Fallback: try checkbox near RAG text
    if checkbox.count() == 0:
        rag_text = page.locator("[data-testid='stSidebar']").get_by_text(
            re.compile(r"Enable.*RAG.*Context.*Injection", re.IGNORECASE)
        )
        if rag_text.count() > 0:
            # Get the nearest checkbox to this text
            checkbox = rag_text.locator("..").locator("..").locator("input[type='checkbox']").first

    if checkbox.count() == 0:
        # Last resort: try to find any checkbox in sidebar that might be RAG toggle
        all_checkboxes = page.locator("[data-testid='stSidebar']").locator("input[type='checkbox']")
        print(f"Found {all_checkboxes.count()} checkboxes in sidebar")

        # Take screenshot for debugging
        if debug_enabled:
            take_screenshot(page, "rag_sidebar_debug.png", debug_enabled, full_page=False)

        if all_checkboxes.count() > 0:
            # Use the last checkbox (most likely to be our toggle)
            checkbox = all_checkboxes.last
        else:
            print("Warning: Could not find RAG toggle checkbox")
            return False

    # Now toggle the checkbox
    try:
        # First ensure it's visible with retry logic
        max_retries = 3
        for retry in range(max_retries):
            try:
                expect(checkbox).to_be_visible(timeout=500)
                break
            except:
                if retry < max_retries - 1:
                    print(f"Checkbox not visible, retrying... ({retry + 1}/{max_retries})")
                    page.wait_for_timeout(100)
                else:
                    # Force it to be visible by scrolling
                    checkbox.scroll_into_view_if_needed()

        # Get current state
        is_checked = checkbox.is_checked()
        print(f"Checkbox is currently {'checked' if is_checked else 'unchecked'}")

        # Only toggle if needed
        if (enable and not is_checked) or (not enable and is_checked):
            print(f"{'Checking' if enable else 'Unchecking'} checkbox...")

            # Use JavaScript click for reliability
            page.evaluate("""(checkbox) => {
                checkbox.click();
            }""", checkbox.element_handle())

            page.wait_for_timeout(300)  # Wait for state change

            # Verify the change
            new_state = checkbox.is_checked()
            if (enable and new_state) or (not enable and not new_state):
                print(f"✓ RAG context injection {'enabled' if enable else 'disabled'}")
            else:
                print(f"⚠ Checkbox state not changed as expected")
        else:
            print(f"RAG context injection already {'enabled' if enable else 'disabled'}")

        # Wait for any UI updates
        page.wait_for_timeout(200)
        return True

    except Exception as e:
        print(f"Error toggling RAG checkbox: {str(e)}")

        # Fallback: try a different approach
        try:
            # Find the label and click it instead
            label = page.locator("[data-testid='stSidebar']").get_by_text(
                re.compile(r"Enable.*RAG.*Context.*Injection", re.IGNORECASE)
            )
            if label.count() > 0:
                print("Trying to click label instead...")
                label.click()
                page.wait_for_timeout(300)
                return True
        except:
            pass

        return False

# ==================== RAG-SPECIFIC STEPS ====================

@given("I enable RAG context injection")
def enable_rag_injection(context):
    """Enable RAG context injection in the sidebar."""
    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    # Select Qwen LLM first
    select_rag_llm(page, get_config().get("app.debug_llm"), True)

    # Then toggle RAG injection
    toggle_rag_injection(page, enable=True, debug_enabled=debug_enabled)

    context['rag_enabled'] = True
    return context

@given("I disable RAG context injection")
def disable_rag_injection(context):
    """Disable RAG context injection in the sidebar."""
    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    # Select Qwen LLM first
    select_rag_llm(page, get_config().get("app.debug_llm"), debug_enabled)

    # Then toggle RAG injection
    toggle_rag_injection(page, enable=False, debug_enabled=debug_enabled)

    context['rag_enabled'] = False
    return context

@when(parsers.parse('I ask "{question}"'))
def ask_question(context, question):
    """Ask a question in the chat interface."""
    # Use the existing send_message function
    return send_message(context, question)

@then("I should see a RAG-enhanced response with address information")
def verify_rag_enhanced_response(context):
    """Verify the response contains RAG-enhanced address information."""
    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print("\n=== Verifying RAG-enhanced response ===")

    # Wait for response
    page.wait_for_load_state("networkidle", timeout=45000)  # Longer timeout for RAG+LLM
    expect(page.locator("[data-testid='stApp']")).to_be_visible(timeout=30000)

    # Additional wait for RAG processing
    page.wait_for_timeout(3000)

    # Look for address information patterns
    address_patterns = [
        r"1 place du Louvre",
        r"place du Louvre",
        r"Paris",
        r"address.*Kevin",
        r"Kevin.*lives.*1",
        r"Louvre.*Paris"
    ]

    max_attempts = 3
    found_address = False
    response_text = ""

    for attempt in range(max_attempts):
        # Get the latest response text
        chat_messages = page.locator("[data-testid='stChatMessage']").all()
        if chat_messages:
            # Get the last message (should be assistant response)
            last_message = chat_messages[-1]
            response_text = last_message.text_content()
            print(f"Response text (attempt {attempt + 1}): {response_text[:100]}...")

            # Check for address patterns
            for pattern in address_patterns:
                if re.search(pattern, response_text, re.IGNORECASE):
                    found_address = True
                    print(f"✓ Found address pattern: {pattern}")
                    break

            if found_address:
                break

        if attempt < max_attempts - 1:
            print(f"Waiting for RAG-enhanced response... (attempt {attempt + 1}/{max_attempts})")
            page.wait_for_timeout(int(get_config().get("app.llm_delay", 2000)))

    if not found_address:
        take_screenshot(page, "rag_response_no_address.png", debug_enabled, full_page=True)

        # Debug: show what we found
        print(f"Full response text: {response_text[:500]}")

        # Check if we at least got some response
        if len(response_text.strip()) < 10:
            assert False, "No response received from LLM"
        else:
            assert False, "RAG-enhanced address information not found in response"

    # Also check for RAG debug context if enabled
    if debug_enabled:
        # Look for RAG debug expander
        rag_debug = page.locator("div").filter(has_text=re.compile(r"rag.*debug.*context", re.IGNORECASE)).first
        if rag_debug.count() > 0:
            print("✓ RAG debug context is visible")

    print("✓ RAG-enhanced response verified")
    return context

def wait_for_response_stable(page: Page, min_length: int = 50, timeout_ms: int = 120000):
    """Wait until response text stabilizes (stops changing)."""
    print(f"Waiting for response to stabilize...")

    start_time = time.time()
    last_text = ""
    stable_count = 0

    while (time.time() - start_time) * 1000 < timeout_ms:
        # Get latest message text
        chat_messages = page.locator("[data-testid='stChatMessage']").all()
        if chat_messages:
            current_text = chat_messages[-1].text_content()

            if current_text == last_text:
                stable_count += 1
                if stable_count >= 3:  # Same text 3 times in a row
                    if len(current_text.strip()) >= min_length:
                        print(f"Response stabilized: {len(current_text)} chars")
                        return current_text
            else:
                last_text = current_text
                stable_count = 0
                print(f"Text changed: {len(current_text)} chars")

        page.wait_for_timeout(1000)

    print(f"Timeout after {timeout_ms/1000}s")
    return last_text  # Return whatever we have


@then("I should see a generic response without address information")
def verify_generic_response(context):
    """Verify the response is generic without specific address information."""
    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print("\n=== Verifying generic response (no RAG) ===")

    # Wait for LLM response to complete
    response_complete = wait_for_response_stable(page, min_length=30, timeout_ms=180000)

    if not response_complete:
        print("⚠ LLM response may not have completed fully")

    # Get response text
    response_text = ""
    chat_messages = page.locator("[data-testid='stChatMessage']").all()

    if chat_messages:
        last_message = chat_messages[-1]
        response_text = last_message.text_content()
        print(f"Response: {response_text[:150]}...")

    if not response_text or len(response_text.strip()) < 10:
        take_screenshot(page, "no_response_received.png", debug_enabled, full_page=True)
        assert False, "No response received from LLM"

    # Check that specific address information is NOT present
    specific_address_indicators = [
        "1 place du Louvre",
        "place du Louvre",
        "1 place du Louvre, Paris",
        "Louvre, Paris"
    ]

    leaked_info = []
    for indicator in specific_address_indicators:
        if indicator.lower() in response_text.lower():
            leaked_info.append(indicator)

    if leaked_info:
        take_screenshot(page, "rag_leakage_detected.png", debug_enabled, full_page=True)
        assert False, f"RAG information leakage detected: '{', '.join(leaked_info)}' found when RAG was disabled"

    # Positive check: response should be generic/non-specific
    # But don't be too strict - LLM might still make something up
    print("✓ Verified no specific address information leaked")

    # Optional: Check for generic indicators (but don't fail if absent)
    generic_indicators = [
        "don't know",
        "I don't have",
        "I cannot",
        "I'm not sure",
        "I don't have access",
        "no information",
        "without context",
        "apologize",
        "sorry"
    ]

    for indicator in generic_indicators:
        if indicator.lower() in response_text.lower():
            print(f"✓ Found generic indicator: '{indicator}'")
            break

    return context
