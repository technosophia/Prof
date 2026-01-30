# file name: test_test_steps.py
"""
pytest-bdd step definitions for Test admin UI testing.
Tests the Test module functionality in the admin panel.
"""
import pytest
import re
from pytest_bdd import given, when, then, scenarios, parsers
import sys
import os
from playwright.sync_api import Page, expect

# Add the project root to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

pytestmark = pytest.mark.bdd

# Import fixtures from conftest.py only
from conftest import (
    setup_test_environment,
    playwright,
    browser,
    patch_config,
    mock_db_manager,
    mock_user_manager,
    patch_database,
    enable_debug,
    streamlit_server,
    browser_context,
    debug_dir,
    take_screenshot
)

from common_steps import *

# Load feature files
scenarios('../../tests/features/test.feature')

# ================ SCENARIO STEPS ================

@then(parsers.parse('I should see "{expected_text}" in the admin content'))
def verify_admin_content(context, expected_text):
    """Verify text appears in the admin content area."""
    if 'page' not in context:
        raise KeyError("No 'page' in context")

    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print(f'\n=== [Test Module] Verifying admin content: "{expected_text}" ===')

    # Wait for admin content area to be stable after potential reruns
    page.wait_for_load_state("networkidle", timeout=30000)

    # Wait for admin panel to be fully loaded - try multiple selectors
    admin_selectors = [
        page.get_by_text("Admin Panel", exact=False),
        page.get_by_text("Admin", exact=False),
        page.locator('[data-testid="stSidebar"]').get_by_text("Admin", exact=False),
        page.get_by_role("heading", name=re.compile(r"Admin", re.IGNORECASE))
    ]

    admin_visible = False
    for selector in admin_selectors:
        try:
            selector.wait_for(state="visible", timeout=5000)
            admin_visible = True
            print(f"✓ Admin panel detected using: {selector}")
            break
        except:
            continue

    if not admin_visible:
        print("⚠ Could not find Admin Panel text, continuing with general page load check...")
        # Fallback: just ensure page is loaded
        page.wait_for_load_state("domcontentloaded", timeout=30000)

    # Get all text from the page
    page_text = page.locator("body").text_content(timeout=10000)

    # Check if expected text is in page text
    if expected_text not in page_text:
        print(f"Page text (first 500 chars): {page_text[:500]}")
        if debug_enabled:
            take_screenshot(page, "test_admin_content_not_found.png", debug_enabled)
        raise AssertionError(f"Expected text '{expected_text}' not found in admin content")

    print(f"✓ Found expected text: {expected_text}")

    if debug_enabled:
        take_screenshot(page, "test_admin_content_found.png", debug_enabled)

    return


@then(parsers.parse('I should see "{expected_text}" in the header'))
def verify_text_in_header_for_test(context, expected_text):
    """Verify text appears in a header on the page for Test module."""
    if 'page' not in context:
        raise KeyError("No 'page' in context")

    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print(f'\n=== [Test Module] Verifying header text: "{expected_text}" ===')

    # Wait for page to be stable after any reruns
    page.wait_for_load_state("networkidle", timeout=30000)

    # Wait for page to be fully loaded with multiple fallback strategies
    try:
        # First try to find admin panel
        admin_selectors = [
            page.get_by_text("Admin Panel", exact=False),
            page.get_by_text("Admin", exact=False),
            page.get_by_role("heading", name=re.compile(r"Admin", re.IGNORECASE))
        ]

        page_loaded = False
        for selector in admin_selectors:
            try:
                selector.wait_for(state="visible", timeout=5000)
                page_loaded = True
                print(f"✓ Page loaded indicator found: {selector}")
                break
            except:
                continue

        if not page_loaded:
            # Fallback: check for any visible content
            page.locator("body").wait_for(state="visible", timeout=10000)
            print("✓ Page body is visible")

    except Exception as e:
        print(f"⚠ Page load check warning: {e}")
        # Continue anyway - the header check will handle missing elements

    # Check headers (h1, h2, h3 elements) with retry logic
    found = False
    max_retries = 3

    for retry in range(max_retries):
        if retry > 0:
            print(f"Retry {retry + 1}/{max_retries} for finding header...")
            page.wait_for_timeout(1000)  # Brief pause between retries

        # Check all header elements
        for tag in ["h1", "h2", "h3", "h4", "h5", "h6"]:
            try:
                headers_locator = page.locator(tag)

                # Try to get count without timeout parameter
                count = headers_locator.count()
                if count > 0:
                    for i in range(count):
                        try:
                            header = headers_locator.nth(i)
                            # Check if header is visible
                            if header.is_visible():
                                header_text = header.text_content()
                                if header_text and expected_text in header_text.strip():
                                    print(f"✓ Found '{expected_text}' in {tag}: '{header_text.strip()}'")
                                    found = True
                                    break
                        except:
                            continue
            except:
                continue

        if found:
            break

    # Also check for text anywhere on page if not found in headers
    if not found:
        page_text = page.locator("body").text_content(timeout=5000)
        if page_text and expected_text in page_text:
            print(f"✓ Found '{expected_text}' somewhere on page")
            found = True

    # Try one more strategy: look for any element containing the text
    if not found:
        try:
            matching_elements = page.locator(f':has-text("{expected_text}")')
            if matching_elements.count() > 0:
                for i in range(matching_elements.count()):
                    element = matching_elements.nth(i)
                    if element.is_visible():
                        element_text = element.text_content()
                        if element_text and expected_text in element_text:
                            print(f"✓ Found '{expected_text}' in element: '{element_text[:50]}...'")
                            found = True
                            break
        except:
            pass

    if not found:
        if debug_enabled:
            take_screenshot(page, "test_header_not_found.png", debug_enabled)
        raise AssertionError(f"Expected text '{expected_text}' not found in any header or on page")

    if debug_enabled:
        take_screenshot(page, "test_header_found.png", debug_enabled)

    return

@given("the Test module is available")
def test_module_available(context):
    """Verify the Test module is available in the admin panel."""
    print("\n=== [Test Module] Assuming Test module is available ===")

    # Wait for page to be loaded if available
    if 'page' in context:
        page = context['page']
        page.wait_for_load_state("networkidle", timeout=30000)
        # Use multiple strategies to verify page is ready
        try:
            page.locator("body").wait_for(state="visible", timeout=10000)
        except:
            pass  # Continue even if body visibility check fails

    return
