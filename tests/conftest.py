"""
Pytest configuration and fixtures.
"""
import sys
import os
import json
import pytest
from unittest.mock import patch

# Add the project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load test config
TEST_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "test_config.json"
)

with open(TEST_CONFIG_PATH, 'r') as f:
    TEST_CONFIG = json.load(f)


@pytest.fixture(autouse=True)
def patch_config():
    """Patch the get_config function for all tests."""
    with patch('shared.config.get_config', return_value=TEST_CONFIG):
        yield
