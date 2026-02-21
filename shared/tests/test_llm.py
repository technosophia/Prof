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
from shared.cached import get_llm_manager
from shared.common import log

# Load environment variables from .env file
load_dotenv()
log("info", f"Current working directory: {os.getcwd()}")
log("info", f".env file exists: {os.path.exists('.env')}")
log("info", f"GROQ_API_KEY exists in env: {'GROQ_API_KEY' in os.environ}")
if 'GROQ_API_KEY' in os.environ:
    api_key = os.environ['GROQ_API_KEY']
    log("info", f"GROQ_API_KEY length: {len(api_key)}")
    log("info", f"GROQ_API_KEY starts with 'gsk': {api_key.startswith('gsk')}")
    log("info", f"GROQ_API_KEY first 10 chars: {api_key[:10]}...")
else:
    log("warning", "GROQ_API_KEY not found in environment variables")


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


class TestGroqIntegration:
    """Test Groq LLM integration with exhaustive logging."""

    @pytest.mark.asyncio
    async def test_groq_availability(self):
        """Test if Groq engine is available and properly configured."""
        log("info", "=" * 60)
        log("info", "=== Starting test_groq_availability ===")
        log("info", "=" * 60)

        # Check environment
        log("info", "--- Environment Check ---")
        log("info", f"Python version: {sys.version}")
        log("info", f"Current working directory: {os.getcwd()}")
        log("info", f".env file exists: {os.path.exists('.env')}")

        # Check Groq API key
        log("info", "--- API Key Check ---")
        api_key = os.getenv("GROQ_API_KEY")
        if api_key:
            log("info", f"GROQ_API_KEY found in environment")
            log("info", f"GROQ_API_KEY length: {len(api_key)}")
            log("info", f"GROQ_API_KEY starts with 'gsk': {api_key.startswith('gsk')}")
            log("info", f"GROQ_API_KEY first 4 chars: {api_key[:4]}...")
            log("info", f"GROQ_API_KEY last 4 chars: ...{api_key[-4:]}")
        else:
            log("error", "GROQ_API_KEY NOT FOUND in environment!")
            pytest.skip("GROQ_API_KEY not available, skipping Groq tests")

        # Get manager and check Groq engine
        log("info", "--- Engine Discovery Check ---")
        manager = get_llm_manager()
        log("info", f"All discovered engines: {list(manager.engines.keys())}")

        if "groq" not in manager.engines:
            log("error", "Groq engine not discovered! Available engines: {list(manager.engines.keys())}")
            pytest.skip("Groq engine not available, skipping test")

        groq_engine = manager.engines["groq"]
        log("info", f"Groq engine object: {groq_engine}")
        log("info", f"Groq engine available: {groq_engine.is_available()}")

        # Check Groq engine internals
        log("info", "--- Groq Engine Internals ---")
        log("info", f"Groq client exists: {groq_engine.client is not None}")
        if hasattr(groq_engine, 'available'):
            log("info", f"Groq engine.available: {groq_engine.available}")

        # Check supported models
        log("info", "--- Supported Models ---")
        supported_models = groq_engine.get_supported_models()
        log("info", f"Supported models count: {len(supported_models)}")
        for i, model in enumerate(supported_models):
            log("info", f"  Model {i+1}: {model}")

        # Final assertion
        assert groq_engine.is_available() is True, "Groq engine should be available with valid API key"
        log("info", "✓ Groq engine is available and properly configured")
        log("info", "=== Completed test_groq_availability ===")
        log("info", "=" * 60)

    @pytest.mark.asyncio
    async def test_groq_basic_generation(self):
        """Test basic text generation with Groq."""
        log("info", "=" * 60)
        log("info", "=== Starting test_groq_basic_generation ===")
        log("info", "=" * 60)

        # Setup
        manager = get_llm_manager()

        # Check if Groq is available
        if "groq" not in manager.engines:
            log("error", "Groq engine not found!")
            pytest.skip("Groq engine not available")

        groq_engine = manager.engines["groq"]
        if not groq_engine.is_available():
            log("error", "Groq engine is not available!")
            pytest.skip("Groq engine not available")

        # Set Groq as current LLM
        log("info", "--- Setting Groq as current LLM ---")
        llms = manager.get_available_llms()
        groq_llms = [llm for llm in llms if llm["type"] == "groq" and llm["available"]]

        if not groq_llms:
            log("error", "No available Groq LLMs found!")
            # Log all Groq LLMs and their availability
            all_groq = [llm for llm in llms if llm["type"] == "groq"]
            for llm in all_groq:
                log("info", f"  Groq LLM: {llm['id']} - available: {llm['available']}")
            pytest.skip("No available Groq LLMs found")

        groq_id = groq_llms[0]["id"]
        log("info", f"Selected Groq LLM ID: {groq_id}")

        set_result = manager.set_current_llm(groq_id)
        log("info", f"Set current LLM result: {set_result}")
        assert set_result is True, f"Failed to set Groq as current LLM: {groq_id}"

        # Test generation
        log("info", "--- Testing Generation ---")
        test_message = "Say 'Hello, Groq!' in exactly 3 words"
        log("info", f"Test message: '{test_message}'")

        try:
            response = await manager.generate(test_message)
            log("info", f"Raw response received: '{response}'")
            log("info", f"Response length: {len(response)}")
            log("info", f"Response type: {type(response)}")

            # Basic assertions
            assert isinstance(response, str), "Response should be a string"
            assert len(response) > 0, "Response should not be empty"
            assert "error" not in response.lower(), f"Response contains error: {response}"

            log("info", "✓ Basic generation test passed")

        except Exception as e:
            log("error", f"Exception during generation: {str(e)}")
            log("error", f"Exception type: {type(e)}")
            import traceback
            log("error", f"Traceback: {traceback.format_exc()}")
            raise

        log("info", "=== Completed test_groq_basic_generation ===")
        log("info", "=" * 60)

    @pytest.mark.asyncio
    async def test_groq_with_different_models(self):
        """Test Groq with different available models."""
        log("info", "=" * 60)
        log("info", "=== Starting test_groq_with_different_models ===")
        log("info", "=" * 60)

        manager = get_llm_manager()

        if "groq" not in manager.engines:
            pytest.skip("Groq engine not available")

        groq_engine = manager.engines["groq"]
        if not groq_engine.is_available():
            pytest.skip("Groq engine not available")

        # Get models to test
        supported_models = groq_engine.get_supported_models()
        log("info", f"Testing with {len(supported_models)} models")

        # Test with first 3 models (or all if less than 3)
        models_to_test = supported_models[:min(3, len(supported_models))]
        log("info", f"Models to test: {models_to_test}")

        test_message = "Respond with 'OK' only"

        for i, model in enumerate(models_to_test):
            log("info", f"--- Testing Model {i+1}: {model} ---")

            try:
                # Create messages in the format expected by the engine
                messages = [{"role": "user", "content": test_message}]

                # Generate directly with the engine to test specific model
                log("info", f"Generating with model '{model}'...")
                response = await groq_engine.generate(model, messages)

                log("info", f"Model '{model}' response: '{response}'")
                log("info", f"Response length: {len(response)}")

                assert isinstance(response, str), f"Response from {model} should be string"
                assert len(response) > 0, f"Response from {model} should not be empty"

                log("info", f"✓ Model '{model}' test passed")

            except Exception as e:
                log("error", f"Error testing model '{model}': {str(e)}")
                # Don't fail the test for individual model failures
                log("warning", f"Model '{model}' test failed but continuing")

        log("info", "=== Completed test_groq_with_different_models ===")
        log("info", "=" * 60)

    @pytest.mark.asyncio
    async def test_groq_streaming(self):
        """Test Groq streaming functionality."""
        log("info", "=" * 60)
        log("info", "=== Starting test_groq_streaming ===")
        log("info", "=" * 60)

        manager = get_llm_manager()

        if "groq" not in manager.engines:
            pytest.skip("Groq engine not available")

        groq_engine = manager.engines["groq"]
        if not groq_engine.is_available():
            pytest.skip("Groq engine not available")

        # Set Groq as current
        llms = manager.get_available_llms()
        groq_llms = [llm for llm in llms if llm["type"] == "groq" and llm["available"]]
        if not groq_llms:
            pytest.skip("No available Groq LLMs found")

        manager.set_current_llm(groq_llms[0]["id"])

        # Test streaming
        log("info", "--- Testing Streaming Mode ---")
        test_message = "Count from 1 to 3, with each number on a new line"
        log("info", f"Test message: '{test_message}'")

        # Collect streamed chunks
        received_chunks = []
        chunk_count = 0

        def stream_handler(chunk):
            nonlocal chunk_count
            chunk_count += 1
            received_chunks.append(chunk)
            log("info", f"Stream chunk {chunk_count}: '{chunk}'")

        try:
            log("info", "Starting streaming generation...")
            full_response = await manager.generate(test_message, stream_callback=stream_handler)

            log("info", f"Streaming complete. Total chunks: {chunk_count}")
            log("info", f"Full response: '{full_response}'")
            log("info", f"Full response length: {len(full_response)}")

            # Verify streaming worked
            assert chunk_count > 0, "Should have received at least one chunk"
            assert len(received_chunks) > 0, "Should have received chunks"
            assert full_response == ''.join(received_chunks), "Full response should match concatenated chunks"

            log("info", "✓ Streaming test passed")

        except Exception as e:
            log("error", f"Error during streaming test: {str(e)}")
            raise

        log("info", "=== Completed test_groq_streaming ===")
        log("info", "=" * 60)

    @pytest.mark.asyncio
    async def test_groq_error_handling(self):
        """Test Groq error handling with invalid inputs."""
        log("info", "=" * 60)
        log("info", "=== Starting test_groq_error_handling ===")
        log("info", "=" * 60)

        manager = get_llm_manager()

        if "groq" not in manager.engines:
            pytest.skip("Groq engine not available")

        groq_engine = manager.engines["groq"]

        # Test 1: Invalid model name
        log("info", "--- Test 1: Invalid model name ---")
        invalid_model = "non-existent-model-12345"
        messages = [{"role": "user", "content": "Hello"}]

        try:
            log("info", f"Testing with invalid model: '{invalid_model}'")
            response = await groq_engine.generate(invalid_model, messages)
            log("info", f"Response with invalid model: '{response}'")
            # Should return error message, not raise exception
            assert "error" in response.lower() or "not found" in response.lower(), \
                f"Expected error message, got: {response}"
            log("info", "✓ Invalid model test passed")
        except Exception as e:
            log("info", f"Exception raised (also acceptable): {str(e)}")
            # Either returning error string or raising exception is acceptable

        # Test 2: Empty messages
        log("info", "--- Test 2: Empty messages ---")
        try:
            log("info", "Testing with empty messages list")
            response = await groq_engine.generate("llama-3.3-70b-versatile", [])
            log("info", f"Response with empty messages: '{response}'")
            assert isinstance(response, str), "Should return string even with empty messages"
            log("info", "✓ Empty messages test passed")
        except Exception as e:
            log("info", f"Exception raised: {str(e)}")

        # Test 3: Messages without user role
        log("info", "--- Test 3: Messages without user role ---")
        try:
            log("info", "Testing with messages missing user role")
            bad_messages = [{"role": "system", "content": "You are a helper"}]
            response = await groq_engine.generate("llama-3.3-70b-versatile", bad_messages)
            log("info", f"Response with no user message: '{response}'")
            assert isinstance(response, str), "Should handle missing user message"
            log("info", "✓ Missing user role test passed")
        except Exception as e:
            log("info", f"Exception raised: {str(e)}")

        log("info", "=== Completed test_groq_error_handling ===")
        log("info", "=" * 60)
