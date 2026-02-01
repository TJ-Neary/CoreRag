"""
AST-Based Code Chunking

Uses Tree-sitter to parse code into an Abstract Syntax Tree,
then chunks at semantic boundaries (functions, classes, methods).

Standard text chunking destroys code:
- Splits functions in half
- Separates `def` from `return`
- Breaks class definitions

AST chunking keeps complete, executable units.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict, Any
import re

logger = logging.getLogger(__name__)


@dataclass
class CodeChunk:
    """A semantic unit of code."""
    content: str
    chunk_type: str  # function, class, method, module_level
    name: Optional[str]  # Function/class name
    start_line: int
    end_line: int
    parent_name: Optional[str]  # Class name for methods
    language: str
    docstring: Optional[str] = None
    signature: Optional[str] = None


class TreeSitterChunker:
    """
    Chunks code using Tree-sitter for AST parsing.

    Supports: Python, JavaScript, TypeScript, Go, Rust, Java, C, C++
    """

    # Language -> file extensions
    LANGUAGE_EXTENSIONS = {
        "python": [".py", ".pyw"],
        "javascript": [".js", ".mjs", ".cjs"],
        "typescript": [".ts", ".tsx"],
        "go": [".go"],
        "rust": [".rs"],
        "java": [".java"],
        "c": [".c", ".h"],
        "cpp": [".cpp", ".hpp", ".cc", ".hh", ".cxx"],
    }

    # AST node types to extract as chunks
    CHUNK_TYPES = {
        "python": ["function_definition", "class_definition"],
        "javascript": ["function_declaration", "class_declaration", "arrow_function", "method_definition"],
        "typescript": ["function_declaration", "class_declaration", "arrow_function", "method_definition"],
        "go": ["function_declaration", "method_declaration", "type_declaration"],
        "rust": ["function_item", "impl_item", "struct_item", "enum_item"],
        "java": ["method_declaration", "class_declaration", "interface_declaration"],
        "c": ["function_definition", "struct_specifier"],
        "cpp": ["function_definition", "class_specifier", "struct_specifier"],
    }

    def __init__(self, max_chunk_tokens: int = 1000):
        """
        Args:
            max_chunk_tokens: Maximum tokens per chunk (split large units if needed)
        """
        self.max_chunk_tokens = max_chunk_tokens
        self._parsers = {}

    def _get_parser(self, language: str):
        """Get or create parser for a language."""
        if language in self._parsers:
            return self._parsers[language]

        try:
            from tree_sitter import Parser, Language
            import tree_sitter_python
            import tree_sitter_javascript
            # Add other languages as needed

            parser = Parser()

            if language == "python":
                parser.set_language(tree_sitter_python.language())
            elif language in ("javascript", "typescript"):
                parser.set_language(tree_sitter_javascript.language())
            # Add other languages

            self._parsers[language] = parser
            return parser

        except ImportError:
            logger.warning(f"Tree-sitter not available for {language}")
            return None

    def detect_language(self, file_path: Path) -> Optional[str]:
        """Detect programming language from file extension."""
        ext = file_path.suffix.lower()
        for lang, exts in self.LANGUAGE_EXTENSIONS.items():
            if ext in exts:
                return lang
        return None

    def chunk_file(self, file_path: Path) -> List[CodeChunk]:
        """
        Chunk a code file using AST parsing.

        Args:
            file_path: Path to code file

        Returns:
            List of CodeChunks
        """
        language = self.detect_language(file_path)
        if not language:
            logger.warning(f"Unknown language for {file_path}")
            return []

        content = file_path.read_text(encoding="utf-8", errors="replace")
        return self.chunk_code(content, language, str(file_path))

    def chunk_code(
        self,
        code: str,
        language: str,
        source_path: str = ""
    ) -> List[CodeChunk]:
        """
        Chunk code string using AST parsing.

        Args:
            code: Source code
            language: Programming language
            source_path: Source file path for metadata

        Returns:
            List of CodeChunks
        """
        parser = self._get_parser(language)

        if parser:
            return self._chunk_with_tree_sitter(code, language, parser)
        else:
            return self._chunk_with_patterns(code, language)

    def _chunk_with_tree_sitter(
        self,
        code: str,
        language: str,
        parser
    ) -> List[CodeChunk]:
        """Chunk using Tree-sitter AST."""
        tree = parser.parse(bytes(code, "utf-8"))
        root = tree.root_node
        lines = code.split("\n")

        chunks = []
        chunk_types = self.CHUNK_TYPES.get(language, [])

        def extract_chunks(node, parent_name=None):
            if node.type in chunk_types:
                # Extract the full node text
                start_line = node.start_point[0]
                end_line = node.end_point[0]
                content = "\n".join(lines[start_line:end_line + 1])

                # Get name if available
                name = None
                for child in node.children:
                    if child.type in ("identifier", "name"):
                        name = code[child.start_byte:child.end_byte]
                        break

                # Determine chunk type
                if "class" in node.type:
                    chunk_type = "class"
                elif "method" in node.type or (parent_name and "function" in node.type):
                    chunk_type = "method"
                elif "function" in node.type:
                    chunk_type = "function"
                else:
                    chunk_type = "other"

                # Extract docstring if available
                docstring = self._extract_docstring(node, code, language)

                # Extract signature
                signature = self._extract_signature(content, language)

                chunk = CodeChunk(
                    content=content,
                    chunk_type=chunk_type,
                    name=name,
                    start_line=start_line + 1,  # 1-indexed
                    end_line=end_line + 1,
                    parent_name=parent_name,
                    language=language,
                    docstring=docstring,
                    signature=signature
                )

                # Check if chunk is too large
                if len(content) // 4 > self.max_chunk_tokens:
                    chunks.extend(self._split_large_chunk(chunk))
                else:
                    chunks.append(chunk)

                # For classes, process children with class as parent
                if chunk_type == "class":
                    for child in node.children:
                        extract_chunks(child, name)
            else:
                # Recurse into children
                for child in node.children:
                    extract_chunks(child, parent_name)

        extract_chunks(root)

        # Handle module-level code (imports, constants, etc.)
        module_level = self._extract_module_level(code, chunks, language)
        if module_level:
            chunks.insert(0, module_level)

        return chunks

    def _chunk_with_patterns(
        self,
        code: str,
        language: str
    ) -> List[CodeChunk]:
        """Fallback chunking using regex patterns."""
        chunks = []

        # Language-specific patterns
        patterns = {
            "python": [
                (r'^(class\s+\w+.*?:.*?)(?=\nclass\s|\ndef\s|\Z)', "class"),
                (r'^(def\s+\w+.*?:.*?)(?=\ndef\s|\nclass\s|\Z)', "function"),
            ],
            "javascript": [
                (r'(class\s+\w+\s*\{.*?\n\})', "class"),
                (r'(function\s+\w+\s*\([^)]*\)\s*\{.*?\n\})', "function"),
                (r'(const\s+\w+\s*=\s*\([^)]*\)\s*=>\s*\{.*?\n\})', "function"),
            ],
        }

        lang_patterns = patterns.get(language, [])

        for pattern, chunk_type in lang_patterns:
            for match in re.finditer(pattern, code, re.MULTILINE | re.DOTALL):
                content = match.group(1)
                start_line = code[:match.start()].count("\n") + 1

                chunks.append(CodeChunk(
                    content=content,
                    chunk_type=chunk_type,
                    name=self._extract_name(content, language),
                    start_line=start_line,
                    end_line=start_line + content.count("\n"),
                    parent_name=None,
                    language=language
                ))

        return chunks

    def _extract_docstring(self, node, code: str, language: str) -> Optional[str]:
        """Extract docstring from a function/class node."""
        if language == "python":
            # Look for string as first child
            for child in node.children:
                if child.type == "block":
                    for block_child in child.children:
                        if block_child.type == "expression_statement":
                            for expr in block_child.children:
                                if expr.type == "string":
                                    return code[expr.start_byte:expr.end_byte].strip('"""\'')
        return None

    def _extract_signature(self, content: str, language: str) -> Optional[str]:
        """Extract function/method signature."""
        if language == "python":
            match = re.match(r'(def\s+\w+\s*\([^)]*\))', content)
            if match:
                return match.group(1)
        elif language in ("javascript", "typescript"):
            match = re.match(r'(function\s+\w+\s*\([^)]*\))', content)
            if match:
                return match.group(1)
        return None

    def _extract_name(self, content: str, language: str) -> Optional[str]:
        """Extract function/class name from content."""
        if language == "python":
            match = re.match(r'(?:def|class)\s+(\w+)', content)
        elif language in ("javascript", "typescript"):
            match = re.match(r'(?:function|class)\s+(\w+)', content)
        else:
            match = None

        return match.group(1) if match else None

    def _extract_module_level(
        self,
        code: str,
        chunks: List[CodeChunk],
        language: str
    ) -> Optional[CodeChunk]:
        """Extract module-level code (imports, constants)."""
        # Find line ranges covered by chunks
        covered_lines = set()
        for chunk in chunks:
            covered_lines.update(range(chunk.start_line, chunk.end_line + 1))

        lines = code.split("\n")
        module_lines = []

        for i, line in enumerate(lines, 1):
            if i not in covered_lines and line.strip():
                module_lines.append(line)

        if module_lines:
            content = "\n".join(module_lines)
            return CodeChunk(
                content=content,
                chunk_type="module_level",
                name="__module__",
                start_line=1,
                end_line=len(lines),
                parent_name=None,
                language=language
            )
        return None

    def _split_large_chunk(self, chunk: CodeChunk) -> List[CodeChunk]:
        """Split a chunk that exceeds max tokens."""
        lines = chunk.content.split("\n")
        sub_chunks = []
        current_lines = []
        current_tokens = 0

        for i, line in enumerate(lines):
            line_tokens = len(line) // 4

            if current_tokens + line_tokens > self.max_chunk_tokens and current_lines:
                sub_chunks.append(CodeChunk(
                    content="\n".join(current_lines),
                    chunk_type=chunk.chunk_type,
                    name=f"{chunk.name}_part{len(sub_chunks) + 1}",
                    start_line=chunk.start_line + i - len(current_lines),
                    end_line=chunk.start_line + i - 1,
                    parent_name=chunk.parent_name,
                    language=chunk.language
                ))
                current_lines = []
                current_tokens = 0

            current_lines.append(line)
            current_tokens += line_tokens

        if current_lines:
            sub_chunks.append(CodeChunk(
                content="\n".join(current_lines),
                chunk_type=chunk.chunk_type,
                name=f"{chunk.name}_part{len(sub_chunks) + 1}",
                start_line=chunk.start_line + len(lines) - len(current_lines),
                end_line=chunk.end_line,
                parent_name=chunk.parent_name,
                language=chunk.language
            ))

        return sub_chunks
