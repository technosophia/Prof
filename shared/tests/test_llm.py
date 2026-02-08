"""
Tests for the LLM Manager
"""

import sys
import os
import asyncio
import json
import pytest
from unittest.mock import patch, Mock

from shared.common import get_available_llms, set_current_llm, llm_generate, get_llm_manager

class TestLLMManager:
    """Test LLM Manager functionality."""

    def test_discover_engines(self):
        """Test that engines are discovered correctly."""
        manager = get_llm_manager()

        # Log what engines were found
        print(f"Discovered engines: {list(manager.engines.keys())}")

        # Should have discovered at least mock engine
        assert "mock" in manager.engines
        assert len(manager.engines) > 0

    def test_get_available_llms(self):
        """Test getting available LLMs."""
        manager = get_llm_manager()
        llms = manager.get_available_llms()

        print(f"Available LLMs: {len(llms)}")
        for llm in llms:
            print(f"  - {llm['id']}: {llm['name']} (type: {llm['type']}, available: {llm['available']})")

        assert isinstance(llms, list)
        assert len(llms) > 0

        mock_llms = [llm for llm in llms if llm["type"] == "mock"]
        assert len(mock_llms) > 0

    def test_set_current_llm(self):
        """Test setting current LLM."""
        manager = get_llm_manager()
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
    async def test_generate_with_mock(self):
        """Test generating response with mock LLM."""
        manager = get_llm_manager()

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

    def test_get_available_llms_public(self):
        """Test public get_available_llms function."""
        llms = get_available_llms()

        print(f"Public interface - Available LLMs: {len(llms)}")
        assert isinstance(llms, list)
        assert len(llms) > 0

    @pytest.mark.asyncio
    async def test_llm_generate_public(self):
        """Test public llm_generate function."""
        # Set to mock LLM first
        llms = get_available_llms()
        mock_llms = [llm_info for llm_info in llms if llm_info["type"] == "mock"]
        assert len(mock_llms) > 0

        mock_id = mock_llms[0]["id"]
        set_current_llm(mock_id)

        response = await llm_generate("Public interface test")
        assert isinstance(response, str)
        assert len(response) > 0
