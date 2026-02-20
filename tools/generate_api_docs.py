# /tools/generate_api_docs.py
"""
API Documentation Generator

Scans Python files for [api] tags in docstrings and generates
one API_<MODULE>.md file per Python file that contains [api] tags.

Usage:
    python tools/generate_api_docs.py
    python tools/generate_api_docs.py --path shared/  # specific directory
    python tools/generate_api_docs.py --dry-run       # preview without writing

Rules:
    - A Python file is included if its module-level docstring contains [api]
    - A class/function/method is included if its docstring contains [api]
    - Output file is named API_<MODULE_PATH>.md (e.g. API_SHARED_COMMON.md)
    - Output files are written next to the source file by default
    - Signatures are always included
"""

import ast
import sys
import os
import argparse
from pathlib import Path
from typing import Optional


def get_docstring(node: ast.AST) -> Optional[str]:
    """Extract docstring from an AST node."""
    if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        if (node.body and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)):
            return node.body[0].value.value
    return None


def has_api_tag(docstring: Optional[str]) -> bool:
    """Check if a docstring contains the [api] tag."""
    return docstring is not None and "[api]" in docstring


def clean_docstring(docstring: str) -> str:
    """Remove [api] tag and strip the docstring for display."""
    cleaned = docstring.replace("[api]", "").strip()
    # Normalize indentation
    lines = cleaned.splitlines()
    if not lines:
        return ""
    # Remove common leading whitespace
    non_empty = [l for l in lines if l.strip()]
    if not non_empty:
        return ""
    min_indent = min(len(l) - len(l.lstrip()) for l in non_empty)
    lines = [l[min_indent:] if len(l) >= min_indent else l for l in lines]
    return "\n".join(lines).strip()


def get_signature(node: ast.AST, source_lines: list[str]) -> str:
    """Extract the function/class signature from source lines."""
    if isinstance(node, ast.ClassDef):
        # Find class definition line(s)
        start = node.lineno - 1
        # Get the class line up to the colon
        line = source_lines[start].rstrip()
        return line.rstrip(":")  .strip() + ":"

    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        start = node.lineno - 1
        end = node.body[0].lineno - 1  # Stop before the body

        # Collect the signature lines
        sig_lines = source_lines[start:end]
        # Remove trailing docstring line if needed
        sig = " ".join(l.strip() for l in sig_lines)
        # Clean up
        sig = sig.rstrip(":").strip() + ":"
        return sig

    return ""


def format_section(title: str, content: str, level: int = 3) -> str:
    """Format a markdown section."""
    hashes = "#" * level
    return f"{hashes} {title}\n\n{content}\n"


def process_file(filepath: Path) -> Optional[str]:
    """
    Process a Python file and return markdown API doc content.
    Returns None if the file has no [api] tags.
    """
    source = filepath.read_text(encoding="utf-8")
    source_lines = source.splitlines()

    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as e:
        print(f"  [SKIP] Syntax error in {filepath}: {e}")
        return None

    module_doc = get_docstring(tree)
    module_has_api = has_api_tag(module_doc)

    # Collect all api-tagged items
    sections = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            class_doc = get_docstring(node)
            class_has_api = has_api_tag(class_doc)

            # Collect api-tagged methods
            method_sections = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    method_doc = get_docstring(item)
                    if has_api_tag(method_doc):
                        sig = get_signature(item, source_lines)
                        doc = clean_docstring(method_doc)
                        method_sections.append(
                            f"#### `{item.name}`\n\n"
                            f"```python\n{sig}\n```\n\n"
                            f"{doc}\n"
                        )

            if class_has_api or method_sections:
                sig = get_signature(node, source_lines)
                doc = clean_docstring(class_doc) if class_doc else ""
                class_content = f"```python\n{sig}\n```\n\n{doc}\n"
                if method_sections:
                    class_content += "\n" + "\n".join(method_sections)
                sections.append(format_section(f"Class `{node.name}`", class_content, level=3))

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Skip methods (they're handled inside classes)
            # Check if parent is module (top-level functions only)
            parent = getattr(node, '_parent', None)
            if parent is not None:
                continue
            func_doc = get_docstring(node)
            if has_api_tag(func_doc):
                sig = get_signature(node, source_lines)
                doc = clean_docstring(func_doc)
                sections.append(
                    f"### `{node.name}`\n\n"
                    f"```python\n{sig}\n```\n\n"
                    f"{doc}\n"
                )

    # Mark parent nodes for top-level detection
    # (Re-process with parent tracking)
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child._parent = node  # type: ignore

    # Re-collect top-level functions with proper parent tracking
    sections = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_doc = get_docstring(node)
            if has_api_tag(func_doc):
                sig = get_signature(node, source_lines)
                doc = clean_docstring(func_doc)
                sections.append(
                    f"### `{node.name}`\n\n"
                    f"```python\n{sig}\n```\n\n"
                    f"{doc}\n"
                )

        elif isinstance(node, ast.ClassDef):
            class_doc = get_docstring(node)
            class_has_api = has_api_tag(class_doc)

            method_sections = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    method_doc = get_docstring(item)
                    if has_api_tag(method_doc):
                        sig = get_signature(item, source_lines)
                        doc = clean_docstring(method_doc)
                        method_sections.append(
                            f"#### `{item.name}`\n\n"
                            f"```python\n{sig}\n```\n\n"
                            f"{doc}\n"
                        )

            if class_has_api or method_sections:
                sig = get_signature(node, source_lines)
                doc = clean_docstring(class_doc) if class_doc else ""
                class_content = f"```python\n{sig}\n```\n\n{doc}\n"
                if method_sections:
                    class_content += "\n" + "\n".join(method_sections)
                sections.append(format_section(f"Class `{node.name}`", class_content, level=3))

    if not module_has_api and not sections:
        return None

    # Build the markdown output
    # Compute relative path from project root for the header comment
    try:
        rel_path = filepath.relative_to(Path.cwd())
    except ValueError:
        rel_path = filepath

    lines = [f"<!-- {rel_path} -->\n"]
    lines.append(f"<!-- GENERATED FILE - do not edit manually -->")
    lines.append(f"<!-- Source: {rel_path} -->\n")

    # Module title
    module_name = filepath.stem.upper()
    lines.append(f"# API — {filepath.stem}\n")

    # Module-level doc
    if module_has_api and module_doc:
        lines.append(clean_docstring(module_doc))
        lines.append("")

    # Sections
    if sections:
        lines.append("---\n")
        lines.extend(sections)

    return "\n".join(lines)


def output_filename(source_path: Path) -> Path:
    """Compute the output API .md filename next to the source file."""
    # e.g. shared/common.py → shared/API_COMMON.md
    # e.g. modules/rag_manager/rag_engine.py → modules/rag_manager/API_RAG_ENGINE.md
    stem = source_path.stem.upper()
    return source_path.parent / f"API_{stem}.md"


def scan_and_generate(root: Path, dry_run: bool = False) -> int:
    """Scan all Python files under root and generate API docs. Returns file count."""
    count = 0
    for py_file in sorted(root.rglob("*.py")):
        # Skip __pycache__, test files, this script itself
        if any(part.startswith("__") for part in py_file.parts):
            continue
        if "test" in py_file.name.lower():
            continue
        if py_file.name == Path(__file__).name:
            continue

        content = process_file(py_file)
        if content is None:
            continue

        out_path = output_filename(py_file)
        count += 1

        if dry_run:
            print(f"  [DRY-RUN] Would write: {out_path}")
            print(content[:300] + ("..." if len(content) > 300 else ""))
            print()
        else:
            out_path.write_text(content, encoding="utf-8")
            print(f"  [OK] Generated: {out_path}")

    return count


def main():
    parser = argparse.ArgumentParser(description="Generate API docs from [api] docstring tags.")
    parser.add_argument("--path", default=".", help="Root path to scan (default: current dir)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    args = parser.parse_args()

    root = Path(args.path).resolve()
    print(f"Scanning: {root}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'WRITE'}\n")

    count = scan_and_generate(root, dry_run=args.dry_run)

    print(f"\nDone. {count} API file(s) {'would be ' if args.dry_run else ''}generated.")


if __name__ == "__main__":
    main()
