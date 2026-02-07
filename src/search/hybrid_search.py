"""
Hybrid Search with Enforced FTS Index

Combines vector search with full-text search using Reciprocal Rank Fusion (RRF).
CRITICAL: FTS index MUST be created for hybrid search to work correctly.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.exceptions import SearchError
from src.utils.query_sanitize import build_filter_clause

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Result from hybrid search with scoring details."""

    id: str
    content: str
    document_id: str
    vector_score: float
    fts_score: Optional[float]
    rrf_score: float
    metadata: dict

    # Debug info
    vector_rank: Optional[int] = None
    fts_rank: Optional[int] = None


class HybridSearcher:
    """
    Hybrid search combining vector similarity and full-text search.

    CRITICAL: Call ensure_fts_index() after table creation or data insertion.
    Without FTS index, keyword search will fail silently or use slow scan.
    """

    # RRF constant (standard value from research)
    RRF_K = 60

    def __init__(self, db, table_name: str = "child_chunks"):
        self.db = db
        self.table_name = table_name
        self._table = None
        self._fts_verified = False

    @property
    def table(self):
        if self._table is None:
            self._table = self.db.open_table(self.table_name)
        return self._table

    def ensure_fts_index(self, text_column: str = "content", replace: bool = False) -> bool:
        """
        CRITICAL: Ensure FTS index exists on the text column.

        This MUST be called after:
        1. Initial table creation
        2. Large batch insertions
        3. Any schema changes

        Args:
            text_column: Column to index for full-text search
            replace: Whether to rebuild existing index

        Returns:
            True if index was created/verified, False on error
        """
        try:
            # Create FTS index
            self.table.create_fts_index(text_column, replace=replace)
            self._fts_verified = True
            logger.info(f"FTS index created/verified on '{text_column}' column")
            return True
        except Exception as e:
            # Index might already exist (which is fine)
            if "already exists" in str(e).lower():
                self._fts_verified = True
                logger.debug(f"FTS index already exists on '{text_column}'")
                return True
            else:
                logger.error(f"Failed to create FTS index: {e}")
                return False

    def verify_fts_index(self) -> bool:
        """
        Verify FTS index is working by running a test query.

        Returns:
            True if FTS is functional
        """
        try:
            # Try a simple FTS query
            self.table.search("test", query_type="fts").limit(1).to_list()
            self._fts_verified = True
            return True
        except Exception as e:
            logger.warning(f"FTS index verification failed: {e}")
            self._fts_verified = False
            return False

    async def search(
        self,
        query: str,
        query_vector: List[float],
        k: int = 10,
        vector_weight: float = 0.7,
        fts_weight: float = 0.3,
        filters: Optional[Dict[str, Any]] = None,
        debug: bool = False,
    ) -> List[SearchResult]:
        """
        Perform hybrid search with RRF fusion.

        Args:
            query: Text query for FTS
            query_vector: Embedded query vector for ANN
            k: Number of results to return
            vector_weight: Weight for vector search (0-1)
            fts_weight: Weight for FTS (0-1)
            filters: Optional metadata filters
            debug: Include ranking debug info

        Returns:
            List of SearchResult sorted by RRF score
        """
        # Validate FTS index
        if not self._fts_verified:
            if not self.verify_fts_index():
                logger.warning("FTS index not available, falling back to vector-only search")
                return await self._vector_only_search(query_vector, k, filters, debug)

        # Oversample for fusion
        oversample = k * 3

        # Vector search
        vector_results = await self._vector_search(query_vector, oversample, filters)

        # Full-text search
        fts_results = await self._fts_search(query, oversample, filters)

        # Fuse with RRF
        fused = self._reciprocal_rank_fusion(
            vector_results, fts_results, vector_weight, fts_weight, debug
        )

        return fused[:k]

    def _build_filter_clause(self, filters: Dict[str, Any]) -> str:
        """Build a WHERE clause from filters dict.

        The 'tags' key is special: it uses LIKE-based matching against
        the comma-delimited tags column (e.g. ",sphr-study,cert-prep,").
        All other keys use exact equality matching.

        Uses centralized query sanitization to prevent SQL injection.
        """
        return build_filter_clause(filters)

    async def _vector_search(
        self, query_vector: List[float], k: int, filters: Optional[Dict[str, Any]]
    ) -> List[Dict]:
        """Perform ANN vector search."""
        search = self.table.search(query_vector).limit(k)

        if filters:
            search = search.where(self._build_filter_clause(filters))

        return search.to_list()

    async def _fts_search(
        self, query: str, k: int, filters: Optional[Dict[str, Any]]
    ) -> List[Dict]:
        """Perform full-text search."""
        try:
            search = self.table.search(query, query_type="fts").limit(k)

            if filters:
                search = search.where(self._build_filter_clause(filters))

            return search.to_list()
        except Exception as e:
            logger.warning(f"FTS search failed: {e}")
            return []

    async def _vector_only_search(
        self, query_vector: List[float], k: int, filters: Optional[Dict[str, Any]], debug: bool
    ) -> List[SearchResult]:
        """Fallback when FTS is unavailable."""
        results = await self._vector_search(query_vector, k, filters)

        return [
            SearchResult(
                id=r["id"],
                content=r["content"],
                document_id=r["document_id"],
                vector_score=r.get("_distance", 0),
                fts_score=None,
                rrf_score=1 / (self.RRF_K + i + 1),
                metadata=r.get("metadata", {}),
                vector_rank=i + 1 if debug else None,
                fts_rank=None,
            )
            for i, r in enumerate(results)
        ]

    def _reciprocal_rank_fusion(
        self,
        vector_results: List[Dict],
        fts_results: List[Dict],
        vector_weight: float,
        fts_weight: float,
        debug: bool,
    ) -> List[SearchResult]:
        """
        Combine results using Reciprocal Rank Fusion.

        RRF score = Σ (weight / (k + rank))

        This is robust to different score scales between retrieval methods.
        """
        # Build ID -> rank mapping
        vector_ranks = {r["id"]: i + 1 for i, r in enumerate(vector_results)}
        fts_ranks = {r["id"]: i + 1 for i, r in enumerate(fts_results)}

        # Collect all unique IDs
        all_ids = set(vector_ranks.keys()) | set(fts_ranks.keys())

        # Calculate RRF scores
        scored = []
        for doc_id in all_ids:
            v_rank = vector_ranks.get(doc_id)
            f_rank = fts_ranks.get(doc_id)

            rrf_score = 0
            if v_rank is not None:
                rrf_score += vector_weight / (self.RRF_K + v_rank)
            if f_rank is not None:
                rrf_score += fts_weight / (self.RRF_K + f_rank)

            # Get document data from whichever result has it
            doc = None
            if doc_id in vector_ranks:
                idx = vector_ranks[doc_id] - 1
                doc = vector_results[idx]
            else:
                idx = fts_ranks[doc_id] - 1
                doc = fts_results[idx]

            scored.append(
                SearchResult(
                    id=doc_id,
                    content=doc["content"],
                    document_id=doc["document_id"],
                    vector_score=doc.get("_distance", 0) if v_rank else None,
                    fts_score=doc.get("_score", 0) if f_rank else None,
                    rrf_score=rrf_score,
                    metadata=doc.get("metadata", {}),
                    vector_rank=v_rank if debug else None,
                    fts_rank=f_rank if debug else None,
                )
            )

        # Sort by RRF score (descending)
        scored.sort(key=lambda x: x.rrf_score, reverse=True)

        return scored


def ensure_hybrid_search_ready(db, table_name: str = "child_chunks") -> HybridSearcher:
    """
    Factory function that creates a HybridSearcher with verified FTS index.

    This should be called during ingestion pipeline initialization.

    Raises:
        SearchError: If FTS index cannot be created
    """
    searcher = HybridSearcher(db, table_name)

    if not searcher.ensure_fts_index():
        raise SearchError(
            f"Failed to create FTS index on {table_name}. "
            "Hybrid search will not function correctly. "
            "Check LanceDB version and table schema."
        )

    return searcher


# Post-ingestion hook
def post_ingestion_index_update(db, table_name: str = "child_chunks"):
    """
    Call this after batch insertions to update FTS index.

    FTS indices in LanceDB may need rebuilding after large insertions
    for optimal performance.
    """
    try:
        table = db.open_table(table_name)
        # Rebuild FTS index
        table.create_fts_index("content", replace=True)
        logger.info(f"FTS index rebuilt for {table_name}")
    except Exception as e:
        logger.error(f"Failed to rebuild FTS index: {e}")
        raise SearchError(f"Failed to rebuild FTS index: {e}") from e
