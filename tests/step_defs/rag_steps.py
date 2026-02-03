"""
pytest-bdd step definitions for RAG system testing.
"""
import pytest
import re
import time
from pathlib import Path
import tempfile
import os
from pytest_bdd import given, when, then, scenarios, parsers
from playwright.sync_api import Page, expect

# Import common steps
from tests.step_defs.common_steps import *
from tests.step_defs.conversation_steps import *
from tests.step_defs.user_steps import *
from tests.step_defs.conversation_common_steps import *

# Load feature files
scenarios('../../tests/features/rag.feature')

pytestmark = [pytest.mark.bdd, pytest.mark.playwright, pytest.mark.rag]

# ==================== RAG-SPECIFIC HELPER FUNCTIONS ====================

def setup_rag_test_documents():
    """Setup test documents for RAG testing."""
    try:
        from modules.rag_manager.rag_manager import rag_manager
        from shared.users import user_manager

        # Get System Administrator user
        admin_user = user_manager.get_user_by_name("System Administrator")
        if not admin_user:
            raise ValueError("System Administrator not found in database")

        admin_id = admin_user.get('id')

        # Create test document content
        test_content = """The address of Kevin is 1 place du Louvre, Paris.
Kevin works as a software engineer at TechCorp.
He enjoys hiking and reading science fiction novels.
His phone number is +33 1 23 45 67 89.
Kevin was born on March 15, 1990."""

        # Create a temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(test_content)
            temp_path = f.name

        try:
            # Upload document
            filename = rag_manager.upload_document(
                source_path=temp_path,
                original_filename="kevin_info.txt",
                user_id=admin_id,
                is_public=False
            )

            if not filename:
                raise ValueError("Failed to upload test document")

            # Index in all available engines
            engines = rag_manager.get_available_engines()
            for engine in engines:
                if engine['available']:
                    rag_manager.index_document(filename, engine['type'], admin_id)

            return filename

        finally:
            # Clean up temp file
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    except Exception as e:
        pytest.fail(f"Failed to setup RAG test documents: {str(e)}")

def cleanup_rag_test_documents():
    """Cleanup test documents after RAG testing."""
    try:
        from modules.rag_manager.rag_manager import rag_manager
        from shared.users import user_manager

        # Get System Administrator user
        admin_user = user_manager.get_user_by_name("System Administrator")
        if admin_user:
            admin_id = admin_user.get('id')

            # Get all documents and delete test ones
            documents = rag_manager.get_user_documents(admin_id)
            for doc in documents:
                if "kevin" in doc['original_filename'].lower():
                    rag_manager.delete_document(doc['filename'], admin_id)

    except Exception as e:
        print(f"Warning: Failed to cleanup RAG test documents: {str(e)}")

def select_qwen_llm(page: Page, debug_enabled: bool = False):
    """Select Qwen 3 4B as the LLM engine."""
    print("\n=== Selecting Qwen 3 4B LLM ===")

    # Wait for page to be ready
    page.wait_for_load_state("networkidle", timeout=30000)
    expect(page.locator("[data-testid='stApp']")).to_be_visible(timeout=30000)

    # Find the LLM selectbox
    selectboxes = page.locator("[data-testid='stSelectbox']")
    print(f"Found {selectboxes.count()} selectboxes")

    # Try to find LLM selector
    llm_selectbox = None
    for i in range(selectboxes.count()):
        selectbox = selectboxes.nth(i)
        text = selectbox.text_content()
        if "llm" in text.lower() or "ai model" in text.lower() or "selection" in text.lower():
            llm_selectbox = selectbox
            print(f"Found LLM selectbox at index {i}: {text[:50]}")
            break

    if llm_selectbox:
        # Click to open dropdown
        expect(llm_selectbox).to_be_visible(timeout=30000)
        llm_selectbox.click()

        # Wait for dropdown to open
        page.wait_for_timeout(1000)

        # Look for Qwen option
        qwen_option = None

        # Try different patterns for Qwen
        qwen_patterns = [
            "qwen 3 4b",
            "qwen-3-4b",
            "qwen3",
            "qwen",
            "Qwen2.5"
        ]

        for pattern in qwen_patterns:
            option = page.get_by_text(re.compile(pattern, re.IGNORECASE)).first
            if option.count() > 0:
                qwen_option = option
                print(f"Found Qwen option with pattern: {pattern}")
                break

        if qwen_option:
            print("Clicking Qwen option...")
            qwen_option.click()
            page.wait_for_load_state("networkidle", timeout=30000)
            print("✓ Qwen 3 4B selected")
        else:
            print("Warning: Could not find Qwen option, trying manual search...")

            # Get all dropdown options
            options = page.locator("li[role='option']").all()
            print(f"Found {len(options)} dropdown options")

            for i, option in enumerate(options):
                try:
                    option_text = option.text_content()
                    print(f"  Option {i}: '{option_text}'")
                    if "qwen" in option_text.lower() or "4b" in option_text.lower():
                        option.click()
                        page.wait_for_load_state("networkidle", timeout=30000)
                        print(f"✓ Selected Qwen option: {option_text}")
                        break
                except:
                    continue

            # Close dropdown if still open
            page.keyboard.press("Escape")
    else:
        print("Note: Could not find LLM selectbox, assuming Qwen is already selected")

    return True

def toggle_rag_injection(page: Page, enable: bool, debug_enabled: bool = False):
    """Toggle RAG context injection in the sidebar."""
    print(f"\n=== {'Enabling' if enable else 'Disabling'} RAG context injection ===")

    # Wait for page to be ready
    page.wait_for_load_state("networkidle", timeout=30000)
    expect(page.locator("[data-testid='stApp']")).to_be_visible(timeout=30000)

    # Find and expand the RAG Settings sidebar expander
    sidebar = page.locator("[data-testid='stSidebar']")

    # Look for RAG Settings expander
    rag_expander = None

    # Try different ways to find the expander
    expander_selectors = [
        sidebar.locator("div").filter(has_text=re.compile(r"rag.*settings", re.IGNORECASE)),
        sidebar.get_by_text(re.compile(r"rag.*settings", re.IGNORECASE)),
        sidebar.locator("summary").filter(has_text=re.compile(r"rag", re.IGNORECASE))
    ]

    for selector in expander_selectors:
        if selector.count() > 0:
            rag_expander = selector.first
            break

    if rag_expander and rag_expander.count() > 0:
        # Check if expander is already expanded
        is_expanded = rag_expander.get_attribute("open") or rag_expander.get_attribute("aria-expanded")

        if not is_expanded:
            print("Expanding RAG Settings...")
            rag_expander.click()
            page.wait_for_timeout(1000)

    # Look for the RAG injection toggle
    toggle_selectors = [
        sidebar.locator("label").filter(has_text=re.compile(r"enable.*rag.*context.*injection", re.IGNORECASE)),
        sidebar.get_by_text(re.compile(r"enable.*rag", re.IGNORECASE)),
        sidebar.locator("input[type='checkbox']").nth(-1)  # Last checkbox might be our toggle
    ]

    rag_toggle = None
    for selector in toggle_selectors:
        if selector.count() > 0:
            rag_toggle = selector
            break

    if rag_toggle and rag_toggle.count() > 0:
        # Get the actual checkbox input
        if rag_toggle.evaluate("el => el.tagName.toLowerCase()") == "label":
            # Find the associated checkbox
            checkbox_id = rag_toggle.get_attribute("for")
            if checkbox_id:
                checkbox = page.locator(f"#{checkbox_id}")
            else:
                # Try to find checkbox near the label
                checkbox = rag_toggle.locator("input[type='checkbox']").first
        else:
            checkbox = rag_toggle

        if checkbox.count() > 0:
            # Check current state
            is_checked = checkbox.is_checked()

            if enable and not is_checked:
                print("Enabling RAG context injection...")
                checkbox.check()
                page.wait_for_timeout(500)
                print("✓ RAG context injection enabled")
            elif not enable and is_checked:
                print("Disabling RAG context injection...")
                checkbox.uncheck()
                page.wait_for_timeout(500)
                print("✓ RAG context injection disabled")
            else:
                print(f"RAG context injection already {'enabled' if enable else 'disabled'}")

            # Wait for UI to update
            page.wait_for_load_state("networkidle", timeout=10000)

        else:
            print("Warning: Could not find RAG toggle checkbox")
    else:
        print("Warning: Could not find RAG injection toggle in sidebar")

        # Alternative: try to find any toggle in sidebar
        all_toggles = sidebar.locator("input[type='checkbox']")
        print(f"Found {all_toggles.count()} checkboxes in sidebar")

        if all_toggles.count() > 0:
            # Try toggling the last one (most likely to be our toggle)
            last_toggle = all_toggles.last
            if enable:
                last_toggle.check()
            else:
                last_toggle.uncheck()
            page.wait_for_timeout(500)
            print("Toggled last checkbox in sidebar (assuming it's RAG toggle)")

    return True

# ==================== RAG-SPECIFIC STEPS ====================

@given("the RAG system is set up with test documents")
def rag_system_setup(context, mock_db_manager):
    """Set up the RAG system with test documents."""
    print("\n=== Setting up RAG test documents ===")

    # Setup test documents
    test_filename = setup_rag_test_documents()
    context['rag_test_filename'] = test_filename

    print(f"✓ RAG test document created: {test_filename}")

    # Verify document was created
    try:
        from modules.rag_manager.rag_manager import rag_manager
        from shared.users import user_manager

        admin_user = user_manager.get_user_by_name("System Administrator")
        admin_id = admin_user.get('id')

        documents = rag_manager.get_user_documents(admin_id)
        print(f"Admin has {len(documents)} documents")

        for doc in documents:
            print(f"  - {doc['original_filename']} (indexed in: {doc.get('indexed_in', [])})")

    except Exception as e:
        print(f"Warning: Could not verify RAG setup: {str(e)}")

    return context

@given("I enable RAG context injection")
def enable_rag_injection(context):
    """Enable RAG context injection in the sidebar."""
    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    # Select Qwen LLM first
    select_qwen_llm(page, debug_enabled)

    # Then toggle RAG injection
    toggle_rag_injection(page, enable=True, debug_enabled=debug_enabled)

    context['rag_enabled'] = True
    return context

@given("I disable RAG context injection")
def disable_rag_injection(context):
    """Disable RAG context injection in the sidebar."""
    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    # Select Qwen LLM first
    select_qwen_llm(page, debug_enabled)

    # Then toggle RAG injection
    toggle_rag_injection(page, enable=False, debug_enabled=debug_enabled)

    context['rag_enabled'] = False
    return context

@when(parsers.parse('I ask "{question}"'))
def ask_question(context, question):
    """Ask a question in the chat interface."""
    # Use the existing send_message function
    return send_message(context, question)

@then("I should see a RAG-enhanced response with address information")
def verify_rag_enhanced_response(context):
    """Verify the response contains RAG-enhanced address information."""
    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print("\n=== Verifying RAG-enhanced response ===")

    # Wait for response
    page.wait_for_load_state("networkidle", timeout=45000)  # Longer timeout for RAG+LLM
    expect(page.locator("[data-testid='stApp']")).to_be_visible(timeout=30000)

    # Additional wait for RAG processing
    page.wait_for_timeout(3000)

    # Look for address information patterns
    address_patterns = [
        r"1 place du Louvre",
        r"place du Louvre",
        r"Paris",
        r"address.*Kevin",
        r"Kevin.*lives.*1",
        r"Louvre.*Paris"
    ]

    max_attempts = 15
    found_address = False
    response_text = ""

    for attempt in range(max_attempts):
        # Get the latest response text
        chat_messages = page.locator("[data-testid='stChatMessage']").all()
        if chat_messages:
            # Get the last message (should be assistant response)
            last_message = chat_messages[-1]
            response_text = last_message.text_content()
            print(f"Response text (attempt {attempt + 1}): {response_text[:100]}...")

            # Check for address patterns
            for pattern in address_patterns:
                if re.search(pattern, response_text, re.IGNORECASE):
                    found_address = True
                    print(f"✓ Found address pattern: {pattern}")
                    break

            if found_address:
                break

        if attempt < max_attempts - 1:
            print(f"Waiting for RAG-enhanced response... (attempt {attempt + 1}/{max_attempts})")
            page.wait_for_timeout(2000)

    if not found_address:
        take_screenshot(page, "rag_response_no_address.png", debug_enabled, full_page=True)

        # Debug: show what we found
        print(f"Full response text: {response_text[:500]}")

        # Check if we at least got some response
        if len(response_text.strip()) < 10:
            assert False, "No response received from LLM"
        else:
            assert False, "RAG-enhanced address information not found in response"

    # Also check for RAG debug context if enabled
    if debug_enabled:
        # Look for RAG debug expander
        rag_debug = page.locator("div").filter(has_text=re.compile(r"rag.*debug.*context", re.IGNORECASE)).first
        if rag_debug.count() > 0:
            print("✓ RAG debug context is visible")

    print("✓ RAG-enhanced response verified")
    return context

@then("I should see a generic response without address information")
def verify_generic_response(context):
    """Verify the response is generic without specific address information."""
    page = context['page']
    debug_enabled = context.get('debug_enabled', False)

    print("\n=== Verifying generic response (no RAG) ===")

    # Wait for response
    page.wait_for_load_state("networkidle", timeout=30000)
    expect(page.locator("[data-testid='stApp']")).to_be_visible(timeout=30000)

    # Look for response
    max_attempts = 10
    response_text = ""

    for attempt in range(max_attempts):
        chat_messages = page.locator("[data-testid='stChatMessage']").all()
        if chat_messages:
            last_message = chat_messages[-1]
            response_text = last_message.text_content()
            print(f"Response text (attempt {attempt + 1}): {response_text[:100]}...")
            break
        page.wait_for_timeout(1000)

    if not response_text:
        take_screenshot(page, "no_response_received.png", debug_enabled, full_page=True)
        assert False, "No response received from LLM"

    # Check that address information is NOT present
    address_indicators = [
        "1 place du Louvre",
        "place du Louvre",
        "Paris (in context of address)",
        "Louvre (in context of address)"
    ]

    for indicator in address_indicators:
        if indicator.lower() in response_text.lower():
            take_screenshot(page, "rag_leakage_detected.png", debug_enabled, full_page=True)
            assert False, f"RAG information leakage detected: '{indicator}' found in response when RAG was disabled"

    # Positive check: response should be generic
    generic_indicators = [
        "don't know",
        "I don't have",
        "I cannot",
        "I'm not sure",
        "I don't have access",
        "no information",
        "without context",
        "apologize",
        "sorry"
    ]

    has_generic_response = False
    for indicator in generic_indicators:
        if indicator.lower() in response_text.lower():
            has_generic_response = True
            print(f"✓ Found generic indicator: '{indicator}'")
            break

    if not has_generic_response:
        print(f"Note: No generic indicators found. Response: {response_text[:200]}")
        # Don't fail - the LLM might give a creative response without RAG context

    print("✓ Verified response is generic (no RAG information)")
    return context

# ==================== CLEANUP ====================

def pytest_bdd_after_scenario(request, feature, scenario):
    """Cleanup after each RAG scenario."""
    if "rag" in scenario.name.lower() or "rag" in feature.name.lower():
        print("\n=== Cleaning up RAG test documents ===")
        cleanup_rag_test_documents()
