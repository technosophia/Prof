"""
Ollama LLM Engine
"""

import os
import json
import re
import requests
from typing import List, Dict, Any, Optional, Callable
from llm_engine import LLMEngine
from shared.logging import log


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
        except:
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
        except:
            pass
        return []

    def _clean_response(self, response: str) -> str:
        """Clean Ollama response by removing <think> tags and content."""
        if not response:
            return response

        # Remove <think> tags and everything between them
        response = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL)
        # Also handle unclosed <think> tags
        response = re.sub(r'<think>.*', '', response, flags=re.DOTALL)
        response = re.sub(r'.*</think>', '', response, flags=re.DOTALL)

        # Remove any leftover XML-like tags
        response = re.sub(r'<\s*/\s*think\s*>', '', response, flags=re.IGNORECASE)
        response = re.sub(r'<[^>]*think[^>]*>', '', response, flags=re.IGNORECASE)

        # Clean up extra whitespace
        response = re.sub(r'\n\s*\n', '\n\n', response)
        response = re.sub(r'^\s+', '', response)
        response = re.sub(r'\s+$', '', response)

        return response.strip()

    async def generate(self, model: str, messages: List[Dict[str, str]],
                      stream_callback: Optional[Callable] = None) -> str:
        """Generate response from Ollama."""
        log("debug", f"Generating Ollama response with model: {model}")

        try:
            # Format messages for Ollama
            formatted_messages = []
            for msg in messages:
                formatted_messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })

            # Check last message is from user
            if formatted_messages and formatted_messages[-1]["role"] != "user":
                log("warning", "Last message not from user, adjusting...")
                formatted_messages.append({
                    "role": "user",
                    "content": "Please respond to the conversation"
                })

            # Ollama API endpoint
            ollama_url = f"{self.base_url}/api/chat"

            # Prepare request
            payload = {
                "model": model,
                "messages": formatted_messages,
                "stream": stream_callback is not None,
                "options": {
                    "temperature": 0.7,
                    "num_predict": 512
                }
            }

            if stream_callback:
                # Streaming response
                log("debug", "Using streaming mode for Ollama")
                response = requests.post(
                    ollama_url,
                    json=payload,
                    stream=True,
                    timeout=120
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
                                if stream_callback:
                                    stream_callback(chunk)
                        except json.JSONDecodeError:
                            continue
                        except Exception as e:
                            log("error", f"Error parsing Ollama stream: {e}")
                            continue

                # Clean the response
                cleaned_response = self._clean_response(full_response)
                log("debug", f"Ollama response length: {len(cleaned_response)}")
                return cleaned_response if cleaned_response else "No response generated"
            else:
                # Non-streaming response
                log("debug", "Using non-streaming mode for Ollama")
                response = requests.post(ollama_url, json=payload, timeout=120)
                if response.status_code == 200:
                    response_text = response.json()["message"]["content"]
                    cleaned_response = self._clean_response(response_text)
                    log("debug", f"Ollama response length: {len(cleaned_response)}")
                    return cleaned_response if cleaned_response else "No response generated"
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
