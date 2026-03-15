"""
CatalogManager — SQLite-backed document catalog.

Tracks every document across all destinations (main RAG, restricted RAG,
Obsidian vault, archive). Provides CRUD operations, search, export tracking,
and aggregate statistics.

The catalog is the single source of truth for "what documents exist and where
they live" across the entire CoreRag system.
"""

import datetime
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from src.exceptions import DatabaseError

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path.home() / "Documents" / "PKM" / "_catalog.db"


@dataclass
class DocumentRecord:
    """A document tracked in the catalog."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    original_filename: str = ""
    original_path: Optional[str] = None
    archive_path: Optional[str] = None
    main_rag_doc_id: Optional[str] = None
    restricted_rag_doc_id: Optional[str] = None
    obsidian_path: Optional[str] = None
    category: Optional[str] = None
    year: Optional[str] = None
    tags: Optional[str] = None  # Comma-delimited collection tags
    is_sensitive: bool = False
    summary: Optional[str] = None
    file_type: Optional[str] = None
    file_size: Optional[int] = None
    chunk_count: int = 0
    parent_count: int = 0
    batch_id: Optional[str] = None
    ingested_at: Optional[str] = None
    updated_at: Optional[str] = None
    status: str = "active"  # active, archived, deleted
    storage_location: str = "local"  # local, external_hd, cloud
    storage_device: Optional[str] = None  # e.g., 'MacBook', 'WD_Passport_2TB'
    storage_accessible: bool = True  # True=reachable, False=offline


@dataclass
class ExportRecord:
    """A record of a document being exported to a destination."""

    document_id: str = ""
    destination: str = ""  # 'main_rag', 'restricted_rag', 'obsidian', 'archive'
    path: Optional[str] = None
    exported_at: Optional[str] = None
    redacted: bool = False


class CatalogManager:
    """SQLite-backed document catalog.

    Tracks documents across all destinations with CRUD operations,
    search, export tracking, and aggregate statistics.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        """Initialize the catalog manager.

        Args:
            db_path: Path to SQLite database. Defaults to ~/Documents/PKM/_catalog.db.
        """
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    original_filename TEXT NOT NULL,
                    original_path TEXT,
                    archive_path TEXT,
                    main_rag_doc_id TEXT,
                    restricted_rag_doc_id TEXT,
                    obsidian_path TEXT,
                    category TEXT,
                    year TEXT,
                    tags TEXT,
                    is_sensitive INTEGER DEFAULT 0,
                    summary TEXT,
                    file_type TEXT,
                    file_size INTEGER,
                    chunk_count INTEGER DEFAULT 0,
                    parent_count INTEGER DEFAULT 0,
                    batch_id TEXT,
                    ingested_at TEXT,
                    updated_at TEXT,
                    status TEXT DEFAULT 'active',
                    storage_location TEXT DEFAULT 'local',
                    storage_device TEXT,
                    storage_accessible INTEGER DEFAULT 1
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS document_exports (
                    document_id TEXT,
                    destination TEXT,
                    path TEXT,
                    exported_at TEXT,
                    redacted INTEGER,
                    FOREIGN KEY (document_id) REFERENCES documents(id)
                )
            """)

            # Indices for common queries
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_docs_category ON documents(category)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_docs_status ON documents(status)")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_docs_sensitive ON documents(is_sensitive)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_exports_doc_id ON document_exports(document_id)"
            )

            conn.commit()
            conn.close()
            logger.info("Catalog database initialized at %s", self.db_path)
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to initialize catalog database: {e}") from e

    def _get_conn(self) -> sqlite3.Connection:
        """Get a database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _now(self) -> str:
        """Return current UTC timestamp as ISO string."""
        return datetime.datetime.now(datetime.timezone.utc).isoformat()

    def _row_to_record(self, row: sqlite3.Row) -> DocumentRecord:
        """Convert a database row to a DocumentRecord."""
        return DocumentRecord(
            id=row["id"],
            original_filename=row["original_filename"],
            original_path=row["original_path"],
            archive_path=row["archive_path"],
            main_rag_doc_id=row["main_rag_doc_id"],
            restricted_rag_doc_id=row["restricted_rag_doc_id"],
            obsidian_path=row["obsidian_path"],
            category=row["category"],
            year=row["year"],
            tags=row["tags"],
            is_sensitive=bool(row["is_sensitive"]),
            summary=row["summary"],
            file_type=row["file_type"],
            file_size=row["file_size"],
            chunk_count=row["chunk_count"] or 0,
            parent_count=row["parent_count"] or 0,
            batch_id=row["batch_id"],
            ingested_at=row["ingested_at"],
            updated_at=row["updated_at"],
            status=row["status"] or "active",
            storage_location=row["storage_location"] or "local",
            storage_device=row["storage_device"],
            storage_accessible=bool(row["storage_accessible"]),
        )

    def register(self, record: DocumentRecord) -> str:
        """Register a new document in the catalog.

        Args:
            record: DocumentRecord to register.

        Returns:
            The document ID.

        Raises:
            DatabaseError: If the insert fails.
        """
        now = self._now()
        if not record.ingested_at:
            record.ingested_at = now
        record.updated_at = now

        # Normalize tags to comma-delimited with leading/trailing commas
        # e.g., "fitness,nutrition" -> ",fitness,nutrition,"
        # This enables delimiter-aware LIKE '%,tag,%' searches
        tags_normalized = record.tags
        if tags_normalized and not tags_normalized.startswith(","):
            tags_normalized = f",{tags_normalized},"

        try:
            conn = self._get_conn()
            conn.execute(
                """
                INSERT INTO documents (
                    id, original_filename, original_path, archive_path,
                    main_rag_doc_id, restricted_rag_doc_id, obsidian_path,
                    category, year, tags, is_sensitive, summary,
                    file_type, file_size, chunk_count, parent_count,
                    batch_id, ingested_at, updated_at, status,
                    storage_location, storage_device, storage_accessible
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    record.id,
                    record.original_filename,
                    record.original_path,
                    record.archive_path,
                    record.main_rag_doc_id,
                    record.restricted_rag_doc_id,
                    record.obsidian_path,
                    record.category,
                    record.year,
                    tags_normalized,
                    int(record.is_sensitive),
                    record.summary,
                    record.file_type,
                    record.file_size,
                    record.chunk_count,
                    record.parent_count,
                    record.batch_id,
                    record.ingested_at,
                    record.updated_at,
                    record.status,
                    record.storage_location,
                    record.storage_device,
                    int(record.storage_accessible),
                ),
            )
            conn.commit()
            conn.close()
            logger.info("Registered document %s: %s", record.id, record.original_filename)
            return record.id
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to register document: {e}") from e

    def get(self, document_id: str) -> Optional[DocumentRecord]:
        """Get a document by ID.

        Args:
            document_id: The document ID.

        Returns:
            DocumentRecord if found, None otherwise.
        """
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        conn.close()

        if row is None:
            return None
        return self._row_to_record(row)

    def update(self, document_id: str, **kwargs: Any) -> bool:
        """Update fields on an existing document.

        Args:
            document_id: The document ID to update.
            **kwargs: Field names and values to update. Only fields present
                in DocumentRecord are accepted.

        Returns:
            True if the document was found and updated, False otherwise.

        Raises:
            DatabaseError: If the update fails.
            ValueError: If an invalid field name is provided.
        """
        if not kwargs:
            return False

        # Validate field names against the schema
        valid_fields = {
            "original_filename",
            "original_path",
            "archive_path",
            "main_rag_doc_id",
            "restricted_rag_doc_id",
            "obsidian_path",
            "category",
            "year",
            "tags",
            "is_sensitive",
            "summary",
            "file_type",
            "file_size",
            "chunk_count",
            "parent_count",
            "batch_id",
            "ingested_at",
            "updated_at",
            "status",
            "storage_location",
            "storage_device",
            "storage_accessible",
        }

        invalid = set(kwargs.keys()) - valid_fields
        if invalid:
            raise ValueError(f"Invalid fields for update: {invalid}")

        # Convert booleans to integers for SQLite
        params: dict[str, Any] = {}
        for k, v in kwargs.items():
            if k in ("is_sensitive", "storage_accessible"):
                params[k] = int(v)
            else:
                params[k] = v

        params["updated_at"] = self._now()

        set_clause = ", ".join(f"{k} = ?" for k in params)
        values = list(params.values()) + [document_id]

        # Query is safe: column names are validated against valid_fields allowlist above.
        # This is sqlite3 (not SQLAlchemy) and all values use parameterized ?.
        query = "UPDATE documents SET " + set_clause + " WHERE id = ?"

        try:
            conn = self._get_conn()
            cursor = conn.execute(query, values)  # nosemgrep: sqlalchemy-execute-raw-query
            conn.commit()
            updated = cursor.rowcount > 0
            conn.close()
            if updated:
                logger.info("Updated document %s: %s", document_id, list(kwargs.keys()))
            return updated
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to update document {document_id}: {e}") from e

    def search(
        self,
        category: Optional[str] = None,
        tag: Optional[str] = None,
        is_sensitive: Optional[bool] = None,
        status: Optional[str] = None,
        file_type: Optional[str] = None,
        storage_location: Optional[str] = None,
    ) -> list[DocumentRecord]:
        """Search documents by various criteria.

        All parameters are optional and combined with AND logic.

        Args:
            category: Filter by category (exact match).
            tag: Filter by tag substring (matches within comma-delimited tags).
            is_sensitive: Filter by sensitivity flag.
            status: Filter by status (default: excludes 'deleted').
            file_type: Filter by file type.
            storage_location: Filter by storage location.

        Returns:
            List of matching DocumentRecords.
        """
        conditions: list[str] = []
        params: list[Any] = []

        if category is not None:
            conditions.append("category = ?")
            params.append(category)

        if tag is not None:
            # Tags are stored comma-delimited: ",tag1,tag2,"
            # Use delimiter-aware matching to avoid substring false positives
            # e.g., searching "study" should not match "sphr-study"
            conditions.append("tags LIKE ?")
            params.append(f"%,{tag},%")

        if is_sensitive is not None:
            conditions.append("is_sensitive = ?")
            params.append(int(is_sensitive))

        if status is not None:
            conditions.append("status = ?")
            params.append(status)
        else:
            # By default, exclude deleted documents
            conditions.append("status != 'deleted'")

        if file_type is not None:
            conditions.append("file_type = ?")
            params.append(file_type)

        if storage_location is not None:
            conditions.append("storage_location = ?")
            params.append(storage_location)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        # Safe: conditions are hardcoded strings, all user values use parameterized ?.
        query = (
            f"SELECT * FROM documents WHERE {where_clause} ORDER BY ingested_at DESC"  # noqa: S608
        )

        conn = self._get_conn()
        rows = conn.execute(query, params).fetchall()  # nosemgrep: sqlalchemy-execute-raw-query
        conn.close()

        return [self._row_to_record(row) for row in rows]

    def delete(self, document_id: str) -> bool:
        """Soft-delete a document (sets status to 'deleted').

        The document remains in the database for audit trail.

        Args:
            document_id: The document ID to delete.

        Returns:
            True if the document was found and marked deleted, False otherwise.
        """
        return self.update(document_id, status="deleted")

    def record_export(self, export: ExportRecord) -> None:
        """Record a document export to a destination.

        Args:
            export: ExportRecord describing the export.

        Raises:
            DatabaseError: If the insert fails.
        """
        if not export.exported_at:
            export.exported_at = self._now()

        try:
            conn = self._get_conn()
            conn.execute(
                """
                INSERT INTO document_exports (
                    document_id, destination, path, exported_at, redacted
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    export.document_id,
                    export.destination,
                    export.path,
                    export.exported_at,
                    int(export.redacted),
                ),
            )
            conn.commit()
            conn.close()
            logger.info("Recorded export for %s to %s", export.document_id, export.destination)
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to record export for {export.document_id}: {e}") from e

    def get_exports(self, document_id: str) -> list[ExportRecord]:
        """Get all exports for a document.

        Args:
            document_id: The document ID.

        Returns:
            List of ExportRecords for the document.
        """
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM document_exports WHERE document_id = ? ORDER BY exported_at",
            (document_id,),
        ).fetchall()
        conn.close()

        return [
            ExportRecord(
                document_id=row["document_id"],
                destination=row["destination"],
                path=row["path"],
                exported_at=row["exported_at"],
                redacted=bool(row["redacted"]),
            )
            for row in rows
        ]

    def get_stats(self) -> dict[str, Any]:
        """Get aggregate statistics about the catalog.

        Returns:
            Dictionary with counts by category, tag, sensitivity, status,
            and overall totals.
        """
        conn = self._get_conn()

        # Total counts
        total = conn.execute(
            "SELECT COUNT(*) as count FROM documents WHERE status != 'deleted'"
        ).fetchone()
        total_count: int = total["count"] if total else 0

        # By category
        category_rows = conn.execute("""
            SELECT category, COUNT(*) as count FROM documents
            WHERE status != 'deleted' AND category IS NOT NULL
            GROUP BY category ORDER BY count DESC
            """).fetchall()
        by_category: dict[str, int] = {row["category"]: row["count"] for row in category_rows}

        # By status
        status_rows = conn.execute(
            "SELECT status, COUNT(*) as count FROM documents GROUP BY status ORDER BY count DESC"
        ).fetchall()
        by_status: dict[str, int] = {row["status"]: row["count"] for row in status_rows}

        # Sensitivity
        sensitive_count_row = conn.execute(
            "SELECT COUNT(*) as count FROM documents WHERE is_sensitive = 1 AND status != 'deleted'"
        ).fetchone()
        sensitive_count: int = sensitive_count_row["count"] if sensitive_count_row else 0

        # Tags — parse comma-delimited tags and count each unique tag
        tag_rows = conn.execute(
            "SELECT tags FROM documents WHERE status != 'deleted' AND tags IS NOT NULL"
        ).fetchall()
        tag_counts: dict[str, int] = {}
        for row in tag_rows:
            tags_str: str = row["tags"]
            for tag in tags_str.split(","):
                tag = tag.strip()
                if tag:
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1

        # Total exports
        export_count_row = conn.execute("SELECT COUNT(*) as count FROM document_exports").fetchone()
        export_count: int = export_count_row["count"] if export_count_row else 0

        conn.close()

        return {
            "total_documents": total_count,
            "by_category": by_category,
            "by_status": by_status,
            "by_tag": tag_counts,
            "sensitive_count": sensitive_count,
            "total_exports": export_count,
        }
