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
