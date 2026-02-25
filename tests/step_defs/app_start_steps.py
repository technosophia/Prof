# file: tests/step_defs/app_start_steps.py
"""
Application startup step definitions.
Handles navigating to the app and waiting for full initialisation.
"""
import pytest
from pytest_bdd import given
from playwright.sync_api import Page, expect

from tests.conftest import TEST_PORT, context, debug_dir, page  # noqa: F401
from tests.step_defs.page_helpers import (
    take_screenshot,
    wait_for_app_stable,
    wait_for_app_fully_loaded,
    APP_FULLY_LOADED_SELECTOR,
    SLOW_TIMEOUT,
    DEFAULT_TIMEOUT,
)
from tests.step_defs.common_steps import (
    _wait_for_app_stable,
    _click_button_by_texts,
    _robust_header_verification,
)


@given("the application is running")
def app_is_running(context: dict, page: Page, debug_dir, streamlit_server) -> dict:
    """Navigate to the app and wait until it is fully initialised."""
    print("\n=== Navigating to application ===")

    page.goto(f"http://localhost:{TEST_PORT}/", wait_until="load")

    # Quick sanity check — Streamlit container is present
    expect(page.locator("div[data-testid='stApp']")).to_be_visible(timeout=DEFAULT_TIMEOUT)

    # Wait for the explicit readiness marker injected at end of main()
    # Use "attached" not "visible" — the marker div is intentionally invisible.
    expect(page.locator(APP_FULLY_LOADED_SELECTOR)).to_be_attached(timeout=SLOW_TIMEOUT)

    # Final stability pass
    wait_for_app_stable(page)

    # Best-effort sidebar check
    try:
        expect(page.locator("[data-testid='stSidebar']")).to_be_visible(timeout=10_000)
    except Exception:
        print("  ⚠ Sidebar not detected — relying on readiness marker")

    take_screenshot(page, "app_running.png", bool(debug_dir), full_page=True)

    context["page"] = page
    context["debug_enabled"] = bool(debug_dir)

    print("  ✓ Application fully loaded")
    return context
