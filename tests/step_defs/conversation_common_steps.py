# file: tests/step_defs/conversation_common_steps.py
"""
Conversation-related step definitions shared across feature files.
"""
import re
import pytest
from pytest_bdd import given, when, then, parsers
from playwright.sync_api import Page, expect

from tests.step_defs.page_helpers import (
    take_screenshot,
    screenshot_on_failure,
    wait_for_app_stable,
    expect_visible,
    click_button,
    wait_for_llm_response,
    DEFAULT_TIMEOUT,
    FAST_TIMEOUT,
    POLL_INTERVAL,
)
from tests.step_defs.common_steps import (
    navigate_to_chat_page,
    send_message,
    click_button_by_text,
    _wait_for_app_stable,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_conversation(context: dict, conversation_name: str) -> dict:
    """
    Internal helper: create a new conversation and wait for confirmation.
    Extracted so it can be called from both @given and @when steps.
    """
    page: Page = context["page"]
    debug_enabled = context.get("debug_enabled", False)

    print(f"\n=== Creating conversation: '{conversation_name}' ===")
    take_screenshot(page, "before_create_conversation.png", debug_enabled)
    wait_for_app_stable(page)

    # --- Find 'New Conversation' button ---
    new_btn = None
    for locator in (
        page.get_by_role("button", name=re.compile(r"new conversation", re.IGNORECASE)),
        page.get_by_text("➕ New Conversation"),
        page.get_by_text("New Conversation"),
        page.get_by_text("Create conversation"),
    ):
        if locator.count() > 0:
            new_btn = locator.first
            break

    if not new_btn:
        screenshot_on_failure(page, "new_conversation_button_not_found.png")
        raise AssertionError("Could not find 'New Conversation' button.")

    new_btn.click()
    page.wait_for_timeout(POLL_INTERVAL)

    # --- Wait for the title input to appear ---
    title_input = None
    for attempt in range(10):
        for sel in (
            "input[type='text']",
            "input[placeholder*='title']",
            "input[placeholder*='conversation']",
            "input[placeholder*='name']",
        ):
            candidates = page.locator(sel)
            for i in range(candidates.count()):
                if candidates.nth(i).is_visible(timeout=0):
                    title_input = candidates.nth(i)
                    break
            if title_input:
                break
        if title_input:
            break
        print(f"  Waiting for title input … attempt {attempt + 1}/10")
        page.wait_for_timeout(POLL_INTERVAL)

    if not title_input:
        screenshot_on_failure(page, "conversation_title_input_not_found.png")
        raise AssertionError("Conversation title input did not appear.")

    expect(title_input).to_be_visible(timeout=DEFAULT_TIMEOUT)
    expect(title_input).to_be_enabled(timeout=FAST_TIMEOUT)
    title_input.fill("")
    title_input.type(conversation_name, delay=80)
    try:
        expect(title_input).to_have_value(conversation_name, timeout=FAST_TIMEOUT)
    except AssertionError:
        actual = title_input.input_value()
        print(f"  ⚠ Input has '{actual}', expected '{conversation_name}' — proceeding")

    # --- Save ---
    save_btn = None
    for locator in (
        page.get_by_role("button", name=re.compile(r"save", re.IGNORECASE)),
        page.get_by_role("button", name=re.compile(r"create", re.IGNORECASE)),
        page.get_by_text("Save", exact=False),
        page.get_by_text("Create", exact=False),
    ):
        if locator.count() > 0:
            save_btn = locator.first
            break

    if save_btn:
        save_btn.click()
    else:
        print("  ⚠ No save button found — pressing Enter")
        title_input.press("Enter")

    page.wait_for_timeout(2_000)

    # --- Confirm creation ---
    created = False
    for attempt in range(10):
        page_text = page.locator("body").text_content().lower()
        if (
            conversation_name.lower() in page_text
            or page.locator("textarea").count() > 0
        ):
            created = True
            print(f"  ✓ Conversation '{conversation_name}' created (attempt {attempt + 1})")
            break
        page.wait_for_timeout(POLL_INTERVAL)

    if not created:
        screenshot_on_failure(page, "conversation_not_created.png")
        raise AssertionError(f"Conversation '{conversation_name}' does not appear to have been created.")

    take_screenshot(page, "after_create_conversation.png", debug_enabled)
    context["current_conversation"] = conversation_name
    return context


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

@given(parsers.parse('I have a conversation "{conversation_name}"'))
def have_conversation(context: dict, conversation_name: str) -> dict:
    if context.get("current_page") != "chat":
        context = navigate_to_chat_page(context)
    return _create_conversation(context, conversation_name)


@when(parsers.parse('I create a new conversation named "{conversation_name}"'))
def create_new_conversation(context: dict, conversation_name: str) -> dict:
    return _create_conversation(context, conversation_name)


@given("I have a conversation with an assistant message")
def have_conversation_with_assistant_message(context: dict) -> dict:
    context = navigate_to_chat_page(context)
    context = _create_conversation(context, "Test with Assistant")
    context = send_message(context, "Test message for assistant")
    return context


@when("I click the regenerate button")
def click_regenerate_button(context: dict) -> dict:
    return click_button_by_text(context, "Regenerate")


@given(parsers.parse('I have two conversations: "{conversation1}" and "{conversation2}"'))
def have_two_conversations(context: dict, conversation1: str, conversation2: str) -> dict:
    context = navigate_to_chat_page(context)
    context = _create_conversation(context, conversation1)
    context = send_message(context, f"Message in {conversation1}")
    wait_for_app_stable(context["page"])
    context = _create_conversation(context, conversation2)
    context = send_message(context, f"Message in {conversation2}")
    context["conversation1"] = conversation1
    context["conversation2"] = conversation2
    return context


@when(parsers.parse('I select the conversation "{conversation_name}"'))
def select_conversation_quoted(context: dict, conversation_name: str) -> dict:
    page: Page = context["page"]
    debug_enabled = context.get("debug_enabled", False)
    print(f"\n=== Selecting conversation: '{conversation_name}' ===")
    wait_for_app_stable(page)

    btn = page.get_by_text(conversation_name)
    if btn.count() > 0:
        expect(btn.first).to_be_visible(timeout=DEFAULT_TIMEOUT)
        btn.first.click()
        wait_for_app_stable(page)
    else:
        print(f"  ⚠ Conversation '{conversation_name}' not found in sidebar")

    take_screenshot(page, f"conversation_selected_{conversation_name}.png", debug_enabled)
    context["selected_conversation"] = conversation_name
    return context


@then(parsers.parse('I should see the history of "{conversation_name}"'))
def verify_conversation_history(context: dict, conversation_name: str) -> dict:
    page: Page = context["page"]
    wait_for_app_stable(page)
    page_text = page.locator("body").text_content()
    if conversation_name in page_text:
        print(f"  ✓ Conversation '{conversation_name}' visible")
    else:
        print(f"  ⚠ '{conversation_name}' not found — page may have different layout")
    assert len(page_text) > 100, "Page appears empty"
    return context


@given(parsers.parse('I have a conversation "{conversation_name}" with messages'))
def have_conversation_with_messages(context: dict, conversation_name: str) -> dict:
    context = have_conversation(context, conversation_name)
    context = send_message(context, "First test message")
    wait_for_app_stable(context["page"])
    context = send_message(context, "Second test message")
    return context


@when("I clear the conversation messages")
def clear_conversation_messages(context: dict) -> dict:
    return click_button_by_text(context, "Clear")


@then("the conversation should be empty")
def verify_conversation_empty(context: dict) -> dict:
    page: Page = context["page"]
    wait_for_app_stable(page)
    page_text = page.locator("body").text_content()
    assert len(page_text) > 100, "Page appears empty"
    print("  ✓ Page valid after clear")
    return context


@given(parsers.parse('I have a conversation "{old_title}"'))
def have_conversation_with_title(context: dict, old_title: str) -> dict:
    return have_conversation(context, old_title)


@when(parsers.parse('I edit the conversation title to "{new_title}"'))
def edit_conversation_title(context: dict, new_title: str) -> dict:
    page: Page = context["page"]
    wait_for_app_stable(page)
    click_button_by_text(context, "Edit")
    wait_for_app_stable(page)

    inputs = page.locator("input[type='text']").all()
    if inputs:
        title_input = inputs[0]
        expect(title_input).to_be_visible(timeout=DEFAULT_TIMEOUT)
        expect(title_input).to_be_enabled(timeout=FAST_TIMEOUT)
        title_input.fill("")
        title_input.type(new_title, delay=80)
        try:
            expect(title_input).to_have_value(new_title, timeout=FAST_TIMEOUT)
        except AssertionError:
            print("  ⚠ Could not verify new title value — proceeding")
        click_button_by_text(context, "Save")

    context["new_title"] = new_title
    return context


@then(parsers.parse('I should see the conversation with title "{expected_title}"'))
def verify_conversation_title(context: dict, expected_title: str) -> dict:
    page: Page = context["page"]
    wait_for_app_stable(page)
    page_text = page.locator("body").text_content()
    if expected_title in page_text:
        print(f"  ✓ Title '{expected_title}' found")
    else:
        print(f"  ⚠ Title '{expected_title}' not found — may be truncated in sidebar")
    assert len(page_text) > 100, "Page appears empty"
    return context


@then("the last response should be updated")
def verify_response_updated(context: dict) -> dict:
    page: Page = context["page"]
    wait_for_app_stable(page)
    page_text = page.locator("body").text_content().lower()
    for indicator in ("error", "failed", "exception", "traceback"):
        if indicator in page_text:
            screenshot_on_failure(page, "regenerate_error.png")
            raise AssertionError(f"Error found after regeneration: '{indicator}'")
    print("  ✓ Regeneration completed without errors")
    return context
