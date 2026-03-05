"""
Base LLM Engine Interface
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Callable


@dataclass
class GenerateResult:
    """Result from an LLM engine generate() call.

    Attributes:
        response:     The final, cleaned text to surface to the caller.
                      For engines that support no_thinking, <think> blocks
                      have already been stripped.
        raw_response: The unmodified text exactly as returned by the engine /
                      API.  Identical to ``response`` for engines that do not
                      perform any post-processing (Groq, Gemini, xAI, Mock).
                      For Ollama with no_thinking=True, this will contain the
                      full <think>…</think> block when the model thought despite
                      the /no_think directive, letting callers audit compliance.
    """
    response: str
    raw_response: str


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
    ) -> GenerateResult:
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

        Returns:
            GenerateResult with ``response`` (cleaned) and ``raw_response``
            (unmodified engine output).
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
