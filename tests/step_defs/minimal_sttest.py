# file name: simplest_test.py
"""
Simplest possible working test.
"""
import os
from streamlit.testing.v1 import AppTest

pytestmark = [pytest.mark.bdd, pytest.mark.streamlit_testing]

def test_find_test_on_page():
    """Simple test that finds 'Test' on the page."""
    os.environ["TEST_MODE"] = "true"

    # Create AppTest
    at = AppTest.from_file("../../prof.py", default_timeout=30)

    # Setup minimal session state
    at.session_state["current_language"] = "en"
    at.session_state["app_initialized"] = True
    at.session_state["current_page"] = "admin"
    at.session_state["admin_current_tab"] = "Test"

    # Run
    at.run()

    # Simple check: is there any 'Test' text on the page?
    found = False

    # Check titles
    for title in at.title:
        if "Test" in str(title.value):
            print(f"Found in title: {title.value}")
            found = True

    # Check headers
    if not found:
        for header in at.get("heading") or []:
            if hasattr(header, 'value') and "Test" in str(header.value):
                print(f"Found in header: {header.value}")
                found = True

    # Check text elements
    if not found:
        for text in at.get("text") or []:
            if hasattr(text, 'value') and "Test" in str(text.value):
                print(f"Found in text: {str(text.value)[:50]}...")
                found = True

    # Check markdown
    if not found:
        for md in at.get("markdown") or []:
            if hasattr(md, 'value') and "Test" in str(md.value):
                print(f"Found in markdown: {str(md.value)[:50]}...")
                found = True

    assert found, "Should find 'Test' somewhere"
    print("✅ Test passed!")

def test_admin_page_loads():
    """Test that admin page loads."""
    os.environ["TEST_MODE"] = "true"

    at = AppTest.from_file("../../prof.py", default_timeout=30)
    at.session_state["current_language"] = "en"
    at.session_state["app_initialized"] = True
    at.session_state["current_page"] = "admin"

    at.run()

    # Verify session state
    assert at.session_state["current_page"] == "admin"

    # Check for admin content
    has_admin = False
    for title in at.title:
        if "Admin" in str(title.value):
            has_admin = True
            break

    if not has_admin:
        for header in at.get("heading") or []:
            if hasattr(header, 'value') and "Admin" in str(header.value):
                has_admin = True
                break

    assert has_admin, "Should have admin content"
    print("✅ Admin page loads correctly")
