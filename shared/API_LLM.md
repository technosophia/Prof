<!-- shared/llm.py -->

<!-- GENERATED FILE - do not edit manually -->
<!-- Source: shared/llm.py -->

# API — llm

LLM Manager using plugin-based engine system.


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
- `get_embedding()`: Embed a single string and return a float vector (384 dims for `all-MiniLM-L6-v2`)
- `get_embeddings()`: Embed a list of strings and return float vectors (384 dims each)
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
