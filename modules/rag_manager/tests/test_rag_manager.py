"""
Tests for RAG Manager module.
"""

import pytest
import tempfile
import os
import sys
import json
from pathlib import Path
import shutil
from unittest.mock import Mock, patch, MagicMock

from modules.rag_manager import RAGManager
import shared.common

# Create a comprehensive mock for the entire users module
mock_user_info = {
    'id': 'test_user',
    'name': 'Test User',
    'role': 'admin'
}

# Create proper mock for UserRole
class MockUserRole:
    ADMIN = "admin"
    MASTER = "master"
    NORMAL = "normal"

    # Make it behave like an enum
    @staticmethod
    def value_of(value):
        return value

# Create mock user manager
mock_user_manager = Mock()
mock_user_manager.get_user = Mock(return_value=mock_user_info)
mock_user_manager.register_before_delete_callback = Mock()

# Create a clean test environment
@pytest.fixture
def temp_rag_manager():
    """Create a temporary RAG manager for testing with isolated environment."""
    import tempfile

    # Create a temporary directory for this specific test
    temp_dir = tempfile.mkdtemp()
    test_data_dir = Path(temp_dir) / "test_rag"

    # Ensure the directory exists
    test_data_dir.mkdir(parents=True, exist_ok=True)

    # Create an empty metadata file to avoid JSON parsing errors
    metadata_file = test_data_dir / "metadata.json"
    with open(metadata_file, 'w', encoding='utf-8') as f:
        json.dump({}, f)

    # Store original function
    original_get_config = shared.common.get_config

    # Create test config
    def mock_get_config():
        return {
            "rag_manager": {
                "data_directory": str(test_data_dir),
                "allowed_extensions": [".txt", ".md"],
                "max_file_size_mb": 10,  # Increased for testing
                "default_engine": "simple"
            }
        }

    # Temporarily replace get_config
    shared.common.get_config = mock_get_config

    # Mock the user imports
    with patch('modules.rag_manager.rag_manager.user_manager', mock_user_manager):
        # Also patch UserRole in the rag_manager module
        with patch('modules.rag_manager.rag_manager.UserRole', MockUserRole):
            # Create manager
            manager = RAGManager()

            # Mock _check_user_permission to always return True for tests
            manager._check_user_permission = Mock(return_value=True)

            # Clear any existing documents before yielding (ADD THIS)
            manager.documents.clear()
            manager._save_metadata()

            yield manager

    # Cleanup
    try:
        # Remove the test data directory
        if test_data_dir.exists():
            shutil.rmtree(test_data_dir)
        if Path(temp_dir).exists():
            shutil.rmtree(temp_dir)
    except Exception as e:
        print(f"Warning during cleanup: {e}")

    # Restore original function
    shared.common.get_config = original_get_config

@pytest.fixture
def test_user_id():
    """Return a test user ID."""
    return "test_user"

def test_init_data_directory(temp_rag_manager):
    """Test data directory initialization."""
    assert temp_rag_manager.data_dir.exists()
    assert temp_rag_manager.data_dir.is_dir()

    # Test engine discovery
    engines = temp_rag_manager.get_available_engines()
    assert len(engines) > 0
    assert any(e['type'] == 'simple' for e in engines)

def test_upload_document(temp_rag_manager, test_user_id):
    """Test document upload with user_id."""
    # Create a test file
    test_content = "This is a test document."
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(test_content)
        temp_path = f.name

    try:
        # Upload the file
        filename = temp_rag_manager.upload_document(
            temp_path,
            "test.txt",
            user_id=test_user_id
        )

        assert filename is not None, f"Upload failed for {temp_path}"
        assert filename in temp_rag_manager.documents

        # Check if file exists
        expected_path = temp_rag_manager.data_dir / filename
        assert expected_path.exists()

        # Check metadata
        doc_info = temp_rag_manager.documents[filename]
        assert doc_info['uploaded_by'] == test_user_id
        assert doc_info['original_filename'] == "test.txt"

    finally:
        # Cleanup
        if os.path.exists(temp_path):
            os.unlink(temp_path)

def test_delete_document(temp_rag_manager, test_user_id):
    """Test document deletion."""
    # First upload a document
    test_content = "Document to delete."
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(test_content)
        temp_path = f.name

    try:
        filename = temp_rag_manager.upload_document(
            temp_path,
            "delete_test.txt",
            user_id=test_user_id
        )
        assert filename is not None, f"Upload failed for {temp_path}"

        # Delete the document
        result = temp_rag_manager.delete_document(filename, user_id=test_user_id)
        assert result is True

        # Check it's gone
        assert filename not in temp_rag_manager.documents

    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

def test_get_user_documents(temp_rag_manager, test_user_id):
    """Test getting documents for a specific user."""
    # Upload a few test documents
    uploaded_filenames = []
    for i in range(3):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(f"Test document {i}")
            temp_path = f.name

        try:
            filename = temp_rag_manager.upload_document(
                temp_path,
                f"test_{i}.txt",
                user_id=test_user_id
            )
            assert filename is not None, f"Upload failed for test_{i}.txt"
            uploaded_filenames.append(filename)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    # Get user documents
    documents = temp_rag_manager.get_user_documents(test_user_id)

    # Should have exactly 3 documents
    assert len(documents) == 3, f"Expected 3 documents, got {len(documents)}"

    # Check document properties
    for doc in documents:
        assert 'filename' in doc
        assert 'original_filename' in doc
        assert 'uploaded_by' in doc
        assert doc['uploaded_by'] == test_user_id

    # Verify our test documents are there
    uploaded_original_names = [d['original_filename'] for d in documents]
    assert set(uploaded_original_names) == {"test_0.txt", "test_1.txt", "test_2.txt"}

def test_file_validation(temp_rag_manager):
    """Test file validation."""
    # Test valid file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("Small file")
        temp_path = f.name

    try:
        is_valid, error = temp_rag_manager.is_valid_file(temp_path)
        assert is_valid is True
        assert error == ""
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    # Test invalid extension
    with tempfile.NamedTemporaryFile(mode='w', suffix='.exe', delete=False) as f:
        f.write("Invalid extension")
        temp_path = f.name

    try:
        is_valid, error = temp_rag_manager.is_valid_file(temp_path)
        assert is_valid is False
        assert "Unsupported" in error
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

def test_metadata_persistence(test_user_id):
    """Test metadata is saved and loaded correctly."""
    # Create a completely fresh manager for this test
    import tempfile

    temp_dir = tempfile.mkdtemp()
    test_data_dir = Path(temp_dir) / "test_rag_persistence"

    # Ensure directory exists
    test_data_dir.mkdir(parents=True, exist_ok=True)

    # Create empty metadata file
    metadata_file = test_data_dir / "metadata.json"
    with open(metadata_file, 'w', encoding='utf-8') as f:
        json.dump({}, f)

    # Store original function
    original_get_config = shared.common.get_config

    # Create test config
    def mock_get_config():
        return {
            "rag_manager": {
                "data_directory": str(test_data_dir),
                "allowed_extensions": [".txt"],
                "max_file_size_mb": 10,
                "default_engine": "simple"
            }
        }

    # Temporarily replace get_config
    shared.common.get_config = mock_get_config

    try:
        # Mock the user imports
        with patch('modules.rag_manager.rag_manager.user_manager', mock_user_manager):
            with patch('modules.rag_manager.rag_manager.UserRole', MockUserRole):
                # Create first manager
                manager1 = RAGManager()
                manager1._check_user_permission = Mock(return_value=True)

                # Upload a document
                test_content = "Metadata test"
                with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                    f.write(test_content)
                    temp_path = f.name

                try:
                    filename = manager1.upload_document(
                        temp_path,
                        "meta_test.txt",
                        user_id=test_user_id
                    )
                    assert filename is not None, f"Upload failed for meta_test.txt"

                    # Save metadata
                    manager1._save_metadata()

                    # The metadata should be saved to file
                    metadata_file = manager1.metadata_file
                    assert metadata_file.exists()

                    # Load metadata directly
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        saved_metadata = json.load(f)

                    # Check if our document is in the saved metadata
                    assert filename in saved_metadata
                    assert saved_metadata[filename]['uploaded_by'] == test_user_id

                finally:
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)

    finally:
        # Cleanup
        try:
            if test_data_dir.exists():
                shutil.rmtree(test_data_dir)
            if Path(temp_dir).exists():
                shutil.rmtree(temp_dir)
        except Exception as e:
            print(f"Warning during cleanup: {e}")

        # Restore original function
        shared.common.get_config = original_get_config

def test_rag_engine_functionality(temp_rag_manager, test_user_id):
    """Test RAG engine indexing and searching."""
    # Get the simple engine
    engine = temp_rag_manager.get_engine("simple")
    assert engine is not None

    # Create a test file
    test_content = "This document contains information about artificial intelligence and machine learning algorithms."
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(test_content)
        temp_path = f.name

    try:
        # First upload the document
        filename = temp_rag_manager.upload_document(
            temp_path,
            "ai_document.txt",
            user_id=test_user_id
        )
        assert filename is not None, f"Upload failed for ai_document.txt"

        # Index the document
        result = temp_rag_manager.index_document(
            filename,
            "simple",
            user_id=test_user_id
        )
        assert result is True

        # Search for content
        search_results = temp_rag_manager.search(
            test_user_id,
            "artificial intelligence",
            engine_type="simple"
        )

        assert "simple" in search_results
        assert len(search_results["simple"]) > 0

        # Test get_rag_context
        context = temp_rag_manager.get_rag_context(
            test_user_id,
            "What is artificial intelligence?",
            engine_type="simple"
        )

        assert context != ""
        assert "Relevant context" in context or "From document" in context

    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

def test_engine_discovery(temp_rag_manager):
    """Test that RAG engines are discovered correctly."""
    engines = temp_rag_manager.get_available_engines()

    # Should have at least the simple engine
    assert len(engines) >= 1

    simple_engine_found = False
    for engine_info in engines:
        if engine_info['type'] == 'simple':
            simple_engine_found = True
            assert engine_info['available'] is True
            break

    assert simple_engine_found is True

    # Test get_default_engine
    default_engine = temp_rag_manager.get_default_engine()
    assert default_engine is not None
    assert default_engine.engine_type == "simple"

def test_document_indexing_status(temp_rag_manager, test_user_id):
    """Test document indexing status tracking."""
    # Create a test file
    test_content = "Test indexing status."
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(test_content)
        temp_path = f.name

    try:
        # Upload document
        filename = temp_rag_manager.upload_document(
            temp_path,
            "index_test.txt",
            user_id=test_user_id
        )
        assert filename is not None, f"Upload failed for index_test.txt"

        # Check initial indexing status
        user_docs = temp_rag_manager.get_user_documents(test_user_id)
        test_doc = next((d for d in user_docs if d['filename'] == filename), None)
        assert test_doc is not None
        assert test_doc.get('indexed_in', []) == []

        # Index the document
        temp_rag_manager.index_document(filename, "simple", test_user_id)

        # Check updated indexing status
        user_docs = temp_rag_manager.get_user_documents(test_user_id)
        test_doc = next((d for d in user_docs if d['filename'] == filename), None)
        assert test_doc is not None
        assert "simple" in test_doc.get('indexed_in', [])

    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

def test_clear_all_documents(temp_rag_manager, test_user_id):
    """Test clearing all documents for a user."""
    # Upload multiple documents
    uploaded_filenames = []
    for i in range(3):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(f"Document {i}")
            temp_path = f.name

        try:
            filename = temp_rag_manager.upload_document(
                temp_path,
                f"clear_test_{i}.txt",
                user_id=test_user_id
            )
            assert filename is not None, f"Upload failed for clear_test_{i}.txt"
            uploaded_filenames.append(filename)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    # Get initial count
    initial_docs = temp_rag_manager.get_user_documents(test_user_id)
    initial_count = len([d for d in initial_docs if d['original_filename'].startswith('clear_test_')])
    assert initial_count == 3, f"Expected 3 documents, got {initial_count}"

    # Clear all documents
    result = temp_rag_manager.clear_all_documents(test_user_id)
    assert result is True

    # Check documents are gone
    after_docs = temp_rag_manager.get_user_documents(test_user_id)
    after_count = len([d for d in after_docs if d['original_filename'].startswith('clear_test_')])
    assert after_count == 0, f"Expected 0 documents after clear, got {after_count}"

def test_public_private_documents(temp_rag_manager):
    """Test public vs private document handling."""
    # This would require a more complex setup with multiple users
    # For now, just test the structure
    assert hasattr(temp_rag_manager, '_check_user_permission')
    assert callable(temp_rag_manager._check_user_permission)

# Test SimpleRAGEngine directly
# Test SimpleRAGEngine directly
def test_simple_rag_engine():
    """Test the SimpleRAGEngine class directly."""
    # Create engine instance directly
    from modules.rag_manager.rag_manager import SimpleRAGEngine

    engine = SimpleRAGEngine()

    # CLEAR EXISTING DATA FIRST - IMPORTANT FOR ISOLATION
    engine.indices.clear()
    engine._save_user_index("test_user")  # This will delete the persisted file

    assert engine.engine_type == "simple"
    assert engine.description != ""
    assert engine.is_available() is True

    # Test indexing
    test_content = "Test content for engine testing."
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(test_content)
        temp_path = f.name

    try:
        # Test index_document
        result = engine.index_document("test_user", "engine_test.txt", temp_path)
        assert result is True

        # Test get_indexed_documents
        docs = engine.get_indexed_documents("test_user")
        # ONLY check for the document we just indexed, not previous ones
        assert len(docs) == 1
        assert docs[0]['filename'] == "engine_test.txt"

        # Test search
        results = engine.search("test_user", "test content")
        assert len(results) == 1
        assert results[0]['filename'] == "engine_test.txt"
        assert results[0]['score'] > 0

        # Test delete_document
        result = engine.delete_document("test_user", "engine_test.txt")
        assert result is True

        # Verify deletion
        docs = engine.get_indexed_documents("test_user")
        assert len(docs) == 0

    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    # Test get_stats
    stats = engine.get_stats()
    assert 'engine_type' in stats
    assert stats['engine_type'] == "simple"

def test_backward_compatibility(temp_rag_manager, test_user_id):
    """Test backward compatibility with old metadata format."""
    # Create old format metadata manually
    old_metadata = {
        "old_doc.txt": {
            "original_filename": "old_doc.txt",
            "uploaded_at": "2024-01-01T00:00:00",
            "file_size_mb": 0.1,
            "file_extension": ".txt",
            "file_path": str(temp_rag_manager.data_dir / "old_doc.txt")
            # Missing uploaded_by, is_public, visible_to, indexed_in
        }
    }

    # Save old metadata
    metadata_file = temp_rag_manager.metadata_file
    with open(metadata_file, 'w', encoding='utf-8') as f:
        json.dump(old_metadata, f)

    # Also create the actual file
    old_file_path = temp_rag_manager.data_dir / "old_doc.txt"
    with open(old_file_path, 'w', encoding='utf-8') as f:
        f.write("Old document content")

    # Force reload metadata by recreating manager
    # We need to create a new manager to test loading

    # Store original function
    original_get_config = shared.common.get_config

    # Create test config with same directory
    def mock_get_config():
        return {
            "rag_manager": {
                "data_directory": str(temp_rag_manager.data_dir),
                "allowed_extensions": [".txt", ".md"],
                "max_file_size_mb": 10,
                "default_engine": "simple"
            }
        }

    # Temporarily replace get_config
    shared.common.get_config = mock_get_config

    try:
        # Mock the user imports
        with patch('modules.rag_manager.rag_manager.user_manager', mock_user_manager):
            with patch('modules.rag_manager.rag_manager.UserRole', MockUserRole):
                # Create new manager that will load the old metadata
                new_manager = RAGManager()
                new_manager._check_user_permission = Mock(return_value=True)

                # Check that the document was loaded
                # The old document should be skipped since it doesn't have uploaded_by
                # and we can't determine the user from filename
                user_docs = new_manager.get_user_documents(test_user_id)

                # The old document should not appear in user documents
                # because it doesn't have uploaded_by field
                old_doc_found = any(doc['filename'] == "old_doc.txt" for doc in user_docs)
                assert not old_doc_found, "Old document without uploaded_by should not appear in user documents"

    finally:
        # Restore original function
        shared.common.get_config = original_get_config

        # Clean up old file
        if old_file_path.exists():
            old_file_path.unlink()

# Simple test without fixtures
def test_basic_rag_operations():
    """Test basic RAG operations without complex fixtures."""
    import tempfile

    # Create temporary directory
    temp_dir = tempfile.mkdtemp()
    test_data_dir = Path(temp_dir) / "test_basic"
    test_data_dir.mkdir(parents=True, exist_ok=True)

    # Create empty metadata file
    metadata_file = test_data_dir / "metadata.json"
    with open(metadata_file, 'w', encoding='utf-8') as f:
        json.dump({}, f)

    # Store original function
    original_get_config = shared.common.get_config

    # Create test config
    def mock_get_config():
        return {
            "rag_manager": {
                "data_directory": str(test_data_dir),
                "allowed_extensions": [".txt"],
                "max_file_size_mb": 10,
                "default_engine": "simple"
            }
        }

    # Temporarily replace get_config
    shared.common.get_config = mock_get_config

    try:
        # Mock the user imports
        with patch('modules.rag_manager.rag_manager.user_manager', mock_user_manager):
            with patch('modules.rag_manager.rag_manager.UserRole', MockUserRole):
                # Create manager
                manager = RAGManager()
                manager._check_user_permission = Mock(return_value=True)

                # Create a test file
                test_content = "Basic test document."
                with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                    f.write(test_content)
                    temp_path = f.name

                try:
                    # Test upload
                    filename = manager.upload_document(
                        temp_path,
                        "basic_test.txt",
                        user_id="test_user"
                    )

                    assert filename is not None
                    assert filename in manager.documents

                    # Test get_user_documents
                    docs = manager.get_user_documents("test_user")
                    assert len(docs) == 1
                    assert docs[0]['original_filename'] == "basic_test.txt"

                finally:
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)

    finally:
        # Cleanup
        try:
            if test_data_dir.exists():
                shutil.rmtree(test_data_dir)
            if Path(temp_dir).exists():
                shutil.rmtree(temp_dir)
        except Exception as e:
            print(f"Warning during cleanup: {e}")

        # Restore original function
        shared.common.get_config = original_get_config

if __name__ == "__main__":
    # Run tests manually if needed
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
