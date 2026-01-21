"""
Groq LLM Engine
"""

import os
from typing import List, Dict, Any, Optional, Callable
from llm_engine import LLMEngine
from shared.logging import log

try:
    from groq import Groq
    HAS_GROQ = True
except ImportError:
    HAS_GROQ = False
    log("warning", "groq not installed, Groq support disabled")


class GroqEngine(LLMEngine):
    """Groq LLM engine for fast inference."""

    def __init__(self):
        super().__init__("groq")
        self.client = None
        self.available = self._check_availability()

    def _check_availability(self) -> bool:
        """Check if Groq is available (API key present)."""
        if not HAS_GROQ:
            return False

        groq_key = os.getenv("GROQ_API_KEY")
        if not groq_key or not groq_key.strip():
            return False

        try:
            self.client = Groq(api_key=groq_key.strip())
            return True
        except:
            return False

    def is_available(self) -> bool:
        return self.available

    def get_supported_models(self) -> List[str]:
        """Get list of available Groq models."""
        # Common Groq models
        return [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "llama-3.2-3b-preview",
            "llama-3.2-1b-preview",
            "llama-guard-3-8b",
            "mixtral-8x7b-32768",
            "gemma2-9b-it"
        ]

    async def generate(self, model: str, messages: List[Dict[str, str]],
                      stream_callback: Optional[Callable] = None) -> str:
        """Generate response from Groq."""
        log("debug", f"Generating Groq response with model: {model}")

        if not self.available or not self.client:
            error_msg = "Groq not available. Check API key and installation."
            log("error", error_msg)
            return error_msg

        try:
            # Format messages for Groq
            if not messages:
                error_msg = "No messages provided"
                log("warning", error_msg)
                return error_msg

            formatted_messages = []
            for msg in messages:
                formatted_messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })

            # Ensure we have at least one user message
            has_user_message = any(msg["role"] == "user" for msg in formatted_messages)
            if not has_user_message:
                log("warning", "No user message found, adding default")
                formatted_messages.append({
                    "role": "user",
                    "content": "Hello"
                })

            # Ensure last message is from user
            if formatted_messages[-1]["role"] != "user":
                log("warning", "Last message not from user, adjusting...")
                user_messages = [m for m in formatted_messages if m["role"] == "user"]
                if user_messages:
                    formatted_messages.append(user_messages[-1])
                else:
                    formatted_messages.append({
                        "role": "user",
                        "content": "Please respond"
                    })

            # Generate response
            if stream_callback:
                # Streaming
                log("debug", "Using streaming mode for Groq")
                stream = self.client.chat.completions.create(
                    model=model,
                    messages=formatted_messages,
                    stream=True,
                    temperature=0.7,
                    max_tokens=1024
                )

                full_response = ""
                for chunk in stream:
                    if chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        full_response += content
                        if stream_callback:
                            stream_callback(content)
                log("debug", f"Groq response length: {len(full_response)}")
                return full_response if full_response else "No response generated"
            else:
                # Non-streaming
                log("debug", "Using non-streaming mode for Groq")
                completion = self.client.chat.completions.create(
                    model=model,
                    messages=formatted_messages,
                    temperature=0.7,
                    max_tokens=1024
                )
                response = completion.choices[0].message.content
                log("debug", f"Groq response length: {len(response) if response else 0}")
                return response or "No response generated"

        except Exception as e:
            error_msg = f"Groq error: {str(e)}"
            log("error", error_msg)
            return error_msg
