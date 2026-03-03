"""
Tests for the Semantic Evaluator
"""

import sys
import os
import pytest
from unittest.mock import Mock, patch, call
import numpy as np

from core.logging import log
from shared.semantic_eval import (
    SemanticEvaluator,
    ContainmentResult,
    SimilarityResult,
    chunk_text,
    _split_sentences,
    _sliding_window_chunks
)
from shared.llm import LLMManager


# ---------------------------------------------------------------------------
# Fixtures for real LLM Manager
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def llm_config():
    """Provide a minimal LLM configuration for testing."""
    return {
        "llms": {
            "test_embedding": {
                "name": "Test Embedding",
                "type": "sentence_transformer",  # This might need adjustment based on your actual engine type
                "model": "all-MiniLM-L6-v2",
                "enabled": True,
                "requires_api_key": False
            }
        },
        "app": {
            "default_llm": "test_embedding"
        }
    }


@pytest.fixture(scope="session")
def real_llm_manager(llm_config):
    """Create a real LLM manager instance (loaded once per test session)."""
    log("info", "=== Loading real LLM manager with embedding model ===")
    manager = LLMManager(llm_config)

    # Warm up the embedding model
    _ = manager.get_embedding("warmup")
    log("info", "=== LLM manager ready ===")
    return manager


@pytest.fixture
def semantic_evaluator(real_llm_manager):
    """Create a SemanticEvaluator with real embeddings."""
    return SemanticEvaluator(
        real_llm_manager,
        default_similarity_threshold=0.7,
        default_containment_threshold=0.45,
        chunk_window=3,
        chunk_step=1
    )


# ---------------------------------------------------------------------------
# Chunking Tests (unchanged - these don't use embeddings)
# ---------------------------------------------------------------------------

class TestChunkingHelpers:
    """Test the text chunking helper functions."""

    def test_split_sentences_basic(self):
        """Test basic sentence splitting."""
        log("info", "=== Starting test_split_sentences_basic ===")

        text = "This is sentence one. This is sentence two! Is this sentence three? Yes."
        sentences = _split_sentences(text, min_length=3)

        log("info", f"Split '{text}' into {len(sentences)} sentences")
        for i, s in enumerate(sentences):
            log("info", f"  Sentence {i+1}: '{s}'")

        assert len(sentences) == 4
        assert "This is sentence one" in sentences[0]
        assert "This is sentence two" in sentences[1]
        assert "Is this sentence three" in sentences[2]
        assert "Yes" in sentences[3]

        log("info", "=== Completed test_split_sentences_basic ===")

    def test_split_sentences_with_newlines(self):
        """Test sentence splitting with newlines."""
        log("info", "=== Starting test_split_sentences_with_newlines ===")

        text = "First paragraph.\n\nSecond paragraph with multiple sentences. Here's another!"
        sentences = _split_sentences(text)

        log("info", f"Split text with newlines into {len(sentences)} sentences")
        for i, s in enumerate(sentences):
            log("info", f"  Sentence {i+1}: '{s}'")

        assert len(sentences) >= 3
        assert "First paragraph" in sentences[0]

        log("info", "=== Completed test_split_sentences_with_newlines ===")

    def test_split_sentences_filters_short(self):
        """Test that very short sentences are filtered out."""
        log("info", "=== Starting test_split_sentences_filters_short ===")

        text = "Hi. This is a longer sentence that should be kept. Bye."
        sentences = _split_sentences(text)

        log("info", f"Split into {len(sentences)} sentences (short ones filtered)")
        for i, s in enumerate(sentences):
            log("info", f"  Sentence {i+1}: '{s}' (length: {len(s)})")

        assert len(sentences) == 1  # Only the longer sentence remains
        assert "longer sentence" in sentences[0]

        log("info", "=== Completed test_split_sentences_filters_short ===")

    def test_sliding_window_chunks_basic(self):
        """Test sliding window chunking."""
        log("info", "=== Starting test_sliding_window_chunks_basic ===")

        sentences = [
            "Sentence one.",
            "Sentence two.",
            "Sentence three.",
            "Sentence four.",
            "Sentence five."
        ]

        chunks = _sliding_window_chunks(sentences, window=3, step=1)

        log("info", f"Created {len(chunks)} chunks from 5 sentences (window=3, step=1)")
        for i, chunk in enumerate(chunks):
            log("info", f"  Chunk {i+1}: '{chunk[:50]}...'")

        assert len(chunks) == 3  # 5 sentences with window=3, step=1 -> 3 chunks
        assert "Sentence one. Sentence two. Sentence three." in chunks[0]
        assert "Sentence three. Sentence four. Sentence five." in chunks[2]

        log("info", "=== Completed test_sliding_window_chunks_basic ===")

    def test_sliding_window_chunks_with_step(self):
        """Test sliding window chunking with custom step."""
        log("info", "=== Starting test_sliding_window_chunks_with_step ===")

        sentences = [
            "Sentence one.",
            "Sentence two.",
            "Sentence three.",
            "Sentence four.",
            "Sentence five.",
            "Sentence six."
        ]

        chunks = _sliding_window_chunks(sentences, window=2, step=2)

        log("info", f"Created {len(chunks)} chunks (window=2, step=2)")
        for i, chunk in enumerate(chunks):
            log("info", f"  Chunk {i+1}: '{chunk[:40]}...'")

        assert len(chunks) == 3  # 6 sentences with window=2, step=2 -> 3 chunks
        assert "Sentence one. Sentence two." in chunks[0]
        assert "Sentence three. Sentence four." in chunks[1]
        assert "Sentence five. Sentence six." in chunks[2]

        log("info", "=== Completed test_sliding_window_chunks_with_step ===")

    def test_chunk_text_adaptive(self):
        """Test the adaptive chunk_text function."""
        log("info", "=== Starting test_chunk_text_adaptive ===")

        # Short text (<= 3 sentences) should return as single chunk
        short_text = "This is sentence one. This is sentence two. This is sentence three."
        chunks = chunk_text(short_text)
        log("info", f"Short text -> {len(chunks)} chunk(s)")
        assert len(chunks) == 1

        # Longer text should be chunked - using longer sentences
        long_text = "This is the first longer sentence. This is the second longer sentence. This is the third longer sentence. This is the fourth longer sentence. This is the fifth longer sentence. This is the sixth longer sentence. This is the seventh longer sentence."
        chunks = chunk_text(long_text, window_size=3, step=1)
        log("info", f"Long text -> {len(chunks)} chunks")
        assert len(chunks) > 1

        # Empty text
        empty_chunks = chunk_text("")
        log("info", f"Empty text -> {len(empty_chunks)} chunks")
        assert len(empty_chunks) == 0

        log("info", "=== Completed test_chunk_text_adaptive ===")


# ---------------------------------------------------------------------------
# Semantic Tests with Real Embeddings
# ---------------------------------------------------------------------------

class TestSemanticEvaluatorReal:
    """Test Semantic Evaluator with real embeddings."""

    def test_similarity_identical_texts(self, semantic_evaluator):
        """Test similarity between identical texts."""
        log("info", "=== Starting test_similarity_identical_texts ===")

        text = "The cat sat on the mat"

        result = semantic_evaluator.similarity(text, text)

        log("info", f"Identical texts similarity: {result.score:.4f}")
        assert result.score > 0.99  # Should be very close to 1.0
        assert result.passed is True

        log("info", "=== Completed test_similarity_identical_texts ===")

    def test_similarity_related_texts(self, semantic_evaluator):
        """Test similarity between semantically related texts."""
        log("info", "=== Starting test_similarity_related_texts ===")

        # Cat and feline should be semantically similar
        result = semantic_evaluator.similarity(
            "The cat is sleeping on the couch",
            "A feline rests peacefully"
        )

        log("info", f"Related texts similarity: {result.score:.4f}")
        # Real embeddings should give moderate to high similarity
        assert result.score > 0.5
        # With default threshold 0.7, this might pass or fail depending on the model
        # We're not asserting result.passed here as it depends on threshold

        log("info", "=== Completed test_similarity_related_texts ===")

    def test_similarity_unrelated_texts(self, semantic_evaluator):
        """Test similarity between unrelated texts."""
        log("info", "=== Starting test_similarity_unrelated_texts ===")

        # Cat and programming should be less similar
        result = semantic_evaluator.similarity(
            "The cat is sleeping",
            "Python programming language syntax"
        )

        log("info", f"Unrelated texts similarity: {result.score:.4f}")
        # Should be lower than related texts, but exact value depends on model
        assert result.score < 0.6  # Conservative upper bound

        log("info", "=== Completed test_similarity_unrelated_texts ===")

    def test_similarity_custom_threshold(self, semantic_evaluator):
        """Test similarity with custom threshold."""
        log("info", "=== Starting test_similarity_custom_threshold ===")

        result = semantic_evaluator.similarity(
            "The cat is sleeping",
            "A feline rests",
            threshold=0.3  # Lower threshold
        )

        log("info", f"Similarity with custom threshold 0.3: {result.score:.4f}, passed: {result.passed}")
        assert result.threshold == 0.3

        log("info", "=== Completed test_similarity_custom_threshold ===")

    def test_contains_concept_basic(self, semantic_evaluator):
        """Test basic concept containment."""
        log("info", "=== Starting test_contains_concept_basic ===")

        text = "The cat slept on the couch. The dog played in the yard. Meanwhile, the programmer wrote Python code."

        # Should contain cat concept
        result_cat = semantic_evaluator.contains_concept(text, "cat")
        log("info", f"Contains 'cat': {result_cat.summary}")
        assert result_cat.passed is True
        assert result_cat.best_score > 0.5

        # Should contain dog concept
        result_dog = semantic_evaluator.contains_concept(text, "dog")
        log("info", f"Contains 'dog': {result_dog.summary}")
        assert result_dog.passed is True

        # Should contain programming concept (might match "Python" or "programmer")
        result_prog = semantic_evaluator.contains_concept(text, "programming")
        log("info", f"Contains 'programming': {result_prog.summary}")
        assert result_prog.passed is True

        log("info", "=== Completed test_contains_concept_basic ===")

    def test_contains_concept_not_present(self, semantic_evaluator):
        """Test concept containment when concept is not present."""
        log("info", "=== Starting test_contains_concept_not_present ===")

        text = "The cat slept on the couch. The dog played in the yard."

        # Should not contain bird concept
        result = semantic_evaluator.contains_concept(text, "bird")
        log("info", f"Contains 'bird': {result.summary}")
        assert result.passed is False
        assert result.best_score < 0.6  # Conservative upper bound

        log("info", "=== Completed test_contains_concept_not_present ===")

    def test_contains_concept_with_chunking(self, semantic_evaluator):
        """Test that chunking helps find concepts in long texts."""
        log("info", "=== Starting test_contains_concept_with_chunking ===")

        # Long text where the concept appears only in one sentence
        text = """
        The weather was nice today. The birds were singing.
        I went for a walk in the park. The flowers were blooming.
        Later, I decided to learn about programming languages.
        Python is a popular choice for beginners.
        It has clear syntax and extensive libraries.
        The cat chased a mouse in the garden.
        The dog barked at the mailman.
        """

        # Should find programming concept even though it's buried
        result = semantic_evaluator.contains_concept(text, "Python programming")
        log("info", f"Found programming concept: {result.summary}")
        log("info", f"Best matching chunk: '{result.best_chunk[:100]}...'")
        assert result.passed is True
        assert "Python" in result.best_chunk or "programming" in result.best_chunk.lower()

        # Check details were populated
        assert len(result.details) > 0
        log("info", f"Top 3 chunks by score:")
        for i, detail in enumerate(result.details[:3]):
            log("info", f"  {i+1}. Score {detail['score']:.3f}: '{detail['chunk'][:50]}...'")

        log("info", "=== Completed test_contains_concept_with_chunking ===")

    def test_contains_all_concepts(self, semantic_evaluator):
        """Test checking for multiple concepts."""
        log("info", "=== Starting test_contains_all_concepts ===")

        text = """
        The cat and dog were friends. They played together in the yard.
        The owner was a programmer who wrote Python code all day.
        """

        # All concepts present (cat, dog, programming)
        result_all = semantic_evaluator.contains_all_concepts(
            text,
            ["cat", "dog", "programming"]
        )

        log("info", f"All concepts present: {result_all['summary']}")
        assert result_all["passed"] is True
        assert len(result_all["failed"]) == 0

        # One concept missing (bird)
        result_missing = semantic_evaluator.contains_all_concepts(
            text,
            ["cat", "bird", "programming"]
        )

        log("info", f"One concept missing: {result_missing['summary']}")
        assert result_missing["passed"] is False
        assert "bird" in result_missing["failed"]
        assert len(result_missing["failed"]) == 1

        log("info", "=== Completed test_contains_all_concepts ===")

    def test_empty_text_handling(self, semantic_evaluator):
        """Test handling of empty texts."""
        log("info", "=== Starting test_empty_text_handling ===")

        # Similarity with empty text
        result_sim = semantic_evaluator.similarity("", "something")
        log("info", f"Similarity with empty: {result_sim.summary}")
        assert result_sim.passed is False
        assert result_sim.score == 0.0

        # Contains concept with empty text
        result_contain = semantic_evaluator.contains_concept("", "cat")
        log("info", f"Contains concept with empty: {result_contain.summary}")
        assert result_contain.passed is False
        assert result_contain.best_score == 0.0

        log("info", "=== Completed test_empty_text_handling ===")


# ---------------------------------------------------------------------------
# Edge Cases (some remain mocked, some use real embeddings)
# ---------------------------------------------------------------------------

class TestSemanticEvaluatorEdgeCases:
    """Test edge cases and error handling."""

    def test_no_llm_manager(self):
        """Test behavior when no LLM manager is provided."""
        log("info", "=== Starting test_no_llm_manager ===")

        evaluator = SemanticEvaluator(None)

        # Should return a failed result gracefully
        result = evaluator.similarity("test", "test")
        log("info", f"Similarity result: {result.summary}")
        assert result.passed is False
        assert result.score == 0.0

        result_contain = evaluator.contains_concept("test", "concept")
        log("info", f"Contains concept result: {result_contain.summary}")
        assert result_contain.passed is False
        assert result_contain.best_score == 0.0

        log("info", "=== Completed test_no_llm_manager ===")

    def test_exception_handling(self, real_llm_manager):
        """Test handling of exceptions during embedding."""
        log("info", "=== Starting test_exception_handling ===")

        # Create a manager that raises exceptions
        failing_manager = Mock()
        failing_manager.get_embedding.side_effect = Exception("Embedding failed")

        evaluator = SemanticEvaluator(failing_manager)

        # Should handle exception gracefully
        result = evaluator.similarity("test", "test")
        log("info", f"Similarity with exception: {result.summary}")
        assert result.passed is False
        assert result.score == 0.0

        result_contain = evaluator.contains_concept("test", "concept")
        log("info", f"Contains concept with exception: {result_contain.summary}")
        assert result_contain.passed is False
        assert result_contain.best_score == 0.0

        log("info", "=== Completed test_exception_handling ===")


# ---------------------------------------------------------------------------
# Integration Tests with Real Embeddings
# ---------------------------------------------------------------------------

class TestSemanticEvaluatorIntegration:
    """Integration-style tests with realistic scenarios using real embeddings."""

    def test_semantic_similarity_hierarchy(self, semantic_evaluator):
        """Test that semantic similarity respects conceptual hierarchy."""
        log("info", "=== Starting test_semantic_similarity_hierarchy ===")

        # Cat should be more similar to feline than to dog
        cat_feline = semantic_evaluator.similarity("cat", "feline")
        cat_dog = semantic_evaluator.similarity("cat", "dog")

        log("info", f"Cat-Feline similarity: {cat_feline.score:.4f}")
        log("info", f"Cat-Dog similarity: {cat_dog.score:.4f}")

        assert cat_feline.score > cat_dog.score

        # Programming should be more similar to python than to cat
        prog_python = semantic_evaluator.similarity("programming", "python")
        prog_cat = semantic_evaluator.similarity("programming", "cat")

        log("info", f"Programming-Python similarity: {prog_python.score:.4f}")
        log("info", f"Programming-Cat similarity: {prog_cat.score:.4f}")

        assert prog_python.score > prog_cat.score

        log("info", "=== Completed test_semantic_similarity_hierarchy ===")

    def test_concept_containment_in_long_text(self, semantic_evaluator):
        """Test finding concepts in a longer, realistic text."""
        log("info", "=== Starting test_concept_containment_in_long_text ===")

        text = """
        Today was a beautiful day. The sun was shining and birds were singing.
        I decided to take my dog for a walk in the park. My golden retriever, Max,
        loves chasing squirrels. Later, I came home and started working on my
        Python project. I was implementing a new feature that would analyze
        data from our cat population study. The feline research has been ongoing
        for three years now. We've tracked over 50 cats in the urban environment.
        The programming language choice was obvious - Python's data analysis
        libraries are excellent. Meanwhile, my colleague Sarah was working on
        the canine behavior study. Her research on dogs has produced fascinating
        results about pack dynamics.
        """

        # Should find cat-related concepts
        cat_result = semantic_evaluator.contains_concept(text, "feline")
        log("info", f"Feline concept: {cat_result.summary}")
        assert cat_result.passed is True
        assert "cat" in cat_result.best_chunk.lower() or "feline" in cat_result.best_chunk.lower()

        # Should find dog-related concepts
        dog_result = semantic_evaluator.contains_concept(text, "canine")
        log("info", f"Canine concept: {dog_result.summary}")
        assert dog_result.passed is True
        assert "dog" in dog_result.best_chunk.lower() or "canine" in dog_result.best_chunk.lower()

        # Should find programming concepts
        prog_result = semantic_evaluator.contains_concept(text, "coding")
        log("info", f"Coding concept: {prog_result.summary}")
        assert prog_result.passed is True
        assert "python" in prog_result.best_chunk.lower() or "programming" in prog_result.best_chunk.lower()

        log("info", "=== Completed test_concept_containment_in_long_text ===")

    def test_threshold_sensitivity(self, semantic_evaluator):
        """Test how different thresholds affect pass/fail decisions."""
        log("info", "=== Starting test_threshold_sensitivity ===")

        text = "The cat slept on the couch while the dog played outside."

        # Test with different thresholds
        thresholds = [0.3, 0.5, 0.7, 0.9]

        for concept in ["cat", "feline", "kitten"]:
            log("info", f"\nTesting concept: '{concept}'")
            base_result = semantic_evaluator.contains_concept(text, concept)

            for thresh in thresholds:
                result = semantic_evaluator.contains_concept(text, concept, threshold=thresh)
                log("info", f"  Threshold {thresh}: {result.passed} (score: {base_result.best_score:.3f})")

                # Higher thresholds should be harder to pass
                if thresh > base_result.best_score:
                    assert result.passed is False
                else:
                    assert result.passed is True

        log("info", "\n=== Completed test_threshold_sensitivity ===")


if __name__ == "__main__":
    # This allows running the tests directly
    pytest.main([__file__, "-v", "-s"])
