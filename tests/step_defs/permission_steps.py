# file: tests/step_defs/permission_steps.py
"""
pytest-bdd step definitions for permission enforcement tests.

New steps defined here:
  - I should see the tab "{tab_name}"
  - I should not see the tab "{tab_name}"
  - the delete button for user "{username}" should be disabled
  - the reset code action should be visible for user "{username}"
  - I should not see "{text}" in the user management list
  - the admin panel button should be disabled

All other steps (app startup, login, navigate to admin, select tab) are
re-used from the common step files.
"""

import re
import pytest
from pytest_bdd import then, scenarios, parsers
from playwright.sync_api import Page, expect

from tests.step_defs.page_helpers import (
    wait_for_app_stable,
    screenshot_on_failure,
    expect_text_on_page,
    DEFAULT_TIMEOUT,
    FAST_TIMEOUT,
)
from tests.step_defs.common_steps import *       # noqa: F401,F403
from tests.step_defs.app_start_steps import *    # noqa: F401,F403
from tests.step_defs.user_steps import *         # noqa: F401,F403

scenarios("../../tests/features/permissions.feature")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_user_row(page: Page, username: str):
    """
    Return the columns block (stColumns / stHorizontalBlock) that is a user
    card row — i.e. it contains both the username text AND a View button.

    Scoped to stMain to avoid sidebar matches.
    The View-button filter distinguishes real user rows from filter sections
    (which also contain username text via dropdowns).
    """
    main = page.locator("[data-testid='stMain']")
    for testid in ("stColumns", "stHorizontalBlock"):
        block = main.locator(f"[data-testid='{testid}']").filter(
            has=page.get_by_text(username, exact=False)
        ).filter(has=page.locator("button").filter(has_text="View"))
        if block.count() > 0:
            return block.first
    return None


def _visible_tabpanel_text(page: Page) -> str:
    """Return the text content of the currently visible tab panel."""
    panels = page.locator("[role='tabpanel']").all()
    for panel in panels:
        if panel.is_visible():
            return panel.text_content() or ""
    # Fallback: main content area
    return page.locator("[data-testid='stMain']").text_content() or ""


def _tabs_in_active_panel(page: Page) -> "Locator":
    """
    Return a locator for [role='tab'] elements scoped to the currently
    visible tabpanel that actually contains tabs.

    This avoids matching hidden tabs from other module tab groups that share
    a tab label (e.g., a plain 'Email Templates' tab in Settings that is
    currently hidden).
    """
    panels = page.locator("[role='tabpanel']").all()
    for panel in panels:
        if panel.is_visible():
            tabs = panel.locator("[role='tab']")
            if tabs.count() > 0:
                return tabs
    # Fallback: all tabs on the page
    return page.locator("[role='tab']")


# ---------------------------------------------------------------------------
# Tab visibility
# ---------------------------------------------------------------------------

@then(parsers.parse('I should see the tab "{tab_name}"'))
def tab_should_be_visible(context: dict, tab_name: str) -> dict:
    page: Page = context["page"]
    wait_for_app_stable(page)
    page.wait_for_timeout(1_000)

    # Scope to visible tabpanel to avoid matching hidden tabs from other modules
    tab = _tabs_in_active_panel(page).filter(has_text=tab_name)
    try:
        expect(tab.first).to_be_visible(timeout=DEFAULT_TIMEOUT)
    except AssertionError:
        screenshot_on_failure(page, f"tab_{tab_name.replace('/', '_')}_missing.png")
        raise AssertionError(f"Tab '{tab_name}' should be visible but was not found.")
    print(f"  ✓ Tab '{tab_name}' is visible")
    return context


@then(parsers.parse('I should not see the tab "{tab_name}"'))
def tab_should_not_be_visible(context: dict, tab_name: str) -> dict:
    page: Page = context["page"]
    wait_for_app_stable(page)
    page.wait_for_timeout(1_000)

    # Scope to visible tabpanel to avoid false matches with hidden tab groups
    tab = _tabs_in_active_panel(page).filter(has_text=tab_name)
    visible = tab.count() > 0 and tab.first.is_visible()
    if visible:
        screenshot_on_failure(page, f"tab_{tab_name.replace('/', '_')}_unexpected.png")
        raise AssertionError(f"Tab '{tab_name}' should NOT be visible but was found.")
    print(f"  ✓ Tab '{tab_name}' is correctly absent")
    return context


# ---------------------------------------------------------------------------
# Delete button disabled
# ---------------------------------------------------------------------------

@then(parsers.parse('the delete button for user "{username}" should be disabled'))
def delete_button_should_be_disabled(context: dict, username: str) -> dict:
    page: Page = context["page"]
    wait_for_app_stable(page)

    row = _find_user_row(page, username)
    if row is None:
        screenshot_on_failure(page, f"delete_btn_row_{username[:20]}_not_found.png")
        raise AssertionError(
            f"Could not find a user row containing '{username}' on this page. "
            f"Make sure the correct tab is selected."
        )

    delete_btn = row.locator("button").filter(has_text="Delete")
    try:
        expect(delete_btn.first).to_be_disabled(timeout=FAST_TIMEOUT)
    except AssertionError:
        screenshot_on_failure(page, f"delete_btn_{username[:20]}_not_disabled.png")
        raise AssertionError(
            f"Delete button for '{username}' should be disabled but is enabled."
        )
    print(f"  ✓ Delete button for '{username}' is correctly disabled")
    return context


# ---------------------------------------------------------------------------
# Text absence scoped to the active tab panel
# ---------------------------------------------------------------------------

@then(parsers.parse('I should not see "{text}" in the user management list'))
def text_not_in_user_management_list(context: dict, text: str) -> dict:
    """
    Check that the text does not appear inside the currently visible tab panel.
    Scoped to avoid false positives from sidebar (current user name) or other tabs.
    """
    page: Page = context["page"]
    wait_for_app_stable(page)

    panel_text = _visible_tabpanel_text(page)
    if text.lower() in panel_text.lower():
        screenshot_on_failure(page, f"unexpected_in_list_{text[:20].replace(' ', '_')}.png")
        raise AssertionError(
            f"'{text}' was found in the user management list but should not be.\n"
            f"Panel preview: {panel_text[:300]}"
        )
    print(f"  ✓ '{text}' is correctly absent from the user management list")
    return context


# ---------------------------------------------------------------------------
# Normal user: admin panel button is disabled
# ---------------------------------------------------------------------------

@then("the admin panel button should be disabled")
def admin_panel_button_disabled(context: dict) -> dict:
    """
    For normal users the Admin nav button exists in the sidebar but is disabled.
    We verify that without trying to click it.
    """
    page: Page = context["page"]
    wait_for_app_stable(page)

    sidebar = page.locator("[data-testid='stSidebar']")
    admin_el = sidebar.get_by_text(re.compile(r"Admin", re.IGNORECASE)).first
    try:
        expect(admin_el).to_be_visible(timeout=DEFAULT_TIMEOUT)
        expect(admin_el).to_be_disabled(timeout=FAST_TIMEOUT)
    except AssertionError:
        screenshot_on_failure(page, "admin_btn_not_disabled_for_normal.png")
        raise AssertionError(
            "Expected the Admin panel button to be disabled for this user, "
            "but it is either missing or enabled."
        )
    print("  ✓ Admin panel button is correctly disabled for this user")
    return context
