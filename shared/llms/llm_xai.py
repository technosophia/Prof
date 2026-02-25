"""
xAI (Grok) LLM Engine
"""

import os
from typing import List, Dict, Any, Optional, Callable
from shared.llm_engine import LLMEngine


from core.logging import log, set_log_module_level

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
    log("warning", "openai not installed, xAI support disabled")


class XAIEngine(LLMEngine):
    """xAI (Grok) LLM engine for Grok models."""

    # Constants
    DEFAULT_BASE_URL = "https://api.x.ai/v1"
    API_KEY_PREFIX = "xai-"
    DEFAULT_TEMPERATURE = 0.7
    DEFAULT_MAX_TOKENS = 1024
    DEFAULT_USER_MESSAGE = "Hello"
    DEFAULT_FALLBACK_MESSAGE = "Please respond"

    # Available models
    SUPPORTED_MODELS = [
        "grok-2-1212",
        "grok-2-vision-1212",
        "grok-beta",
    ]

    def __init__(self):
        super().__init__("xai")
        self.client = None
        self.base_url = os.getenv("XAI_BASE_URL", self.DEFAULT_BASE_URL)
        self.available = self._check_availability()

    def _get_api_key(self) -> Optional[str]:
        """Retrieve and validate API key from environment."""
        api_key = os.getenv("XAI_API_KEY")
        if not api_key or not api_key.strip():
            log("error", "XAI_API_KEY not found in environment variables")
            return None
        return api_key.strip()

    def _validate_api_key_format(self, api_key: str) -> bool:
        """Validate that API key has the correct format."""
        if not api_key.startswith(self.API_KEY_PREFIX):
            error_msg = (
                f"Invalid XAI_API_KEY format: API key must start with '{self.API_KEY_PREFIX}'"
            )
            log("error", error_msg)
            raise ValueError(error_msg)
        return True

    def _initialize_client(self, api_key: str) -> Optional["OpenAI"]:
        """Initialize OpenAI-compatible client for xAI."""
        try:
            return OpenAI(
                api_key=api_key,
                base_url=self.base_url,
            )
        except Exception as e:
            log("error", f"Failed to initialize xAI client: {str(e)}")
            return None

    def _check_availability(self) -> bool:
        """Check if xAI is available (API key present and valid format)."""
        if not HAS_OPENAI:
            return False
        api_key = self._get_api_key()
        if not api_key:
            return False
        self._validate_api_key_format(api_key)
        self.client = self._initialize_client(api_key)
        return self.client is not None

    def is_available(self) -> bool:
        return self.available

    def get_supported_models(self) -> List[str]:
        """Get list of available xAI models."""
        return self.SUPPORTED_MODELS.copy()

    def _format_messages(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Format and validate messages for xAI API."""
        if not messages:
            log("warning", "No messages provided")
            return []

        formatted_messages = [
            {"role": msg["role"], "content": msg["content"]} for msg in messages
        ]

        if not any(msg["role"] == "user" for msg in formatted_messages):
            log("warning", "No user message found, adding default")
            formatted_messages.append({"role": "user", "content": self.DEFAULT_USER_MESSAGE})

        if formatted_messages[-1]["role"] != "user":
            log("warning", "Last message not from user, adjusting...")
            user_messages = [m for m in formatted_messages if m["role"] == "user"]
            if user_messages:
                formatted_messages.append(user_messages[-1])
            else:
                formatted_messages.append({"role": "user", "content": self.DEFAULT_FALLBACK_MESSAGE})

        return formatted_messages

    def _validate_request(self) -> None:
        """Validate that the engine is ready to make requests."""
        if not self.available or not self.client:
            error_msg = "xAI not available. Check API key and installation."
            log("error", error_msg)
            raise RuntimeError(error_msg)
        api_key = self._get_api_key()
        if api_key:
            self._validate_api_key_format(api_key)

    def _handle_streaming_response(self, stream, stream_callback: Callable) -> str:
        """Handle streaming response from xAI."""
        full_response = ""
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                full_response += content
                stream_callback(content)
        return full_response

    def _handle_non_streaming_response(self, completion) -> str:
        """Handle non-streaming response from xAI."""
        return completion.choices[0].message.content

    async def generate(
        self,
        model: str,
        messages: List[Dict[str, str]],
        stream_callback: Optional[Callable] = None,
        response_format: Optional[str] = None,
    ) -> str:
        """Generate response from xAI (Grok).

        Args:
            model: xAI model name (e.g., grok-2-1212, grok-beta).
            messages: Conversation messages.
            stream_callback: Optional streaming callback.
            response_format: Pass ``"json"`` to set ``response_format`` to
                ``{"type": "json_object"}`` in the API request (OpenAI-compatible
                JSON mode). The model will always return valid JSON. Note: JSON
                mode is incompatible with streaming on xAI; if both are
                requested, streaming takes precedence and JSON mode is skipped
                with a warning. Defaults to ``None`` (plain text).
        """
        log("debug", f"Generating xAI response with model: {model}")

        try:
            self._validate_request()

            formatted_messages = self._format_messages(messages)
            if not formatted_messages:
                return "No valid messages provided"

            common_params: Dict[str, Any] = {
                "model": model,
                "messages": formatted_messages,
                "temperature": self.DEFAULT_TEMPERATURE,
                "max_tokens": self.DEFAULT_MAX_TOKENS,
            }

            # xAI uses OpenAI-compatible response_format field.
            # JSON mode is not supported with streaming; skip it with a warning.
            if response_format == "json":
                if stream_callback:
                    log("warning", "xAI JSON mode is not supported with streaming; ignoring response_format")
                else:
                    common_params["response_format"] = {"type": "json_object"}
                    log("debug", "xAI JSON mode enabled (response_format=json_object)")

            if stream_callback:
                log("debug", "Using streaming mode for xAI")
                stream = self.client.chat.completions.create(**common_params, stream=True)
                full_response = self._handle_streaming_response(stream, stream_callback)
            else:
                log("debug", "Using non-streaming mode for xAI")
                completion = self.client.chat.completions.create(**common_params)
                full_response = self._handle_non_streaming_response(completion)

            full_response = full_response or "No response generated"
            log("debug", f"xAI response length: {len(full_response)}")
            return full_response

        except RuntimeError as e:
            return str(e)
        except Exception as e:
            error_msg = f"xAI error: {str(e)}"
            log("error", error_msg)
            return error_msg
