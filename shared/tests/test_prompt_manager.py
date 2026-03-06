# file name: tests/test_prompt_manager.py
"""
Test the prompt manager functionality.
"""

import os
import sys
import tempfile
import yaml
from pathlib import Path

from shared.prompt_manager import PromptManager


def test_prompt_manager():
    """Test basic prompt manager functionality."""

    # Create a temporary directory structure
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create module structure
        modules_dir = Path(tmpdir) / "modules"
        modules_dir.mkdir()

        # Create test_module1
        module1_dir = modules_dir / "test_module1"
        module1_dir.mkdir()

        # Create prompts.yaml for test_module1
        module1_prompts = {
            "test_module1": {
                "ui": {
                    "title": "📚 Test Module 1",
                    "stats": {
                        "total_items": "Total Items",
                        "total_size": "Total Size"
                    }
                },
                "context": {
                    "header": "CONTEXT FROM MODULE 1:",
                    "instructions": "Use this context from module 1"
                }
            }
        }

        with open(module1_dir / "prompts.yaml", "w", encoding="utf-8") as f:
            yaml.dump(module1_prompts, f)

        # Create test_module2
        module2_dir = modules_dir / "test_module2"
        module2_dir.mkdir()

        module2_prompts = {
            "test_module2": {
                "greeting": "Hello, {name}!",
                "farewell": "Goodbye!",
                "nested": {
                    "level1": {
                        "level2": "Deeply nested value"
                    }
                }
            }
        }

        with open(module2_dir / "prompts.yaml", "w", encoding="utf-8") as f:
            yaml.dump(module2_prompts, f)

        # Create a shared prompts file
        shared_dir = Path(tmpdir) / "shared"
        shared_dir.mkdir()

        shared_prompts = {
            "shared": {
                "common": {
                    "loading": "Loading...",
                    "error": "An error occurred"
                },
                "system": {
                    "welcome": "Welcome to the system"
                }
            }
        }

        with open(shared_dir / "prompts.yaml", "w", encoding="utf-8") as f:
            yaml.dump(shared_prompts, f)

        # Test prompt manager
        pm = PromptManager()
        pm.load_all_prompts(tmpdir)

        # Debug: print all loaded prompts
        print("\nAll loaded prompts:")
        print(yaml.dump(pm.get_all_prompts(), default_flow_style=False))

        # Test getting prompts from test_module1
        assert pm.get_prompt("test_module1.ui.title") == "📚 Test Module 1"
        assert pm.get_prompt("test_module1.ui.stats.total_items") == "Total Items"
        assert pm.get_prompt("test_module1.context.header") == "CONTEXT FROM MODULE 1:"

        # Test getting prompts from test_module2
        assert pm.get_prompt("test_module2.greeting") == "Hello, {name}!"
        assert pm.get_prompt("test_module2.farewell") == "Goodbye!"
        assert pm.get_prompt("test_module2.nested.level1.level2") == "Deeply nested value"

        # Test getting prompts from shared
        assert pm.get_prompt("shared.common.loading") == "Loading..."
        assert pm.get_prompt("shared.system.welcome") == "Welcome to the system"

        # Test default values
        assert pm.get_prompt("nonexistent.key", "default_value") == "default_value"

        # Test module listing
        modules = pm.list_modules()
        print(f"\nListed modules: {modules}")
        assert "test_module1" in modules
        assert "test_module2" in modules
        assert "shared" in modules

        # Test getting module prompts
        module1_prompts = pm.get_module_prompts("test_module1")
        assert "ui" in module1_prompts
        assert module1_prompts["ui"]["title"] == "📚 Test Module 1"

        module2_prompts = pm.get_module_prompts("test_module2")
        assert "greeting" in module2_prompts
        assert module2_prompts["greeting"] == "Hello, {name}!"

        # Test search functionality
        search_results = pm.search_prompts("Loading")
        print(f"\nSearch results for 'Loading': {search_results}")
        assert len(search_results) > 0

        # Test source files
        assert pm.get_source_file("test_module1") is not None
        assert "prompts.yaml" in pm.get_source_file("test_module1")

        print("\n✅ All prompt manager tests passed!")


if __name__ == "__main__":
    test_prompt_manager()
