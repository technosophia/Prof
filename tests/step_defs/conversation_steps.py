"""
pytest-bdd step definitions for conversation testing.
Tests the complete conversation flow with mock LLM.
"""
import pytest
import re
from pytest_bdd import given, when, then, scenarios, parsers
import sys
import os
import subprocess
import requests
from playwright.sync_api import Page, expect, BrowserContext

# Add the project root to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

# Load feature files
scenarios('../../tests/features/conversation.feature')

pytestmark = [pytest.mark.bdd, pytest.mark.playwright]

# Re-use fixtures from conversation tests
from tests.conftest import (
    setup_test_environment,
    playwright,
    browser,

    enable_debug,
    streamlit_server,
    browser_context,
    page as conversation_page,
    debug_dir,
    take_screenshot
)

from tests.step_defs.common_steps import *
from tests.step_defs.app_start_steps import *
from tests.step_defs.user_steps import *
from tests.step_defs.common_steps import _wait_for_app_stable, _click_button_by_texts, _robust_header_verification
from tests.step_defs.llm_steps import *
from tests.step_defs.conversation_common_steps import *
