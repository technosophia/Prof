"""
Mock LLM Engine for testing
"""

import asyncio
import json
import random
from typing import List, Dict, Any, Optional, Callable
from shared.llm_engine import LLMEngine


from core.logging import log, set_module_level


class MockEngine(LLMEngine):
    """Mock LLM engine for testing purposes."""

    def __init__(self):
        super().__init__("mock")
        self.available = True
        self.responses = [
            "(Mock) This is a mock response from the test LLM.",
            "(Mock) Hello! I'm a mock AI assistant for testing.",
            "(Mock) I can help you test your application without real API calls.",
            "(Mock) This response simulates what a real LLM would return.",
            "(Mock) Testing, testing, 1, 2, 3... Mock LLM is working!",
            "(Mock) I'm here to help with testing. What would you like to test today?",
        ]

    def is_available(self) -> bool:
        return self.available

    def get_supported_models(self) -> List[str]:
        """Get list of available mock models."""
        return [
            "mock-fast",
            "mock-smart",
            "mock-creative",
            "mock-precise",
        ]

    async def generate(
        self,
        model: str,
        messages: List[Dict[str, str]],
        stream_callback: Optional[Callable] = None,
        response_format: Optional[str] = None,
    ) -> str:
        """Generate mock response.

        Args:
            model: Ignored — any mock model name is accepted.
            messages: Conversation messages.
            stream_callback: Optional streaming callback.
            response_format: Pass ``"json"`` to receive a minimal valid JSON
                object instead of a plain-text mock response. Useful for
                testing code paths that parse the LLM output. Defaults to
                ``None`` (plain text).
        """
        log("debug", f"Generating mock response with model: {model}")

        await asyncio.sleep(0.1)

        user_messages = [msg["content"] for msg in messages if msg["role"] == "user"]
        last_message = user_messages[-1] if user_messages else "Hello"

        if response_format == "json":
            # Return a minimal but valid JSON payload so callers can parse it.
            response = json.dumps({
                "mock": True,
                "model": model,
                "user_input": last_message[:50],
                "message": random.choice(self.responses),
            })
        else:
            base_response = random.choice(self.responses)
            response = f"{base_response}\n\nUser said: '{last_message[:50]}...'"

        if stream_callback:
            log("debug", "Using streaming mode for Mock")
            for char in response:
                stream_callback(char)
                await asyncio.sleep(0.01)

        log("debug", f"Mock response length: {len(response)}")
        return response
