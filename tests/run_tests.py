#!/usr/bin/env python3
"""
Test runner for translator tests.
"""
import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Run the tests
from shared.test_translate import run_all_tests

if __name__ == "__main__":
    print("Starting translator test suite...")
    success = run_all_tests()

    if success:
        print("\nAll tests completed successfully!")
        sys.exit(0)
    else:
        print("\nSome tests failed!")
        sys.exit(1)
