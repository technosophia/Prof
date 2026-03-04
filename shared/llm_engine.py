"""
Base LLM Engine Interface
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Callable


class LLMEngine(ABC):
    """Base class for all LLM engines."""

    def __init__(self, engine_type: str):
        self.engine_type = engine_type
        self.available = False

    @abstractmethod
    async def generate(
        self,
        model: str,
        messages: List[Dict[str, str]],
        stream_callback: Optional[Callable] = None,
        response_format: Optional[str] = None,
        no_thinking: bool = False,
    ) -> str:
        """Generate response from the LLM.

        Args:
            model: Model identifier to use.
            messages: Conversation messages in role/content format.
            stream_callback: Optional callable receiving incremental chunks.
            response_format: Optional output format hint. Pass ``"json"`` to
                request a structured JSON response. Each engine translates this
                to its own native API parameter. Defaults to ``None`` (plain
                text), preserving backward-compatible behaviour.
            no_thinking: If True, instruct the model to skip its chain-of-thought
                reasoning and strip any residual <think> tags from the output.
                Only meaningful for models that support thinking mode (e.g. Ollama
                with qwen3). Ignored silently by engines that do not support it.
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the engine is available (API key, connection, etc.)."""
        pass

    @abstractmethod
    def get_supported_models(self) -> List[str]:
        """Get list of supported models for this engine."""
        pass
