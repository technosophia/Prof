"""
LLM Manager using plugin-based engine system.
[api]

# LLM Management System (`shared/llm.py`)
Manages multiple LLM providers and models with unified interface. Supports streaming, conversation history, and context injection. Support multiple engines : groq, ollama, gemini, xai.

**Exported functions:**
- `get_llm_manager()`: Get global LLM manager instance
- `llm_conversation_generate()` / `llm()`: Generate response from current LLM
- `set_current_llm()`: Switch active LLM
- `get_available_llms()`: List all configured LLMs
- `get_current_llm_info()`: Get current LLM details
- `get_current_llm_id()`: Get current LLM identifier
- `get_llm_by_name()`: Find LLM by name
- `register_llm_callback()`: Register context generation callback - legacy
- `unregister_llm_callback()`: Remove context callback - legacy
- `register_llm_context_callback()`: Register structured context callback
- `unregister_llm_context_callback()`: Remove structured context callback

# Prompt Management System (`shared/prompt_manager.py`)
Centralized prompt management with dot-notation access. Automatically discovers and merges prompts.yaml files throughout the project. Supports multilingual prompts.

**Exported functions:**
- `get_prompt()`: Get prompt by key using dot notation
- `get_all_prompts()`: Get all loaded prompts
- `get_module_prompts()`: Get prompts for a specific module
- `list_modules_with_prompts()`: List all modules with prompts
- `get_available_prompt_languages()`: List dynamic available languages
- `is_multilingual()`: Check if multilingual mode is enabled
- `set_default_language()`: Set default prompt language
- `get_prompt_manager()`: Access prompt manager instance

Key features:
- Automatic discovery of all prompts.yaml/prompts.xx.yaml files
- Multilingual support with language-specific prompt files
- Cached for performance
- Supports hierarchical organization
- Provides admin interface to view all prompts
- Integration with shared/common.py via get_prompt()
-
## LLM System (`shared/llm.py`)

### Purpose
Unified interface for multiple Large Language Models (Ollama, Gemini, Groq) with streaming support and configuration-based management.

### Key Functions

#### Initialization and Setup
```python
from shared.common import llm_conversation_generate, set_current_llm, get_available_llms, get_current_llm_info

# LLM manager is automatically initialized with app config
# No manual initialization needed
```

#### Generating Responses
```python
import asyncio

# Simple text generation
response = await llm_conversation_generate("Hello, how are you?")
print(response)

# With streaming (real-time response)
def stream_callback(chunk):
    print(chunk, end="", flush=True)

response = await llm_conversation_generate("Tell me a story", stream_callback)
```

### Context injection
Any module can inject context in the current conversation. It will be added at the end of the history
```
 from shared.common import register_llm_callback, unregister_llm_callback

def inject_current_time_context(user_id: str, messages: List[Dict]) -> str:
    from datetime import datetime
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"Current time: {current_time}"

# Register the callback (typically during initialization)
register_llm_callback(inject_current_time_context)
```

### Enhanced Context Injection
Any module can inject context with more control over placement and role
```
from shared.common import register_context_callback, unregister_context_callback

def inject_weather_context(user_id: str, messages: List[Dict]) -> tuple:
    weather = get_current_weather()
    return weather, "system", "top"  # context, role, position

# Register the enhanced callback
register_context_callback(inject_weather_context)
```

"""

import os
import sys
import importlib
import pkgutil
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Callable, Tuple, Union
import asyncio
from enum import Enum
from core.logging import log
from shared.llm_engine import LLMEngine


class ContextPosition(Enum):
    """Position where context should be inserted in the messages list."""
    TOP = "top"          # Insert at the beginning (first system messages)
    BOTTOM = "bottom"    # Insert just before the last user message (before final query)


class ContextRole(Enum):
    """Role for the context message."""
    SYSTEM = "system"
    USER = "user"


class LLMManager:
    def __init__(self, config):
        """Initialize LLM Manager using plugin-based engine system."""
        self.config = config
        self.engines = {}
        self.current_llm = None
        self.llm_callbacks = []  # Legacy callbacks: return just context string
        self.context_callbacks = []  # Enhanced callbacks: return (context, role, position)

        # Discover and load all engine modules
        self.discover_engines()

        # Validate config
        self.validate_config()

        # Initialize current LLM
        self.initialize_current_llm()

        log("debug", f"LLMManager initialized with {len(self.engines)} engines")

    def discover_engines(self):
        """Discover and load all LLM engine modules from shared/llms directory."""
        # Get the path to the shared directory
        shared_dir = os.path.dirname(__file__)
        llms_dir = os.path.join(shared_dir, 'llms')

        log("debug", f"Looking for engines in: {llms_dir}")

        if not os.path.exists(llms_dir):
            log("error", f"LLMs directory not found: {llms_dir}")
            return

        # Ensure the directory is in sys.path for import
        if shared_dir not in sys.path:
            sys.path.insert(0, shared_dir)

        # Use pkgutil to iterate through modules
        try:
            # Create a proper package path for pkgutil
            for _, module_name, is_pkg in pkgutil.iter_modules([llms_dir]):
                if not is_pkg and module_name.startswith('llm_'):
                    try:
                        # Import the module
                        full_module_name = f"llms.{module_name}"
                        module = importlib.import_module(full_module_name)

                        # Find engine classes
                        for attr_name in dir(module):
                            attr = getattr(module, attr_name)
                            if (isinstance(attr, type) and
                                issubclass(attr, LLMEngine) and
                                attr != LLMEngine and
                                attr_name.endswith('Engine')):

                                # Create instance
                                engine = attr()
                                engine_type = engine.engine_type

                                # Add to engines
                                self.engines[engine_type] = engine
                                log("info", f"Loaded LLM engine: {engine_type} from {module_name}")
                                break

                    except Exception as e:
                        log("error", f"Failed to load engine module {module_name}: {e}")

        except Exception as e:
            log("error", f"Failed to discover engines using pkgutil: {e}")

        # Log discovered engines
        log("debug", f"Discovered engines: {list(self.engines.keys())}")

    def get_engine(self, engine_type: str) -> Optional[LLMEngine]:
        """Get engine by type."""
        return self.engines.get(engine_type)

    def initialize_current_llm(self):
        """Initialize the current LLM from config."""
        default_llm_name = self.config.get("app.default_llm", "Ollama Small")
        log("debug", f"Looking for default LLM: '{default_llm_name}'")

        available_llms = self.get_available_llms()

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

            # Check if engine exists
            engine = self.get_engine(llm_type)

            # Check availability
            is_available = False
            if enabled and engine:
                if llm_config.get("requires_api_key", False):
                    is_available = engine.is_available()
                else:
                    is_available = True

            llms.append({
                "id": llm_id,
                "name": llm_config.get("name", llm_id),
                "type": llm_type,
                "model": llm_config.get("model", "unknown"),
                "description": llm_config.get("description", ""),
                "enabled": enabled,
                "available": is_available,
                "requires_api_key": llm_config.get("requires_api_key", False),
                "engine": engine
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

            # Check if engine exists for this type
            engine_type = llm_config.get("type")
            if engine_type not in self.engines:
                log("warning", f"LLM '{llm_id}' uses unknown engine type: {engine_type}")
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

    def register_llm_callback(self, callback_func: Callable[[str, List[Dict]], str]):
        """Register a legacy callback to add LLM context to LLM queries.

        Legacy callback returns just a context string (implicitly SYSTEM role, BOTTOM position).

        Args:
            callback_func: Function that takes (user_id, messages) and returns context string
        """
        if callback_func not in self.llm_callbacks:
            self.llm_callbacks.append(callback_func)
            log("debug", f"Registered legacy LLM callback: {callback_func.__name__}")

    def unregister_llm_callback(self, callback_func: Callable[[str, List[Dict]], str]):
        """Unregister a legacy LLM callback."""
        if callback_func in self.llm_callbacks:
            self.llm_callbacks.remove(callback_func)
            log("debug", f"Unregistered legacy LLM callback: {callback_func.__name__}")

    def register_context_callback(self,
                                 callback_func: Callable[[str, List[Dict]], Tuple[str, str, str]]):
        """Register an enhanced context callback with control over role and position.

        The callback should return a tuple: (context, role, position)
        where:
          - context: string to add as context
          - role: "system" or "user"
          - position: "top" or "bottom"

        Args:
            callback_func: Function that takes (user_id, messages) and returns (context, role, position)
        """
        if callback_func not in self.context_callbacks:
            self.context_callbacks.append(callback_func)
            log("debug", f"Registered enhanced context callback: {callback_func.__name__}")

    def unregister_context_callback(self,
                                   callback_func: Callable[[str, List[Dict]], Tuple[str, str, str]]):
        """Unregister an enhanced context callback."""
        if callback_func in self.context_callbacks:
            self.context_callbacks.remove(callback_func)
            log("debug", f"Unregistered enhanced context callback: {callback_func.__name__}")

    def _add_llm_context(self, user_id: str, messages: List[Dict]) -> List[Dict]:
        """Add LLM context to messages using registered callbacks.

        This method handles both legacy callbacks (returning just context string)
        and enhanced callbacks (returning context, role, position tuple).

        Args:
            user_id: User identifier
            messages: List of message dictionaries

        Returns:
            Updated list of messages with context added
        """
        if (not self.llm_callbacks and not self.context_callbacks) or not messages:
            return messages

        # Find the position of the last user message for BOTTOM insertion
        last_user_msg_index = -1
        for i, msg in enumerate(messages):
            if msg.get("role") == "user":
                last_user_msg_index = i

        # Prepare context messages to insert
        top_contexts = []     # Contexts to insert at the beginning
        bottom_contexts = []  # Contexts to insert before the last user message

        # Process legacy callbacks (implicitly SYSTEM role, BOTTOM position)
        for callback in self.llm_callbacks:
            try:
                context = callback(user_id, messages)
                if context and context.strip():
                    bottom_contexts.append({
                        "role": "system",
                        "content": context.strip(),
                        "source": callback.__name__
                    })
                    log("debug", f"Added legacy context from {callback.__name__}")
            except Exception as e:
                log("error", f"Legacy LLM callback {callback.__name__} failed: {e}")

        # Process enhanced context callbacks
        for callback in self.context_callbacks:
            try:
                result = callback(user_id, messages)
                if result and len(result) >= 3:
                    context, role_str, position_str = result[:3]

                    if not context or not context.strip():
                        continue

                    # Validate role
                    role = ContextRole.SYSTEM  # Default to SYSTEM
                    try:
                        role = ContextRole(role_str.lower())
                    except ValueError:
                        log("warning", f"Invalid role '{role_str}' from {callback.__name__}, using 'system'")

                    # Validate position
                    position = ContextPosition.BOTTOM  # Default to BOTTOM
                    try:
                        position = ContextPosition(position_str.lower())
                    except ValueError:
                        log("warning", f"Invalid position '{position_str}' from {callback.__name__}, using 'bottom'")

                    context_msg = {
                        "role": role.value,
                        "content": context.strip(),
                        "source": callback.__name__
                    }

                    if position == ContextPosition.TOP:
                        top_contexts.append(context_msg)
                    else:  # BOTTOM
                        bottom_contexts.append(context_msg)

                    log("debug", f"Added enhanced context from {callback.__name__} (role: {role.value}, position: {position.value})")

            except Exception as e:
                log("error", f"Enhanced context callback {callback.__name__} failed: {e}")

        # Insert contexts at appropriate positions
        if top_contexts:
            # Insert at the beginning in reverse order to maintain callback order
            for context_msg in reversed(top_contexts):
                messages.insert(0, context_msg)

        if bottom_contexts and last_user_msg_index >= 0:
            # Insert before the last user message in reverse order to maintain callback order
            for context_msg in reversed(bottom_contexts):
                messages.insert(last_user_msg_index, context_msg)

        return messages

    async def generate(self,
                    message: str,
                    stream_callback: Optional[Callable] = None,
                    conversation_history: Optional[List[Dict]] = None,
                    user_id: Optional[str] = None) -> str:

        # Prepare messages for the LLM
        messages = []

        # Add conversation history if provided
        if conversation_history:
            messages.extend(conversation_history)

        # Check if the last message in history is already from the user
        # If so, we shouldn't add another user message
        if conversation_history and messages:
            last_message = messages[-1]
            if last_message.get("role") == "user" and last_message.get("content") == message.strip():
                # The user message is already in history, don't duplicate it
                pass
            else:
                # Add current user message (it's not in history yet)
                messages.append({"role": "user", "content": message})
        else:
            # No history or empty history, add the user message
            messages.append({"role": "user", "content": message})

        # Add LLM context if user_id is provided and callbacks are registered
        if user_id and (self.llm_callbacks or self.context_callbacks):
            messages = self._add_llm_context(user_id, messages)

        return await self.internal_response(self.current_llm, messages, stream_callback)

    async def internal_response(self, llm_id: str, messages: list,
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

        # Get the engine
        engine = self.get_engine(llm_type)
        if not engine:
            error_msg = f"No engine found for type: {llm_type}"
            log("error", error_msg)
            return error_msg

        # Check availability
        requires_api_key = llm_config.get("requires_api_key", False)
        if requires_api_key and not engine.is_available():
            error_msg = f"LLM {llm_id} requires API key which is not configured"
            log("error", error_msg)
            return error_msg

        # Filter empty messages
        filtered_messages = [msg for msg in messages if msg.get("content", "").strip()]

        if not filtered_messages:
            error_msg = "No valid messages provided"
            log("warning", error_msg)
            return error_msg

        # Generate response using the engine
        try:
            response = await engine.generate(model_name, filtered_messages, stream_callback)
            if hasattr(self, '_monitor_callbacks') and self._monitor_callbacks:
                try:
                    monitor_data = {
                        "llm_id": llm_id,
                        "llm_type": llm_type,
                        "model": model_name,
                        "messages": filtered_messages,
                        "response": response,
                        "user_id": None,  # Will be filled by caller if available
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "engine_type": engine.engine_type,
                        "success": True,
                        "error": None
                    }
                    self._notify_monitor_callbacks(monitor_data)
                except Exception as e:
                    log("error", f"Error notifying monitor callbacks: {str(e)}", exc_info=True)
            return response
        except Exception as e:
            error_msg = f"Error generating response from {llm_id}: {str(e)}"
            log("error", error_msg)
            return error_msg

    def register_monitor_callback(self, callback_func: Callable[[Dict[str, Any]], None]):
        """Register a callback to monitor LLM usage and costs.

        Args:
            callback_func: Function that receives a dictionary with monitoring data
        """
        if not hasattr(self, '_monitor_callbacks'):
            self._monitor_callbacks = []

        if callback_func not in self._monitor_callbacks:
            self._monitor_callbacks.append(callback_func)
            log("debug", f"Registered monitor callback: {callback_func.__name__}")

    def unregister_monitor_callback(self, callback_func: Callable[[Dict[str, Any]], None]):
        """Unregister a monitor callback."""
        if hasattr(self, '_monitor_callbacks') and callback_func in self._monitor_callbacks:
            self._monitor_callbacks.remove(callback_func)
            log("debug", f"Unregistered monitor callback: {callback_func.__name__}")

    def _notify_monitor_callbacks(self, data: Dict[str, Any]):
        """Notify all registered monitor callbacks."""
        if hasattr(self, '_monitor_callbacks'):
            for callback in self._monitor_callbacks:
                try:
                    callback(data)
                except Exception as e:
                    log("error", f"Monitor callback error: {e}")
