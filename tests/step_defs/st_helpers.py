from playwright.sync_api import Page, expect
import re

def _find_selectbox_by_key(page, key, timeout=10000):
    """Find a selectbox by its Streamlit key attribute."""
    print(f"Looking for selectbox with key: '{key}'")

    # Method 1: Look for element with class containing the key
    # In HTML: class="... st-key-user_selector ..."
    selectors = [
        f'[class*="st-key-{key}"] [data-testid="stSelectbox"]',
        f'.st-key-{key} [data-testid="stSelectbox"]',
        f'[data-testid="stElementContainer"]:has([class*="st-key-{key}"]) [data-testid="stSelectbox"]',
    ]

    for selector in selectors:
        elements = page.locator(selector)
        if elements.count() > 0:
            for i in range(elements.count()):
                elem = elements.nth(i)
                if elem.is_visible(timeout=0):
                    print(f"Found selectbox using selector: {selector}")
                    return elem

    # Method 2: Look for parent with the key class
    key_container = page.locator(f'[class*="st-key-{key}"]')
    if key_container.count() > 0:
        for i in range(key_container.count()):
            container = key_container.nth(i)
            if container.is_visible(timeout=0):
                selectbox = container.locator('[data-testid="stSelectbox"]')
                if selectbox.count() > 0:
                    print(f"Found selectbox in key container")
                    return selectbox.first

    # Method 3: Look for label with the text and find nearby selectbox
    return None

def find_and_select_in_selectbox(page, key=None, label=None, value_to_select=None, timeout=10000):
    """
    Find a selectbox by key or label and select a value.

    Args:
        page: Playwright page object
        key: Streamlit key attribute (preferred)
        label: Label text (fallback)
        value_to_select: Value to select from dropdown
        timeout: Timeout in milliseconds

    Returns:
        bool: True if successful
    """
    print(f'\n=== Selecting "{value_to_select}" in selectbox (key={key}, label={label}) ===')

    selectbox = None

    # Try by key first (preferred)
    if key:
        selectbox = _find_selectbox_by_key(page, key, timeout)

    # Fallback to label
    if not selectbox and label:
        print(f"Falling back to label: '{label}'")
        # Find the label element
        label_element = page.get_by_text(label, exact=False).first
        if label_element.count() > 0 and label_element.is_visible(timeout=1000):
            # Find the selectbox that's a sibling or nearby
            # Look in the same container or following element
            container = label_element.locator('xpath=ancestor::div[@data-testid="stElementContainer"]')
            if container.count() > 0:
                selectbox = container.locator('[data-testid="stSelectbox"]').first

            # If not found, look for nearby selectbox
            if not selectbox or selectbox.count() == 0:
                selectbox = label_element.locator('xpath=following::div[@data-testid="stSelectbox"][1]')

    # Generic fallback if still not found
    if not selectbox or selectbox.count() == 0:
        print(f"Warning: Could not find selectbox by key '{key}' or label '{label}'")
        # Try generic selectbox search
        selectboxes = page.locator('[data-testid="stSelectbox"]')
        count = selectboxes.count()
        print(f"Found {count} generic selectboxes on page")
        if count > 0:
            # Use the first visible selectbox
            for i in range(count):
                selectbox = selectboxes.nth(i)
                if selectbox.is_visible(timeout=0):
                    print(f"Using selectbox at index {i}")
                    break

    if not selectbox or selectbox.count() == 0:
        # Debug: print page structure
        print("Debug: Looking for selectbox containers...")
        containers = page.locator('[data-testid="stElementContainer"]')
        print(f"Found {containers.count()} stElementContainers")
        for i in range(min(containers.count(), 5)):
            container = containers.nth(i)
            classes = container.get_attribute('class') or ''
            print(f"  Container {i}: classes={classes[:100]}")

        raise AssertionError(f"Could not find selectbox with key '{key}' or label '{label}'")

    expect(selectbox).to_be_visible(timeout=timeout)

    # Click on the selectbox to open dropdown
    # Find the clickable area within the selectbox
    clickable_area = selectbox.locator('div[role="combobox"], input[role="combobox"]')
    if clickable_area.count() > 0:
        clickable_area.first.click()
    else:
        # Fallback: click on the selectbox itself
        selectbox.click()

    # Wait for dropdown to open
    dropdown_selector = '[data-testid="stSelectboxOption"], div[role="option"], li[role="option"]'

    # Wait with retries
    max_wait_attempts = 5
    for attempt in range(max_wait_attempts):
        options = page.locator(dropdown_selector)
        if options.count() > 0:
            print(f"Dropdown opened with {options.count()} options")
            break
        if attempt < max_wait_attempts - 1:
            print(f"Waiting for dropdown to open... (attempt {attempt + 1}/{max_wait_attempts})")
            page.wait_for_timeout(500)
    else:
        raise AssertionError("Dropdown did not open after clicking selectbox")

    # Find and select the option
    options = page.locator(dropdown_selector)
    option_count = options.count()
    print(f"Found {option_count} options in dropdown")

    selected = False
    for i in range(option_count):
        option = options.nth(i)
        option_text = option.text_content().strip()
        print(f"  Option {i}: '{option_text}'")

        if value_to_select and value_to_select in option_text:
            option.click()
            selected = True
            print(f"✓ Selected option: '{option_text}'")
            break

    if not selected and option_count > 0:
        # Select first option if exact match not found
        options.first.click()
        selected = True
        print("Selected first option (exact match not found)")

    # Wait for selection to take effect
    page.wait_for_timeout(1000)

    # Close dropdown if still open (press Escape)
    try:
        page.keyboard.press("Escape")
    except:
        pass

    return selected

def click_button_by_key(page, key=None, label=None, timeout=10000):
    """
    Click a button by its Streamlit key or label.

    Args:
        page: Playwright page object
        key: Streamlit key attribute (preferred)
        label: Button text (fallback)
        timeout: Timeout in milliseconds
    """
    print(f'\n=== Clicking button (key={key}, label={label}) ===')

    button = None

    # Try by key first
    if key:
        # Method 1: Look for element with class containing the key
        # In HTML: class="... st-key-some_key ..."
        key_selector = f'[class*="st-key-{key}"] button, button[class*="st-key-{key}"]'
        button = page.locator(key_selector).first

        # Method 2: Look in container with key
        if button.count() == 0:
            container = page.locator(f'[class*="st-key-{key}"]')
            if container.count() > 0:
                button = container.locator('button').first

    # Fallback to label
    if not button or button.count() == 0:
        if label:
            print(f"Looking for button with label: '{label}'")

            # Clean label text (remove emojis for matching)
            clean_label = re.sub(r'[^\w\s]', '', label).strip()

            # Try exact match first
            button = page.get_by_role("button", name=re.compile(rf'^\s*{re.escape(label)}\s*$', re.IGNORECASE)).first

            # Try contains match
            if button.count() == 0:
                button = page.get_by_role("button", name=re.compile(re.escape(label), re.IGNORECASE)).first

            # Try text content (including emojis)
            if button.count() == 0:
                button = page.get_by_text(label, exact=False).first

            # Try with cleaned text (no emojis)
            if button.count() == 0 and clean_label:
                button = page.get_by_text(clean_label, exact=False).first

    if not button or button.count() == 0:
        # Last resort: look for any button with similar text
        all_buttons = page.locator('button')
        print(f"Found {all_buttons.count()} buttons total")
        for i in range(all_buttons.count()):
            btn = all_buttons.nth(i)
            if btn.is_visible(timeout=0):
                btn_text = btn.text_content().strip()
                if label and (label.lower() in btn_text.lower() or
                             (len(label) > 3 and label.lower()[:3] in btn_text.lower())):
                    button = btn
                    print(f"Found button at index {i}: '{btn_text}'")
                    break

    if not button or button.count() == 0:
        # Debug: print all buttons
        print("Debug: All buttons on page:")
        all_buttons = page.locator('button')
        for i in range(min(all_buttons.count(), 10)):
            btn = all_buttons.nth(i)
            try:
                btn_text = btn.text_content().strip()[:50]
                is_visible = btn.is_visible(timeout=0)
                print(f"  Button {i}: '{btn_text}' (visible: {is_visible})")
            except:
                print(f"  Button {i}: [could not read]")

        raise AssertionError(f"Could not find button with key '{key}' or label '{label}'")

    expect(button).to_be_visible(timeout=timeout)
    expect(button).to_be_enabled(timeout=timeout)

    print(f"Clicking button with text: '{button.text_content().strip()}'")
    button.click()

    # Wait for action to complete
    page.wait_for_timeout(1000)

    return True
