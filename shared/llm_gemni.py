"""
Gemini LLM Engine
"""

import os
from typing import List, Dict, Any, Optional, Callable
from llm_engine import LLMEngine
from shared.logging import log

try:
    import google.genai as genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False
    log("warning", "google-genai not installed, Gemini support disabled")


class GeminiEngine(LLMEngine):
    """Google Gemini LLM engine."""

    def __init__(self):
        super().__init__("gemini")
        self.client = None
        self.available = self._check_availability()

    def _check_availability(self) -> bool:
        """Check if Gemini is available (API key present)."""
        if not HAS_GEMINI:
            return False

        gemini_key = os.getenv("GEMINI_API_KEY")
        if not gemini_key or not gemini_key.strip():
            return False

        try:
            self.client = genai.Client(api_key=gemini_key.strip())
            return True
        except:
            return False

    def is_available(self) -> bool:
        return self.available

    def get_supported_models(self) -> List[str]:
        """Get list of available Gemini models."""
        # Common Gemini models
        return [
            "gemini-2.0-flash-exp",
            "gemini-1.5-flash",
            "gemini-1.5-pro",
            "gemini-1.0-pro"
        ]

    async def generate(self, model: str, messages: List[Dict[str, str]],
                      stream_callback: Optional[Callable] = None) -> str:
        """Generate response from Gemini."""
        log("debug", f"Generating Gemini response with model: {model}")

        if not self.available or not self.client:
            error_msg = "Gemini not available. Check API key and installation."
            log("error", error_msg)
            return error_msg

        try:
            # Convert messages to Gemini format
            history = []
            for msg in messages:
                role = "user" if msg["role"] == "user" else "model"
                history.append({
                    "role": role,
                    "parts": [{"text": msg["content"]}]
                })

            # Create conversation
            conversation = self.client.aio.chats.create(
                model=model,
                history=history[:-1] if len(history) > 1 else []
            )

            # Last message (user message)
            last_message = history[-1]["parts"][0]["text"] if history else ""

            if stream_callback:
                # Streaming response
                log("debug", "Using streaming mode for Gemini")
                full_response = ""
                try:
                    async for chunk in conversation.send_message_stream(last_message):
                        if chunk.text:
                            full_response += chunk.text
                            if stream_callback:
                                stream_callback(chunk.text)
                    log("debug", f"Gemini response length: {len(full_response)}")
                    return full_response if full_response else "No response generated"
                except Exception as e:
                    log("error", f"Gemini streaming error: {e}")
                    # Fallback to non-streaming
                    response = await conversation.send_message(last_message)
                    return response.text if response.text else "No response generated"
            else:
                # Non-streaming
                log("debug", "Using non-streaming mode for Gemini")
                response = await conversation.send_message(last_message)
                log("debug", f"Gemini response length: {len(response.text) if response.text else 0}")
                return response.text if response.text else "No response generated"

        except Exception as e:
            error_msg = f"Gemini error: {str(e)}"
            log("error", error_msg)
            return error_msg
