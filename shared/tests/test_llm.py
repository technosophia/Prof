"""
Tests for the LLM Manager
"""

import sys
import os
import asyncio
import json
import pytest
from unittest.mock import patch, Mock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

# Load test config from tests/ directory
TEST_CONFIG_PATH = os.path.join(
    PROJECT_ROOT,  # This should be /home/joriel/Code/Prof
    "tests",
    "test_config.json"
)

print(f"Looking for test config at: {TEST_CONFIG_PATH}")
print(f"File exists: {os.path.exists(TEST_CONFIG_PATH)}")

if not os.path.exists(TEST_CONFIG_PATH):
    # Try alternative locations
    alternative_paths = [
        os.path.join(PROJECT_ROOT, "test_config.json"),
        os.path.join(os.path.dirname(__file__), "test_config.json"),
        "test_config.json",
    ]

    for alt_path in alternative_paths:
        print(f"Trying alternative: {alt_path}")
        if os.path.exists(alt_path):
            TEST_CONFIG_PATH = alt_path
            print(f"Found at: {alt_path}")
            break

if not os.path.exists(TEST_CONFIG_PATH):
    raise FileNotFoundError(f"Test config not found at {TEST_CONFIG_PATH}")

with open(TEST_CONFIG_PATH, 'r') as f:
    TEST_CONFIG = json.load(f)

print(f"Successfully loaded test config from: {TEST_CONFIG_PATH}")
print(f"Test config has llms section: {'llms' in TEST_CONFIG}")
if 'llms' in TEST_CONFIG:
    print(f"LLMs in config: {list(TEST_CONFIG['llms'].keys())}")


@pytest.fixture
def patched_llm_manager():
    """Fixture that provides an LLMManager with test configuration."""
    # Clear cached imports
    modules_to_clear = ['shared.llm', 'shared.config']
    for module in modules_to_clear:
        if module in sys.modules:
            del sys.modules[module]

    # Now patch the config
    with patch('shared.config.get_config', return_value=TEST_CONFIG):
        # Import after patching
        from shared.llm import LLMManager
        manager = LLMManager()
        yield manager


@pytest.fixture
def patched_llm_module():
    """Fixture that patches the llm module for public interface tests."""
    # Clear cached imports
    modules_to_clear = ['shared.llm', 'shared.config']
    for module in modules_to_clear:
        if module in sys.modules:
            del sys.modules[module]

    # Patch before importing
    with patch('shared.config.get_config', return_value=TEST_CONFIG):
        # Import the module
        import shared.llm as llm_module

        # Clear any existing manager
        if hasattr(llm_module, '_manager'):
            llm_module._manager = None

        yield llm_module


class TestLLMManager:
    """Test LLM Manager functionality."""

    def test_discover_engines(self, patched_llm_manager):
        """Test that engines are discovered correctly."""
        manager = patched_llm_manager

        # Log what engines were found
        print(f"Discovered engines: {list(manager.engines.keys())}")

        # Should have discovered at least mock engine
        assert "mock" in manager.engines
        assert len(manager.engines) > 0

    def test_get_available_llms(self, patched_llm_manager):
        """Test getting available LLMs."""
        manager = patched_llm_manager
        llms = manager.get_available_llms()

        print(f"Available LLMs: {len(llms)}")
        for llm in llms:
            print(f"  - {llm['id']}: {llm['name']} (type: {llm['type']}, available: {llm['available']})")

        assert isinstance(llms, list)
        assert len(llms) > 0

        mock_llms = [llm for llm in llms if llm["type"] == "mock"]
        assert len(mock_llms) > 0

    def test_set_current_llm(self, patched_llm_manager):
        """Test setting current LLM."""
        manager = patched_llm_manager
        llms = manager.get_available_llms()

        mock_llms = [llm for llm in llms if llm["type"] == "mock"]
        assert len(mock_llms) > 0

        mock_id = mock_llms[0]["id"]

        result = manager.set_current_llm(mock_id)
        assert result is True
        assert manager.current_llm == mock_id

        result = manager.set_current_llm("non_existent")
        assert result is False

    @pytest.mark.asyncio
    async def test_generate_with_mock(self, patched_llm_manager):
        """Test generating response with mock LLM."""
        manager = patched_llm_manager

        llms = manager.get_available_llms()
        mock_llms = [llm for llm in llms if llm["type"] == "mock"]
        assert len(mock_llms) > 0

        mock_id = mock_llms[0]["id"]
        manager.set_current_llm(mock_id)

        response = await manager.generate("Hello, test!")
        assert isinstance(response, str)
        assert len(response) > 0


class TestPublicInterface:
    """Test the public interface functions."""

    def test_get_available_llms_public(self, patched_llm_module):
        """Test public get_available_llms function."""
        llm = patched_llm_module
        llms = llm.get_available_llms()

        print(f"Public interface - Available LLMs: {len(llms)}")
        assert isinstance(llms, list)
        assert len(llms) > 0

    @pytest.mark.asyncio
    async def test_llm_generate_public(self, patched_llm_module):
        """Test public llm_generate function."""
        llm = patched_llm_module

        # Set to mock LLM first
        llms = llm.get_available_llms()
        mock_llms = [llm_info for llm_info in llms if llm_info["type"] == "mock"]
        assert len(mock_llms) > 0

        mock_id = mock_llms[0]["id"]
        llm.set_current_llm(mock_id)

        response = await llm.llm_generate("Public interface test")
        assert isinstance(response, str)
        assert len(response) > 0
