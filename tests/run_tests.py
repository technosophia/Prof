#!/usr/bin/env python3
"""
Test runner for all tests using pytest.
"""
import sys
import os
import subprocess

def discover_test_files():
    """Discover all test files in the project."""
    test_files = []
    current_dir = os.path.dirname(os.path.abspath(__file__))

    # Look for test files
    for root, dirs, files in os.walk(current_dir):
        for file in files:
            if file.startswith('test_') and file.endswith('.py'):
                test_files.append(os.path.join(root, file))

    return test_files

def run_pytest_on_all():
    """Run pytest on all discovered test files."""
    print("Starting complete test suite with pytest...")
    print("="*60)

    # Get current directory
    current_dir = os.path.dirname(os.path.abspath(__file__))

    # Run pytest on the entire directory
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", current_dir, "-v"],
            check=False,
            capture_output=True,
            text=True
        )

        # Print output
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print("Stderr:", result.stderr)

        print("="*60)

        if result.returncode == 0:
            print("✅ All tests passed!")
        else:
            print("❌ Some tests failed!")

        return result.returncode == 0
    except Exception as e:
        print(f"Error running tests: {e}")
        return False

def run_specific_test_suites():
    """Run specific test suites in order."""
    print("Starting complete test suite...")
    print("="*60)

    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)

    test_suites = [
        (os.path.join(project_root, "shared", "tests", "test_translate.py"), "Translator Tests"),
        (os.path.join(project_root, "shared", "tests", "test_llm.py"), "LLM Tests"),
        (os.path.join(current_dir, "step_defs", "test_button_steps.py"), "BDD Button Tests"),
    ]

    all_passed = True

    for test_file, suite_name in test_suites:
        if not os.path.exists(test_file):
            print(f"\n⚠️  {suite_name}: File not found at {test_file}")
            continue

        print(f"\n" + "="*60)
        print(f"Running {suite_name}...")
        print("="*60)

        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", test_file, "-v"],
                check=False,
                capture_output=True,
                text=True
            )

            # Print output
            if result.stdout:
                print(result.stdout)

            if result.returncode != 0:
                all_passed = False
                if result.stderr:
                    print("Errors:", result.stderr)

        except Exception as e:
            print(f"Error running {suite_name}: {e}")
            all_passed = False

    print("="*60)
    return all_passed

if __name__ == "__main__":
    # Choose which method to use:
    # Method 1: Run all tests with pytest (recommended)
    # success = run_pytest_on_all()

    # Method 2: Run specific test suites
    success = run_specific_test_suites()

    if success:
        print("\n✅ All tests completed successfully!")
        sys.exit(0)
    else:
        print("\n❌ Some tests failed!")
        sys.exit(1)
