"""AST-aware chunking for Python files, line-based fallback for other languages.

Splits code files at function/class boundaries for meaningful RAG chunks.
Python gets AST parsing; all other languages get line-based chunking with overlap.
"""

import ast
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".rb"}
AST_EXTENSIONS = {".py"}


@dataclass
class CodeChunk:
    """A chunk of source code with metadata."""

    content: str
    start_line: int
    end_line: int
    kind: str  # "function", "class", "module", "block"
    name: str  # function/class name or ""


def chunk_python(source: str) -> list[CodeChunk]:
    """Split Python source at function/class boundaries.

    Falls back to line-based chunking on syntax errors or files with no definitions.
    Empty files return an empty list.
    """
    if not source.strip():
        return []

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return chunk_by_lines(source)

    lines = source.splitlines(keepends=True)

    # Get top-level definitions
    nodes = [
        n
        for n in ast.iter_child_nodes(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]

    if not nodes:
        return chunk_by_lines(source)

    chunks = []

    # Module-level code BEFORE first definition
    if nodes[0].lineno > 1:
        content = "".join(lines[: nodes[0].lineno - 1]).strip()
        if content:
            chunks.append(CodeChunk(content, 1, nodes[0].lineno - 1, "module", ""))

    # Each top-level definition
    for node in nodes:
        end = getattr(node, "end_lineno", node.lineno + 10)
        content = "".join(lines[node.lineno - 1 : end]).strip()
        kind = "class" if isinstance(node, ast.ClassDef) else "function"
        chunks.append(CodeChunk(content, node.lineno, end, kind, node.name))

    # Module-level code AFTER last definition (e.g., if __name__ == "__main__")
    last_end = getattr(nodes[-1], "end_lineno", nodes[-1].lineno + 10)
    if last_end < len(lines):
        trailing = "".join(lines[last_end:]).strip()
        if trailing:
            chunks.append(CodeChunk(trailing, last_end + 1, len(lines), "module", "__tail__"))

    return chunks if chunks else chunk_by_lines(source)


def chunk_by_lines(source: str, chunk_size: int = 60, overlap: int = 10) -> list[CodeChunk]:
    """Line-based chunking with overlap for non-Python files.

    Empty source returns an empty list.
    """
    lines = source.splitlines(keepends=True)
    if not lines:
        return []

    chunks = []
    for i in range(0, len(lines), chunk_size - overlap):
        chunk_lines = lines[i : i + chunk_size]
        content = "".join(chunk_lines).strip()
        if content:
            chunks.append(CodeChunk(content, i + 1, i + len(chunk_lines), "block", ""))
    return chunks


def chunk_code(source: str, extension: str) -> list[CodeChunk]:
    """Route to appropriate chunker based on file extension."""
    if extension in AST_EXTENSIONS:
        return chunk_python(source)
    return chunk_by_lines(source)
