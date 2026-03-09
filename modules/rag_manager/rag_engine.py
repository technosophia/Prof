from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Tuple, Any, Callable


class RAGEngine(ABC):
    """Abstract base class for all RAG engines."""

    def __init__(self, engine_type: str):
        self.engine_type = engine_type
        self.description = ""
        self.model_name = "all-MiniLM-L6-v2"  # Default model
        self.dimension = 384  # Default dimension

    @abstractmethod
    def index_document(self, user_id: str, filename: str, file_path: str, content: Optional[str] = None) -> bool:
        """Index a document for a specific user."""
        pass

    @abstractmethod
    def delete_document(self, user_id: str, filename: str) -> bool:
        """Delete a document from the index."""
        pass

    @abstractmethod
    def search(self, user_id: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search for relevant documents/chunks."""
        pass

    @abstractmethod
    def get_indexed_documents(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get list of indexed documents."""
        pass

    @abstractmethod
    def clear_user_index(self, user_id: str) -> bool:
        """Clear all indexed documents for a user."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the engine is available."""
        pass

    @abstractmethod
    def get_stats(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Get engine statistics."""
        pass

    # ------------------------------------------------------------------
    # Live config override — engines override this to apply changes
    # without requiring reconstruction of the singleton.
    # ------------------------------------------------------------------

    def get_config(self) -> Dict[str, Any]:
        """
        Return the current runtime config of this engine as a plain dict.
        Override in subclasses to expose all tunable parameters.
        The default implementation returns an empty dict.
        """
        return {}

    def update_config(self, overrides: Dict[str, Any]) -> None:
        """
        Apply runtime config overrides without reconstructing the engine.
        Override in subclasses to handle each relevant key.

        Args:
            overrides: Dict of config keys → new values.
                       Only keys present in the dict are updated;
                       unmentioned keys keep their current value.
        """
        pass  # Default: no-op. Subclasses implement what they support.
