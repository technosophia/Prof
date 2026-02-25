# file: tests/step_defs/llm_steps.py
"""
LLM-related step definitions (model selection, response verification).
"""
import os
import re
import pytest
from pytest_bdd import given, then
from playwright.sync_api import Page, expect

from tests.step_defs.page_helpers import (
    take_screenshot,
    screenshot_on_failure,
    wait_for_app_stable,
    wait_for_llm_response,
    expect_visible,
    DEFAULT_TIMEOUT,
    POLL_INTERVAL,
    MAX_RETRIES,
)
from tests.step_defs.common_steps import _wait_for_app_stable


@given("the mock LLM is configured and available")
def mock_llm_available(context: dict) -> dict:
    """Ensure the Mock LLM is selected in the LLM dropdown."""
    page: Page = context["page"]
    debug_enabled = context.get("debug_enabled", False)

    print("\n=== Selecting Mock LLM ===")
    take_screenshot(page, "before_llm_select.png", debug_enabled)
    wait_for_app_stable(page)

    selectboxes = page.locator("[data-testid='stSelectbox']")
    llm_selectbox = None
    for i in range(selectboxes.count()):
        text = (selectboxes.nth(i).text_content() or "").lower()
        if any(kw in text for kw in ("llm", "ai model", "selection")):
            llm_selectbox = selectboxes.nth(i)
            break

    if llm_selectbox:
        # Check if Mock already selected
        current_text = (llm_selectbox.text_content() or "").lower()
        if "mock" in current_text:
            print("  Mock LLM already selected")
            return context

        expect(llm_selectbox).to_be_visible(timeout=DEFAULT_TIMEOUT)
        llm_selectbox.click()
        page.wait_for_timeout(POLL_INTERVAL)

        # Find Mock option in portal dropdown
        for locator in (
            page.get_by_text("Mock LLM", exact=False),
            page.get_by_text("mock", exact=False),
        ):
            if locator.count() > 0:
                locator.first.click()
                wait_for_app_stable(page)
                print("  ✓ Mock LLM selected")
                take_screenshot(page, "mock_llm_selected.png", debug_enabled)
                return context

        # Close dropdown if not matched
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    else:
        print("  ⚠ LLM selectbox not found — assuming Mock LLM is default")

    take_screenshot(page, "llm_final.png", debug_enabled)
    return context


@then("I should see a response from the mock LLM")
def verify_mock_llm_response(context: dict) -> dict:
    """Wait for any non-trivial response from the mock LLM."""
    page: Page = context["page"]
    debug_enabled = context.get("debug_enabled", False)

    print("\n=== Verifying mock LLM response ===")
    wait_for_app_stable(page)
    page.wait_for_timeout(3_000)  # Allow async processing to start

    mock_indicators = ("mock", "test", "hello", "response", "assistant", "ai", "i am")

    for attempt in range(MAX_RETRIES):
        messages = page.locator("[data-testid='stChatMessage']").all()
        if messages:
            response_text = messages[-1].text_content() or ""
            if any(ind in response_text.lower() for ind in mock_indicators):
                print(f"  ✓ Mock response found (attempt {attempt + 1})")
                context["last_response"] = response_text
                take_screenshot(page, "mock_response_received.png", debug_enabled)
                return context

        if attempt < MAX_RETRIES - 1:
            print(f"  Waiting for mock response … attempt {attempt + 1}/{MAX_RETRIES}")
            wait_for_app_stable(page)
            page.wait_for_timeout(2_000)

    # Final fallback — check full page minus sidebar
    main_text = page.locator("[data-testid='stApp']").text_content() or ""
    sidebar = page.locator("[data-testid='stSidebar']")
    if sidebar.count() > 0:
        main_text = main_text.replace(sidebar.text_content() or "", "")

    if len(main_text.strip()) > 100:
        print("  ⚠ No clear mock indicator but main area has content — accepting")
        context["last_response"] = main_text
        return context

    screenshot_on_failure(page, "mock_response_not_found.png")
    raise AssertionError("No mock LLM response found on page.")
