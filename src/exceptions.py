"""
CoreRag Exception Hierarchy

Base exception class and specialized subclasses for different error categories.
Use these instead of bare `except:` or generic `Exception`.

Hierarchy:
    CoreRagError (base)
    ├── ProcessingError      — File processing failures
    ├── EmbeddingError       — Embedding generation failures
    ├── DatabaseError        — LanceDB/SQLite operations
    ├── SearchError          — Search and retrieval failures
    ├── ConfigurationError   — Missing or invalid configuration
    └── MemoryError          — Memory threshold exceeded (not Python's built-in)

Usage:
    from src.exceptions import ProcessingError, DatabaseError

    try:
        result = process_document(path)
    except ProcessingError as e:
        logger.error(f"Processing failed: {e}")
        # Handle or re-raise
"""

import logging

logger = logging.getLogger(__name__)


class CoreRagError(Exception):
    """Base exception for all CoreRag errors.

    All custom exceptions inherit from this, making it easy to catch
    any CoreRag-specific error:

        try:
            ...
        except CoreRagError as e:
            logger.error(f"CoreRag error: {e}")
    """

    def __init__(self, message: str, *args, **kwargs):
        self.message = message
        super().__init__(message, *args, **kwargs)

    def __str__(self) -> str:
        return self.message


class ProcessingError(CoreRagError):
    """Error during file processing (extraction, analysis, staging).

    Raised when:
    - File extraction fails (PDF, DOCX, etc.)
    - AI analysis returns invalid/incomplete data
    - Staging manifest update fails
    """

    def __init__(self, message: str, file_path: str | None = None, **kwargs):
        self.file_path = file_path
        if file_path:
            message = f"{message} (file: {file_path})"
        super().__init__(message, **kwargs)


class EmbeddingError(CoreRagError):
    """Error generating or using embeddings.

    Raised when:
    - Embedding model fails to load
    - Embedding generation times out
    - Dimension mismatch between query and index
    """

    def __init__(self, message: str, model_name: str | None = None, **kwargs):
        self.model_name = model_name
        if model_name:
            message = f"{message} (model: {model_name})"
        super().__init__(message, **kwargs)


class DatabaseError(CoreRagError):
    """Error with database operations (LanceDB, SQLite).

    Raised when:
    - Database connection fails
    - Table creation/opening fails
    - Query execution fails
    - Index rebuild fails
    """

    def __init__(self, message: str, table_name: str | None = None, **kwargs):
        self.table_name = table_name
        if table_name:
            message = f"{message} (table: {table_name})"
        super().__init__(message, **kwargs)


class SearchError(CoreRagError):
    """Error during search and retrieval operations.

    Raised when:
    - Hybrid search fails
    - Reranking fails
    - HyDE expansion fails
    - No results found when required
    """

    def __init__(self, message: str, query: str | None = None, **kwargs):
        self.query = query
        if query:
            # Truncate long queries in error message
            truncated = query[:50] + "..." if len(query) > 50 else query
            message = f"{message} (query: {truncated})"
        super().__init__(message, **kwargs)


class ConfigurationError(CoreRagError):
    """Error with configuration or environment setup.

    Raised when:
    - Required environment variable missing
    - Invalid configuration value
    - Required directory doesn't exist
    - Required dependency not installed
    """

    def __init__(self, message: str, config_key: str | None = None, **kwargs):
        self.config_key = config_key
        if config_key:
            message = f"{message} (config: {config_key})"
        super().__init__(message, **kwargs)


class CoreRagMemoryError(CoreRagError):
    """Memory threshold exceeded during processing.

    Named CoreRagMemoryError to avoid shadowing Python's built-in MemoryError.

    Raised when:
    - RAM usage exceeds safe threshold
    - Batch size too large for available memory
    - Need to pause processing for memory recovery
    """

    def __init__(
        self,
        message: str,
        current_usage: float | None = None,
        threshold: float | None = None,
        **kwargs,
    ):
        self.current_usage = current_usage
        self.threshold = threshold
        if current_usage is not None and threshold is not None:
            message = f"{message} (usage: {current_usage:.1%}, threshold: {threshold:.1%})"
        super().__init__(message, **kwargs)


# Convenience aliases for common patterns
__all__ = [
    "CoreRagError",
    "ProcessingError",
    "EmbeddingError",
    "DatabaseError",
    "SearchError",
    "ConfigurationError",
    "CoreRagMemoryError",
]
