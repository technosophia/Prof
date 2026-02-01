"""
Module Development Guide: Config, Logging, Translation & LLM Systems

[agent]

## Overview

This application provides four core utilities that all modules can use: **configuration management**, **logging**, **translation**, and **LLM integration**. Each system is designed for simple one-line initialization and easy use throughout your modules.

## Best Practices

1. **Initialize in correct order**: Always load config first, then other systems
2. **Use async for LLM calls**: Always use `asyncio.run()` or async context for LLM operations
3. **Handle streaming properly**: Use callbacks for real-time response display
4. **Log errors with tracebacks**: Use `exc_info=True` for error logs to get stack traces
5. **Check LLM availability**: Verify `llm_info["available"]` before trying to use an LLM
6. **Use environment variables**: Keep API keys in `.env` file, not in code
7. **Validate configurations**: Ensure your `config.json` has all required fields
8. **Graceful error handling**: Always wrap LLM calls in try-except blocks

## Quick Reference

```python
# Most common imports
from shared.config import get_config
from shared.logging import log
from shared.common import _
from shared.llm import llm_generate, set_current_llm

# Most common patterns
config = get_config()
log("info", "Message here")
translated_text = _("translation_key")
response = await llm_generate("Your prompt")
```

## Troubleshooting

### Common Issues

1. **"No available LLMs found"**: Check your `.env` file for missing API keys
2. **"cannot access local variable 'llm'"**: Avoid using `llm` as variable name in loops
3. **Configuration errors**: Ensure config is loaded before importing other modules
4. **Streaming not working**: Verify the LLM supports streaming and callback is defined
5. **Translation errors**: Check that translation files exist and keys match

### Debug Tips

1. Enable traceback in logging config: `"include_traceback": true`
2. Check LLM availability: `get_available_llms()` returns detailed status
3. Verify environment variables: Use debug section in Streamlit app
4. Monitor logs: All system operations are logged with appropriate levels

This integrated system allows each module to be self-contained with its own configuration, translations, logging, and LLM capabilities while seamlessly integrating with the main application.

"""
