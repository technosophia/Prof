<!-- shared/conversation.py -->

<!-- GENERATED FILE - do not edit manually -->
<!-- Source: shared/conversation.py -->

# API — conversation

Conversation management with database backend.
Handles multiple conversations per user with LLM interactions.


# Conversation Management System (`shared/conversation.py`)
Stores and manages user conversations with LLM interactions. Supports multiple conversations per user with full message history.

**Exported components:**
- `Message`: Conversation message model
- `get_conversation_manager()`: Access conversation management
- `cleanup_user_conversations()`: Cleanup conversations before user deletion
- Automatic cleanup when users are deleted
