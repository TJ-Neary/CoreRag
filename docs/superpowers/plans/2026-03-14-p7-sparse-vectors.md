# P7 Task 1: BGE-M3 Sparse Vectors for 3-Way Hybrid Search

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add learned sparse vectors (BGE-M3 lexical weights) as a third retrieval signal alongside dense vectors and BM25, enabling 3-way hybrid search via LanceDB's native sparse support.

**Architecture:** Use `FlagEmbedding.BGEM3FlagModel` for dual dense+sparse encoding. Store sparse vectors in a new `sparse_vector` column (LanceDB `SparseVector` type). Modify `HybridSearcher` to perform 3-way search using LanceDB's built-in multi-vector API. Re-embed all 7,329 chunks via the existing backfill script.

**Tech Stack:** FlagEmbedding (new dep), LanceDB v0.27+ (SparseVector, SPARSE_INVERTED index), sentence-transformers (existing)

**Research:** `_RESEARCH/sparse_vector_feasibility.md` — confirms LanceDB native support, MPS compatibility, 2-5% encoding overhead.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `requirements.txt` | Modify | Add FlagEmbedding |
| `src/embeddings/embedding_service.py` | Modify | Add `embed_with_sparse()` method using BGEM3FlagModel |
| `src/search/hybrid_search.py` | Modify | 3-way search using LanceDB multi-vector API |
| `scripts/migrate_embeddings.py` | Modify | Add `--include-sparse` flag for sparse column migration |
| `src/ingest_service.py` | Modify | Use `embed_with_sparse()` when available |

---

## Task 1: Install FlagEmbedding + Add Sparse Encoding

**Files:**
- Modify: `requirements.txt`
- Modify: `src/embeddings/embedding_service.py`

- [ ] **Step 1: Install FlagEmbedding**

```bash
source venv/bin/activate
pip install FlagEmbedding
```

- [ ] **Step 2: Add to requirements.txt**

Add after the `sentence-transformers` line:
```
FlagEmbedding>=1.2.0
```

- [ ] **Step 3: Add `embed_with_sparse()` method to EmbeddingService**

Add a new method that returns both dense and sparse vectors. Use `BGEM3FlagModel` only when the model is `BAAI/bge-m3` — fall back to dense-only for other models.

```python
def embed_with_sparse(
    self, documents: list[str], show_progress: bool = True
) -> tuple[list[list[float]], list[dict[int, float]]]:
    """Return (dense_vectors, sparse_vectors) using BGE-M3's dual output.

    Sparse vectors are dicts of {token_id: weight}. Only available for BGE-M3.
    For other models, returns empty dicts as sparse vectors.
    """
    if "bge-m3" not in self.model_name.lower():
        dense = self.embed_documents(documents, show_progress=show_progress)
        return dense, [{}] * len(documents)

    if not hasattr(self, "_flag_model"):
        from FlagEmbedding import BGEM3FlagModel
        import torch

        device = "mps" if torch.backends.mps.is_available() else "cpu"
        self._flag_model = BGEM3FlagModel(
            self.model_name, use_fp16=(device != "cpu"), devices=device
        )

    output = self._flag_model.encode(
        documents, return_dense=True, return_sparse=True, batch_size=32
    )

    dense_vecs = output["dense_vecs"].tolist()
    sparse_vecs = [
        {int(k): float(v) for k, v in weights.items()}
        for weights in output["lexical_weights"]
    ]

    return dense_vecs, sparse_vecs
```

Similarly add `embed_query_with_sparse()`:

```python
def embed_query_with_sparse(self, query: str) -> tuple[list[float], dict[int, float]]:
    """Embed a query returning both dense vector and sparse weights."""
    dense_list, sparse_list = self.embed_with_sparse([query], show_progress=False)
    return dense_list[0], sparse_list[0]
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/ --tb=short -q`
Expected: All 623 pass (new methods don't affect existing tests).

- [ ] **Step 5: Commit**

```bash
git add requirements.txt src/embeddings/embedding_service.py
git commit -m "feat: add sparse vector encoding via FlagEmbedding BGEM3FlagModel"
```

---

## Task 2: Update HybridSearcher for 3-Way Search

**Files:**
- Modify: `src/search/hybrid_search.py`

- [ ] **Step 1: Add `_sparse_search()` method**

Add alongside existing `_vector_search()` and `_fts_search()`:

```python
async def _sparse_search(
    self, query_sparse: dict[int, float], k: int, filters=None
) -> list:
    """Search using sparse vector (learned lexical weights)."""
    try:
        search_op = self.table.search(query_sparse, vector_column_name="sparse_vector").limit(k)
        if filters:
            clause = build_filter_clause(filters)
            if clause:
                search_op = search_op.where(clause)
        return search_op.to_list()
    except Exception as e:
        logger.warning(f"Sparse search failed (non-fatal): {e}")
        return []
```

- [ ] **Step 2: Update `search()` to use 3-way fusion when sparse is available**

Modify the `search()` method to check if `sparse_vector` column exists, and if the caller provides a sparse query vector:

```python
async def search(
    self,
    query: str,
    query_vector: list[float],
    k: int = 10,
    vector_weight: float = 0.5,
    fts_weight: float = 0.2,
    sparse_weight: float = 0.3,
    query_sparse: dict[int, float] | None = None,
    filters: dict | None = None,
    debug: bool = False,
) -> list[SearchResult]:
```

Inside the method, after the existing vector + FTS searches:

```python
# Sparse search (if sparse query provided and column exists)
sparse_results = []
if query_sparse:
    sparse_results = await self._sparse_search(query_sparse, oversample, filters)

# Fuse with 3-way RRF
fused = self._reciprocal_rank_fusion_3way(
    vector_results, fts_results, sparse_results,
    vector_weight, fts_weight, sparse_weight, debug
)
```

- [ ] **Step 3: Add `_reciprocal_rank_fusion_3way()`**

Extend the existing RRF to handle 3 result lists:

```python
def _reciprocal_rank_fusion_3way(
    self, vector_results, fts_results, sparse_results,
    vector_weight, fts_weight, sparse_weight, debug
) -> list[SearchResult]:
    """3-way RRF fusion: dense + FTS + sparse."""
    # Build rank maps
    v_ranks = {r.get("id", r.get("_rowid", i)): i + 1 for i, r in enumerate(vector_results)}
    f_ranks = {r.get("id", r.get("_rowid", i)): i + 1 for i, r in enumerate(fts_results)}
    s_ranks = {r.get("id", r.get("_rowid", i)): i + 1 for i, r in enumerate(sparse_results)}

    all_ids = set(v_ranks) | set(f_ranks) | set(s_ranks)
    doc_data = {}
    for r in vector_results + fts_results + sparse_results:
        rid = r.get("id", r.get("_rowid"))
        if rid and rid not in doc_data:
            doc_data[rid] = r

    scored = []
    for doc_id in all_ids:
        score = 0.0
        if doc_id in v_ranks:
            score += vector_weight / (self.RRF_K + v_ranks[doc_id])
        if doc_id in f_ranks:
            score += fts_weight / (self.RRF_K + f_ranks[doc_id])
        if doc_id in s_ranks:
            score += sparse_weight / (self.RRF_K + s_ranks[doc_id])

        r = doc_data.get(doc_id, {})
        scored.append(SearchResult(
            id=doc_id,
            content=r.get("content", ""),
            document_id=r.get("document_id", ""),
            vector_score=r.get("_distance", 0),
            fts_score=r.get("_score"),
            rrf_score=score,
            metadata={k: v for k, v in r.items() if k not in ("content", "vector", "sparse_vector", "_distance", "_score", "_rowid")},
        ))

    scored.sort(key=lambda x: x.rrf_score, reverse=True)
    return scored
```

- [ ] **Step 4: Maintain backward compatibility**

When `query_sparse` is None (callers that don't have sparse vectors), fall back to existing 2-way fusion. The default `sparse_weight=0.3` only activates when sparse results are present.

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_hybrid_search.py -v --tb=short`
Expected: All existing tests pass (they don't provide `query_sparse`, so 2-way fusion is used).

- [ ] **Step 6: Commit**

```bash
git add src/search/hybrid_search.py
git commit -m "feat: 3-way RRF fusion in HybridSearcher (dense + sparse + BM25)"
```

---

## Task 3: Migrate Existing Chunks (Add Sparse Column)

**Files:**
- Modify: `scripts/migrate_embeddings.py`

- [ ] **Step 1: Add `--include-sparse` flag**

Add a CLI argument:
```python
parser.add_argument("--include-sparse", action="store_true",
                    help="Generate sparse vectors alongside dense (requires FlagEmbedding)")
```

- [ ] **Step 2: Implement sparse migration logic**

When `--include-sparse` is set:
1. Use `EmbeddingService.embed_with_sparse()` instead of `embed_documents()`
2. Add `sparse_vector` column to the output data
3. Create `SPARSE_INVERTED` index after table creation

Key code:
```python
if args.include_sparse:
    dense_vecs, sparse_vecs = embedder.embed_with_sparse(texts, show_progress=True)
    for i, row in enumerate(child_data):
        row["vector"] = dense_vecs[i]
        row["sparse_vector"] = sparse_vecs[i]
else:
    vectors = embedder.embed_documents(texts, show_progress=True)
    for i, row in enumerate(child_data):
        row["vector"] = vectors[i]
```

After table creation:
```python
if args.include_sparse:
    try:
        table.create_index(column="sparse_vector", index_type="SPARSE_INVERTED")
        logger.info("Sparse inverted index created")
    except Exception as e:
        logger.warning(f"Sparse index creation failed (non-fatal): {e}")
```

- [ ] **Step 3: Run migration (dry-run first)**

```bash
python scripts/migrate_embeddings.py --include-sparse --dry-run
python scripts/migrate_embeddings.py --include-sparse
```

Expected: ~2-5 minutes for 7,329 chunks. Each chunk gets both a 1024d dense vector and a sparse weight dict.

- [ ] **Step 4: Commit**

```bash
git add scripts/migrate_embeddings.py
git commit -m "feat: sparse vector migration support in migrate_embeddings.py"
```

---

## Task 4: Wire Sparse Into Search Pipeline

**Files:**
- Modify: `src/mcp_server/server.py` (search_knowledge handler)
- Modify: `src/api/v1_routes.py` (REST search endpoint)

- [ ] **Step 1: Update MCP search_knowledge to pass sparse query**

In `server.py`, where `search_knowledge` calls `hybrid_searcher.search()`, add sparse query:

```python
# After embedding the query
query_vector = _embedding_service.embed_query(search_text)

# Generate sparse query if available
query_sparse = None
if hasattr(_embedding_service, 'embed_query_with_sparse'):
    try:
        _, query_sparse = _embedding_service.embed_query_with_sparse(search_text)
    except Exception:
        pass  # Fall back to 2-way

results = await hybrid_searcher.search(
    query=search_text,
    query_vector=query_vector,
    query_sparse=query_sparse,
    k=k,
    filters=filters,
)
```

- [ ] **Step 2: Update REST search endpoint similarly**

In `v1_routes.py`, where the search endpoint calls `hybrid_searcher.search()`, add the same sparse query generation.

- [ ] **Step 3: Run full test suite**

Run: `pytest --tb=short -q`
Expected: All 623+ pass. Sparse is additive — callers that don't have sparse data get 2-way fusion.

- [ ] **Step 4: Commit**

```bash
git add src/mcp_server/server.py src/api/v1_routes.py
git commit -m "feat: wire sparse query vectors into MCP and REST search pipelines"
```

---

## Task 5: Update IngestService for Dual Encoding

**Files:**
- Modify: `src/ingest_service.py`

- [ ] **Step 1: Use `embed_with_sparse()` when available**

In the embedding phase of `IngestService.ingest()`, check if the embedder supports sparse:

```python
# ── Embed (context + content) ─────────────────────────────
embed_texts = []
for c, ctx in zip(children, context_prefixes):
    embed_texts.append(f"{ctx}\n\n{c.content}" if ctx else c.content)

# Dual encoding if sparse is available
sparse_vecs = [{}] * len(embed_texts)
if hasattr(self._embedder, 'embed_with_sparse'):
    try:
        embeddings, sparse_vecs = self._embedder.embed_with_sparse(
            embed_texts, show_progress=False
        )
    except Exception:
        embeddings = self._embedder.embed_documents(embed_texts, show_progress=False)
else:
    embeddings = self._embedder.embed_documents(embed_texts, show_progress=False)
```

Then add `sparse_vector` to the child data dict:
```python
child_data.append({
    ...
    "vector": embeddings[i],
    "sparse_vector": sparse_vecs[i],  # Empty dict if sparse not available
    ...
})
```

- [ ] **Step 2: Run tests**

Run: `pytest --tb=short -q`
Expected: All pass. Empty sparse dicts are valid LanceDB SparseVector values.

- [ ] **Step 3: Commit**

```bash
git add src/ingest_service.py
git commit -m "feat: IngestService generates sparse vectors during ingestion"
```

---

## Verification

After all tasks complete:

- [ ] **Run full test suite**

Run: `pytest --tb=short -q`
Expected: 623+ pass, no regressions.

- [ ] **Run migration to add sparse vectors to existing data**

```bash
python scripts/migrate_embeddings.py --include-sparse
```

- [ ] **Test 3-way search manually**

```python
# Quick verification
from src.embeddings.embedding_service import create_embedding_service
svc = create_embedding_service()
dense, sparse = svc.embed_query_with_sparse("test query about Python")
print(f"Dense: {len(dense)} dims, Sparse: {len(sparse)} non-zero entries")
```

---

## Summary

| Task | What | Files | Effort |
|------|------|-------|--------|
| 1 | FlagEmbedding + sparse encoding | requirements.txt, embedding_service.py | ~30 lines |
| 2 | 3-way RRF fusion | hybrid_search.py | ~60 lines |
| 3 | Migration script | migrate_embeddings.py | ~20 lines |
| 4 | Wire into search pipeline | server.py, v1_routes.py | ~15 lines |
| 5 | IngestService dual encoding | ingest_service.py | ~10 lines |

**Total: 5 tasks, ~135 lines, estimated 30-45 minutes + migration time.**
