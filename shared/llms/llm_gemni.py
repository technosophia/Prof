"""
Gemini LLM Engine
"""

import os
from typing import List, Dict, Any, Optional, Callable
from shared.llm_engine import LLMEngine, GenerateResult


from core.logging import log, set_log_module_level

try:
    import google.genai as genai
    from google.genai import types as genai_types
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False
    log("warning", "google-genai not installed, Gemini support disabled")


class GeminiEngine(LLMEngine):
    """Google Gemini LLM engine."""

    def __init__(self):
        super().__init__("gemini")
        self._api_key = None
        self.available = self._check_availability()

    def _check_availability(self) -> bool:
        """Check if Gemini is available (API key present)."""
        if not HAS_GEMINI:
            return False
        gemini_key = os.getenv("GEMINI_API_KEY")
        if not gemini_key or not gemini_key.strip():
            return False
        self._api_key = gemini_key.strip()
        return True

    def _get_client(self):
        """Return a fresh Gemini client to avoid closed event loop issues."""
        if not HAS_GEMINI or not self._api_key:
            return None
        return genai.Client(api_key=self._api_key)

    def is_available(self) -> bool:
        return self.available

    def get_supported_models(self) -> List[str]:
        """Get list of available Gemini models."""
        return [
            "gemini-2.5-flash",
            "gemini-1.5-flash",
        ]

    async def generate(
        self,
        model: str,
        messages: List[Dict[str, str]],
        stream_callback: Optional[Callable] = None,
        response_format: Optional[str] = None,
        no_thinking: bool = False,
    ) -> GenerateResult:
        """Generate response from Gemini.

        Args:
            model: Gemini model name.
            messages: Conversation messages.
            stream_callback: Optional streaming callback.
            response_format: Pass ``"json"`` to set ``response_mime_type`` to
                ``"application/json"``.
            no_thinking: Accepted for interface compatibility; ignored because
                Gemini models do not expose a thinking-suppression directive.

        Returns:
            GenerateResult where response == raw_response (no post-processing).
        """
        if not self.available:
            err = "Gemini not available. Check API key and installation."
            return GenerateResult(response=err, raw_response=err)

        client = self._get_client()
        if not client:
            err = "Gemini client could not be created."
            return GenerateResult(response=err, raw_response=err)

        try:
            history = []
            for msg in messages:
                role = "user" if msg["role"] == "user" else "model"
                history.append({"role": role, "parts": [{"text": msg["content"]}]})

            gen_config = None
            if response_format == "json":
                try:
                    gen_config = genai_types.GenerateContentConfig(
                        response_mime_type="application/json"
                    )
                    log("debug", "Gemini JSON mode enabled (response_mime_type=application/json)")
                except Exception as e:
                    log("warning", f"Could not build GenerateContentConfig, trying dict fallback: {e}")
                    gen_config = {"response_mime_type": "application/json"}

            create_kwargs: Dict[str, Any] = {
                "model": model,
                "history": history[:-1] if len(history) > 1 else [],
            }
            if gen_config is not None:
                create_kwargs["config"] = gen_config

            conversation = client.aio.chats.create(**create_kwargs)
            last_message = history[-1]["parts"][0]["text"] if history else ""

            if stream_callback:
                text = ""
                try:
                    async for chunk in await conversation.send_message_stream(last_message):
                        if chunk.text:
                            text += chunk.text
                            stream_callback(chunk.text)
                    text = text or "No response generated"
                except Exception as e:
                    log("error", f"Gemini streaming error: {e}")
                    response = await conversation.send_message(last_message)
                    text = response.text or "No response generated"
            else:
                response = await conversation.send_message(last_message)
                text = response.text or "No response generated"

            # Gemini does no post-processing: raw == response
            return GenerateResult(response=text, raw_response=text)

        except Exception as e:
            err = f"Gemini error: {str(e)}"
            log("error", err)
            return GenerateResult(response=err, raw_response=err)
