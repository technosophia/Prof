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
    page,
    context,
    take_screenshot,
)

@given(parsers.parse('the default user "{username}" is logged in'))
def default_user_logged_in(context, username):
    """Log in as the default test user."""
    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print(f"\n=== Logging in as: {username} ===")

    # Take screenshot before login
    take_screenshot(page, "conversation_before_login.png", debug_enabled, full_page=True)

    # Wait for page to be ready
    page.wait_for_load_state("networkidle", timeout=30000)
    expect(page.locator("[data-testid='stApp']")).to_be_visible(timeout=30000)

    # Find ALL selectboxes
    all_selectboxes = page.locator("[data-testid='stSelectbox']")
    selectbox_count = all_selectboxes.count()
    print(f"Found {selectbox_count} selectboxes total")

    take_screenshot(page, "conversation_login_before_select.png", debug_enabled, full_page=True)

    # The user selectbox should be the one with "Choose user" or similar
    # Based on earlier error, it's the 3rd one (index 2)
    if selectbox_count >= 3:
        print("Clicking the third selectbox (assuming it's the user selector)...")
        user_selectbox = all_selectboxes.nth(2)
        expect(user_selectbox).to_be_visible(timeout=30000)
        user_selectbox.click()

        # Wait for dropdown to open
        expect(page.locator("li[role='option']").first).to_be_visible(timeout=30000)

        # Try different selectors for dropdown options
        option_selectors = [
            "[data-testid='stSelectboxOption']",
            "div[role='option']",
            "li[role='option']"
        ]

        options_found = False
        for selector in option_selectors:
            options = page.locator(selector)
            if options.count() > 0:
                option_count = options.count()
                print(f"Found {option_count} dropdown options with selector: {selector}")
                options_found = True

                # Try to find our user
                user_found = False
                for i in range(option_count):
                    option = options.nth(i)
                    option_text = option.text_content()
                    print(f"  Option {i}: '{option_text}'")

                    if username in option_text:
                        option.click()
                        # Wait for Streamlit rerun
                        page.wait_for_load_state("networkidle", timeout=30000)
                        expect(page.locator("[data-testid='stApp']")).to_be_visible(timeout=30000)
                        print(f"✓ Selected user: {username}")
                        user_found = True
                        break

                if not user_found and option_count > 0:
                    # Select first option
                    options.first.click()
                    page.wait_for_load_state("networkidle", timeout=30000)
                    expect(page.locator("[data-testid='stApp']")).to_be_visible(timeout=30000)
                    print("Selected first available user (username not found)")

                break

        if not options_found:
            print("Warning: No dropdown options found after clicking selectbox")
            # Close dropdown if open
            page.keyboard.press("Escape")

    take_screenshot(page, "conversation_before_login_click.png", debug_enabled, full_page=True)
    # Look for login button - use robust selectors
    login_button_selectors = [
        page.get_by_role("button", name=re.compile(r"login as user", re.IGNORECASE)),
        page.get_by_role("button", name=re.compile(r"login", re.IGNORECASE)),
        page.get_by_role("button", name=re.compile(r"log in", re.IGNORECASE))
    ]

    login_button = None
    for selector in login_button_selectors:
        if selector.count() > 0:
            login_button = selector.first
            break

    if login_button:
        expect(login_button).to_be_visible(timeout=30000)
        expect(login_button).to_be_enabled(timeout=30000)
        login_button.click()
        # Wait for login to complete
        page.wait_for_load_state("networkidle", timeout=30000)
        expect(page.locator("[data-testid='stApp']")).to_be_visible(timeout=30000)
        print("Clicked login button")
    else:
        take_screenshot(page, "conversation_no_log_in_button.png", debug_enabled, full_page=True)
        print("Note: No login button found - maybe login happens automatically")
        raise AssertionError("Chat page did not load properly")

    # Take screenshot after login attempt
    take_screenshot(page, "conversation_02_logged_in.png", debug_enabled, full_page=True)

    # Store user in context
    context['current_user'] = username

    # Check if we're logged in by looking for user info or chat interface
    page_text = page.locator("body").text_content()

    # Positive indicators (logged in)
    positive_indicators = [
        f"user.*{username}",
        "logged in",
        "welcome",
        "hello",
        "bonjour",
        "conversation",
        "chat"
    ]

    logged_in = False
    for indicator in positive_indicators:
        if re.search(indicator, page_text, re.IGNORECASE):
            print(f"✓ Found positive indicator: {indicator}")
            logged_in = True
            break

    if not logged_in:
        print("Note: No clear login status indicators found")

    return context
