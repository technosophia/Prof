"""
Tests for RAG Manager module.
"""

import pytest
import tempfile
import os
import sys
from pathlib import Path
import shutil

# Fix import path to find the RAGManager
current_dir = Path(__file__).parent
module_dir = current_dir.parent
project_root = module_dir.parent.parent

# Add project root to sys.path to allow importing modules
sys.path.insert(0, str(project_root))

# Now import the RAGManager
from modules.rag_manager import RAGManager

@pytest.fixture
def temp_rag_manager():
    """Create a temporary RAG manager for testing with isolated environment."""
    import tempfile
    import shared.config

    # Create a temporary directory for this specific test
    temp_dir = tempfile.mkdtemp()
    test_data_dir = Path(temp_dir) / "test_rag"

    # Store original function
    original_get_config = shared.config.get_config

    # Create test config
    def mock_get_config():
        return {
            "rag_manager": {
                "data_directory": str(test_data_dir),
                "allowed_extensions": [".txt", ".md"],
                "max_file_size_mb": 1
            }
        }

    # Temporarily replace get_config
    shared.config.get_config = mock_get_config

    # Create manager
    manager = RAGManager()

    yield manager

    # Cleanup - ONLY clean the files we know we created in tests
    try:
        # Get list of all files before cleanup
        all_files = list(manager.documents.keys())

        # Only delete files that were created by our tests
        # (filenames starting with timestamp or containing specific test patterns)
        for filename in all_files:
            if any(pattern in filename.lower() for pattern in ['test', 'delete_test', 'meta_test']):
                manager.delete_document(filename)

        # Remove the test data directory (it should be empty now)
        if test_data_dir.exists():
            # Try to remove files first
            for file_path in test_data_dir.glob("*"):
                if file_path.is_file():
                    try:
                        file_path.unlink()
                    except:
                        pass
            # Then remove directory
            try:
                test_data_dir.rmdir()
            except:
                pass

        # Remove the temp directory
        if Path(temp_dir).exists():
            try:
                shutil.rmtree(temp_dir)
            except:
                pass
    except Exception as e:
        print(f"Warning during cleanup: {e}")

    # Restore original function
    shared.config.get_config = original_get_config

@pytest.fixture
def clean_rag_manager():
    """Create a clean RAG manager that doesn't persist between tests."""
    # This fixture is for tests that need an empty manager
    return temp_rag_manager()

def test_init_data_directory(temp_rag_manager):
    """Test data directory initialization."""
    assert temp_rag_manager.data_dir.exists()
    assert temp_rag_manager.data_dir.is_dir()

def test_upload_document(temp_rag_manager):
    """Test document upload."""
    # Create a test file
    test_content = "This is a test document."
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(test_content)
        temp_path = f.name

    try:
        # Upload the file
        filename = temp_rag_manager.upload_document(temp_path, "test.txt")

        assert filename is not None
        assert filename in temp_rag_manager.documents

        # Check if file exists
        expected_path = temp_rag_manager.data_dir / filename
        assert expected_path.exists()

    finally:
        # Cleanup
        os.unlink(temp_path)

def test_delete_document(temp_rag_manager):
    """Test document deletion."""
    # First upload a document
    test_content = "Document to delete."
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(test_content)
        temp_path = f.name

    try:
        filename = temp_rag_manager.upload_document(temp_path, "delete_test.txt")
        assert filename is not None

        # Delete the document
        result = temp_rag_manager.delete_document(filename)
        assert result is True

        # Check it's gone
        assert filename not in temp_rag_manager.documents

    finally:
        os.unlink(temp_path)

def test_get_document_list(temp_rag_manager):
    """Test getting document list."""
    # Clear any existing test files first by getting current count
    initial_count = len(temp_rag_manager.documents)

    # Upload a few test documents
    for i in range(3):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(f"Test document {i}")
            temp_path = f.name

        try:
            temp_rag_manager.upload_document(temp_path, f"test_{i}.txt")
        finally:
            os.unlink(temp_path)

    # Get list
    documents = temp_rag_manager.get_document_list()

    # Should have initial_count + 3 documents
    assert len(documents) == initial_count + 3
    assert all('filename' in doc for doc in documents)
    assert all('original_filename' in doc for doc in documents)

    # Verify we have the right documents among the last 3 uploaded
    recent_docs = documents[:3]  # Newest first
    filenames = [doc['original_filename'] for doc in recent_docs]

    # Check that our test files are in the list (order might vary)
    expected_filenames = {"test_0.txt", "test_1.txt", "test_2.txt"}
    actual_filenames = set(filenames)

    # We should find all our test files among the uploaded ones
    for expected in expected_filenames:
        assert any(expected in doc['original_filename'] for doc in recent_docs)

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
        os.unlink(temp_path)

def test_metadata_persistence():
    """Test metadata is saved and loaded correctly."""
    # Create a completely fresh manager for this test
    import tempfile
    import shared.config

    temp_dir = tempfile.mkdtemp()
    test_data_dir = Path(temp_dir) / "test_rag_persistence"

    # Store original function
    original_get_config = shared.config.get_config

    # Create test config
    def mock_get_config():
        return {
            "rag_manager": {
                "data_directory": str(test_data_dir),
                "allowed_extensions": [".txt"],
                "max_file_size_mb": 10
            }
        }

    # Temporarily replace get_config
    shared.config.get_config = mock_get_config

    try:
        # Create first manager
        manager1 = RAGManager()

        # Upload a document
        test_content = "Metadata test"
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(test_content)
            temp_path = f.name

        try:
            filename = manager1.upload_document(temp_path, "meta_test.txt")
            assert filename is not None

            # Save metadata
            manager1._save_metadata()

            # The metadata should be saved to file
            metadata_file = manager1.metadata_file
            assert metadata_file.exists()

            # Load metadata directly
            import json
            with open(metadata_file, 'r') as f:
                saved_metadata = json.load(f)

            # Check if our document is in the saved metadata
            assert filename in saved_metadata

        finally:
            os.unlink(temp_path)

    finally:
        # Cleanup
        try:
            # Only delete the specific test file we created
            test_files = [k for k in manager1.documents.keys() if 'meta_test' in k]
            for filename in test_files:
                manager1.delete_document(filename)

            # Clean up directory
            if test_data_dir.exists():
                for file_path in test_data_dir.glob("*"):
                    if file_path.is_file():
                        try:
                            file_path.unlink()
                        except:
                            pass
                try:
                    test_data_dir.rmdir()
                except:
                    pass

            if Path(temp_dir).exists():
                try:
                    shutil.rmtree(temp_dir)
                except:
                    pass
        except Exception as e:
            print(f"Warning during cleanup: {e}")

        # Restore original function
        shared.config.get_config = original_get_config
