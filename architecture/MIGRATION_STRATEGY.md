# Embedding Model Migration Strategy

> **Status**: ✅ Implemented | See `src/embeddings/embedding_service.py` for implementation

## Overview

As embedding models improve, you may want to migrate to a newer model without losing your knowledge base. This document outlines the strategy for safely migrating embeddings.

---

## Why Migrate?

| Reason | Example |
|--------|---------|
| Better quality | nomic-embed-text-v2 released with 15% better retrieval |
| Dimension change | Moving from 768 to 1024 dimensions |
| Multimodal | Adding image embedding capability |
| Performance | Faster model available |
| Cost | Cheaper API alternative found |

---

## Migration Approaches

### Approach 1: Parallel Index (Recommended)

Run both old and new embeddings simultaneously during transition.

```
                    ┌─────────────────┐
                    │   New Content   │
                    └────────┬────────┘
                             │
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│  Old Index      │ │  New Index      │ │  Transition     │
│  (v1 model)     │ │  (v2 model)     │ │  Tracking       │
│  [read-only]    │ │  [read-write]   │ │                 │
└─────────────────┘ └─────────────────┘ └─────────────────┘
         │                   │                   │
         └───────────────────┼───────────────────┘
                             ▼
                    ┌─────────────────┐
                    │  Hybrid Search  │
                    │  (merge results)│
                    └─────────────────┘
```

**Pros**: No downtime, can compare quality, easy rollback
**Cons**: 2x storage during migration, complex search logic

### Approach 2: In-Place Reindexing

Recompute embeddings for all content using new model.

```
1. Create backup
2. For each document in batches:
   - Load content
   - Compute new embedding
   - Update vector in place
3. Verify integrity
4. Delete backup
```

**Pros**: No extra storage long-term
**Cons**: Downtime during migration, no comparison period

### Approach 3: Shadow Index

Build new index in background, then swap.

```
1. Create new empty index
2. Background job: populate new index
3. Track changes during migration
4. Apply pending changes to new index
5. Atomic swap: new → active, old → archive
```

**Pros**: Minimal downtime (only during swap)
**Cons**: Requires change tracking, complex logic

---

## Migration Procedure (Parallel Approach)

### Phase 1: Preparation

```python
# 1. Create migration plan
migration = MigrationManager(
    old_model="nomic-embed-text-v1.5",
    new_model="nomic-embed-text-v2",
    old_dimensions=768,
    new_dimensions=1024
)

# 2. Estimate resources
estimate = migration.estimate_work()
print(f"Documents: {estimate['total_documents']}")
print(f"Estimated time: {estimate['hours']} hours")
print(f"Storage needed: {estimate['storage_gb']} GB")

# 3. Create backup
backup.create_backup("pre_migration")
```

### Phase 2: Build New Index

```python
# 4. Create parallel index structure
migration.create_new_index()

# 5. Start background migration
job = migration.start_background_migration(
    batch_size=100,
    workers=4,
    use_safe_processor=True  # Respect hardware limits
)

# 6. Monitor progress
while not job.is_complete:
    progress = migration.get_progress()
    print(f"Progress: {progress['percent']:.1f}%")
    print(f"Rate: {progress['docs_per_minute']}/min")
    print(f"ETA: {progress['eta_minutes']} minutes")
    time.sleep(60)
```

### Phase 3: Validation

```python
# 7. Run quality comparison
comparison = migration.compare_search_quality(
    test_queries=VALIDATION_QUERIES,
    sample_size=100
)

print(f"Old model MRR: {comparison['old_mrr']:.3f}")
print(f"New model MRR: {comparison['new_mrr']:.3f}")
print(f"Improvement: {comparison['improvement']:.1%}")

# 8. User acceptance testing
# Run both indexes in parallel for 1 week
# Collect feedback on result quality
migration.enable_ab_testing(new_model_percentage=50)
```

### Phase 4: Cutover

```python
# 9. If quality is acceptable, switch
if comparison['improvement'] > 0:
    migration.set_primary_index("new")
    migration.set_fallback_index("old")

# 10. After 30 days with no issues
migration.archive_old_index()
migration.cleanup()
```

---

## Code: Migration Manager

```python
# src/utils/migration.py

class MigrationManager:
    """Manage embedding model migrations."""

    def __init__(
        self,
        old_model: str,
        new_model: str,
        old_dimensions: int,
        new_dimensions: int,
        db_path: Path
    ):
        self.old_model = old_model
        self.new_model = new_model
        self.old_dimensions = old_dimensions
        self.new_dimensions = new_dimensions
        self.db_path = db_path

        self.old_index = f"vectors_v1_{old_model.replace('-', '_')}"
        self.new_index = f"vectors_v2_{new_model.replace('-', '_')}"

    def estimate_work(self) -> Dict:
        """Estimate migration workload."""
        # Count documents
        db = lancedb.connect(self.db_path)
        old_table = db.open_table(self.old_index)
        total_docs = len(old_table)

        # Estimate based on benchmarks
        docs_per_minute = 50  # Conservative estimate
        hours = total_docs / docs_per_minute / 60

        # Storage estimate (new dimensions)
        storage_per_doc = self.new_dimensions * 4  # float32
        storage_gb = total_docs * storage_per_doc / 1e9

        return {
            "total_documents": total_docs,
            "hours": hours,
            "storage_gb": storage_gb
        }

    def create_new_index(self) -> None:
        """Create new index with updated schema."""
        db = lancedb.connect(self.db_path)

        schema = {
            "id": str,
            "content": str,
            "embedding": f"vector[{self.new_dimensions}]",
            "migrated_at": str,
            "source_id": str  # Link to original
        }

        db.create_table(self.new_index, schema=schema)

    def migrate_batch(self, batch_ids: List[str]) -> Dict:
        """Migrate a batch of documents."""
        db = lancedb.connect(self.db_path)
        old_table = db.open_table(self.old_index)
        new_table = db.open_table(self.new_index)

        # Load content
        docs = old_table.search().where(f"id IN {batch_ids}").to_list()

        # Generate new embeddings
        new_embeddings = embed_with_model(
            texts=[d["content"] for d in docs],
            model=self.new_model
        )

        # Insert into new table
        new_records = []
        for doc, embedding in zip(docs, new_embeddings):
            new_records.append({
                "id": doc["id"],
                "content": doc["content"],
                "embedding": embedding,
                "migrated_at": datetime.now().isoformat(),
                "source_id": doc["id"]
            })

        new_table.add(new_records)

        return {"migrated": len(new_records)}

    def compare_search_quality(
        self,
        test_queries: List[Dict],
        sample_size: int = 100
    ) -> Dict:
        """Compare search quality between models."""
        db = lancedb.connect(self.db_path)
        old_table = db.open_table(self.old_index)
        new_table = db.open_table(self.new_index)

        old_scores = []
        new_scores = []

        for test in test_queries[:sample_size]:
            query = test["query"]
            expected = test["expected_results"]

            # Search old index
            old_results = old_table.search(
                embed_with_model(query, self.old_model)
            ).limit(10).to_list()

            # Search new index
            new_results = new_table.search(
                embed_with_model(query, self.new_model)
            ).limit(10).to_list()

            # Compute MRR
            old_mrr = compute_mrr(old_results, expected)
            new_mrr = compute_mrr(new_results, expected)

            old_scores.append(old_mrr)
            new_scores.append(new_mrr)

        avg_old = sum(old_scores) / len(old_scores)
        avg_new = sum(new_scores) / len(new_scores)

        return {
            "old_mrr": avg_old,
            "new_mrr": avg_new,
            "improvement": (avg_new - avg_old) / avg_old
        }
```

---

## Dimension Change Handling

If new model has different dimensions:

### Option A: Separate Tables

```python
# Old: vectors_768
# New: vectors_1024
# Keep separate, search appropriate table based on model version
```

### Option B: Padding/Truncation (Not Recommended)

```python
# Pad 768 → 1024 with zeros
# Truncate 1024 → 768
# Quality loss, not recommended
```

### Option C: Projection Layer

```python
# Train linear projection: 768 → 1024
# Allows unified search space
# Requires training data
```

---

## Rollback Procedure

If migration fails or quality decreases:

```python
# 1. Stop using new index
migration.disable_new_index()

# 2. Restore old index as primary
migration.set_primary_index("old")

# 3. Investigate issues
issues = migration.diagnose_failures()

# 4. Optionally delete new index
migration.delete_new_index()  # After confirmation
```

---

## Checklist

- [ ] Create full backup before starting
- [ ] Estimate time and storage requirements
- [ ] Set up monitoring for migration job
- [ ] Define quality metrics and thresholds
- [ ] Plan A/B testing period
- [ ] Prepare rollback procedure
- [ ] Schedule during low-usage period
- [ ] Notify stakeholders of timeline
- [ ] Keep old index for 30+ days after cutover
