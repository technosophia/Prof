"""
Gemini LLM Engine
"""

import os
from typing import List, Dict, Any, Optional, Callable
from shared.llm_engine import LLMEngine


from core.logging import log, set_module_level
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
        self._api_key = None          # store key, not a client
        self.available = self._check_availability()

    def _check_availability(self) -> bool:
        if not HAS_GEMINI:
            return False
        gemini_key = os.getenv("GEMINI_API_KEY")
        if not gemini_key or not gemini_key.strip():
            return False
        self._api_key = gemini_key.strip()
        return True

    def _get_client(self):
        """Fresh client every time – avoids 'Event loop is closed' errors."""
        if not HAS_GEMINI or not self._api_key:
            return None
        return genai.Client(api_key=self._api_key)

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

    async def generate(self, model, messages, stream_callback=None):
        if not self.available:
            return "Gemini not available. Check API key and installation."

        client = self._get_client()   # ← fresh client each call
        if not client:
            return "Gemini client could not be created."

        try:
            history = []
            for msg in messages:
                role = "user" if msg["role"] == "user" else "model"
                history.append({"role": role, "parts": [{"text": msg["content"]}]})

            conversation = client.aio.chats.create(   # ← client, not self.client
                model=model,
                history=history[:-1] if len(history) > 1 else []
            )
            last_message = history[-1]["parts"][0]["text"] if history else ""

            if stream_callback:
                full_response = ""
                try:
                    async for chunk in conversation.send_message_stream(last_message):
                        if chunk.text:
                            full_response += chunk.text
                            stream_callback(chunk.text)
                    return full_response or "No response generated"
                except Exception as e:
                    log("error", f"Gemini streaming error: {e}")
                    response = await conversation.send_message(last_message)
                    return response.text or "No response generated"
            else:
                response = await conversation.send_message(last_message)
                return response.text or "No response generated"

        except Exception as e:
            log("error", f"Gemini error: {str(e)}")
            return f"Gemini error: {str(e)}"
