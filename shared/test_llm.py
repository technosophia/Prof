"""
Tests for the LLM Manager
"""

import sys
import os
import asyncio
import json
import pytest
from unittest.mock import patch

# Add the parent directory to sys.path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load test config - it's in the tests/ directory
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_CONFIG_PATH = os.path.join(
    PROJECT_ROOT,
    "tests",
    "test_config.json"
)

# Check if file exists
if not os.path.exists(TEST_CONFIG_PATH):
    # Try alternative location (same directory as test file)
    TEST_CONFIG_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "test_config.json"
    )

if not os.path.exists(TEST_CONFIG_PATH):
    raise FileNotFoundError(f"Test config not found. Tried: {TEST_CONFIG_PATH}")

with open(TEST_CONFIG_PATH, 'r') as f:
    TEST_CONFIG = json.load(f)


@pytest.fixture
def patched_llm_manager():
    """Fixture that provides an LLMManager with test configuration."""
    with patch('shared.config.get_config', return_value=TEST_CONFIG):
        # Clear cached import
        sys.modules.pop('llm', None)

        from llm import LLMManager
        manager = LLMManager()
        yield manager

        # Cleanup
        del manager


@pytest.fixture
def patched_llm_module():
    """Fixture that patches the llm module for public interface tests."""
    with patch('shared.config.get_config', return_value=TEST_CONFIG):
        # Clear cached import
        sys.modules.pop('llm', None)

        import llm
        yield llm


class TestLLMManager:
    """Test LLM Manager functionality."""

    def test_discover_engines(self, patched_llm_manager):
        """Test that engines are discovered correctly."""
        manager = patched_llm_manager

        # Should have discovered at least mock engine
        assert "mock" in manager.engines
        assert len(manager.engines) > 0

    def test_get_available_llms(self, patched_llm_manager):
        """Test getting available LLMs."""
        manager = patched_llm_manager
        llms = manager.get_available_llms()

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

    @pytest.mark.asyncio
    async def test_generate_with_ollama(self, patched_llm_manager):
        """Test generating response with mock LLM."""
        manager = patched_llm_manager

        llms = manager.get_available_llms()
        mock_llms = [llm for llm in llms if llm["type"] == "ollama"]
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
