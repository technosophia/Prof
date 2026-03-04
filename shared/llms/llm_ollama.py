"""
Ollama LLM Engine
"""

import os
import json
import re
import requests
from typing import List, Dict, Any, Optional, Callable
from shared.llm_engine import LLMEngine


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
        """Clean Ollama response by removing <think> tags and content."""
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

    async def generate(
        self,
        model: str,
        messages: List[Dict[str, str]],
        stream_callback: Optional[Callable] = None,
        response_format: Optional[str] = None,
        no_thinking: bool = False,
    ) -> str:
        """Generate response from Ollama.

        Args:
            model: Ollama model name.
            messages: Conversation messages.
            stream_callback: Optional streaming callback.
            response_format: Pass ``"json"`` to enable Ollama native JSON mode
                (sets ``format: "json"`` in the request payload).
            no_thinking: If True, appends ``/no_think`` to the last user message
                to instruct thinking-capable models (e.g. qwen3) to skip their
                chain-of-thought pass. The response is always stripped of any
                residual ``<think>`` blocks regardless of this flag.
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

            # Inject /no_think directive into the last user message so that
            # thinking-capable Ollama models (qwen3, deepseek-r1, …) skip their
            # chain-of-thought pass entirely. This is Ollama's supported way to
            # disable thinking at the per-request level.
            if no_thinking and formatted_messages:
                last_idx = len(formatted_messages) - 1
                # Walk backwards to find the last user turn
                for i in range(last_idx, -1, -1):
                    if formatted_messages[i]["role"] == "user":
                        formatted_messages[i] = dict(formatted_messages[i])  # copy
                        content = formatted_messages[i]["content"]
                        if "/no_think" not in content:
                            formatted_messages[i]["content"] = f"{content} /no_think"
                        break

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

            # Helper: always strip think-tags unless we are in raw JSON mode
            # (stripping there could corrupt the JSON structure if the model
            # somehow emits tags inside the JSON body, which should not happen
            # with /no_think but is a safe guard).
            def _maybe_clean(text: str) -> str:
                if response_format == "json":
                    return text.strip()
                return self._clean_response(text)

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
                    return error_msg

                full_response = ""
                for line in response.iter_lines():
                    if line:
                        try:
                            data = json.loads(line)
                            if "message" in data and "content" in data["message"]:
                                chunk = data["message"]["content"]
                                full_response += chunk
                                stream_callback(chunk)
                        except json.JSONDecodeError:
                            continue
                        except Exception as e:
                            log("error", f"Error parsing Ollama stream: {e}")
                            continue

                cleaned = _maybe_clean(full_response)
                log("debug", f"Ollama response length: {len(cleaned)}")
                return cleaned or "No response generated"

            else:
                log("debug", "Using non-streaming mode for Ollama")
                response = requests.post(ollama_url, json=payload, timeout=120)
                if response.status_code == 200:
                    response_text = response.json()["message"]["content"]
                    cleaned = _maybe_clean(response_text)
                    log("debug", f"Ollama response length: {len(cleaned)}")
                    return cleaned or "No response generated"
                else:
                    error_msg = f"Ollama error: {response.status_code}"
                    log("error", error_msg)
                    return error_msg

        except requests.exceptions.ConnectionError:
            error_msg = "Cannot connect to Ollama. Make sure Ollama is running."
            log("error", error_msg)
            return f"❌ {error_msg}"
        except requests.exceptions.Timeout:
            error_msg = "Ollama request timed out. Try again or check if the model is loaded."
            log("error", error_msg)
            return f"⏱️ {error_msg}"
        except Exception as e:
            error_msg = f"Ollama error: {str(e)}"
            log("error", error_msg)
            return error_msg
