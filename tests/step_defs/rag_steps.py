# file: tests/step_defs/rag_steps.py
"""
pytest-bdd step definitions for RAG system testing.
"""
import re
import time
import pytest
from pytest_bdd import given, when, then, scenarios, parsers
from playwright.sync_api import Page, expect

from tests.step_defs.page_helpers import *
from tests.step_defs.app_start_steps import *
from tests.step_defs.common_steps import *
from tests.step_defs.user_steps import *
from tests.step_defs.conversation_common_steps import *


try:
    from st_shared.cached import get_config
except ImportError:
    def get_config():
        return {}

scenarios("../../tests/features/rag.feature")

pytestmark = [pytest.mark.bdd, pytest.mark.playwright, pytest.mark.rag]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _select_rag_llm(page: Page, model_names: list, debug_enabled: bool = False) -> bool:
    """Select an LLM from the dropdown matching any of the given name patterns."""
    wait_for_app_stable(page)
    selectboxes = page.locator("[data-testid='stSelectbox']")

    llm_selectbox = None
    for i in range(selectboxes.count()):
        text = (selectboxes.nth(i).text_content() or "").lower()
        if any(kw in text for kw in ("llm", "ai model", "selection")):
            llm_selectbox = selectboxes.nth(i)
            break

    if not llm_selectbox:
        print("  ⚠ LLM selectbox not found — assuming correct model already selected")
        return True

    expect(llm_selectbox).to_be_visible(timeout=DEFAULT_TIMEOUT)
    llm_selectbox.click()
    page.wait_for_timeout(POLL_INTERVAL)

    option_sel = '[data-testid="stSelectboxOption"], div[role="option"], li[role="option"]'
    options = page.locator(option_sel)
    for i in range(options.count()):
        opt_text = options.nth(i).text_content() or ""
        for pattern in model_names:
            if pattern.lower() in opt_text.lower():
                options.nth(i).click()
                wait_for_app_stable(page)
                print(f"  ✓ Selected LLM: '{opt_text.strip()}'")
                return True

    page.keyboard.press("Escape")
    print(f"  ⚠ None of {model_names} found in LLM dropdown")
    return False


def _toggle_rag(page: Page, enable: bool, debug_enabled: bool = False) -> bool:
    """Toggle the RAG context injection checkbox in the sidebar."""
    print(f"\n=== {'Enabling' if enable else 'Disabling'} RAG context injection ===")
    wait_for_app_stable(page)

    sidebar = page.locator("[data-testid='stSidebar']")

    # Expand RAG Settings expander if present
    expander = sidebar.get_by_text(
        re.compile(r"⚙️\s*RAG Settings|RAG Settings", re.IGNORECASE)
    )
    if expander.count() > 0:
        expander.click()
        page.wait_for_timeout(500)

    # Locate the checkbox
    checkbox = None
    for sel in (
        "input[type='checkbox'][aria-label*='RAG'][aria-label*='Context'][aria-label*='Injection']",
        "input[type='checkbox'][aria-label*='RAG']",
    ):
        candidate = sidebar.locator(sel)
        if candidate.count() > 0:
            checkbox = candidate.first
            break

    # Fallback: checkbox near RAG text
    if not checkbox or checkbox.count() == 0:
        rag_text = sidebar.get_by_text(
            re.compile(r"Enable.*RAG.*Context.*Injection", re.IGNORECASE)
        )
        if rag_text.count() > 0:
            checkbox = rag_text.locator("..").locator("..").locator("input[type='checkbox']").first

    # Last resort: any sidebar checkbox
    if not checkbox or checkbox.count() == 0:
        all_cb = sidebar.locator("input[type='checkbox']")
        if all_cb.count() > 0:
            checkbox = all_cb.last
        else:
            print("  ⚠ RAG toggle checkbox not found — skipping")
            return False

    try:
        checkbox.scroll_into_view_if_needed()
        is_checked = checkbox.is_checked()
        if (enable and not is_checked) or (not enable and is_checked):
            page.evaluate("(cb) => cb.click()", checkbox.element_handle())
            # Wait for checkbox to actually change state
            page.wait_for_function(
                f"cb => cb.checked === {str(enable).lower()}",
                arg=checkbox.element_handle(),
                timeout=5000
            )
            # Wait for any network requests triggered by the toggle
            page.wait_for_load_state("networkidle", timeout=5000)
        else:
            print(f"  RAG already {'enabled' if enable else 'disabled'}")
        return True

        page.wait_for_timeout(200)
        return True

    except Exception as exc:
        print(f"  ⚠ Error toggling RAG: {exc}")
        # Fallback: click the label
        label = sidebar.get_by_text(
            re.compile(r"Enable.*RAG.*Context.*Injection", re.IGNORECASE)
        )
        if label.count() > 0:
            label.click()
            page.wait_for_timeout(300)
            return True
        return False


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

@given("I enable RAG context injection")
def enable_rag_injection(context: dict) -> dict:
    page: Page = context["page"]
    debug_enabled = context.get("debug_enabled", False)
    cfg = get_config() if callable(get_config) else {}
    model_names = cfg.get("app.debug_llm") if cfg else ["Ollama Small", "Groq Llama 3", "Gemini"]
    _select_rag_llm(page, model_names, debug_enabled)
    _toggle_rag(page, enable=True, debug_enabled=debug_enabled)
    # Wait for the app to fully stabilise after toggle
    wait_for_app_stable(page)
    time.sleep(0.5)
    context["rag_enabled"] = True
    return context


@given("I disable RAG context injection")
def disable_rag_injection(context: dict) -> dict:
    page: Page = context["page"]
    debug_enabled = context.get("debug_enabled", False)
    cfg = get_config() if callable(get_config) else {}
    model_names = cfg.get("app.debug_llm") if cfg else ["Ollama Small", "Groq Llama 3", "Gemini"]
    _select_rag_llm(page, model_names, debug_enabled)
    _toggle_rag(page, enable=False, debug_enabled=debug_enabled)
    wait_for_app_stable(page)
    context["rag_enabled"] = False
    return context


@when(parsers.parse('I ask "{question}"'))
def ask_question(context: dict, question: str) -> dict:
    return send_message(context, question)


@then("I should see a RAG-enhanced response with address information")
def verify_rag_enhanced_response(context: dict) -> dict:
    page: Page = context["page"]
    debug_enabled = context.get("debug_enabled", False)

    print("\n=== Verifying RAG-enhanced response ===")
    wait_for_app_stable(page)
    page.wait_for_timeout(3_000)

    address_patterns = (
        r"1 place du Louvre",
        r"place du Louvre",
        r"Paris",
        r"address.*Kevin",
        r"Kevin.*lives",
        r"Louvre.*Paris",
    )

    cfg = get_config() if callable(get_config) else {}
    poll_ms = int(cfg.get("app.llm_delay", 2000)) if cfg else 2000

    response_text = wait_for_response_stable(page, min_length=30, timeout_ms=180_000)

    for pattern in address_patterns:
        if re.search(pattern, response_text, re.IGNORECASE):
            print(f"  ✓ Address pattern found: '{pattern}'")
            return context

    screenshot_on_failure(page, "rag_no_address.png")
    raise AssertionError(
        f"RAG-enhanced address not found in response.\nResponse preview: {response_text[:400]}"
    )


@then("I should see a generic response without address information")
def verify_generic_response(context: dict) -> dict:
    page: Page = context["page"]
    debug_enabled = context.get("debug_enabled", False)

    print("\n=== Verifying generic response (RAG disabled) ===")
    response_text = wait_for_response_stable(page, min_length=30, timeout_ms=180_000)

    if not response_text or len(response_text.strip()) < 10:
        screenshot_on_failure(page, "no_response_received.png")
        raise AssertionError("No response received from LLM.")

    forbidden = (
        "1 place du Louvre",
        "place du Louvre",
        "1 place du Louvre, Paris",
        "Louvre, Paris",
    )
    leaked = [f for f in forbidden if f.lower() in response_text.lower()]
    if leaked:
        screenshot_on_failure(page, "rag_leakage_detected.png")
        raise AssertionError(
            f"RAG information leaked when disabled: {leaked}\n"
            f"Response preview: {response_text[:400]}"
        )

    print("  ✓ No specific address information leaked")
    return context
