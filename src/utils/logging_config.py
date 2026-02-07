"""
Logging and debugging configuration for CoreRag.

Provides structured logging with multiple outputs and debug tools.
"""

import functools
import json
import logging
import logging.handlers
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional


class StructuredFormatter(logging.Formatter):
    """JSON-structured log formatter for machine parsing."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add exception info if present
        if record.exc_info and record.exc_info[0] is not None:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": traceback.format_exception(*record.exc_info),
            }

        # Add any extra fields
        if hasattr(record, "extra_data"):
            log_data["data"] = record.extra_data

        return json.dumps(log_data)


class ColoredFormatter(logging.Formatter):
    """Colored console formatter for human readability."""

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        """Format with colors."""
        color = self.COLORS.get(record.levelname, "")
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


def setup_logging(
    level: str = "INFO",
    log_dir: Optional[Path] = None,
    console: bool = True,
    json_logs: bool = True,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
) -> logging.Logger:
    """
    Set up logging configuration.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        log_dir: Directory for log files
        console: Enable console output
        json_logs: Enable JSON structured logs
        max_bytes: Max size per log file
        backup_count: Number of backup files to keep

    Returns:
        Root logger
    """
    from src.config import LOG_DIR

    log_dir = log_dir or LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger("corerag")
    root_logger.setLevel(getattr(logging, level.upper()))

    # Clear existing handlers
    root_logger.handlers.clear()

    # Also configure the Python root logger so that all loggers (including
    # those created with logging.getLogger(__name__)) inherit the same
    # handlers and level.  This replaces any prior logging.basicConfig() call.
    _root = logging.getLogger()
    _root.setLevel(getattr(logging, level.upper()))
    _root.handlers.clear()

    # Build handlers list — added to both the "corerag" logger and the
    # Python root logger so that loggers created with getLogger(__name__)
    # (e.g. "src.server") also emit through the same handlers.
    handlers: list[logging.Handler] = []

    # Console handler with colors
    if console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.DEBUG)

        console_format: logging.Formatter
        if sys.stderr.isatty():
            console_format = ColoredFormatter(
                "%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s", datefmt="%H:%M:%S"
            )
        else:
            console_format = logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s", datefmt="%H:%M:%S"
            )

        console_handler.setFormatter(console_format)
        handlers.append(console_handler)

    # File handler for human-readable logs
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "corerag.log", maxBytes=max_bytes, backupCount=backup_count
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(module)s:%(lineno)d | %(message)s"
        )
    )
    handlers.append(file_handler)

    # JSON structured logs for machine parsing
    if json_logs:
        json_handler = logging.handlers.RotatingFileHandler(
            log_dir / "corerag.json.log", maxBytes=max_bytes, backupCount=backup_count
        )
        json_handler.setLevel(logging.DEBUG)
        json_handler.setFormatter(StructuredFormatter())
        handlers.append(json_handler)

    # Error-only log for quick problem identification
    error_handler = logging.handlers.RotatingFileHandler(
        log_dir / "corerag.error.log", maxBytes=max_bytes, backupCount=backup_count
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(module)s:%(lineno)d\n"
            "%(message)s\n"
            "%(exc_info)s\n"
            "---"
        )
    )
    handlers.append(error_handler)

    # Attach handlers to the "corerag" logger
    for h in handlers:
        root_logger.addHandler(h)

    # Prevent double-logging: "corerag" logger won't propagate to root
    root_logger.propagate = False

    # Attach the same handlers to the Python root logger so that loggers
    # outside the "corerag" namespace (e.g. "src.server") also benefit.
    for h in handlers:
        _root.addHandler(h)

    return root_logger


class LogContext:
    """Context manager for adding context to logs."""

    def __init__(self, logger: logging.Logger, **context):
        """
        Add context to all logs within this block.

        Usage:
            with LogContext(logger, request_id="abc123", user="tj"):
                logger.info("Processing request")
        """
        self.logger = logger
        self.context = context
        self._old_factory = None

    def __enter__(self):
        self._old_factory = logging.getLogRecordFactory()

        context = self.context

        def record_factory(*args, **kwargs):
            record = self._old_factory(*args, **kwargs)
            record.extra_data = context
            return record

        logging.setLogRecordFactory(record_factory)
        return self

    def __exit__(self, *args):
        logging.setLogRecordFactory(self._old_factory)


def log_performance(logger: Optional[logging.Logger] = None):
    """
    Decorator to log function performance.

    Usage:
        @log_performance()
        def slow_function():
            ...
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            log = logger or logging.getLogger(func.__module__)

            start = time.time()
            try:
                result = func(*args, **kwargs)
                elapsed = (time.time() - start) * 1000

                log.debug(f"{func.__name__} completed in {elapsed:.1f}ms")

                return result

            except Exception as e:
                elapsed = (time.time() - start) * 1000
                log.error(f"{func.__name__} failed after {elapsed:.1f}ms: {e}", exc_info=True)
                raise

        return wrapper

    return decorator


class DebugTimer:
    """
    Timer for debugging performance.

    Usage:
        with DebugTimer("embedding generation"):
            embeddings = generate_embeddings(texts)
    """

    def __init__(self, name: str, logger: Optional[logging.Logger] = None):
        self.name = name
        self.logger = logger or logging.getLogger("corerag.debug")
        self.start_time: Optional[float] = None
        self.checkpoints: list[tuple[str, float]] = []

    def __enter__(self):
        self.start_time = time.time()
        return self

    def checkpoint(self, name: str):
        """Record a checkpoint."""
        assert self.start_time is not None
        elapsed = time.time() - self.start_time
        self.checkpoints.append((name, elapsed))
        self.logger.debug(f"[{self.name}] {name}: {elapsed * 1000:.1f}ms")

    def __exit__(self, *args):
        assert self.start_time is not None
        elapsed = time.time() - self.start_time
        self.logger.debug(f"[{self.name}] Total: {elapsed * 1000:.1f}ms")


class QueryLogger:
    """
    Log search queries for analysis.

    Separate from main logs for query-specific analysis.
    """

    def __init__(self, log_dir: Optional[Path] = None):
        from src.config import LOG_DIR

        self.log_dir = log_dir or LOG_DIR / "queries"
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def log_query(
        self,
        query: str,
        results_count: int,
        latency_ms: float,
        filters: Optional[Dict] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Log a search query."""
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "query": query,
            "results_count": results_count,
            "latency_ms": latency_ms,
            "filters": filters or {},
            "user_id": user_id,
        }

        # Daily query log file
        date_str = datetime.now().strftime("%Y-%m-%d")
        log_file = self.log_dir / f"queries_{date_str}.jsonl"

        with open(log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def get_popular_queries(self, days: int = 7, limit: int = 20) -> Dict[str, int]:
        """Get most popular queries."""
        query_counts: dict[str, int] = {}

        for i in range(days):
            date = datetime.now() - timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            log_file = self.log_dir / f"queries_{date_str}.jsonl"

            if log_file.exists():
                with open(log_file) as f:
                    for line in f:
                        try:
                            entry = json.loads(line)
                            query = entry["query"].lower().strip()
                            query_counts[query] = query_counts.get(query, 0) + 1
                        except (json.JSONDecodeError, KeyError, TypeError):
                            # Skip malformed or incomplete log entries
                            pass

        # Sort by count
        sorted_queries = sorted(query_counts.items(), key=lambda x: x[1], reverse=True)

        return dict(sorted_queries[:limit])


# Convenience function
def get_logger(name: str) -> logging.Logger:
    """Get a logger for a module."""
    return logging.getLogger(f"corerag.{name}")
