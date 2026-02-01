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
from src.search.decay_scoring import (
    DecayConfig,
    apply_decay_to_results,
    combined_temporal_scoring,
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
    # Decay Scoring
    "DecayConfig",
    "apply_decay_to_results",
    "combined_temporal_scoring",
]
