"""
Ollama LLM Engine
"""

import os
import json
import re
import requests
from typing import List, Dict, Any, Optional, Callable
from shared.llm_engine import LLMEngine, GenerateResult, _debug_log_messages


from core.logging import log, set_log_module_level


class OllamaEngine(LLMEngine):
    """Ollama LLM engine for local models."""

    def __init__(self):
        super().__init__("ollama")
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.available = self._check_availability()

    def _check_availability(self) -> bool:
        """Check if Ollama is available."""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return response.status_code == 200
        except Exception:
            return False

    def is_available(self) -> bool:
        return self.available

    def get_supported_models(self) -> List[str]:
        """Get list of available Ollama models."""
        if not self.available:
            return []
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if response.status_code == 200:
                data = response.json()
                return [model["name"] for model in data.get("models", [])]
        except Exception:
            pass
        return []

    def _clean_response(self, response: str) -> str:
        """Strip <think> blocks and surrounding whitespace from a response."""
        if not response:
            return response

        response = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL)
        response = re.sub(r'<think>.*', '', response, flags=re.DOTALL)
        response = re.sub(r'.*</think>', '', response, flags=re.DOTALL)
        response = re.sub(r'<\s*/\s*think\s*>', '', response, flags=re.IGNORECASE)
        response = re.sub(r'<[^>]*think[^>]*>', '', response, flags=re.IGNORECASE)
        response = re.sub(r'\n\s*\n', '\n\n', response)
        response = re.sub(r'^\s+', '', response)
        response = re.sub(r'\s+$', '', response)

        return response.strip()

    def _inject_no_think(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Append /no_think to the last user message.

        This is Ollama's documented per-request mechanism to suppress
        chain-of-thought for thinking-capable models (qwen3, deepseek-r1, …).
        We copy the message dict to avoid mutating the caller's list.
        """
        for i in range(len(messages) - 1, -1, -1):
            if messages[i]["role"] == "user":
                msg = dict(messages[i])
                if "/no_think" not in msg["content"]:
                    msg["content"] = f"{msg['content']} /no_think"
                    messages = list(messages)
                    messages[i] = msg
                break
        return messages

    async def generate(
        self,
        model: str,
        messages: List[Dict[str, str]],
        stream_callback: Optional[Callable] = None,
        response_format: Optional[str] = None,
        no_thinking: bool = False,
    ) -> GenerateResult:
        """Generate response from Ollama.

        Args:
            model: Ollama model name.
            messages: Conversation messages.
            stream_callback: Optional streaming callback.
            response_format: Pass ``"json"`` to enable Ollama native JSON mode
                (sets ``format: "json"`` in the request payload).
            no_thinking: If True, appends ``/no_think`` to the last user
                message to instruct thinking-capable models to skip their
                chain-of-thought pass.  The raw API response is always
                preserved in ``GenerateResult.raw_response``; ``<think>``
                blocks are stripped from ``GenerateResult.response``
                regardless of this flag so the caller gets clean text.
                If thinking tags are detected in the raw response despite
                ``no_thinking=True``, a warning is logged.

        Returns:
            GenerateResult(response=cleaned_text, raw_response=raw_text)
        """
        log("debug", f"Generating Ollama response with model: {model}, no_thinking={no_thinking}")

        try:
            formatted_messages = [
                {"role": msg["role"], "content": msg["content"]}
                for msg in messages
            ]

            if formatted_messages and formatted_messages[-1]["role"] != "user":
                log("warning", "Last message not from user, adjusting...")
                formatted_messages.append({
                    "role": "user",
                    "content": "Please respond to the conversation",
                })

            # Inject /no_think directive before sending to the API so that
            # thinking-capable models skip their chain-of-thought pass entirely.
            if no_thinking:
                formatted_messages = self._inject_no_think(formatted_messages)

            ollama_url = f"{self.base_url}/api/chat"

            payload: Dict[str, Any] = {
                "model": model,
                "messages": formatted_messages,
                "stream": stream_callback is not None,
                "options": {
                    "temperature": 0.7,
                    "num_predict": 2048,
                },
            }

            if response_format == "json":
                payload["format"] = "json"
                log("debug", "Ollama JSON mode enabled")

            def _build_result(raw: str) -> GenerateResult:
                """Build a GenerateResult, stripping think tags for response.

                In JSON mode we skip tag-stripping to avoid corrupting the
                JSON payload — thinking models should not emit think blocks
                when /no_think is active, and JSON mode implies structured
                output anyway.
                """
                if response_format == "json":
                    cleaned = raw.strip()
                else:
                    cleaned = self._clean_response(raw)

                if no_thinking and cleaned != raw.strip():
                    log("warning",
                        f"Model '{model}' produced <think> content despite no_thinking=True. "
                        "The thinking was stripped but consider using a non-thinking model variant.")

                return GenerateResult(
                    response=cleaned or "No response generated",
                    raw_response=raw,
                )

            if stream_callback:
                log("debug", "Using streaming mode for Ollama")
                response = requests.post(
                    ollama_url,
                    json=payload,
                    stream=True,
                    timeout=180,
                )

                if response.status_code != 200:
                    error_msg = f"Ollama API error: {response.status_code}"
                    log("error", error_msg)
                    return GenerateResult(response=error_msg, raw_response=error_msg)

                raw_response = ""
                for line in response.iter_lines():
                    if line:
                        try:
                            data = json.loads(line)
                            if "message" in data and "content" in data["message"]:
                                chunk = data["message"]["content"]
                                raw_response += chunk
                                stream_callback(chunk)
                        except json.JSONDecodeError:
                            continue
                        except Exception as e:
                            log("error", f"Error parsing Ollama stream: {e}")
                            continue

                result = _build_result(raw_response)
                log("debug", f"Ollama response length: {len(result.response)}")
                return result

            else:
                log("debug", "Using non-streaming mode for Ollama")
                response = requests.post(ollama_url, json=payload, timeout=120)
                if response.status_code == 200:
                    raw_response = response.json()["message"]["content"]
                    result = _build_result(raw_response)
                    log("debug", f"Ollama response length: {len(result.response)}")
                    return result
                else:
                    error_msg = f"Ollama error: {response.status_code}"
                    log("error", error_msg)
                    return GenerateResult(response=error_msg, raw_response=error_msg)

        except requests.exceptions.ConnectionError:
            error_msg = "Cannot connect to Ollama. Make sure Ollama is running."
            log("error", error_msg)
            msg = f"❌ {error_msg}"
            return GenerateResult(response=msg, raw_response=msg)
        except requests.exceptions.Timeout:
            error_msg = "Ollama request timed out. Try again or check if the model is loaded."
            log("error", error_msg)
            msg = f"⏱️ {error_msg}"
            return GenerateResult(response=msg, raw_response=msg)
        except Exception as e:
            error_msg = f"Ollama error: {str(e)}"
            log("error", error_msg)
            return GenerateResult(response=error_msg, raw_response=error_msg)
