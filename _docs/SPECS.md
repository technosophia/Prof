<!-- /_docs/SPECS.md --> 

# Functional High-Level Specifications

The goal is to build a "Professor" application. It takes training material (pdf, markdown) of a real training course, and give it to an LLM to help students so that they can learn more interactively. So basically it's a RAG, but with a memory of the student pedagogical progression. The main benefit is in that memory and pro-active suggestions.

Planned Features:
- Base: 
  - multi-user, multilingual, multi-LLM, multi-conversation.
- MVP Features:
  - RAG with different RAG engines, means to compare and debug them.
  - Token stats: monitoring token usage per user.
  - Training : follow user progression, learning path, level assessment through discussion rather than questionnaires.

Additional Features:
- Retrieval of YouTube playlists and PDFs for importing RAG content.
- mem0 advanced memory
- semantic graph RAG
