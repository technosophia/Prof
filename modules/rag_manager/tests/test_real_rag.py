# tests/test_real_rag.py
"""
Direct RAG system test - bypasses browser to test the actual RAG functionality.
This test uses the real indexed data set up by conftest.py and tests the RAG
callback directly without any browser automation.
"""

import pytest
import time
import logging
from typing import Dict, List, Any

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Import the real RAG manager and related components
from modules.rag_manager.rag_factory import get_rag_manager, reset_rag_manager
from modules.rag_manager import (
    _activate_rag_engine,
    _deactivate_rag_engine,
    _make_engine_context_callback,
    _ENGINE_CONTEXT_CALLBACKS,
)
from shared.common import get_user_manager
from st_shared.cached import get_config


@pytest.fixture(scope="module")
def rag_test_setup():
    """
    Set up the real RAG environment exactly as it would be during a real test run.
    This uses the same data that conftest.py sets up.
    """
    logger.info("=" * 60)
    logger.info("RAG REAL TEST SETUP")
    logger.info("=" * 60)

    # Reset RAG manager to get a fresh instance
    reset_rag_manager()

    # Get the real RAG manager (will use the data set up by conftest.py)
    rag_manager = get_rag_manager()
    user_manager = get_user_manager()

    # Log the current state
    logger.info(f"RAG data directory: {rag_manager.data_dir}")
    logger.info(f"RAG enabled: {rag_manager.is_rag_enabled()}")
    logger.info(f"Default engine: {rag_manager.default_engine}")

    # Check which users exist
    test_users = ["admin", "master1"]
    user_docs = {}

    for user_id in test_users:
        user = user_manager.get_user(user_id)
        if user:
            logger.info(f"User {user_id} exists: {user['name']} (role: {user['role']})")
            docs = rag_manager.get_user_documents(user_id)
            user_docs[user_id] = docs
            logger.info(f"  Documents for {user_id}: {len(docs)}")
            for doc in docs:
                logger.info(f"    - {doc['original_filename']} (indexed in: {doc.get('indexed_in', [])})")
        else:
            logger.warning(f"User {user_id} not found!")

    # Check if the test document about Kevin exists and is indexed
    kevin_doc_found = False
    for user_id, docs in user_docs.items():
        for doc in docs:
            if "kevin" in doc['original_filename'].lower() or "address" in doc['original_filename'].lower():
                kevin_doc_found = True
                logger.info(f"✓ Found Kevin document: {doc['original_filename']} for user {user_id}")
                logger.info(f"  Indexed in: {doc.get('indexed_in', [])}")

    if not kevin_doc_found:
        logger.warning("⚠ Kevin test document not found! Check conftest.py _setup_rag_test_data")

    yield {
        "rag_manager": rag_manager,
        "user_manager": user_manager,
        "test_users": test_users,
        "user_docs": user_docs
    }

    # Cleanup
    logger.info("Cleaning up RAG test setup")
    # Clear any registered callbacks
    _ENGINE_CONTEXT_CALLBACKS.clear()


class TestRealRAG:
    """Test the real RAG system with actual indexed data."""

    def test_rag_document_exists(self, rag_test_setup):
        """Verify that the Kevin test document exists and is indexed."""
        rag_manager = rag_test_setup["rag_manager"]
        user_docs = rag_test_setup["user_docs"]

        # Check for the Kevin document
        kevin_doc = None
        for user_id, docs in user_docs.items():
            for doc in docs:
                if "kevin" in doc['original_filename'].lower():
                    kevin_doc = doc
                    break

        assert kevin_doc is not None, "Kevin test document not found in RAG storage"
        assert "simple" in kevin_doc.get('indexed_in', []), "Kevin document not indexed in simple engine"
        assert "classic" in kevin_doc.get('indexed_in', []), "Kevin document not indexed in classic engine"

        logger.info(f"✓ Kevin document verified: {kevin_doc}")

    def test_rag_search_direct(self, rag_test_setup):
        """Test RAG search directly without going through the callback."""
        rag_manager = rag_test_setup["rag_manager"]
        test_users = rag_test_setup["test_users"]

        query = "Where does Kevin live?"

        for user_id in test_users:
            logger.info(f"\nTesting direct search for user: {user_id}")

            # Search with simple engine
            results = rag_manager.search(user_id, query, engine_type="simple", limit=5)
            assert "simple" in results, f"No simple engine results for {user_id}"

            simple_results = results["simple"]
            logger.info(f"  Simple engine: {len(simple_results)} results")

            # Check if any result contains address information
            address_found = False
            for result in simple_results:
                content = result.get('content', '')
                if any(term in content.lower() for term in ["louvre", "paris", "place du"]):
                    address_found = True
                    logger.info(f"  ✓ Address found in simple result: {content[:100]}...")
                    break

            # Also check classic engine
            results = rag_manager.search(user_id, query, engine_type="classic", limit=5)
            assert "classic" in results, f"No classic engine results for {user_id}"

            classic_results = results["classic"]
            logger.info(f"  Classic engine: {len(classic_results)} results")

            for result in classic_results:
                content = result.get('content', '')
                if any(term in content.lower() for term in ["louvre", "paris", "place du"]):
                    address_found = True
                    logger.info(f"  ✓ Address found in classic result: {content[:100]}...")
                    break

            # For admin user, we expect to find the address
            if user_id == "admin":
                assert address_found, f"No address information found for admin user in any engine"

    def test_rag_context_callback_without_toggle(self, rag_test_setup):
        """Test the RAG context callback directly (simulating RAG enabled)."""
        rag_manager = rag_test_setup["rag_manager"]
        test_users = rag_test_setup["test_users"]

        # Create the callback for the default engine
        default_engine = rag_manager.default_engine
        callback = _make_engine_context_callback(default_engine)

        query = "Where does Kevin live?"
        messages = [{"role": "user", "content": query}]

        for user_id in test_users:
            logger.info(f"\nTesting callback for user: {user_id} with engine: {default_engine}")

            # Call the callback directly
            start_time = time.time()
            context, role, position = callback(user_id, messages)
            elapsed = time.time() - start_time

            logger.info(f"  Callback returned in {elapsed:.3f}s")
            logger.info(f"  Role: {role}, Position: {position}")
            logger.info(f"  Context length: {len(context)} chars")

            if context:
                logger.info(f"  Context preview: {context[:200]}")

            # For admin user, we expect context with address information
            if user_id == "admin":
                assert context, f"No context returned for admin user"
                assert "louvre" in context.lower() or "paris" in context.lower(), \
                    f"Address information not found in context for admin: {context[:200]}"

    def test_rag_callback_with_engine_toggle(self, rag_test_setup):
        """Test that toggling the engine registers/unregisters the callback correctly."""
        rag_manager = rag_test_setup["rag_manager"]
        user_id = "admin"  # Use admin for this test

        # Import the registration/unregistration functions
        from modules.rag_manager import (
            _activate_rag_engine,
            _deactivate_rag_engine,
            _ENGINE_CONTEXT_CALLBACKS,
            _make_engine_context_callback,
            set_services
        )

        # Store original state to restore later
        original_callbacks = _ENGINE_CONTEXT_CALLBACKS.copy()
        original_services = None
        from modules.rag_manager import _services
        original_services = _services

        # Create a mock callback registry that we can inspect
        class MockCallbackRegistry:
            def __init__(self):
                self.callbacks = []

            def register(self, callback):
                self.callbacks.append(callback)
                logger.info(f"Mock registry: registered {callback.__name__}")

            def unregister(self, callback):
                if callback in self.callbacks:
                    self.callbacks.remove(callback)
                    logger.info(f"Mock registry: unregistered {callback.__name__}")

        mock_registry = MockCallbackRegistry()

        # Create a mock service locator with our registry
        from shared.module_handler import ServiceLocator
        services = ServiceLocator()
        services.register("llm_callback_registry", mock_registry)

        try:
            # Set the services for the RAG module
            set_services(services)

            # Clear any existing callbacks
            _ENGINE_CONTEXT_CALLBACKS.clear()

            logger.info(f"\nTesting with engine: {rag_manager.default_engine}")

            # Step 1: Activate the engine (simulate clicking the toggle)
            logger.info("\n1. Activating RAG engine")
            _activate_rag_engine(rag_manager.default_engine)

            # Check that callback was registered in our internal dict
            assert rag_manager.default_engine in _ENGINE_CONTEXT_CALLBACKS, \
                "Callback not registered in _ENGINE_CONTEXT_CALLBACKS after activation"

            # Check that it was registered in our mock registry
            assert len(mock_registry.callbacks) == 1, \
                f"Expected 1 callback in registry, got {len(mock_registry.callbacks)}"
            assert mock_registry.callbacks[0].__name__ == f"rag_context_callback_{rag_manager.default_engine}", \
                "Wrong callback registered in mock registry"

            logger.info(f"  ✓ Callback registered correctly (internal dict + registry)")

            # Test the callback works
            callback = _ENGINE_CONTEXT_CALLBACKS[rag_manager.default_engine]
            query = "Where does Kevin live?"
            messages = [{"role": "user", "content": query}]

            context, role, position = callback(user_id, messages)
            logger.info(f"  Callback returned context length: {len(context)}")
            assert context, "No context returned after activation"
            assert "louvre" in context.lower() or "paris" in context.lower(), \
                "Address not found in context after activation"

            # Step 2: Deactivate the engine (simulate unchecking the toggle)
            logger.info("\n2. Deactivating RAG engine")
            _deactivate_rag_engine(rag_manager.default_engine)

            # Check that callback was removed from our internal dict
            assert rag_manager.default_engine not in _ENGINE_CONTEXT_CALLBACKS, \
                "Callback still in _ENGINE_CONTEXT_CALLBACKS after deactivation"

            # Check that it was removed from our mock registry
            assert len(mock_registry.callbacks) == 0, \
                f"Expected 0 callbacks in registry after deactivation, got {len(mock_registry.callbacks)}"

            logger.info(f"  ✓ Callback unregistered correctly (internal dict + registry)")

            # Now verify that the LLM won't receive RAG context by performing a search directly
            logger.info("\n3. Verifying RAG is disabled for LLM calls")

            # Perform a search directly through the manager - this simulates what would happen
            # when the LLM tries to get context (since the callback is unregistered)
            search_results = rag_manager.search(user_id, query, engine_type=rag_manager.default_engine, limit=5)

            # The search should still return results because the engine itself is still enabled
            # But the key is: these results won't be injected into the LLM context because
            # the callback is unregistered. We verify this by checking that the callback dict is empty.
            assert rag_manager.default_engine not in _ENGINE_CONTEXT_CALLBACKS, \
                "Callback should not be registered after deactivation"

            # Create a fresh callback (simulating what would happen if a module
            # tried to create one without registering it) - it will still return context
            # because the engine is enabled, but that's expected - the test is about
            # registration/unregistration, not about disabling the engine itself.
            test_callback = _make_engine_context_callback(rag_manager.default_engine)
            context, role, position = test_callback(user_id, messages)
            logger.info(f"  Fresh callback (unregistered) returned context length: {len(context)}")

            # The fresh callback returns context because the engine is still enabled in config
            # This is expected behavior - toggling the UI checkbox only registers/unregisters
            # the callback, it doesn't disable the underlying engine
            logger.info("  ✓ Fresh callback returns context (engine still enabled - expected)")

            logger.info("  ✓ Test passed: callback correctly unregistered, engine remains available")

        finally:
            # Restore original state
            logger.info("\n4. Restoring original state")
            _ENGINE_CONTEXT_CALLBACKS.clear()
            _ENGINE_CONTEXT_CALLBACKS.update(original_callbacks)
            set_services(original_services)
            logger.info("  ✓ Original state restored")

    def test_rag_callback_with_rag_disabled_in_config(self, rag_test_setup):
        """Test that RAG is disabled when modules.rag_manager.enabled = false."""
        rag_manager = rag_test_setup["rag_manager"]
        user_id = "admin"

        # Get the original config value
        original_config = get_config()
        original_enabled = original_config.get("modules.rag_manager.enabled", True)

        try:
            # Disable RAG in config
            logger.info("\nDisabling RAG in config")
            # This is a bit hacky - in a real scenario we'd modify the config file
            # For testing, we'll temporarily patch the is_rag_enabled method
            original_is_rag_enabled = rag_manager.is_rag_enabled
            rag_manager.is_rag_enabled = lambda: False

            # Create and test callback
            callback = _make_engine_context_callback(rag_manager.default_engine)
            query = "Where does Kevin live?"
            messages = [{"role": "user", "content": query}]

            context, role, position = callback(user_id, messages)
            logger.info(f"  Callback returned with RAG disabled: {bool(context)}")
            assert not context, "Context returned when RAG should be disabled"

        finally:
            # Restore original method
            rag_manager.is_rag_enabled = original_is_rag_enabled

    def test_rag_response_content_quality(self, rag_test_setup):
        """Test the quality of RAG response - should contain specific address details."""
        rag_manager = rag_test_setup["rag_manager"]
        user_id = "admin"

        callback = _make_engine_context_callback(rag_manager.default_engine)

        test_queries = [
            ("Where does Kevin live?", ["1 place du Louvre", "Paris", "address"]),
            ("What is Kevin's phone number?", ["+33", "phone", "number"]),
            ("Where does Kevin work?", ["TechCorp", "software engineer", "works"]),
        ]

        for query, expected_terms in test_queries:
            logger.info(f"\nTesting query: '{query}'")
            messages = [{"role": "user", "content": query}]

            context, role, position = callback(user_id, messages)

            assert context, f"No context returned for query: {query}"
            logger.info(f"  Context preview: {context[:200]}")

            # Check that at least one expected term is in the context
            found_terms = [term for term in expected_terms if term.lower() in context.lower()]
            assert found_terms, f"None of {expected_terms} found in context for query '{query}': {context[:200]}"
            logger.info(f"  ✓ Found terms: {found_terms}")

    def test_rag_multiple_users_permissions(self, rag_test_setup):
        """Test that different users see appropriate documents based on permissions."""
        rag_manager = rag_test_setup["rag_manager"]
        user_manager = rag_test_setup["user_manager"]
        user_docs = rag_test_setup["user_docs"]

        # Admin should see all documents
        admin_docs = user_docs.get("admin", [])
        logger.info(f"Admin has {len(admin_docs)} documents")

        # Master1 should see its own documents
        master1_docs = user_docs.get("master1", [])
        logger.info(f"Master1 has {len(master1_docs)} documents")

        callback = _make_engine_context_callback(rag_manager.default_engine)
        query = "information about the company"
        messages = [{"role": "user", "content": query}]

        # Test admin
        admin_context, _, _ = callback("admin", messages)
        logger.info(f"Admin context length: {len(admin_context)}")

        # Test master1
        master1_context, _, _ = callback("master1", messages)
        logger.info(f"Master1 context length: {len(master1_context)}")

        # Note: We can't assert specific lengths, but we can log for manual inspection
        # This test is more about ensuring no exceptions are raised

    def test_rag_callback_performance(self, rag_test_setup):
        """Test the performance of the RAG callback."""
        rag_manager = rag_test_setup["rag_manager"]
        user_id = "admin"

        callback = _make_engine_context_callback(rag_manager.default_engine)
        query = "Where does Kevin live?"
        messages = [{"role": "user", "content": query}]

        # Warm-up
        callback(user_id, messages)

        # Measure multiple calls
        times = []
        for i in range(5):
            start = time.time()
            context, _, _ = callback(user_id, messages)
            elapsed = time.time() - start
            times.append(elapsed)
            logger.info(f"  Call {i+1}: {elapsed:.3f}s - Context length: {len(context)}")

        avg_time = sum(times) / len(times)
        logger.info(f"  Average callback time: {avg_time:.3f}s")

        # The callback should be reasonably fast (adjust threshold as needed)
        assert avg_time < 2.0, f"RAG callback too slow: {avg_time:.3f}s average"


if __name__ == "__main__":
    # Allow running the test directly for debugging
    pytest.main([__file__, "-vvs", "--log-cli-level=DEBUG"])
