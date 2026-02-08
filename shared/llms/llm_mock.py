"""
Mock LLM Engine for testing
"""

import asyncio
import random
from typing import List, Dict, Any, Optional, Callable
from shared.llm_engine import LLMEngine
from shared.common import log


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
            "(Mock) I'm here to help with testing. What would you like to test today?"
        ]

    def is_available(self) -> bool:
        return self.available

    def get_supported_models(self) -> List[str]:
        """Get list of available mock models."""
        return [
            "mock-fast",
            "mock-smart",
            "mock-creative",
            "mock-precise"
        ]

    async def generate(self, model: str, messages: List[Dict[str, str]],
                      stream_callback: Optional[Callable] = None) -> str:
        """Generate mock response."""
        log("debug", f"Generating mock response with model: {model}")

        # Simulate processing delay
        await asyncio.sleep(0.1)

        # Get last user message
        user_messages = [msg["content"] for msg in messages if msg["role"] == "user"]
        last_message = user_messages[-1] if user_messages else "Hello"

        # Generate response
        base_response = random.choice(self.responses)
        response = f"{base_response}\n\nUser said: '{last_message[:50]}...'"

        if stream_callback:
            # Simulate streaming
            log("debug", "Using streaming mode for Mock")
            for char in response:
                if stream_callback:
                    stream_callback(char)
                await asyncio.sleep(0.01)

        log("debug", f"Mock response length: {len(response)}")
        return response
