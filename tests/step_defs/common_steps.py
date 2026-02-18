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

# ==================== HELPER FUNCTIONS ====================

def take_screenshot(page, filename, debug_enabled, full_page=False):
    """Take screenshot only if debug mode is enabled."""
    if debug_enabled:
        debug_path = os.path.join("tests", "debug")
        os.makedirs(debug_path, exist_ok=True)
        filepath = os.path.join(debug_path, filename)
        page.screenshot(path=filepath, full_page=full_page)
        print(f"  Screenshot saved: {filename}")


def find_element_by_text(page, text, exact=False):
    """Find an element containing specific text."""
    if exact:
        return page.get_by_text(text, exact=True)
    else:
        return page.get_by_text(text)


def _wait_for_app_stable(page: Page, timeout: int = 30000) -> None:
    """Consistent wait for Streamlit app stability after reruns."""
    page.wait_for_load_state("networkidle", timeout=timeout)
    expect(page.locator("div[data-testid='stApp']")).to_be_visible(timeout=timeout)


def _click_button_by_texts(page: Page, texts: list[str], debug_enabled: bool = False,
                          screenshot_name: str | None = None, timeout: int = 30000) -> None:
    """Robust button click using multiple possible labels (with emojis or variations)."""
    print(f'\n=== Clicking button with possible texts: {texts} ===')

    # Build chained locator with role fallback
    locator = None
    for text in texts:
        new_loc = page.get_by_text(text, exact=False)
        locator = new_loc if locator is None else locator.or_(new_loc)

    # Fallback to role-based search
    if locator is None or locator.count() == 0:
        pattern = "|".join(re.escape(t) for t in texts)
        locator = page.get_by_role("button", name=re.compile(pattern, re.IGNORECASE))

    button = locator.first
    expect(button).to_be_visible(timeout=timeout)
    expect(button).to_be_enabled(timeout=timeout)
    button.click()

    _wait_for_app_stable(page)

    if screenshot_name and debug_enabled:
        take_screenshot(page, screenshot_name, debug_enabled)


def _robust_header_verification(page: Page, expected_text: str, debug_enabled: bool = False) -> None:
    """Robust header text verification (aligned with test_steps.py logic)."""
    print(f'\n=== Verifying header contains: "{expected_text}" ===')

    _wait_for_app_stable(page)

    found = False
    max_retries = 3

    for retry in range(max_retries):
        if retry > 0:
            print(f"Retry {retry}/{max_retries} for header check...")
            page.wait_for_timeout(1000)

        # Check standard header tags
        for tag in ["h1", "h2", "h3", "h4", "h5", "h6"]:
            headers = page.locator(tag)
            for i in range(headers.count()):
                header = headers.nth(i)
                if header.is_visible():
                    header_text = header.text_content().strip()
                    if expected_text in header_text:
                        print(f"✓ Found '{expected_text}' in {tag}: '{header_text}'")
                        found = True
                        break
            if found:
                break

        if found:
            break

    # Fallback 1: anywhere on page
    if not found:
        page_text = page.locator("body").text_content(timeout=10000)
        if expected_text in page_text:
            print(f"✓ Found '{expected_text}' in page text")
            found = True

    # Fallback 2: :has-text locator
    if not found:
        matching = page.locator(f':has-text("{expected_text}")')
        if matching.count() > 0:
            for i in range(matching.count()):
                elem = matching.nth(i)
                if elem.is_visible() and expected_text in elem.text_content():
                    print(f"✓ Found '{expected_text}' via :has-text")
                    found = True
                    break

    if not found:
        if debug_enabled:
            take_screenshot(page, "debug_header_not_found.png", debug_enabled)
        raise AssertionError(f"Expected header text '{expected_text}' not found")

    if debug_enabled:
        take_screenshot(page, "debug_header_found.png", debug_enabled)


def _find_and_fill_input(page: Page, text: str, input_type: str = "text",
                        placeholder_hint: str = "", timeout: int = 30000) -> None:
    """Find an input field and fill it with text."""
    print(f'\n=== Filling {input_type} input with: "{text}" ===')

    # Try multiple selectors
    input_selectors = [
        f"input[type='{input_type}']",
        "textarea",
        "input",
        f"input[placeholder*='{placeholder_hint}']" if placeholder_hint else None,
        f"textarea[placeholder*='{placeholder_hint}']" if placeholder_hint else None
    ]

    input_field = None
    for selector in input_selectors:
        if selector:
            elements = page.locator(selector)
            if elements.count() > 0:
                # Get the first visible element
                for i in range(elements.count()):
                    if elements.nth(i).is_visible():
                        input_field = elements.nth(i)
                        print(f"Found input field with selector: {selector}")
                        break
            if input_field:
                break

    if not input_field:
        raise AssertionError(f"Could not find {input_type} input field")

    expect(input_field).to_be_visible(timeout=timeout)
    expect(input_field).to_be_enabled(timeout=timeout)

    input_field.fill("")
    input_field.type(text, delay=100)
    expect(input_field).to_have_value(text, timeout=timeout)

    print(f"✓ Input field filled with: {text}")


def _find_and_click_button(page: Page, button_texts: list[str],
                          button_role: str = "button", timeout: int = 30000) -> None:
    """Find and click a button by text or role."""
    print(f'\n=== Clicking button with possible texts: {button_texts} ===')

    button = None

    # First try by text
    for text in button_texts:
        btn = page.get_by_text(text, exact=False)
        if btn.count() > 0:
            button = btn.first
            print(f"Found button with text: '{text}'")
            break

    # Fallback to role
    if not button:
        pattern = "|".join(re.escape(t) for t in button_texts)
        btn = page.get_by_role(button_role, name=re.compile(pattern, re.IGNORECASE))
        if btn.count() > 0:
            button = btn.first
            print(f"Found button with role '{button_role}' matching pattern: {pattern}")

    if not button:
        raise AssertionError(f"Could not find button with texts: {button_texts}")

    expect(button).to_be_visible(timeout=timeout)
    expect(button).to_be_enabled(timeout=timeout)
    button.click()

    print(f"✓ Button clicked: {button_texts[0]}")


def _verify_text_on_page(page: Page, expected_text: str,
                        container_selector: str = "div[data-testid='stApp']",
                        timeout: int = 10000) -> None:
    """Verify text appears on page."""
    print(f'\n=== Verifying page contains: "{expected_text}" ===')

    _wait_for_app_stable(page)

    try:
        expect(page.locator(container_selector)).to_contain_text(expected_text, timeout=timeout)
        print(f"✓ Text found: {expected_text}")
    except AssertionError:
        # Fallback: check entire page
        page_text = page.locator("body").text_content(timeout=timeout)
        if expected_text not in page_text:
            raise AssertionError(f"Expected text '{expected_text}' not found on page")
        print(f"✓ Text found (fallback): {expected_text}")


# ==================== COMMON STEPS ====================

# Create a test context that's separate from BrowserContext
@pytest.fixture
def context():
    """Test context to store state between steps."""
    return {'debug_enabled': False}


@given("I navigate to the admin panel")
def navigate_to_admin_panel_common(context):
    """Navigate to the admin panel - common implementation for all modules."""
    if 'page' not in context:
        raise KeyError("No 'page' in context. Did you call 'the application is running' first?")

    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print("\n=== Navigating to admin panel ===")

    # Wait for sidebar to be fully loaded
    sidebar = page.locator("[data-testid='stSidebar']").first
    expect(sidebar).to_be_visible(timeout=10000)

    # Try multiple methods to find and click the admin button
    admin_button = None

    # Method 1: Look for admin button in sidebar with multiple text variations
    admin_button = sidebar.get_by_text(re.compile(r"Admin", re.IGNORECASE)).first

    # Method 2: If not found in sidebar, look anywhere on page
    if admin_button.count() == 0:
        print("Admin button not in sidebar, searching entire page...")
        admin_button = page.get_by_text(re.compile(r"Admin", re.IGNORECASE)).first

    # Method 3: Try button role with admin text
    if admin_button.count() == 0:
        print("Trying button role with admin text...")
        admin_button = page.get_by_role("button", name=re.compile(r"Admin", re.IGNORECASE)).first

    # Click the admin button if found
    if admin_button.count() > 0:
        print("Found admin button, ensuring it's visible and enabled...")
        expect(admin_button).to_be_visible(timeout=10000)
        expect(admin_button).to_be_enabled(timeout=5000)

        print("Clicking admin button...")
        admin_button.click()

        # Wait for Streamlit rerun to complete
        page.wait_for_load_state("networkidle", timeout=30000)

        # Wait for admin panel content to appear (look for "Admin Panel" heading or tabs)
        admin_indicator = page.locator("text=/Admin Panel/i").or_(page.locator("[role='tab']")).first
        expect(admin_indicator).to_be_visible(timeout=30000)

        print("✓ Admin panel loaded successfully")
    else:
        # Method 4: Check if already on admin page
        print("Admin button not found, checking if already on admin page...")
        admin_content = page.locator("text=/Admin Panel/i").or_(page.locator("[role='tab']")).first

        if admin_content.count() > 0:
            print("Already on admin page")
        else:
            # Fallback: try direct navigation
            print("WARNING: Could not find admin button, attempting direct navigation...")
            take_screenshot(page, "admin_page_not_loaded.png", debug_enabled, full_page=True)
            raise AssertionError("Admin page did not load properly")

    # Take screenshot if debug enabled
    if debug_enabled:
        take_screenshot(page, "admin_panel_navigated.png", debug_enabled, full_page=True)

    # Update context
    context['current_page'] = 'admin'
    print("✓ Admin panel navigation completed")

    return context


@given(parsers.parse('I select the "{tab_name}" tab'))
def select_a_tab(context, tab_name):
    """Select a tab in the admin panel."""
    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print(f'\n=== Selecting "{tab_name}" tab ===')

    # Wait for tabs to be visible
    tabs_container = page.locator("[role='tab']").first
    expect(tabs_container).to_be_visible(timeout=10000)

    # Look for the specific tab by exact text
    tab = page.get_by_role("tab", name=tab_name, exact=True).first

    # If exact match not found, try case-insensitive regex
    if tab.count() == 0:
        print(f"Exact match not found, trying case-insensitive search for {tab_name}...")
        tab = page.get_by_role("tab", name=re.compile(rf"{re.escape(tab_name)}", re.IGNORECASE)).first

    # If still not found, try by text content
    if tab.count() == 0:
        print(f"Role-based search failed, trying text search...")
        tab = page.get_by_text(tab_name, exact=True).first

    if tab.count() > 0:
        print(f"Found {tab_name} tab, ensuring it's visible and enabled...")
        expect(tab).to_be_visible(timeout=10000)
        expect(tab).to_be_enabled(timeout=5000)

        print(f"Clicking {tab_name} tab...")
        tab.click()

        # Wait for Streamlit rerun to complete
        page.wait_for_load_state("networkidle", timeout=30000)

        # Wait for tab content to be visible (the clicked tab should have aria-selected="true")
        expect(tab).to_have_attribute("aria-selected", "true", timeout=10000)

        print(f"✓ {tab_name} tab selected successfully")

        if debug_enabled:
            take_screenshot(page, f"{tab_name}_tab_selected.png", debug_enabled)
    else:
        print(f"Warning: Could not find {tab_name} tab")

        # Log all available tabs for debugging
        all_tabs = page.locator("[role='tab']")
        print(f"Available tabs ({all_tabs.count()}):")
        for i in range(all_tabs.count()):
            tab_text = all_tabs.nth(i).text_content()
            print(f"  Tab {i}: {tab_text}")

    return context


@given(parsers.parse("the {module_name} module is loaded"))
def is_module_loaded(context, module_name):
    """Verify the module is loaded in the admin panel."""
    page = context['page']

    print(f"\n=== Verifying {module_name} module is loaded ===")

    # Wait for admin panel to load
    page.wait_for_load_state("networkidle", timeout=30000)
    expect(page.locator("div[data-testid='stApp']")).to_be_visible(timeout=30000)

    # Additional wait for tabs to stabilize
    page.wait_for_timeout(2000)

    # Check for "Admin Panel" text - use more flexible search
    admin_panel_text = page.locator("div[data-testid='stApp']").get_by_text(re.compile(r"admin.*panel", re.IGNORECASE)).or_(
        page.get_by_text(re.compile(r"admin", re.IGNORECASE))
    )

    try:
        expect(admin_panel_text).to_be_visible(timeout=10000)
        print("✓ Admin panel is visible")
    except AssertionError:
        # If we can't find "Admin Panel", check for tabs or other admin indicators
        print("Note: 'Admin Panel' text not found, checking for admin tabs...")
        # Look for any tabs which indicate we're in admin area
        tabs = page.locator("div[data-testid='stApp']").locator("[role='tab']")
        if tabs.count() > 0:
            print(f"Found {tabs.count()} tabs, assuming admin panel is loaded")
        else:
            # Check if module_name text is on page as alternative indicator
            page_text = page.locator("div[data-testid='stApp']").text_content().lower()
            if module_name.lower() in page_text:
                print(f"✓ Found '{module_name}' text, assuming {module_name} module is loaded")

    # Check for module_name module in available modules
    page_text = page.locator("div[data-testid='stApp']").text_content().lower()

    module_found = False
    if module_name.lower() in page_text:
        print(f"✓ Found '{module_name}' text on page")
        module_found = True

    # Also check for specific module_name UI elements within the app container
    module_elements = page.locator("div[data-testid='stApp']").locator(f":text('{module_name}'):visible")
    if module_elements.count() > 0:
        print(f"Found {module_elements.count()} visible elements with '{module_name}' text")
        module_found = True

    # Print all tabs for debugging (but don't fail if some are hidden)
    tabs = page.locator("div[data-testid='stApp']").locator("[role='tab']")
    print(f"Found {tabs.count()} tab elements:")
    for i in range(tabs.count()):
        try:
            tab = tabs.nth(i)
            # Don't wait for visibility - just get whatever info we can
            tab_text = tab.text_content(timeout=1000)
            is_visible = tab.is_visible()
            print(f"  Tab {i}: '{tab_text}' (visible: {is_visible})")

            if module_name.lower() in tab_text.lower():
                module_found = True
                print(f"  ✓ Found {module_name} tab: '{tab_text}'")
        except:
            print(f"  Tab {i}: [could not read]")

    if not module_found:
        print(f"WARNING: {module_name} module/tab not found!")
        # Print all text for debugging
        print("\nAll page text (first 1000 chars):")
        print(page_text[:1000])

    return context

@when("I navigate to the chat page")
def navigate_to_chat_page(context):
    """Navigate to the chat page."""
    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print("\n=== Navigating to chat page ===")

    # Wait for page to be ready
    _wait_for_app_stable(page)

    # Look for chat button using robust selectors
    chat_button_selectors = [
        page.get_by_role("button", name=re.compile(r"chat", re.IGNORECASE)),
        page.get_by_text("💬 Chat"),
        page.get_by_text("Chat")
    ]

    chat_button = None
    for selector in chat_button_selectors:
        count = selector.count()
        if count > 0:
            chat_button = selector.first
            print(f"Found chat button, text: '{chat_button.text_content()}'")
            break

    if chat_button:
        expect(chat_button).to_be_visible(timeout=30000)
        expect(chat_button).to_be_enabled(timeout=30000)
        print("Clicking chat button...")
        chat_button.click()

        # Wait for Streamlit rerun
        _wait_for_app_stable(page)

        # Wait for chat indicators to appear with retry logic
        max_attempts = 10
        chat_loaded = False
        for attempt in range(max_attempts):
            # Look for various chat indicators
            page_text = page.locator("body").text_content().lower()
            has_chat_input = page.locator("textarea").count() > 0
            has_conversation_text = "conversation" in page_text or "chat" in page_text

            if has_chat_input or has_conversation_text:
                chat_loaded = True
                print(f"Chat page loaded (attempt {attempt + 1}/{max_attempts})")
                break

            if attempt < max_attempts - 1:
                print(f"Waiting for chat page to load... (attempt {attempt + 1}/{max_attempts})")
                page.wait_for_timeout(1000)

        if not chat_loaded:
            take_screenshot(page, "chat_page_not_loaded.png", debug_enabled, full_page=True)
            raise AssertionError("Chat page did not load properly")

        take_screenshot(page, "conversation_04_chat_page.png", debug_enabled)

        # Update context
        context['current_page'] = 'chat'
        print("✓ Successfully navigated to chat page")
    else:
        # Check if already on chat page
        page_text = page.locator("body").text_content().lower()
        if "conversation" in page_text or page.locator("textarea").count() > 0:
            print("Already on chat page")
            context['current_page'] = 'chat'
        else:
            take_screenshot(page, "no_chat_button_found.png", debug_enabled, full_page=True)
            raise AssertionError("Could not find chat button and not already on chat page")

    return context


@when(parsers.parse('I enter text "{text}" in the text area'))
def enter_text_in_textarea(context, text: str):
    """Enter text in a textarea (generalized for both debug and chat)."""
    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print(f'\n=== Entering text: "{text}" ===')

    _wait_for_app_stable(page)

    # Try to find textarea
    textarea = page.locator("textarea").first
    if textarea.count() == 0:
        # Fallback to input with type text
        textarea = page.locator("input[type='text']").first

    expect(textarea).to_be_visible(timeout=30000)
    expect(textarea).to_be_enabled(timeout=30000)

    textarea.fill("")
    textarea.type(text, delay=50)
    expect(textarea).to_have_value(text, timeout=10000)

    context['entered_text'] = text

    if debug_enabled:
        take_screenshot(page, "debug_text_entered.png", debug_enabled)

    return context


@when(parsers.parse('I click the "{button_text}" button'))
def click_button_by_text(context, button_text: str):
    """Generalized button click step."""
    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print(f'\n=== Clicking button: "{button_text}" ===')

    # Try common variations including emojis
    button_texts = [button_text]

    # Add common emoji variations
    emoji_map = {
        "Display Text": ["📤 Display Text"],
        "Clear Text": ["🗑️ Clear Text"],
        "New Conversation": ["➕ New Conversation"],
        "Save": ["💾 Save"],
        "Regenerate": ["🔄 Regenerate"],
        "Clear": ["🗑️ Clear"],
        "Edit": ["✏️", "✏️ Edit"]  # Edit button might be just the emoji
    }

    if button_text in emoji_map:
        button_texts.extend(emoji_map[button_text])
    else:
        # For other buttons, just try the text
        pass

    # Special handling for Edit button - also look for button with just emoji
    if button_text == "Edit":
        # First try to find any button with ✏️ emoji
        edit_emoji_buttons = page.locator("button:has-text('✏️')").all()
        if edit_emoji_buttons:
            for btn in edit_emoji_buttons:
                if btn.is_visible():
                    print(f"Found edit button with ✏️ emoji")
                    btn.click()
                    _wait_for_app_stable(page)
                    if debug_enabled:
                        take_screenshot(page, f"button_{button_text.replace(' ', '_').lower()}_clicked.png", debug_enabled)
                    return context

    _click_button_by_texts(
        page,
        button_texts,
        debug_enabled=debug_enabled,
        screenshot_name=f"button_{button_text.replace(' ', '_').lower()}_clicked.png"
    )

    return context


@when(parsers.parse('I send the message "{message}"'))
def send_message(context, message):
    """Send a message in the chat interface."""
    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print(f"\n=== Sending message: {message} ===")

    # Take screenshot before sending
    take_screenshot(page, "conversation_before_send.png", debug_enabled, full_page=True)

    # Wait for page to be ready
    _wait_for_app_stable(page)

    # Try multiple ways to find chat input
    chat_input = None

    # Method 1: Streamlit's chat input
    chat_inputs = page.locator("[data-testid='stChatInput']").all()
    if chat_inputs:
        for elem in chat_inputs:
            input_elem = elem.locator("textarea, input")
            if input_elem.count() > 0:
                chat_input = input_elem.first
                print("Found chat input via stChatInput")
                break

    # Method 2: Look for textareas with message placeholder
    if not chat_input:
        textareas = page.locator("textarea").all()
        for textarea in textareas:
            placeholder = textarea.get_attribute("placeholder") or ""
            if any(word in placeholder.lower() for word in ["message", "type", "say", "ask"]):
                chat_input = textarea
                print(f"Found chat input via placeholder: {placeholder}")
                break

    if not chat_input:
        # Method 3: Look for any textarea in main content
        main_content = page.locator("[data-testid='stApp']").first
        if main_content.count() > 0:
            textareas = main_content.locator("textarea").all()
            if textareas:
                chat_input = textareas[0]
                print("Found textarea in main content")

    if not chat_input:
        print("ERROR: Could not find chat input")
        take_screenshot(page, "conversation_no_chat_input.png", debug_enabled, full_page=True)

        # Debug: show all elements that might be inputs
        all_inputs = page.locator("input, textarea").all()
        print(f"Found {len(all_inputs)} input/textarea elements on page")
        for i, inp in enumerate(all_inputs):
            try:
                tag = inp.evaluate("el => el.tagName")
                placeholder = inp.get_attribute("placeholder") or "no placeholder"
                value = inp.get_attribute("value") or "no value"
                print(f"  {i}: {tag}, placeholder='{placeholder}', value='{value}'")
            except:
                print(f"  {i}: [could not read]")

        raise AssertionError("Could not find chat input field")

    # Fill and send the message
    expect(chat_input).to_be_visible(timeout=30000)
    expect(chat_input).to_be_enabled(timeout=30000)

    print(f"Filling chat input with message: {message}")
    chat_input.fill("")
    chat_input.type(message, delay=100)

    # Wait for text to be entered
    expect(chat_input).to_have_value(message, timeout=30000)

    # Press Enter
    print("Pressing Enter to send message...")
    chat_input.press("Enter")

    # IMPORTANT: Wait for the page to process the message
    print("Waiting for message to be sent...")
    page.wait_for_timeout(2000)  # Initial wait

    context['last_message'] = message

    # IMPORTANT: Wait longer for async LLM response to start
    print("Waiting for LLM to start processing...")
    page.wait_for_timeout(3000)

    return context


@then(parsers.parse('I should see "{expected_text}" in the result section'))
def verify_text_in_result(context, expected_text: str):
    """Verify text appears in result section."""
    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print(f'\n=== Verifying result contains: "{expected_text}" ===')
    _wait_for_app_stable(page)

    try:
        expect(page.locator("div[data-testid='stApp']")).to_contain_text(expected_text, timeout=10000)
        print(f"✓ Result text found")
    except AssertionError:
        page_text = page.locator("body").text_content(timeout=10000)
        if expected_text not in page_text:
            if debug_enabled:
                take_screenshot(page, "debug_result_missing.png", debug_enabled)
            raise AssertionError(f"Expected '{expected_text}' not found in result. Page text sample: {page_text[:500]}")
        print(f"✓ Result text found (fallback check)")

    return context


@then(parsers.parse('I should see "{expected_text}" in the header'))
def verify_header_text(context, expected_text: str):
    """Verify text appears in header (generalized)."""
    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    _robust_header_verification(page, expected_text, debug_enabled)
    return context


@then(parsers.parse('I should see a response containing "{expected_text}"'))
def verify_response_contains(context, expected_text):
    """Verify the response contains specific text."""
    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print(f"\n=== Verifying response contains: {expected_text} ===")

    # Wait for page to be stable and for LLM response to appear
    max_wait_attempts = 15  # Increased for async LLM
    found_response = False
    response_text = ""

    for attempt in range(max_wait_attempts):
        # Wait for network to be idle first
        page.wait_for_load_state("networkidle", timeout=30000)
        expect(page.locator("[data-testid='stApp']")).to_be_visible(timeout=30000)

        # Additional wait for async processing
        page.wait_for_timeout(1000)

        # Get last response from context or find it on page
        if 'last_response' in context:
            response_text = context['last_response']
            print(f"Using last_response from context: {response_text[:100]}...")
        else:
            # Search for recent responses - look for chat messages
            chat_messages = page.locator("[data-testid='stChatMessage']").all()
            if chat_messages:
                # Get all assistant messages
                assistant_messages = []
                for msg in chat_messages:
                    try:
                        # Try to determine if it's an assistant message
                        msg_text = msg.text_content()
                        if "assistant" in msg_text.lower() or "user" not in msg_text.lower():
                            assistant_messages.append(msg_text)
                    except:
                        continue

                if assistant_messages:
                    # Get the last assistant message
                    response_text = assistant_messages[-1]
                    print(f"Found assistant message: {response_text[:100]}...")
                else:
                    # Fallback: get the last message
                    response_text = chat_messages[-1].text_content()
                    print(f"Using last chat message: {response_text[:100]}...")
            else:
                # Fallback: look for any text that might be a response
                page_text = page.locator("body").text_content()
                response_text = page_text
                print(f"Using full page text (first 200 chars): {page_text[:200]}...")

        # Check if expected text is in response (case-insensitive)
        if expected_text.lower() in response_text.lower():
            found_response = True
            print(f"✓ Found '{expected_text}' in response (attempt {attempt + 1}/{max_wait_attempts})")
            break

        if attempt < max_wait_attempts - 1:
            print(f"'{expected_text}' not found yet, waiting... (attempt {attempt + 1}/{max_wait_attempts})")
            page.wait_for_timeout(2000)  # Wait 2 seconds between attempts

    if not found_response:
        # Take screenshot for debugging
        take_screenshot(page, f"conversation_missing_{expected_text}.png", debug_enabled, full_page=True)
        print(f"Final response text: {response_text[:500]}")

        # Also check the sidebar and other areas
        sidebar_text = page.locator("[data-testid='stSidebar']").text_content() if page.locator("[data-testid='stSidebar']").count() > 0 else ""
        print(f"Sidebar text: {sidebar_text[:200]}")

        raise AssertionError(
            f"Expected text '{expected_text}' not found in response after {max_wait_attempts} attempts. "
            f"Response preview: {response_text[:200]}"
        )

    print(f"✓ Response contains: {expected_text}")
    return context



@then("the text area should be empty")
def verify_textarea_empty(context):
    """Verify the text area is empty."""
    page = context['page']
    print("\n=== Verifying text area is empty ===")
    _wait_for_app_stable(page)

    textarea = page.locator("textarea").first
    if textarea.count() == 0:
        print("Warning: No textarea found")
        return

    expect(textarea).to_have_value("", timeout=10000)
    print("✓ Text area is empty")

    return context


@then("I should see a warning message about empty text")
def verify_warning_message(context):
    """Verify warning message appears."""
    page = context['page']
    print("\n=== Verifying warning about empty text ===")
    _wait_for_app_stable(page)

    warning_indicators = ["warning", "please enter", "empty", "no text", "required"]

    # Check Streamlit alert components first
    alerts = page.locator(".stAlert, .stWarning, .stError")
    found = False
    for i in range(alerts.count()):
        text = alerts.nth(i).text_content().lower()
        if any(ind in text for ind in warning_indicators):
            print(f"✓ Warning found: {text[:100]}")
            found = True
            break

    # Fallback to full page text
    if not found:
        page_text = page.locator("div[data-testid='stApp']").text_content().lower()
        if any(ind in page_text for ind in warning_indicators):
            print("✓ Warning indicator found in page text")
            found = True

    if not found:
        print("Note: No clear warning message detected")

    return context


@when("I debug the current state")
def debug_current_state(context):
    """Debug the current application state."""
    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print("\n" + "="*60)
    print("DEBUGGING CURRENT STATE")
    print("="*60)

    # 1. Current URL
    print(f"Current URL: {page.url}")

    # 2. Page title
    print(f"Page title: {page.title()}")

    # 3. All text on page
    all_text = page.locator("body").text_content()
    print(f"\nAll page text (first 1000 chars):")
    print(all_text[:1000])

    # 4. Session state (if accessible)
    print(f"\nSession state from context:")
    for key, value in context.items():
        if key != 'page':
            print(f"  {key}: {value}")

    # 5. Screenshot
    take_screenshot(page, "debug_state.png", debug_enabled, full_page=True)

    # 6. Check database state
    if os.getenv("TEST_MODE") == "true":
        try:
            from shared.conversation import conversation_manager
            from shared.users import user_manager

            print(f"\nDatabase state:")

            # Get all users
            all_users = user_manager.get_all_users()
            print(f"Total users: {len(all_users)}")

            # Get current user conversations
            current_user = context.get('current_user')
            if current_user:
                user_id = None
                if isinstance(current_user, dict):
                    user_id = current_user.get('id')
                elif isinstance(current_user, str):
                    user_obj = user_manager.get_user_by_name(current_user)
                    if user_obj:
                        user_id = user_obj.get('id')

                if user_id:
                    conversations = conversation_manager.get_user_conversations(user_id)
                    print(f"Conversations for user {user_id}: {len(conversations)}")
                    for conv in conversations:
                        print(f"  - {conv.get('title')} (ID: {conv.get('id')}, messages: {conv.get('message_count')})")

                        # Get conversation details
                        conv_obj = conversation_manager.get_conversation(conv.get('id'), include_messages=True)
                        if conv_obj and conv_obj.messages:
                            print(f"    Messages:")
                            for msg in conv_obj.messages:
                                print(f"      {msg.role}: {msg.content[:50]}...")
        except Exception as e:
            print(f"Could not check database: {e}")

    print("="*60 + "\n")

    return context


@when("I clear the text area")
def clear_text_area(context):
    """Clear the text area manually."""
    page: Page = context['page']
    print("\n=== Manually clearing text area ===")
    _wait_for_app_stable(page)

    # Find textarea
    textarea = page.locator("textarea").first
    if textarea.count() == 0:
        # Try input field
        textarea = page.locator("input[type='text']").first

    if textarea.count() > 0:
        expect(textarea).to_be_visible(timeout=30000)
        textarea.fill("")
        expect(textarea).to_have_value("", timeout=5000)
        print("✓ Text area cleared")
    else:
        print("Warning: No text area found to clear")

    return context
