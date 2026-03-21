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
- `unregister_llm_callback()`: Remove callback - legacy
- `register_llm_context_callback()`: Register structured context callback
- `unregister_llm_context_callback()`: Remove  callback
- `register_monitor_callback()`: Register callback to monitor every llm call
- `unregister_monitor_callback()`: Remove monitor callback

# Prompt Management System (`shared/prompt_manager.py`)
Centralized prompt management with dot-notation access. Automatically discovers and merges prompts.yaml files throughout the project. Supports multilingual prompts.

**Exported functions:**
- `get_prompt()`: Get prompt by key using dot notation
- `set_prompt()`: Set prompt in memory
- `save_prompt()`: Save prompt on disk
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
from core.logging import log, set_log_module_level
from shared.llm_engine import LLMEngine, GenerateResult
from core.callback import register_callback, unregister_callback


class ContextPosition(Enum):
    """Position where context should be inserted in the messages list."""

    TOP = "top"  # Insert at the beginning (first system messages)
    BOTTOM = "bottom"  # Insert just before the last user message (before final query)


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
        self._monitor_callbacks = []  # Initialize monitor callbacks list

        # Load embedding configuration
        self.embedding_model_name = self.config.get(
            "embedding.model_name", "all-MiniLM-L6-v2"
        )
        self.embedding_vector_dimension = self.config.get(
            "embedding.vector_dimension", 384
        )

        # Discover and load all engine modules
        self.discover_engines()

        # Validate config
        self.validate_config()

        # Initialize current LLM
        self.initialize_current_llm()

        log("debug", f"LLMManager initialized with {len(self.engines)} engines")
        log(
            "debug",
            f"Embedding model: {self.embedding_model_name} ({self.embedding_vector_dimension} dims)",
        )

    def _get_embedding_model(self):
        """Return cached sentence-transformers model for the configured default.
        Lazily initialized on first call."""
        if hasattr(self, "_embedding_model") and self._embedding_model is not None:
            return self._embedding_model

        try:
            from sentence_transformers import SentenceTransformer
        except Exception as e:
            log(
                "error",
                "sentence-transformers is required for embeddings but is not installed",
                stacktrace=True,
            )
            raise RuntimeError(
                "sentence-transformers is required for embeddings"
            ) from e

        import torch

        device = (
            "cuda"
            if torch.cuda.is_available()
            else "mps"
            if torch.backends.mps.is_available()
            else "cpu"
        )
        self._embedding_model = SentenceTransformer(
            self.embedding_model_name, device=device
        )
        log(
            "info",
            f"Loaded embedding model: {self.embedding_model_name} ({self.embedding_vector_dimension} dims)",
        )
        return self._embedding_model

    def _get_named_embedding_model(self, model_name: str):
        """
        Load and cache a sentence-transformers model by explicit name.

        This is separate from the default model cache so that:
          - Existing code using get_embedding() is unaffected.
          - The calibrator can load multiple models simultaneously.
          - Each named model is cached after first load (session lifetime).

        Args:
            model_name: HuggingFace model identifier, e.g. "all-mpnet-base-v2"
        """
        # Lazy-init the multi-model cache
        if not hasattr(self, "_model_cache"):
            self._model_cache: dict = {}

        if model_name in self._model_cache:
            return self._model_cache[model_name]

        try:
            from sentence_transformers import SentenceTransformer
        except Exception as e:
            raise RuntimeError(
                "sentence-transformers is required for embeddings"
            ) from e

        import torch

        device = (
            "cuda"
            if torch.cuda.is_available()
            else "mps"
            if torch.backends.mps.is_available()
            else "cpu"
        )
        log("info", f"Loading named embedding model: {model_name} on {device}")
        model = SentenceTransformer(model_name, device=device)
        self._model_cache[model_name] = model
        log("info", f"Named embedding model loaded and cached: {model_name}")
        return model

    def get_embedding_for_model(self, text: str, model_name: str) -> List[float]:
        """
        Embed a single string using a specific (possibly non-default) model.

        The model is lazy-loaded and cached on first call.
        Subsequent calls with the same model_name reuse the cached instance.

        Args:
            text:       String to embed.
            model_name: HuggingFace model identifier.

        Returns:
            Float vector as a plain Python list.
        """
        model = self._get_named_embedding_model(model_name)
        vector = model.encode(text or "", convert_to_numpy=True)
        return vector.tolist()

    def get_embeddings_for_model(
        self, texts: List[str], model_name: str
    ) -> List[List[float]]:
        """
        Embed a list of strings using a specific (possibly non-default) model.

        The model is lazy-loaded and cached on first call.
        Subsequent calls with the same model_name reuse the cached instance.

        Args:
            texts:      List of strings to embed.
            model_name: HuggingFace model identifier.

        Returns:
            List of float vectors as plain Python lists.
        """
        model = self._get_named_embedding_model(model_name)
        vectors = model.encode(texts or [], convert_to_numpy=True)
        return vectors.tolist()

    def get_embedding(self, text: str) -> List[float]:
        """Embed a single string. Returns a float vector."""
        model = self._get_embedding_model()
        vector = model.encode(text or "", convert_to_numpy=True)
        return vector.tolist()

    def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of strings. Returns a list of float vectors."""
        model = self._get_embedding_model()
        vectors = model.encode(texts or [], convert_to_numpy=True)
        return vectors.tolist()

    def discover_engines(self):
        """Discover and load all LLM engine modules from shared/llms directory."""
        shared_dir = os.path.dirname(__file__)
        llms_dir = os.path.join(shared_dir, "llms")

        log("debug", f"Looking for engines in: {llms_dir}")

        if not os.path.exists(llms_dir):
            log("error", f"LLMs directory not found: {llms_dir}")
            return

        if shared_dir not in sys.path:
            sys.path.insert(0, shared_dir)

        try:
            for _, module_name, is_pkg in pkgutil.iter_modules([llms_dir]):
                if not is_pkg and module_name.startswith("llm_"):
                    try:
                        full_module_name = f"llms.{module_name}"
                        module = importlib.import_module(full_module_name)

                        for attr_name in dir(module):
                            attr = getattr(module, attr_name)
                            if (
                                isinstance(attr, type)
                                and issubclass(attr, LLMEngine)
                                and attr != LLMEngine
                                and attr_name.endswith("Engine")
                            ):
                                engine = attr()
                                engine_type = engine.engine_type
                                self.engines[engine_type] = engine
                                log(
                                    "info",
                                    f"Loaded LLM engine: {engine_type} from {module_name}",
                                )
                                break

                    except Exception as e:
                        log("error", f"Failed to load engine module {module_name}: {e}")

        except Exception as e:
            log("error", f"Failed to discover engines using pkgutil: {e}")

        log("debug", f"Discovered engines: {list(self.engines.keys())}")

    def get_engine(self, engine_type: str) -> Optional[LLMEngine]:
        """Get engine by type."""
        return self.engines.get(engine_type)

    def initialize_current_llm(self):
        """Initialize the current LLM from config."""
        default_llm_id = self.config.get("app.default_llm")
        log("debug", f"Looking for default LLM ID: '{default_llm_id}'")

        available_llms = self.get_available_llms()

        if available_llms:
            log("debug", f"Available LLMs found: {len(available_llms)}")
            for llm in available_llms:
                log(
                    "debug",
                    f"  - '{llm['name']}' (ID: '{llm['id']}', Available: {llm['available']})",
                )
        else:
            log("debug", "No LLMs returned from get_available_llms()")

        # Try to find by ID first (primary method)
        if default_llm_id:
            for llm in available_llms:
                if llm["id"] == default_llm_id:
                    if llm["available"]:
                        self.current_llm = llm["id"]
                        log(
                            "info",
                            f"Current LLM set by ID: {default_llm_id} (name: {llm['name']})",
                        )
                        return
                    else:
                        log(
                            "warning",
                            f"Default LLM ID '{default_llm_id}' found but not available",
                        )
                        break

        # Fallback: try to find by name (for backward compatibility)
        if default_llm_id:
            for llm in available_llms:
                if llm["name"] == default_llm_id:
                    if llm["available"]:
                        self.current_llm = llm["id"]
                        log(
                            "warning",
                            f"Default LLM found by name (deprecated): '{default_llm_id}' -> ID: {llm['id']}",
                        )
                        return
                    else:
                        log(
                            "warning",
                            f"Default LLM '{default_llm_id}' found by name but not available",
                        )

            for llm in available_llms:
                if llm["name"].lower() == default_llm_id.lower():
                    if llm["available"]:
                        self.current_llm = llm["id"]
                        log(
                            "warning",
                            f"Default LLM found by case-insensitive name (deprecated): '{default_llm_id}' -> ID: {llm['id']}",
                        )
                        return
                    else:
                        log(
                            "warning",
                            f"Default LLM '{default_llm_id}' found by case-insensitive name but not available",
                        )

        # Fallback to first available LLM
        for llm in available_llms:
            if llm["available"]:
                self.current_llm = llm["id"]
                log(
                    "warning",
                    f"No default LLM '{default_llm_id}' found or available, falling back to: {llm['name']} (ID: {llm['id']})",
                )
                return

        if available_llms:
            log(
                "error",
                f"No available LLMs found among {len(available_llms)} configured LLMs",
            )
            self.current_llm = available_llms[0]["id"]
            log(
                "warning",
                f"Forcing current LLM to first configured: {available_llms[0]['name']} (ID: {available_llms[0]['id']})",
            )
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
            engine = self.get_engine(llm_type)

            is_available = False
            if enabled and engine:
                if llm_config.get("requires_api_key", False):
                    is_available = engine.is_available()
                else:
                    is_available = True

            llms.append(
                {
                    "id": llm_id,
                    "name": llm_config.get("name", llm_id),
                    "type": llm_type,
                    "model": llm_config.get("model", "unknown"),
                    "description": llm_config.get("description", ""),
                    "enabled": enabled,
                    "available": is_available,
                    "requires_api_key": llm_config.get("requires_api_key", False),
                    "engine": engine,
                }
            )

        total = len(llms)
        available_count = sum(1 for llm in llms if llm["available"])
        enabled_count = sum(1 for llm in llms if llm["enabled"])
        log(
            "debug",
            f"LLM Status: {available_count}/{total} available, {enabled_count}/{total} enabled",
        )

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
                    log(
                        "warning",
                        f"LLM {llm_id} is not available (enabled: {llm['enabled']})",
                    )
                    return False

        log("error", f"LLM {llm_id} not found in available LLMs")
        return False

    def validate_config(self):
        """Validate the LLM configuration."""
        if "llms" not in self.config:
            log("error", "No 'llms' section in configuration")
            return False

        # Validate embedding configuration
        if "embedding" not in self.config:
            log("warning", "No 'embedding' section in configuration, using defaults")
        else:
            embedding_config = self.config.get("embedding", {})
            if "model_name" not in embedding_config:
                log("warning", "Embedding config missing 'model_name', using default")
            if "vector_dimension" not in embedding_config:
                log(
                    "warning",
                    "Embedding config missing 'vector_dimension', using default",
                )

        llms_config = self.config.get("llms", {})
        if not isinstance(llms_config, dict):
            log(
                "error",
                f"'llms' section should be a dictionary, got: {type(llms_config)}",
            )
            return False

        valid_count = 0
        for llm_id, llm_config in llms_config.items():
            if not isinstance(llm_config, dict):
                log(
                    "warning",
                    f"LLM '{llm_id}' config is not a dictionary: {llm_config}",
                )
                continue
            if "type" not in llm_config:
                log("warning", f"LLM '{llm_id}' missing 'type' field")
                continue
            if "model" not in llm_config:
                log("warning", f"LLM '{llm_id}' missing 'model' field")
                continue
            engine_type = llm_config.get("type")
            if engine_type not in self.engines:
                log(
                    "warning", f"LLM '{llm_id}' uses unknown engine type: {engine_type}"
                )
                continue
            valid_count += 1

        log("info", f"Validated {valid_count} LLM configurations")
        return valid_count > 0

    def get_llm_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Get LLM information by name."""
        for llm in self.get_available_llms():
            if llm["name"] == name:
                return llm
        return None

    def get_current_llm_info(self) -> Optional[Dict[str, Any]]:
        """Get information about the current LLM."""
        if not self.current_llm:
            return None
        for llm in self.get_available_llms():
            if llm["id"] == self.current_llm:
                return llm
        return None

    def register_llm_callback(self, callback_func: Callable[[str, List[Dict]], str]):
        """Register a legacy callback to add LLM context to LLM queries.

        Legacy callback returns just a context string (implicitly SYSTEM role, BOTTOM position).
        """
        register_callback(self.llm_callbacks, callback_func, "legacy LLM callback")

    def unregister_llm_callback(self, callback_func: Callable[[str, List[Dict]], str]):
        """Unregister a legacy LLM callback."""
        unregister_callback(self.llm_callbacks, callback_func, "legacy LLM callback")

    def register_context_callback(
        self, callback_func: Callable[[str, List[Dict]], Tuple[str, str, str]]
    ):
        """Register an enhanced context callback with control over role and position.

        The callback should return a tuple: (context, role, position)
        where role is "system" or "user" and position is "top" or "bottom".
        """
        register_callback(
            self.context_callbacks, callback_func, "enhanced context callback"
        )

    def unregister_context_callback(
        self, callback_func: Callable[[str, List[Dict]], Tuple[str, str, str]]
    ):
        """Unregister an enhanced context callback."""
        unregister_callback(
            self.context_callbacks, callback_func, "enhanced context callback"
        )

    def _add_llm_context(self, user_id: str, messages: List[Dict]) -> List[Dict]:
        """Add LLM context to messages using registered callbacks."""
        if (not self.llm_callbacks and not self.context_callbacks) or not messages:
            return messages

        last_user_msg_index = -1
        for i, msg in enumerate(messages):
            if msg.get("role") == "user":
                last_user_msg_index = i

        top_contexts = []
        bottom_contexts = []

        for callback in self.llm_callbacks:
            try:
                # NEW: Check if callback accepts query_id parameter
                import inspect

                sig = inspect.signature(callback)
                if "query_id" in sig.parameters:
                    context = callback(
                        user_id,
                        messages,
                        query_id=getattr(self, "_current_query_id", None),
                    )
                else:
                    context = callback(user_id, messages)

                if context and context.strip():
                    bottom_contexts.append(
                        {
                            "role": "system",
                            "content": context.strip(),
                            "source": callback.__name__,
                        }
                    )
                    log("debug", f"Added legacy context from {callback.__name__}")
            except Exception as e:
                log("error", f"Legacy LLM callback {callback.__name__} failed: {e}")

        for callback in self.context_callbacks:
            try:
                # NEW: Check if callback accepts query_id parameter
                import inspect

                sig = inspect.signature(callback)
                log(
                    "debug", f"[_add_llm_context] Calling callback: {callback.__name__}"
                )
                if "query_id" in sig.parameters:
                    result = callback(
                        user_id,
                        messages,
                        query_id=getattr(self, "_current_query_id", None),
                    )
                else:
                    result = callback(user_id, messages)

                if result and len(result) >= 3:
                    context, role_str, position_str = result[:3]
                    log(
                        "debug",
                        f"[_add_llm_context] {callback.__name__} returned: context_len={len(context) if context else 0}, role={role_str}, position={position_str}",
                    )
                else:
                    log(
                        "debug",
                        f"[_add_llm_context] {callback.__name__} returned None or invalid result",
                    )

                if result and len(result) >= 3:
                    context, role_str, position_str = result[:3]
                    if not context or not context.strip():
                        continue

                    role = ContextRole.SYSTEM
                    try:
                        role = ContextRole(role_str.lower())
                    except ValueError:
                        log(
                            "warning",
                            f"Invalid role '{role_str}' from {callback.__name__}, using 'system'",
                        )

                    position = ContextPosition.BOTTOM
                    try:
                        position = ContextPosition(position_str.lower())
                    except ValueError:
                        log(
                            "warning",
                            f"Invalid position '{position_str}' from {callback.__name__}, using 'bottom'",
                        )

                    context_msg = {
                        "role": role.value,
                        "content": context.strip(),
                        "source": callback.__name__,
                    }

                    source = callback.__name__
                    content_hash = hash(context.strip())

                    if hasattr(self, "_seen_context_sources"):
                        if source in self._seen_context_sources:
                            log(
                                "warning",
                                f"Duplicate context source '{source}' detected - skipping duplicate injection",
                            )
                            continue
                        self._seen_context_sources.add(source)
                    else:
                        self._seen_context_sources = {source}

                    if hasattr(self, "_seen_context_contents"):
                        if content_hash in self._seen_context_contents:
                            log(
                                "warning",
                                f"Duplicate context content from '{source}' detected - skipping duplicate",
                            )
                            continue
                        self._seen_context_contents.add(content_hash)
                    else:
                        self._seen_context_contents = {content_hash}

                    if position == ContextPosition.TOP:
                        top_contexts.append(context_msg)
                    else:
                        bottom_contexts.append(context_msg)

                    log(
                        "debug",
                        f"Added enhanced context from {callback.__name__} (role: {role.value}, position: {position.value})",
                    )

            except Exception as e:
                log(
                    "error",
                    f"Enhanced context callback {callback.__name__} failed: {e}",
                )

        if top_contexts:
            for context_msg in reversed(top_contexts):
                messages.insert(0, context_msg)

        if bottom_contexts and last_user_msg_index >= 0:
            for context_msg in reversed(bottom_contexts):
                messages.insert(last_user_msg_index, context_msg)

        return messages

    async def generate(
        self,
        message: str,
        stream_callback: Optional[Callable] = None,
        conversation_history: Optional[List[Dict]] = None,
        user_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        query_id: Optional[str] = None,  # NEW parameter for RAG context limit
    ) -> str:
        """Generate a response for a user-facing conversation turn.

        This method is intended for interactive chat. For internal LLM calls
        (e.g. from plugins), use :meth:`internal_response` directly.

        Args:
            message: The user's message
            stream_callback: Optional callback for streaming chunks
            conversation_history: Optional conversation history
            user_id: Optional user identifier
            conversation_id: Optional conversation identifier
            query_id: Optional query ID for RAG context limit overrides

        Returns the cleaned response string (backward compatible).
        """
        messages = []

        if conversation_history:
            messages.extend(conversation_history)

        if conversation_history and messages:
            last_message = messages[-1]
            if not (
                last_message.get("role") == "user"
                and last_message.get("content") == message.strip()
            ):
                messages.append({"role": "user", "content": message})
        else:
            messages.append({"role": "user", "content": message})

        if user_id and (self.llm_callbacks or self.context_callbacks):
            # NEW: Pass query_id to context callbacks
            # We need to modify the callback mechanism to pass query_id
            # For now, we'll store it temporarily
            log(
                "debug",
                f"[_add_llm_context] user_id={user_id}, {len(self.llm_callbacks)} legacy callbacks, {len(self.context_callbacks)} context callbacks",
            )
            self._current_query_id = query_id
            messages = self._add_llm_context(user_id, messages)
            self._current_query_id = None

        return await self.internal_response(
            self.current_llm,
            messages,
            stream_callback,
            user_id=user_id,
            conversation_id=conversation_id,
        )

    async def internal_response(
        self,
        llm_id: str,
        messages: list,
        stream_callback: Optional[Callable] = None,
        response_format: Optional[str] = None,
        user_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> str:
        """Generate a response from the selected LLM.

        This is the low-level entry point used by plugins and internal
        components. It bypasses context-injection callbacks intentionally.

        Args:
            llm_id: Identifier of the LLM to use (must exist in config).
            messages: Full message list in role/content format.
            stream_callback: Optional callable receiving incremental text chunks.
            response_format: Optional output format hint forwarded verbatim to
                the engine. Pass ``"json"`` to request structured JSON output.
            user_id: Optional user identifier (forwarded to monitor callbacks).
            conversation_id: Optional conversation identifier forwarded to monitor callbacks.

        Returns:
            The cleaned response string.  Use monitor callbacks to access the
            full ``raw_response`` when needed (e.g. to audit thinking content).
        """
        # Check for FORCE_LLM environment variable to override llm_id
        force_llm = os.getenv("FORCE_LLM")
        if force_llm:
            if force_llm in self.config.get("llms", {}):
                original_llm_id = llm_id
                llm_id = force_llm
                log(
                    "debug",
                    f"FORCE_LLM environment variable overrides LLM choice: {original_llm_id} -> {llm_id}",
                )
            else:
                log(
                    "warning",
                    f"FORCE_LLM environment variable set to '{force_llm}' but this LLM is not configured. Using original: {llm_id}",
                )

        log("debug", f"Generating response with LLM: {llm_id}")
        log(
            "debug",
            f"Messages: {len(messages)} messages, response_format={response_format!r}",
        )

        llm_config = self.config.get("llms", {}).get(llm_id, {})
        if not llm_config:
            error_msg = f"LLM {llm_id} not found in configuration"
            log("error", error_msg)
            return error_msg

        if not llm_config.get("enabled", True):
            error_msg = f"LLM {llm_id} is disabled"
            log("error", error_msg)
            return error_msg

        llm_type = llm_config.get("type")
        model_name = llm_config.get("model")

        # Read no_thinking from per-LLM config (opt-in, defaults to False)
        no_thinking: bool = bool(llm_config.get("no_thinking", False))
        if no_thinking:
            log("debug", f"no_thinking=True configured for LLM '{llm_id}'")

        engine = self.get_engine(llm_type)
        if not engine:
            error_msg = f"No engine found for type: {llm_type}"
            log("error", error_msg)
            return error_msg

        if hasattr(engine, "set_config"):
            engine.set_config(llm_config)

        requires_api_key = llm_config.get("requires_api_key", False)
        if requires_api_key and not engine.is_available():
            error_msg = f"LLM {llm_id} requires API key which is not configured"
            log("error", error_msg)
            return error_msg

        filtered_messages = [msg for msg in messages if msg.get("content", "").strip()]
        if not filtered_messages:
            error_msg = "No valid messages provided"
            log("warning", error_msg)
            return error_msg

        try:
            result: GenerateResult = await engine.generate(
                model_name,
                filtered_messages,
                stream_callback,
                response_format,
                no_thinking,
            )

            # Soft dependency: record LLM usage in driver when available.
            try:
                from shared.driver import get_driver

                prompt_tokens = sum(
                    len((msg.get("content") or "").split()) for msg in filtered_messages
                )
                completion_tokens = len((result.response or "").split())
                get_driver().record_llm_call(llm_id, prompt_tokens, completion_tokens)
            except Exception:
                pass

            if hasattr(self, "_monitor_callbacks") and self._monitor_callbacks:
                try:
                    monitor_data = {
                        "llm_id": llm_id,
                        "llm_type": llm_type,
                        "model": model_name,
                        "messages": filtered_messages,
                        # Cleaned, post-processed response (same as return value)
                        "response": result.response,
                        # Unmodified engine output — may contain <think> blocks
                        # for Ollama models when no_thinking=True was requested
                        # but the model thought anyway.
                        "raw_response": result.raw_response,
                        "response_format": response_format,
                        "no_thinking": no_thinking,
                        "user_id": user_id,
                        "conversation_id": conversation_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "engine_type": engine.engine_type,
                        "success": True,
                        "error": None,
                    }
                    self._notify_monitor_callbacks(monitor_data)
                except Exception as e:
                    log(
                        "error",
                        f"Error notifying monitor callbacks: {str(e)}",
                        stacktrace=True,
                    )

            # Return only the cleaned response string — full backward compat.
            return result.response

        except Exception as e:
            error_msg = f"Error generating response from {llm_id}: {str(e)}"
            log("error", error_msg)
            return error_msg

    def register_monitor_callback(
        self, callback_func: Callable[[Dict[str, Any]], None]
    ):
        """Register a callback to monitor LLM usage and costs."""
        register_callback(
            callback_list=self._monitor_callbacks,
            callback_func=callback_func,
            callback_type="monitor callback",
            allow_replace=True,  # or False based on your preference
        )

    def unregister_monitor_callback(
        self, callback_func: Callable[[Dict[str, Any]], None]
    ):
        """Unregister a monitor callback."""
        unregister_callback(
            callback_list=self._monitor_callbacks,
            callback_func=callback_func,
            callback_type="monitor callback",
        )

    def _notify_monitor_callbacks(self, data: Dict[str, Any]):
        """Notify all registered monitor callbacks."""
        if hasattr(self, "_monitor_callbacks"):
            for callback in self._monitor_callbacks:
                try:
                    callback(data)
                except Exception as e:
                    log("error", f"Monitor callback error: {e}")
