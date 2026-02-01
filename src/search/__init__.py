"""Search module for PKM."""

from src.search.hyde import (
    HyDEExpander,
    HyDESearcher,
    HyDEResult,
    HyDEConfig,
    create_hyde_expander,
    hyde_search,
)
from src.search.multi_query import (
    MultiQuerySearcher,
    QueryDecomposer,
    ReciprocalRankFusion,
    SubQuery,
    FusedResult,
    MultiQueryResult,
    multi_query_search,
)

__all__ = [
    # HyDE
    "HyDEExpander",
    "HyDESearcher",
    "HyDEResult",
    "HyDEConfig",
    "create_hyde_expander",
    "hyde_search",
    # Multi-Query
    "MultiQuerySearcher",
    "QueryDecomposer",
    "ReciprocalRankFusion",
    "SubQuery",
    "FusedResult",
    "MultiQueryResult",
    "multi_query_search",
]
