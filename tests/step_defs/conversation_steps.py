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

# Load feature files
scenarios('../../tests/features/conversation.feature')

pytestmark = [pytest.mark.bdd, pytest.mark.playwright]


from tests.step_defs.page_helpers import *
from tests.step_defs.app_start_steps import *
from tests.step_defs.user_steps import *
from tests.step_defs.llm_steps import *
from tests.step_defs.conversation_common_steps import *
from tests.step_defs.common_steps import *
