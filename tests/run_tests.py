#!/usr/bin/env python3
"""
Test runner for all tests using pytest.
"""
import sys
import os
import subprocess
from pathlib import Path

def discover_test_files_recursive(start_path=None, exclude_dirs=None):
    """
    Recursively discover all test files in the project.

    Args:
        start_path: Starting directory for discovery (default: current directory)
        exclude_dirs: List of directory names to exclude from search

    Returns:
        List of absolute paths to test files
    """
    if start_path is None:
        start_path = os.path.dirname(os.path.abspath(__file__))

    if exclude_dirs is None:
        exclude_dirs = ['.git', '__pycache__', '.pytest_cache', 'venv', '.venv', 'env', 'node_modules']

    test_files = []

    def should_exclude_dir(dir_path):
        """Check if a directory should be excluded from search."""
        dir_name = os.path.basename(dir_path)
        return dir_name in exclude_dirs

    def scan_directory(current_dir):
        """Recursively scan a directory for test files."""
        try:
            with os.scandir(current_dir) as entries:
                for entry in entries:
                    if entry.is_dir():
                        # Skip excluded directories
                        if not should_exclude_dir(entry.path):
                            scan_directory(entry.path)
                    elif entry.is_file():
                        # Check if it's a test file
                        if entry.name.startswith('test_') and entry.name.endswith('.py'):
                            test_files.append(os.path.abspath(entry.path))
        except (PermissionError, OSError) as e:
            print(f"Warning: Could not scan directory {current_dir}: {e}")

    # Start recursive scanning
    print(f"🔍 Scanning for test files starting from: {start_path}")
    scan_directory(start_path)

    # Sort test files for consistent output
    test_files.sort()

    return test_files

def discover_test_files_by_pattern(start_path=None, pattern="test_*.py"):
    """
    Discover test files using glob pattern matching.

    Args:
        start_path: Starting directory for discovery
        pattern: Glob pattern to match test files

    Returns:
        List of absolute paths to test files
    """
    if start_path is None:
        start_path = Path(os.path.dirname(os.path.abspath(__file__)))
    else:
        start_path = Path(start_path)

    # Define directories to exclude
    exclude_patterns = [
        "**/.git/**",
        "**/__pycache__/**",
        "**/.pytest_cache/**",
        "**/venv/**",
        "**/.venv/**",
        "**/env/**",
        "**/node_modules/**"
    ]

    test_files = []

    for test_file in start_path.rglob(pattern):
        # Check if file is in excluded directory
        exclude = False
        for exclude_pattern in exclude_patterns:
            if test_file.match(exclude_pattern):
                exclude = True
                break

        if not exclude:
            test_files.append(str(test_file.absolute()))

    # Sort test files for consistent output
    test_files.sort()

    return test_files

def print_test_discovery_summary(test_files):
    """Print a summary of discovered test files."""
    if not test_files:
        print("❌ No test files found!")
        return

    print(f"\n📊 Found {len(test_files)} test file(s):")
    print("-" * 60)

    # Group test files by directory
    test_files_by_dir = {}
    for test_file in test_files:
        dir_name = os.path.dirname(test_file)
        if dir_name not in test_files_by_dir:
            test_files_by_dir[dir_name] = []
        test_files_by_dir[dir_name].append(os.path.basename(test_file))

    # Print grouped results
    for dir_name in sorted(test_files_by_dir.keys()):
        print(f"\n📁 {os.path.relpath(dir_name)}:")
        for test_file in sorted(test_files_by_dir[dir_name]):
            print(f"  └─ {test_file}")

    print("-" * 60)

def run_pytest_on_all(test_files=None, verbose=True):
    """
    Run pytest on all discovered test files or specific files.

    Args:
        test_files: List of test files to run (None = run all tests)
        verbose: Whether to show verbose output

    Returns:
        bool: True if all tests passed
    """
    print("\n🚀 Starting complete test suite with pytest...")
    print("=" * 80)

    current_dir = os.path.dirname(os.path.abspath(__file__))

    # Build pytest command
    cmd = [sys.executable, "-m", "pytest"]

    if verbose:
        cmd.append("-v")

    # Add coverage if coverage module is available
    try:
        import coverage
        cmd.extend(["--cov=.", "--cov-report=term-missing"])
    except ImportError:
        pass

    # If specific test files are provided, run only those
    if test_files:
        print(f"Running {len(test_files)} specific test file(s)...")
        cmd.extend(test_files)
    else:
        # Run all tests in the current directory
        print("Running all tests in the project...")
        cmd.append(current_dir)

    try:
        # Run pytest
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            encoding='utf-8'
        )

        # Print output
        if result.stdout:
            print(result.stdout)

        if result.stderr:
            print("\n⚠️  Stderr output:")
            print(result.stderr)

        print("=" * 80)

        if result.returncode == 0:
            print("✅ All tests passed!")
            return True
        else:
            print("❌ Some tests failed!")
            return False

    except subprocess.CalledProcessError as e:
        print(f"❌ Pytest execution failed with return code {e.returncode}")
        print(f"Stdout: {e.stdout}")
        print(f"Stderr: {e.stderr}")
        return False
    except Exception as e:
        print(f"❌ Error running tests: {e}")
        return False

def run_tests_by_category():
    """
    Run tests by category (shared, modules, etc.) for better organization.

    Returns:
        bool: True if all tests passed
    """
    print("\n📊 Running tests by category...")
    print("=" * 80)

    current_dir = os.path.dirname(os.path.abspath(__file__))
    all_passed = True

    # Define test categories and their directories
    test_categories = [
        ("Shared Modules", os.path.join(current_dir, "shared")),
        ("Main Application", os.path.join(current_dir, ".")),
        ("All Modules", os.path.join(current_dir, "modules"))
    ]

    for category_name, category_dir in test_categories:
        if not os.path.exists(category_dir):
            print(f"\n⚠️  Skipping {category_name}: Directory not found at {category_dir}")
            continue

        print(f"\n📦 {category_name}")
        print("-" * 40)

        # Discover test files in this category
        if category_name == "All Modules":
            # For modules, we need to scan recursively
            test_files = discover_test_files_by_pattern(category_dir)
        else:
            test_files = discover_test_files_by_pattern(category_dir)

        if not test_files:
            print(f"  No test files found in {category_dir}")
            continue

        # Print which test files we found
        print(f"  Found {len(test_files)} test file(s):")
        for test_file in test_files[:5]:  # Show first 5
            print(f"    • {os.path.basename(test_file)}")
        if len(test_files) > 5:
            print(f"    • ... and {len(test_files) - 5} more")

        # Run tests for this category
        cmd = [sys.executable, "-m", "pytest", "-v"]
        cmd.extend(test_files)

        try:
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True
            )

            # Print summary
            if result.returncode == 0:
                print(f"  ✅ {category_name} tests passed")
            else:
                print(f"  ❌ {category_name} tests failed")
                all_passed = False

            # Show brief output
            if result.stdout:
                # Extract summary lines
                lines = result.stdout.strip().split('\n')
                summary_lines = [line for line in lines if 'passed' in line or 'failed' in line or 'ERROR' in line]
                if summary_lines:
                    print(f"  Summary: {' | '.join(summary_lines[-3:])}")

        except Exception as e:
            print(f"  ❌ Error running {category_name} tests: {e}")
            all_passed = False

    print("=" * 80)
    return all_passed

def main():
    """Main function to run tests."""
    print("🧪 Test Runner for Modular Application")
    print("=" * 80)

    # Parse command line arguments
    import argparse
    parser = argparse.ArgumentParser(description="Run tests for the modular application")
    parser.add_argument("--discover", action="store_true", help="Only discover test files without running them")
    parser.add_argument("--category", action="store_true", help="Run tests by category")
    parser.add_argument("--module", help="Run tests for a specific module only")
    parser.add_argument("--quick", action="store_true", help="Run tests without verbose output")
    parser.add_argument("--coverage", action="store_true", help="Generate coverage report")
    parser.add_argument("test_files", nargs="*", help="Specific test files to run")

    args = parser.parse_args()

    # Discover test files
    test_files = discover_test_files_by_pattern()

    if args.discover:
        # Just discover and list test files
        print_test_discovery_summary(test_files)
        return 0

    if args.module:
        # Run tests for a specific module
        module_test_files = []
        module_pattern = f"**/modules/{args.module}/**/test_*.py"
        current_dir = os.path.dirname(os.path.abspath(__file__))
        module_test_files = discover_test_files_by_pattern(current_dir, module_pattern)

        if not module_test_files:
            print(f"❌ No test files found for module: {args.module}")
            print(f"   Searched for pattern: {module_pattern}")
            return 1

        print(f"🧪 Running tests for module: {args.module}")
        success = run_pytest_on_all(module_test_files, verbose=not args.quick)

    elif args.test_files:
        # Run specific test files provided as arguments
        # Convert relative paths to absolute
        absolute_test_files = []
        for test_file in args.test_files:
            if os.path.isabs(test_file):
                absolute_test_files.append(test_file)
            else:
                absolute_test_files.append(os.path.abspath(test_file))

        # Verify files exist
        missing_files = []
        for test_file in absolute_test_files:
            if not os.path.exists(test_file):
                missing_files.append(test_file)

        if missing_files:
            print("❌ The following test files were not found:")
            for missing in missing_files:
                print(f"   {missing}")
            return 1

        success = run_pytest_on_all(absolute_test_files, verbose=not args.quick)

    elif args.category:
        # Run tests by category
        success = run_tests_by_category()

    else:
        # Run all tests (default behavior)
        print_test_discovery_summary(test_files)
        success = run_pytest_on_all(verbose=not args.quick)

    # Exit with appropriate code
    if success:
        print("\n🎉 All tests completed successfully!")
        return 0
    else:
        print("\n💥 Some tests failed!")
        return 1

if __name__ == "__main__":
    sys.exit(main())
