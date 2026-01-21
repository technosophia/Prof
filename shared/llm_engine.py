"""
Base LLM Engine Interface
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Callable
from shared.logging import log


class LLMEngine(ABC):
    """Base class for all LLM engines."""

    def __init__(self, engine_type: str):
        self.engine_type = engine_type
        self.available = False

    @abstractmethod
    async def generate(self, model: str, messages: List[Dict[str, str]],
                      stream_callback: Optional[Callable] = None) -> str:
        """Generate response from the LLM."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the engine is available (API key, connection, etc.)."""
        pass

    @abstractmethod
    def get_supported_models(self) -> List[str]:
        """Get list of supported models for this engine."""
        pass
