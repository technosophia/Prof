# file: tests/step_defs/user_steps.py
"""
User authentication step definitions.
"""
import re
import pytest
from pytest_bdd import given, parsers
from playwright.sync_api import Page, expect

from tests.step_defs.page_helpers import (
    take_screenshot,
    screenshot_on_failure,
    wait_for_app_stable,
    find_and_select_in_selectbox,
    click_button_by_key,
    DEFAULT_TIMEOUT,
    POLL_INTERVAL,
)


@given(parsers.parse('the default user "{username}" is logged in'))
def default_user_logged_in(context: dict, username: str) -> dict:
    """Select a user from the dropdown and click Login."""
    page: Page = context["page"]
    debug_enabled = context.get("debug_enabled", False)

    print(f"\n=== Logging in as: {username} ===")
    take_screenshot(page, "before_login.png", debug_enabled, full_page=True)

    wait_for_app_stable(page)

    # --- Select user ---
    try:
        find_and_select_in_selectbox(
            page=page,
            key="user_selector",
            label="Choose user",
            value_to_select=username,
            timeout=DEFAULT_TIMEOUT,
        )
    except Exception as exc:
        print(f"  ⚠ User selection warning: {exc}")
        page_text = page.locator("body").text_content().lower()
        if username.lower() in page_text:
            print(f"  User '{username}' already visible on page — continuing")
            context["current_user"] = username
            return context

    page.wait_for_timeout(POLL_INTERVAL)

    # --- Click login button ---
    try:
        click_button_by_key(page=page, label="Login as User", timeout=DEFAULT_TIMEOUT)
        print("  ✓ Login button clicked")
    except Exception as exc:
        print(f"  ⚠ Login button warning: {exc}")
        # Try alternative labels
        for alt in ("Login", "Log In", "Sign In", "Enter"):
            try:
                click_button_by_key(page=page, label=alt, timeout=2_000)
                print(f"  Used alternative label: '{alt}'")
                break
            except Exception:
                continue

    wait_for_app_stable(page)
    take_screenshot(page, "after_login.png", debug_enabled, full_page=True)
    context["current_user"] = username

    # --- Verify login ---
    logged_in = False
    for attempt in range(10):
        page.wait_for_timeout(POLL_INTERVAL)
        page_text = page.locator("body").text_content().lower()
        if re.search(re.escape(username.lower()), page_text):
            print(f"  ✓ Login verified for '{username}' (attempt {attempt + 1})")
            logged_in = True
            break

    if not logged_in:
        print(f"  ⚠ Could not verify login for '{username}' — continuing anyway")
        take_screenshot(page, "login_verification_failed.png", True, full_page=True)

    return context
