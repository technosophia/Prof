"""
Groq LLM Engine
"""

import os
from typing import List, Dict, Any, Optional, Callable
from shared.llm_engine import LLMEngine


from core.logging import log, set_module_level

try:
    from groq import Groq
    HAS_GROQ = True
except ImportError:
    HAS_GROQ = False
    log("warning", "groq not installed, Groq support disabled")


class GroqEngine(LLMEngine):
    """Groq LLM engine for fast inference."""

    # Constants
    API_KEY_PREFIX = "gsk"
    DEFAULT_TEMPERATURE = 0.7
    DEFAULT_MAX_TOKENS = 1024
    DEFAULT_USER_MESSAGE = "Hello"
    DEFAULT_FALLBACK_MESSAGE = "Please respond"

    # Available models
    SUPPORTED_MODELS = [
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "openai/gpt-oss-120b",
    ]

    def __init__(self):
        super().__init__("groq")
        self.client = None
        self.available = self._check_availability()

    def _get_api_key(self) -> Optional[str]:
        """Retrieve and validate API key from environment."""
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key or not api_key.strip():
            log("error", "GROQ_API_KEY not found in environment variables")
            return None
        return api_key.strip()

    def _validate_api_key_format(self, api_key: str) -> bool:
        """Validate that API key has the correct format."""
        if not api_key.startswith(self.API_KEY_PREFIX):
            error_msg = (
                f"Invalid GROQ_API_KEY format: API key must start with '{self.API_KEY_PREFIX}'"
            )
            log("error", error_msg)
            raise ValueError(error_msg)
        return True

    def _initialize_client(self, api_key: str) -> Optional["Groq"]:
        """Initialize Groq client with API key."""
        try:
            return Groq(api_key=api_key)
        except Exception as e:
            log("error", f"Failed to initialize Groq client: {str(e)}")
            return None

    def _check_availability(self) -> bool:
        """Check if Groq is available (API key present and valid format)."""
        if not HAS_GROQ:
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
        """Get list of available Groq models."""
        return self.SUPPORTED_MODELS.copy()

    def _format_messages(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Format and validate messages for Groq API."""
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
            error_msg = "Groq not available. Check API key and installation."
            log("error", error_msg)
            raise RuntimeError(error_msg)
        api_key = self._get_api_key()
        if api_key:
            self._validate_api_key_format(api_key)

    def _handle_streaming_response(self, stream, stream_callback: Callable) -> str:
        """Handle streaming response from Groq."""
        full_response = ""
        for chunk in stream:
            if chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                full_response += content
                stream_callback(content)
        return full_response

    def _handle_non_streaming_response(self, completion) -> str:
        """Handle non-streaming response from Groq."""
        return completion.choices[0].message.content

    async def generate(
        self,
        model: str,
        messages: List[Dict[str, str]],
        stream_callback: Optional[Callable] = None,
        response_format: Optional[str] = None,
    ) -> str:
        """Generate response from Groq.

        Args:
            model: Groq model name.
            messages: Conversation messages.
            stream_callback: Optional streaming callback.
            response_format: Pass ``"json"`` to set ``response_format`` to
                ``{"type": "json_object"}`` in the API request (OpenAI-compatible
                JSON mode). The model will always return valid JSON. Note: JSON
                mode is incompatible with streaming on Groq; if both are
                requested, streaming takes precedence and JSON mode is skipped
                with a warning. Defaults to ``None`` (plain text).
        """
        log("debug", f"Generating Groq response with model: {model}")

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

            # Groq uses the OpenAI-compatible response_format field.
            # JSON mode is not supported with streaming; skip it with a warning.
            if response_format == "json":
                if stream_callback:
                    log("warning", "Groq JSON mode is not supported with streaming; ignoring response_format")
                else:
                    common_params["response_format"] = {"type": "json_object"}
                    log("debug", "Groq JSON mode enabled (response_format=json_object)")

            if stream_callback:
                log("debug", "Using streaming mode for Groq")
                stream = self.client.chat.completions.create(**common_params, stream=True)
                full_response = self._handle_streaming_response(stream, stream_callback)
            else:
                log("debug", "Using non-streaming mode for Groq")
                completion = self.client.chat.completions.create(**common_params)
                full_response = self._handle_non_streaming_response(completion)

            full_response = full_response or "No response generated"
            log("debug", f"Groq response length: {len(full_response)}")
            return full_response

        except RuntimeError as e:
            return str(e)
        except Exception as e:
            error_msg = f"Groq error: {str(e)}"
            log("error", error_msg)
            return error_msg
