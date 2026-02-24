"""
Tests for the LLM Manager
"""

import sys
import os
import asyncio
import json
import pytest
from unittest.mock import patch, Mock
from dotenv import load_dotenv

from shared.common import get_available_llms, set_current_llm, llm_conversation_generate
from st_shared.cached import get_llm_manager


from core.logging import log, set_module_level
class TestLLMManager:
    """Test LLM Manager functionality."""

    def test_discover_engines(self):
        """Test that engines are discovered correctly."""
        log("info", "=== Starting test_discover_engines ===")
        manager = get_llm_manager()

        # Log what engines were found
        discovered_engines = list(manager.engines.keys())
        log("info", f"Discovered engines: {discovered_engines}")

        for engine_name in discovered_engines:
            engine = manager.engines[engine_name]
            log("info", f"Engine '{engine_name}' available: {engine.is_available()}")

        # Should have discovered at least mock engine
        assert "mock" in manager.engines
        assert len(manager.engines) > 0
        log("info", "=== Completed test_discover_engines ===")

    def test_get_available_llms(self):
        """Test getting available LLMs."""
        log("info", "=== Starting test_get_available_llms ===")
        manager = get_llm_manager()
        llms = manager.get_available_llms()

        log("info", f"Available LLMs count: {len(llms)}")
        for llm in llms:
            log("info", f"  - {llm['id']}: {llm['name']} (type: {llm['type']}, available: {llm['available']})")
            if llm['type'] == 'groq' and not llm['available']:
                log("warning", f"    Groq engine '{llm['id']}' is not available. Check API key and installation.")

        assert isinstance(llms, list)
        assert len(llms) > 0

        mock_llms = [llm for llm in llms if llm["type"] == "mock"]
        log("info", f"Found {len(mock_llms)} mock LLMs")
        assert len(mock_llms) > 0

        groq_llms = [llm for llm in llms if llm["type"] == "groq"]
        log("info", f"Found {len(groq_llms)} groq LLMs")
        log("info", "=== Completed test_get_available_llms ===")

    def test_set_current_llm(self):
        """Test setting current LLM."""
        log("info", "=== Starting test_set_current_llm ===")
        manager = get_llm_manager()
        llms = manager.get_available_llms()

        mock_llms = [llm for llm in llms if llm["type"] == "mock"]
        assert len(mock_llms) > 0

        mock_id = mock_llms[0]["id"]
        log("info", f"Attempting to set current LLM to mock: {mock_id}")

        result = manager.set_current_llm(mock_id)
        log("info", f"Set current LLM result: {result}")
        assert result is True
        assert manager.current_llm == mock_id
        log("info", f"Current LLM is now: {manager.current_llm}")

        log("info", "Attempting to set current LLM to non-existent ID: non_existent")
        result = manager.set_current_llm("non_existent")
        log("info", f"Set non-existent LLM result: {result}")
        assert result is False
        log("info", "=== Completed test_set_current_llm ===")

    @pytest.mark.asyncio
    async def test_generate_with_mock(self):
        """Test generating response with mock LLM."""
        log("info", "=== Starting test_generate_with_mock ===")
        manager = get_llm_manager()

        llms = manager.get_available_llms()
        mock_llms = [llm for llm in llms if llm["type"] == "mock"]
        assert len(mock_llms) > 0

        mock_id = mock_llms[0]["id"]
        log("info", f"Setting current LLM to mock: {mock_id}")
        manager.set_current_llm(mock_id)

        test_message = "Hello, test!"
        log("info", f"Generating response for message: '{test_message}'")
        response = await manager.generate(test_message)

        log("info", f"Mock response received: '{response}'")
        log("info", f"Response length: {len(response)}")

        assert isinstance(response, str)
        assert len(response) > 0
        log("info", "=== Completed test_generate_with_mock ===")


class TestPublicInterface:
    """Test the public interface functions."""

    def test_get_available_llms_public(self):
        """Test public get_available_llms function."""
        log("info", "=== Starting test_get_available_llms_public ===")
        llms = get_available_llms()

        log("info", f"Public interface - Available LLMs count: {len(llms)}")
        for llm in llms:
            log("info", f"  - {llm['id']}: {llm['name']} (type: {llm['type']}, available: {llm['available']})")

        assert isinstance(llms, list)
        assert len(llms) > 0
        log("info", "=== Completed test_get_available_llms_public ===")

    @pytest.mark.asyncio
    async def test_llm_conversation_generate_public(self):
        """Test public llm_conversation_generate function."""
        log("info", "=== Starting test_llm_conversation_generate_public ===")

        # Set to mock LLM first
        llms = get_available_llms()
        mock_llms = [llm_info for llm_info in llms if llm_info["type"] == "mock"]
        assert len(mock_llms) > 0

        mock_id = mock_llms[0]["id"]
        log("info", f"Setting current LLM to mock via public interface: {mock_id}")
        set_current_llm(mock_id)

        test_message = "Public interface test"
        log("info", f"Generating response for message: '{test_message}'")
        response = await llm_conversation_generate(test_message)

        log("info", f"Public interface response received: '{response}'")
        log("info", f"Response length: {len(response)}")

        assert isinstance(response, str)
        assert len(response) > 0
        log("info", "=== Completed test_llm_conversation_generate_public ===")
