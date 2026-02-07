"""
Test RAG system functionality
"""

import pytest
import tempfile
import os
from pathlib import Path
from modules.rag_manager.rag_manager import RAGManager, SimpleRAGEngine


def test_rag_engine_initialization():
    """Test RAG engine initialization."""
    engine = SimpleRAGEngine()
    assert engine.engine_type == "simple"
    assert engine.description != ""
    assert engine.is_available() == True


def test_document_indexing():
    """Test document indexing."""
    engine = SimpleRAGEngine()

    # Create a test document
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("This is a test document about artificial intelligence and machine learning.")
        temp_path = f.name

    try:
        # Index document
        success = engine.index_document("test_user", "test.txt", temp_path)
        assert success == True

        # Check if document is in index
        docs = engine.get_indexed_documents("test_user")
        assert len(docs) == 1
        assert docs[0]['filename'] == "test.txt"

        # Search for document
        results = engine.search("test_user", "artificial intelligence")
        assert len(results) == 1
        assert results[0]['filename'] == "test.txt"
        assert results[0]['score'] > 0

    finally:
        # Cleanup
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def test_rag_manager_engine_discovery():
    """Test RAG manager engine discovery."""
    manager = RAGManager()

    engines = manager.get_available_engines()
    assert len(engines) > 0

    # Check if simple engine is available
    simple_engine_found = any(e['type'] == 'simple' for e in engines)
    assert simple_engine_found == True

    # Get default engine
    default_engine = manager.get_default_engine()
    assert default_engine is not None
    assert default_engine.engine_type == "simple"


def test_user_permissions():
    """Test user permissions for document access."""
    # This would require a full user manager setup
    # For now, just test the permission logic structure
    manager = RAGManager()

    # These tests would require actual user records in the database
    # We'll test the structure instead
    assert hasattr(manager, '_check_user_permission')
    assert callable(manager._check_user_permission)


if __name__ == "__main__":
    print("Running RAG system tests...")

    test_rag_engine_initialization()
    print("✓ RAG engine initialization test passed")

    test_document_indexing()
    print("✓ Document indexing test passed")

    test_rag_manager_engine_discovery()
    print("✓ RAG manager engine discovery test passed")

    test_user_permissions()
    print("✓ User permissions test structure validated")

    print("\nAll tests passed!")
