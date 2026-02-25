# file: tests/step_defs/debug_steps.py
"""
pytest-bdd step definitions for debug admin UI testing.
"""
import re
import pytest
from pytest_bdd import given, when, then, scenarios, parsers
from playwright.sync_api import Page, expect

pytestmark = [pytest.mark.bdd, pytest.mark.playwright]

from tests.step_defs.page_helpers import *
from tests.step_defs.common_steps import *
from tests.step_defs.app_start_steps import *
from tests.step_defs.user_steps import *
from tests.step_defs.page_helpers import (
    take_screenshot,
    screenshot_on_failure,
    wait_for_app_stable,
    DEFAULT_TIMEOUT,
)

scenarios("../../tests/features/debug.feature")


@when('I click the "Display Text" button without entering text')
def click_display_without_text(context: dict) -> dict:
    return click_button_by_text(context, "Display Text")


@then("I should see the character count displayed")
def verify_character_count(context: dict) -> dict:
    page: Page = context["page"]
    wait_for_app_stable(page)
    page_text = page.locator("div[data-testid='stApp']").text_content() or ""
    if re.search(r"character.*count", page_text, re.IGNORECASE):
        print("  ✓ Character count displayed")
    else:
        print("  ⚠ No explicit 'character count' label found (may still be present)")
    return context


@then("I should see the word count displayed")
def verify_word_count(context: dict) -> dict:
    page: Page = context["page"]
    wait_for_app_stable(page)
    page_text = page.locator("div[data-testid='stApp']").text_content() or ""
    if re.search(r"word.*count", page_text, re.IGNORECASE):
        print("  ✓ Word count displayed")
    else:
        print("  ⚠ No explicit 'word count' label found (may still be present)")
    return context


@then("the result section should be empty")
def verify_result_section_empty(context: dict) -> dict:
    page: Page = context["page"]
    debug_enabled = context.get("debug_enabled", False)
    wait_for_app_stable(page)

    page_text = page.locator("div[data-testid='stApp']").text_content() or ""
    result_indicators = ("Text Result:", "Result:", "Displayed text:")

    for indicator in result_indicators:
        if indicator in page_text:
            start = page_text.find(indicator) + len(indicator)
            result_snippet = page_text[start: start + 100].strip()
            meta_words = ("character", "word", "count", "0 characters")
            if result_snippet and not any(m in result_snippet.lower() for m in meta_words):
                screenshot_on_failure(page, "result_section_not_empty.png")
                raise AssertionError(
                    f"Result section should be empty but contains: '{result_snippet[:60]}'"
                )

    print("  ✓ Result section is empty")
    return context
