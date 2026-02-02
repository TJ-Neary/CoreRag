# Performance Optimization Guide

> **Status**: ✅ Applied across codebase

> **Target Hardware**: 2024 MacBook Pro M4 Max, 48GB Unified Memory
>
> This guide ensures all code is optimized for Apple Silicon performance.

---

## M4 Max Specifications

| Component | Spec | Implication |
|-----------|------|-------------|
| CPU | 14-core (10 performance + 4 efficiency) | Use multiprocessing for CPU-bound tasks |
| GPU | 32-core | Leverage Metal/MLX for ML workloads |
| Neural Engine | 16-core | Some ML frameworks can utilize |
| Unified Memory | 48GB | No GPU memory transfer overhead |
| Memory Bandwidth | 400 GB/s | Fast model loading and inference |

---

## Critical Performance Rules

### 1. Use MLX Framework for ML Workloads

**MLX is Apple's native ML framework** - it's faster than PyTorch/TensorFlow on Apple Silicon.

```python
# ✅ PREFERRED: Use MLX-native libraries when available
import mlx_whisper  # For audio transcription

# ✅ GOOD: Use MLX directly for custom models
import mlx.core as mx
import mlx.nn as nn

# ⚠️ ACCEPTABLE: PyTorch with MPS backend
import torch
device = torch.device("mps")  # Metal Performance Shaders

# ❌ AVOID: CPU-only PyTorch for large models
device = torch.device("cpu")  # Wastes GPU potential
```

### 2. Sentence Transformers on Apple Silicon

```python
from sentence_transformers import SentenceTransformer

# ✅ CORRECT: Let it auto-detect MPS
model = SentenceTransformer("nomic-ai/nomic-embed-text-v1.5")
# It will use MPS (Metal) automatically on Apple Silicon

# For batch processing, optimal batch sizes:
EMBEDDING_BATCH_SIZE = 32  # Sweet spot for 48GB unified memory
```

### 3. Memory Management

With 48GB unified memory, you have flexibility, but should still be conscious:

```python
# ✅ GOOD: Process files in batches
def process_files_in_batches(files: List[Path], batch_size: int = 100):
    for i in range(0, len(files), batch_size):
        batch = files[i:i + batch_size]
        results = process_batch(batch)
        yield results
        # Memory freed between batches

# ✅ GOOD: Stream large files
def process_large_file(path: Path):
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            yield process_chunk(chunk)

# ❌ AVOID: Loading everything into memory
all_embeddings = []
for file in all_files:  # If all_files is huge, this explodes
    all_embeddings.append(embed(file))
```

### 4. Parallel Processing

```python
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import os

# CPU-bound tasks (file parsing, chunking): Use processes
# I/O-bound tasks (file reading, network): Use threads

# ✅ CORRECT: CPU-bound work with process pool
def process_documents_parallel(file_paths: List[Path]):
    # Use performance cores (10 on M4 Max)
    max_workers = min(10, os.cpu_count() or 4)

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(process_single_document, file_paths))
    return results

# ✅ CORRECT: I/O-bound work with thread pool
def read_files_parallel(file_paths: List[Path]):
    with ThreadPoolExecutor(max_workers=20) as executor:
        contents = list(executor.map(read_file, file_paths))
    return contents

# ⚠️ CAUTION: Don't parallelize GPU work this way
# GPU operations should be batched, not parallelized
```

### 5. LanceDB Optimization

```python
import lancedb

# ✅ CORRECT: Use appropriate index for dataset size
db = lancedb.connect("~/.corerag/lancedb")

# For < 100K vectors: Flat index is fine (no index needed)
table = db.create_table("chunks", data)

# For 100K - 1M vectors: IVF index
table.create_index(
    metric="cosine",
    num_partitions=256,  # sqrt(n) is a good starting point
    num_sub_vectors=96,  # For 768-dim vectors
)

# For > 1M vectors: IVF_PQ (quantized)
table.create_index(
    metric="cosine",
    index_type="IVF_PQ",
    num_partitions=1024,
    num_sub_vectors=48,
)

# ✅ CORRECT: Batch insertions
data_batches = [data[i:i+1000] for i in range(0, len(data), 1000)]
for batch in data_batches:
    table.add(batch)
```

---

## Optimal Batch Sizes

Based on 48GB unified memory:

| Operation | Batch Size | Memory Usage |
|-----------|------------|--------------|
| Embedding generation | 32 texts | ~2-4GB |
| Whisper transcription | 1 file (streaming) | ~4-6GB |
| LanceDB insert | 1000 rows | ~500MB |
| PDF processing | 10 files | ~2-3GB |
| Image processing | 20 images | ~1-2GB |

---

## Whisper (Audio) Optimization

```python
# ✅ CORRECT: Use mlx-whisper for Apple Silicon
import mlx_whisper

# For speed: use medium model
result = mlx_whisper.transcribe("audio.mp3", path_or_hf_repo="mlx-community/whisper-medium-mlx")

# For quality: use large-v3 model
result = mlx_whisper.transcribe("audio.mp3", path_or_hf_repo="mlx-community/whisper-large-v3-mlx")

# For very long audio (>1 hour): Stream in chunks
# mlx-whisper handles this automatically
```

---

## Vision Model Optimization

```python
# For local image/video description, use smaller models

# ✅ GOOD: LLaVA 7B fits well in 48GB
# Leaves room for embeddings and other operations

# ⚠️ CAUTION: LLaVA 13B uses ~16GB
# Still works but less headroom

# ❌ AVOID: LLaVA 34B needs >40GB
# Would starve other operations
```

---

## File Processing Pipeline

```python
from typing import Generator
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor

def optimized_ingestion_pipeline(
    input_dir: Path,
    batch_size: int = 100,
    max_workers: int = 8
) -> Generator:
    """
    Optimized pipeline for M4 Max.

    Uses:
    - Parallel file discovery (I/O bound - threads)
    - Parallel parsing (CPU bound - processes)
    - Batched embedding (GPU bound - sequential batches)
    - Streaming database inserts
    """
    # Phase 1: Discover files (fast, I/O bound)
    files = list(input_dir.rglob("*"))

    # Phase 2: Parse in parallel (CPU bound)
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        for batch_start in range(0, len(files), batch_size):
            batch_files = files[batch_start:batch_start + batch_size]

            # Parse batch in parallel
            parsed_docs = list(executor.map(parse_file, batch_files))

            # Phase 3: Chunk (fast, CPU)
            all_chunks = []
            for doc in parsed_docs:
                if doc:
                    all_chunks.extend(chunk_document(doc))

            # Phase 4: Embed in GPU batches
            for i in range(0, len(all_chunks), 32):
                chunk_batch = all_chunks[i:i + 32]
                embeddings = embed_batch([c.text for c in chunk_batch])

                for chunk, emb in zip(chunk_batch, embeddings):
                    chunk.embedding = emb

                # Phase 5: Stream to database
                yield chunk_batch
```

---

## Monitoring Performance

```python
import time
import psutil
import os

class PerformanceMonitor:
    """Monitor resource usage during operations."""

    def __init__(self):
        self.process = psutil.Process(os.getpid())

    def log_usage(self, operation: str):
        mem = self.process.memory_info()
        cpu = self.process.cpu_percent()

        print(f"[{operation}] Memory: {mem.rss / 1e9:.2f}GB, CPU: {cpu:.1f}%")

        # Warn if memory is getting high
        if mem.rss > 40e9:  # 40GB of 48GB
            print("⚠️ WARNING: High memory usage, consider smaller batches")

# Usage
monitor = PerformanceMonitor()

for batch in process_files(files):
    monitor.log_usage("Processing batch")
```

---

## Environment Variables for Performance

```bash
# .env file

# Parallelism
CORERAG_MAX_WORKERS=8                    # CPU workers (leave cores for system)
CORERAG_EMBEDDING_BATCH_SIZE=32          # GPU batch size

# Memory limits
CoreRag_MAX_MEMORY_GB=40                 # Leave 8GB for system
CORERAG_CHUNK_BUFFER_SIZE=1000           # Chunks to buffer before DB write

# MLX/Metal settings
PYTORCH_ENABLE_MPS_FALLBACK=1        # Fallback for unsupported ops
MLX_USE_DEFAULT_DEVICE=1             # Use GPU by default
```

---

## Benchmarks to Target

Based on M4 Max capabilities:

| Operation | Target | Notes |
|-----------|--------|-------|
| PDF page extraction | 100+ pages/sec | With parallel processing |
| Embedding generation | 1000+ texts/sec | With batching |
| LanceDB query | < 50ms | With proper indexing |
| Whisper transcription | 10-20x realtime | With large-v3 |
| Full file ingestion | 50+ files/min | Mixed file types |

---

## Anti-Patterns to Avoid

```python
# ❌ DON'T: Process one item at a time with GPU
for text in texts:
    embedding = model.encode(text)  # GPU underutilized!

# ✅ DO: Batch for GPU efficiency
embeddings = model.encode(texts, batch_size=32)


# ❌ DON'T: Load huge models repeatedly
for file in files:
    model = SentenceTransformer(...)  # Slow! Loads each time
    embed(file)

# ✅ DO: Load once, reuse
model = SentenceTransformer(...)
for file in files:
    embed(file, model=model)


# ❌ DON'T: Ignore memory in loops
all_results = []
for file in million_files:
    all_results.append(process(file))  # Memory explodes

# ✅ DO: Stream results
def process_all():
    for file in million_files:
        yield process(file)  # Constant memory
```

---

*Follow these guidelines to maximize M4 Max performance. Update benchmarks as real measurements are collected.*
