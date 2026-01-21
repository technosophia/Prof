"""
LLM Manager using shared config and logging systems.
"""

import os
import json
from typing import Dict, Any, List, Optional, Callable
import asyncio
import re
import requests

# Import shared systems
from shared.config import get_config
from shared.logging import log

# Try to import optional dependencies
try:
    import google.genai as genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False
    log("warning", "google-genai not installed, Gemini support disabled")

try:
    from groq import Groq
    HAS_GROQ = True
except ImportError:
    HAS_GROQ = False
    log("warning", "groq not installed, Groq support disabled")


class LLMManager:
    def __init__(self):
        """Initialize LLM Manager using shared config system."""
        self.config = get_config()
        self.clients = {}
        self.current_llm = None
        # Validate config first
        self.validate_config()

        self.setup_clients()
        self.initialize_current_llm()
        log("debug", "LLMManager initialized")

        # Log environment variable status for debugging
        self.log_env_status()

    def log_env_status(self):
        """Log status of environment variables for debugging."""
        gemini_key = os.getenv("GEMINI_API_KEY")
        groq_key = os.getenv("GROQ_API_KEY")

        if gemini_key:
            # Show first and last few chars for security
            masked = f"{gemini_key[:4]}...{gemini_key[-4:]}" if len(gemini_key) > 8 else "***"
            log("debug", f"GEMINI_API_KEY found: {masked}")
        else:
            log("warning", "GEMINI_API_KEY not found in environment")

        if groq_key:
            masked = f"{groq_key[:4]}...{groq_key[-4:]}" if len(groq_key) > 8 else "***"
            log("debug", f"GROQ_API_KEY found: {masked}")
        else:
            log("warning", "GROQ_API_KEY not found in environment")

    def setup_clients(self):
        """Setup API clients based on configuration."""
        # Setup Gemini if available
        if HAS_GEMINI:
            gemini_key = os.getenv("GEMINI_API_KEY")
            if gemini_key and gemini_key.strip():
                try:
                    self.clients["gemini"] = genai.Client(api_key=gemini_key.strip())
                    log("info", "Gemini client initialized successfully")
                except Exception as e:
                    log("error", f"Error setting up Gemini client: {e}")
                    self.clients["gemini"] = None
            else:
                self.clients["gemini"] = None
                log("warning", "GEMINI_API_KEY not found or empty in environment")
        else:
            self.clients["gemini"] = None

        # Setup Groq if available
        if HAS_GROQ:
            groq_key = os.getenv("GROQ_API_KEY")
            if groq_key and groq_key.strip():
                try:
                    self.clients["groq"] = Groq(api_key=groq_key.strip())
                    log("info", "Groq client initialized successfully")
                except Exception as e:
                    log("error", f"Error setting up Groq client: {e}")
                    self.clients["groq"] = None
            else:
                self.clients["groq"] = None
                log("warning", "GROQ_API_KEY not found or empty in environment")
        else:
            self.clients["groq"] = None

        log("debug", f"Clients initialized: {list(self.clients.keys())}")

    def initialize_current_llm(self):
        """Initialize the current LLM from config."""
        default_llm_name = self.config.get("app.default_llm", "Qwen 3 4B")
        log("debug", f"Looking for default LLM: '{default_llm_name}'")

        available_llms = self.get_available_llms()

        # Debug: log what LLMs we found
        if available_llms:
            log("debug", f"Available LLMs found: {len(available_llms)}")
            for llm in available_llms:
                log("debug", f"  - '{llm['name']}' (ID: '{llm['id']}', Available: {llm['available']})")
        else:
            log("debug", "No LLMs returned from get_available_llms()")

        # First try to find by exact name match
        for llm in available_llms:
            if llm["name"] == default_llm_name:
                if llm["available"]:
                    self.current_llm = llm["id"]
                    log("info", f"Current LLM set to: {default_llm_name} (ID: {self.current_llm})")
                    return
                else:
                    log("warning", f"Default LLM '{default_llm_name}' found but not available")

        # If not found by exact name, try case-insensitive match
        for llm in available_llms:
            if llm["name"].lower() == default_llm_name.lower():
                if llm["available"]:
                    self.current_llm = llm["id"]
                    log("info", f"Current LLM set to: {llm['name']} (ID: {self.current_llm})")
                    return
                else:
                    log("warning", f"Default LLM '{llm['name']}' found (case-insensitive) but not available")

        # If not found by name, try by ID (in case default_llm is actually an ID)
        for llm in available_llms:
            if llm["id"] == default_llm_name:
                if llm["available"]:
                    self.current_llm = llm["id"]
                    log("info", f"Current LLM set by ID: {default_llm_name}")
                    return
                else:
                    log("warning", f"Default LLM ID '{default_llm_name}' found but not available")

        # Fallback to first available LLM
        for llm in available_llms:
            if llm["available"]:
                self.current_llm = llm["id"]
                log("warning", f"No default LLM '{default_llm_name}' found, falling back to: {llm['name']}")
                return

        if available_llms:
            log("error", f"No available LLMs found among {len(available_llms)} configured LLMs")
            # At least set the first one even if not available
            self.current_llm = available_llms[0]["id"]
            log("warning", f"Forcing current LLM to first configured: {available_llms[0]['name']}")
        else:
            log("error", "No LLMs configured at all")
            self.current_llm = None

    def get_available_llms(self) -> List[Dict[str, Any]]:
        """Get list of available LLMs from configuration."""
        llms = []

        if "llms" not in self.config:
            log("error", "No 'llms' section found in configuration")
            return llms

        for llm_id, llm_config in self.config.get("llms", {}).items():
            if not isinstance(llm_config, dict):
                log("warning", f"Invalid LLM config for '{llm_id}': {llm_config}")
                continue

            enabled = llm_config.get("enabled", True)
            llm_type = llm_config.get("type", "unknown")

            # Check if LLM is actually available
            is_available = enabled
            requires_api_key = llm_config.get("requires_api_key", False)

            if enabled:
                if requires_api_key:
                    if llm_type == "gemini":
                        is_available = self.clients.get("gemini") is not None
                        if not is_available:
                            log("debug", f"Gemini LLM '{llm_id}' requires API key but client not available")
                    elif llm_type == "groq":
                        is_available = self.clients.get("groq") is not None
                        if not is_available:
                            log("debug", f"Groq LLM '{llm_id}' requires API key but client not available")
                    elif llm_type == "ollama":
                        # Ollama doesn't require API key
                        is_available = True
                    else:
                        log("warning", f"Unknown LLM type '{llm_type}' for '{llm_id}'")
                        is_available = False
                else:
                    # Doesn't require API key, so it's available if enabled
                    is_available = True

            llms.append({
                "id": llm_id,
                "name": llm_config.get("name", llm_id),
                "type": llm_type,
                "model": llm_config.get("model", "unknown"),
                "description": llm_config.get("description", ""),
                "enabled": enabled,
                "available": is_available,
                "requires_api_key": requires_api_key
            })

        # Log availability summary
        total = len(llms)
        available_count = sum(1 for llm in llms if llm["available"])
        enabled_count = sum(1 for llm in llms if llm["enabled"])

        log("debug", f"LLM Status: {available_count}/{total} available, {enabled_count}/{total} enabled")

        return llms

    def set_current_llm(self, llm_id: str) -> bool:
        """Set the current LLM to use."""
        available_llms = self.get_available_llms()

        log("debug", f"Attempting to set LLM to: {llm_id}")

        for llm in available_llms:
            if llm["id"] == llm_id:
                if llm["available"]:
                    self.current_llm = llm_id
                    log("info", f"Current LLM changed to: {llm['name']} ({llm_id})")
                    return True
                else:
                    log("warning", f"LLM {llm_id} is not available (enabled: {llm['enabled']})")
                    return False

        log("error", f"LLM {llm_id} not found in available LLMs")
        return False

    def validate_config(self):
        """Validate the LLM configuration."""
        if "llms" not in self.config:
            log("error", "No 'llms' section in configuration")
            return False

        llms_config = self.config.get("llms", {})
        if not isinstance(llms_config, dict):
            log("error", f"'llms' section should be a dictionary, got: {type(llms_config)}")
            return False

        valid_count = 0
        for llm_id, llm_config in llms_config.items():
            if not isinstance(llm_config, dict):
                log("warning", f"LLM '{llm_id}' config is not a dictionary: {llm_config}")
                continue

            if "type" not in llm_config:
                log("warning", f"LLM '{llm_id}' missing 'type' field")
                continue

            if "model" not in llm_config:
                log("warning", f"LLM '{llm_id}' missing 'model' field")
                continue

            valid_count += 1

        log("info", f"Validated {valid_count} LLM configurations")
        return valid_count > 0

    def get_llm_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Get LLM information by name."""
        available_llms = self.get_available_llms()

        for llm in available_llms:
            if llm["name"] == name:
                return llm

        return None

    def get_current_llm_info(self) -> Optional[Dict[str, Any]]:
        """Get information about the current LLM."""
        if not self.current_llm:
            return None

        available_llms = self.get_available_llms()
        for llm in available_llms:
            if llm["id"] == self.current_llm:
                return llm

        return None

    async def generate(self, message: str, stream_callback: Optional[Callable] = None) -> str:
        """Generate response from current LLM."""
        if not self.current_llm:
            error_msg = "No LLM selected"
            log("error", error_msg)
            return error_msg

        log("info", f"Generating response with current LLM: {self.current_llm}")
        log("debug", f"Message: {message[:100]}...")

        # Prepare messages for the LLM
        messages = [{"role": "user", "content": message}]

        return await self.generate_response(self.current_llm, messages, stream_callback)

    async def generate_response(self, llm_id: str, messages: list,
                               stream_callback: Optional[Callable] = None) -> str:
        """Generate response from selected LLM."""
        log("info", f"Generating response with LLM: {llm_id}")
        log("debug", f"Messages: {len(messages)} messages")

        llm_config = self.config.get("llms", {}).get(llm_id, {})
        llm_type = llm_config.get("type")
        model_name = llm_config.get("model")

        if not llm_config:
            error_msg = f"LLM {llm_id} not found in configuration"
            log("error", error_msg)
            return error_msg

        # Check if LLM is available (enabled and has required API key if needed)
        if not llm_config.get("enabled", True):
            error_msg = f"LLM {llm_id} is disabled"
            log("error", error_msg)
            return error_msg

        # Check API key requirements
        requires_api_key = llm_config.get("requires_api_key", False)
        if requires_api_key:
            if llm_type == "gemini" and not self.clients.get("gemini"):
                error_msg = f"LLM {llm_id} requires Gemini API key which is not configured"
                log("error", error_msg)
                return error_msg
            elif llm_type == "groq" and not self.clients.get("groq"):
                error_msg = f"LLM {llm_id} requires Groq API key which is not configured"
                log("error", error_msg)
                return error_msg

        # Filter empty messages
        filtered_messages = [msg for msg in messages if msg.get("content", "").strip()]

        if not filtered_messages:
            error_msg = "No valid messages provided"
            log("warning", error_msg)
            return error_msg

        try:
            if llm_type == "ollama":
                return await self._generate_ollama(model_name, filtered_messages, stream_callback)
            elif llm_type == "gemini":
                return await self._generate_gemini(model_name, filtered_messages, stream_callback)
            elif llm_type == "groq":
                return await self._generate_groq(model_name, filtered_messages, stream_callback)
            else:
                error_msg = f"Unsupported LLM type: {llm_type}"
                log("error", error_msg)
                return error_msg
        except Exception as e:
            error_msg = f"Error generating response from {llm_id}: {str(e)}"
            log("error", error_msg)
            return error_msg

    def _clean_ollama_response(self, response: str) -> str:
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

    async def _generate_ollama(self, model: str, messages: list,
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
                # Add a user message if needed
                formatted_messages.append({
                    "role": "user",
                    "content": "Please respond to the conversation"
                })

            # Ollama API endpoint
            ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434") + "/api/chat"

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
                cleaned_response = self._clean_ollama_response(full_response)
                log("debug", f"Ollama response length: {len(cleaned_response)}")
                return cleaned_response if cleaned_response else "No response generated"
            else:
                # Non-streaming response
                log("debug", "Using non-streaming mode for Ollama")
                response = requests.post(ollama_url, json=payload, timeout=120)
                if response.status_code == 200:
                    response_text = response.json()["message"]["content"]
                    cleaned_response = self._clean_ollama_response(response_text)
                    log("debug", f"Ollama response length: {len(cleaned_response)}")
                    return cleaned_response if cleaned_response else "No response generated"
                else:
                    error_msg = f"Ollama error: {response.status_code}"
                    log("error", error_msg)
                    return error_msg

        except requests.exceptions.ConnectionError:
            error_msg = "Cannot connect to Ollama. Make sure Ollama is running on localhost:11434"
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

    async def _generate_gemini(self, model: str, messages: list,
                               stream_callback: Optional[Callable] = None) -> str:
        """Generate response from Gemini."""
        log("debug", f"Generating Gemini response with model: {model}")

        if not HAS_GEMINI:
            error_msg = "Gemini support not available (google-genai not installed)"
            log("error", error_msg)
            return error_msg

        gemini_client = self.clients.get("gemini")
        if not gemini_client:
            error_msg = "Gemini API key not configured. Add GEMINI_API_KEY to .env file"
            log("error", error_msg)
            return f"🔑 {error_msg}"

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
            conversation = gemini_client.aio.chats.create(
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

    async def _generate_groq(self, model: str, messages: list,
                             stream_callback: Optional[Callable] = None) -> str:
        """Generate response from Groq."""
        log("debug", f"Generating Groq response with model: {model}")

        if not HAS_GROQ:
            error_msg = "Groq support not available (groq not installed)"
            log("error", error_msg)
            return error_msg

        groq_client = self.clients.get("groq")
        if not groq_client:
            error_msg = "Groq API key not configured. Add GROQ_API_KEY to .env file"
            log("error", error_msg)
            return f"🔑 {error_msg}"

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
                stream = groq_client.chat.completions.create(
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
                completion = groq_client.chat.completions.create(
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


# Global instance
_manager = LLMManager()

# Simple public interface
async def llm_generate(message: str, stream_callback: Optional[Callable] = None) -> str:
    """Simple interface to generate response from current LLM."""
    return await _manager.generate(message, stream_callback)

def set_current_llm(llm_id: str) -> bool:
    """Set the current LLM to use."""
    return _manager.set_current_llm(llm_id)

def get_available_llms() -> List[Dict[str, Any]]:
    """Get list of available LLMs."""
    return _manager.get_available_llms()

def get_current_llm_info() -> Optional[Dict[str, Any]]:
    """Get information about the current LLM."""
    return _manager.get_current_llm_info()

def get_llm_by_name(name: str) -> Optional[Dict[str, Any]]:
    """Get LLM information by name."""
    return _manager.get_llm_by_name(name)

def get_default_llm_name() -> str:
    """Get the default LLM name from config."""
    config = get_config()
    return config.get("app.default_llm", "Qwen 3 4B")

# Alias for backward compatibility
llm = llm_generate
