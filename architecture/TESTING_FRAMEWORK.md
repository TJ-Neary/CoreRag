# Testing & Validation Framework

> **Status**: ✅ Implemented | See `tests/golden_set/` for implementation

> Compare local vs API options with data-driven decisions.

---

## Overview

This framework enables systematic comparison of:
- **Embedding models** (local vs OpenAI)
- **Transcription** (mlx-whisper vs OpenAI Whisper API)
- **Vision models** (local LLaVA vs GPT-4 Vision)
- **Chunking strategies** (semantic vs fixed-size)

The goal: **Make informed decisions about when local is "good enough" vs when APIs are worth the cost.**

---

## Quality Metrics

### Embedding Quality

| Metric | Description | How to Measure |
|--------|-------------|----------------|
| **Retrieval Accuracy** | Does the right document come back? | % of queries where ground-truth doc is in top-K |
| **MRR (Mean Reciprocal Rank)** | How high is the right doc ranked? | 1/rank averaged across queries |
| **Semantic Coherence** | Do similar docs cluster together? | Cosine similarity within known-similar docs |
| **Query Latency** | How fast is search? | ms per query (p50, p95, p99) |

### Transcription Quality

| Metric | Description | How to Measure |
|--------|-------------|----------------|
| **WER (Word Error Rate)** | Transcription accuracy | Levenshtein distance vs ground truth |
| **Punctuation Accuracy** | Proper sentences? | Manual spot-check score |
| **Speaker Diarization** | Who said what? | If needed, compare speaker labels |
| **Processing Speed** | Realtime factor | audio_duration / processing_time |

### Vision/Description Quality

| Metric | Description | How to Measure |
|--------|-------------|----------------|
| **Content Coverage** | Are key elements described? | Checklist of expected elements |
| **Accuracy** | Are descriptions correct? | Manual review score (1-5) |
| **Searchability** | Can you find the image later? | Query hit rate |

---

## A/B Testing Framework

### Test Configuration

```yaml
# tests/ab_config.yaml

embedding_models:
  - name: "nomic-local"
    type: "local"
    model: "nomic-ai/nomic-embed-text-v1.5"
    cost_per_1k_tokens: 0.0

  - name: "openai-small"
    type: "api"
    model: "text-embedding-3-small"
    cost_per_1k_tokens: 0.00002

  - name: "openai-large"
    type: "api"
    model: "text-embedding-3-large"
    cost_per_1k_tokens: 0.00013

transcription_models:
  - name: "mlx-whisper-medium"
    type: "local"
    model: "mlx-community/whisper-medium-mlx"
    cost_per_minute: 0.0

  - name: "mlx-whisper-large"
    type: "local"
    model: "mlx-community/whisper-large-v3-mlx"
    cost_per_minute: 0.0

  - name: "openai-whisper"
    type: "api"
    model: "whisper-1"
    cost_per_minute: 0.006

test_datasets:
  embeddings:
    - name: "retrieval_benchmark"
      queries: "tests/data/benchmark_queries.json"
      ground_truth: "tests/data/ground_truth.json"

  transcription:
    - name: "audio_benchmark"
      files: "tests/data/audio_samples/"
      ground_truth: "tests/data/transcripts/"
```

### Test Runner

```python
# tests/ab_test_runner.py

from dataclasses import dataclass
from typing import List, Dict, Any
import json
import time
from pathlib import Path

@dataclass
class TestResult:
    model_name: str
    model_type: str  # "local" or "api"
    metric_name: str
    metric_value: float
    latency_ms: float
    cost_usd: float
    timestamp: str

class ABTestRunner:
    """Run A/B tests comparing local vs API models."""

    def __init__(self, config_path: Path):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)
        self.results: List[TestResult] = []

    def run_embedding_comparison(self, queries: List[str], ground_truth: Dict) -> List[TestResult]:
        """Compare embedding models on retrieval task."""
        results = []

        for model_config in self.config["embedding_models"]:
            model = self._load_embedding_model(model_config)

            # Run test
            start = time.time()
            predictions = self._run_retrieval(model, queries)
            latency = (time.time() - start) * 1000

            # Calculate metrics
            accuracy = self._calculate_retrieval_accuracy(predictions, ground_truth)
            mrr = self._calculate_mrr(predictions, ground_truth)

            # Calculate cost
            total_tokens = sum(len(q.split()) * 1.3 for q in queries)  # Rough estimate
            cost = (total_tokens / 1000) * model_config["cost_per_1k_tokens"]

            results.append(TestResult(
                model_name=model_config["name"],
                model_type=model_config["type"],
                metric_name="accuracy@10",
                metric_value=accuracy,
                latency_ms=latency,
                cost_usd=cost,
                timestamp=datetime.now().isoformat()
            ))

            results.append(TestResult(
                model_name=model_config["name"],
                model_type=model_config["type"],
                metric_name="mrr",
                metric_value=mrr,
                latency_ms=latency,
                cost_usd=cost,
                timestamp=datetime.now().isoformat()
            ))

        return results

    def run_transcription_comparison(self, audio_files: List[Path], ground_truth: Dict) -> List[TestResult]:
        """Compare transcription models on accuracy."""
        results = []

        for model_config in self.config["transcription_models"]:
            for audio_file in audio_files:
                # Run transcription
                start = time.time()
                transcript = self._transcribe(model_config, audio_file)
                latency = (time.time() - start) * 1000

                # Calculate WER
                expected = ground_truth[audio_file.name]
                wer = self._calculate_wer(transcript, expected)

                # Calculate cost
                duration_minutes = self._get_audio_duration(audio_file) / 60
                cost = duration_minutes * model_config["cost_per_minute"]

                results.append(TestResult(
                    model_name=model_config["name"],
                    model_type=model_config["type"],
                    metric_name="wer",
                    metric_value=wer,
                    latency_ms=latency,
                    cost_usd=cost,
                    timestamp=datetime.now().isoformat()
                ))

        return results

    def generate_report(self, results: List[TestResult]) -> str:
        """Generate comparison report."""
        report = ["# A/B Test Results\n"]

        # Group by metric
        by_metric = {}
        for r in results:
            if r.metric_name not in by_metric:
                by_metric[r.metric_name] = []
            by_metric[r.metric_name].append(r)

        for metric, metric_results in by_metric.items():
            report.append(f"\n## {metric}\n")
            report.append("| Model | Type | Score | Latency | Cost |")
            report.append("|-------|------|-------|---------|------|")

            # Sort by score (higher is better, except WER)
            reverse = metric != "wer"
            sorted_results = sorted(metric_results, key=lambda x: x.metric_value, reverse=reverse)

            for r in sorted_results:
                report.append(
                    f"| {r.model_name} | {r.model_type} | {r.metric_value:.4f} | "
                    f"{r.latency_ms:.0f}ms | ${r.cost_usd:.4f} |"
                )

        # Recommendation
        report.append("\n## Recommendation\n")
        report.append(self._generate_recommendation(results))

        return "\n".join(report)

    def _generate_recommendation(self, results: List[TestResult]) -> str:
        """Generate data-driven recommendation."""
        # Find best local and best API for each metric
        recommendations = []

        # Group results
        local_results = [r for r in results if r.model_type == "local"]
        api_results = [r for r in results if r.model_type == "api"]

        if not api_results:
            return "Only local models tested. Run with API models for comparison."

        # Compare quality
        local_avg = sum(r.metric_value for r in local_results) / len(local_results)
        api_avg = sum(r.metric_value for r in api_results) / len(api_results)

        quality_diff = abs(api_avg - local_avg) / api_avg * 100

        if quality_diff < 5:
            recommendations.append(
                f"✅ **Local is recommended**: Quality difference is only {quality_diff:.1f}% "
                "with zero ongoing cost."
            )
        elif quality_diff < 15:
            recommendations.append(
                f"⚠️ **Consider hybrid**: API is {quality_diff:.1f}% better. "
                "Use local for most queries, API for important ones."
            )
        else:
            recommendations.append(
                f"🔴 **API recommended for quality**: {quality_diff:.1f}% quality improvement "
                "may justify the cost for production use."
            )

        return "\n".join(recommendations)
```

---

## Benchmark Datasets

### Creating Ground Truth

```python
# tests/create_benchmark.py

def create_retrieval_benchmark(
    documents: List[Document],
    num_queries: int = 100
) -> Dict:
    """
    Create benchmark with ground truth.

    For each query, we know which document(s) should be retrieved.
    """
    benchmark = {
        "queries": [],
        "ground_truth": {}
    }

    for doc in documents[:num_queries]:
        # Generate query from document content
        # (In production, use human-written queries)
        query = generate_query_from_doc(doc)

        benchmark["queries"].append({
            "id": str(uuid.uuid4()),
            "text": query,
            "expected_doc_id": doc.id
        })

        benchmark["ground_truth"][query] = {
            "doc_id": doc.id,
            "doc_title": doc.title,
            "relevance": 1.0
        }

    return benchmark
```

### Sample Benchmark Structure

```
tests/data/
├── benchmark_queries.json      # 100 test queries
├── ground_truth.json           # Expected results
├── audio_samples/
│   ├── sample_01.mp3           # 1-minute clips
│   ├── sample_02.mp3
│   └── ...
└── transcripts/
    ├── sample_01.txt           # Human-verified transcripts
    ├── sample_02.txt
    └── ...
```

---

## Decision Matrix

Use this matrix to decide when to use local vs API:

```python
# src/utils/model_selector.py

from dataclasses import dataclass
from typing import Literal

@dataclass
class ModelDecision:
    model_name: str
    model_type: Literal["local", "api"]
    reason: str

class ModelSelector:
    """Select optimal model based on context."""

    def __init__(self, benchmark_results: Dict):
        self.benchmarks = benchmark_results

    def select_embedding_model(
        self,
        privacy_tier: str,
        quality_requirement: str,  # "standard", "high", "critical"
        batch_size: int
    ) -> ModelDecision:
        """Select embedding model based on context."""

        # Rule 1: Privacy overrides everything
        if privacy_tier in ["private", "sensitive"]:
            return ModelDecision(
                model_name="nomic-local",
                model_type="local",
                reason="Privacy tier requires local processing"
            )

        # Rule 2: Quality requirements
        if quality_requirement == "critical":
            # Check if API is significantly better
            local_score = self.benchmarks.get("nomic-local", {}).get("accuracy", 0.85)
            api_score = self.benchmarks.get("openai-large", {}).get("accuracy", 0.92)

            if api_score - local_score > 0.05:
                return ModelDecision(
                    model_name="openai-large",
                    model_type="api",
                    reason=f"Critical quality: API is {(api_score-local_score)*100:.1f}% better"
                )

        # Rule 3: Cost optimization for large batches
        if batch_size > 10000:
            return ModelDecision(
                model_name="nomic-local",
                model_type="local",
                reason=f"Large batch ({batch_size}): Local saves ${batch_size * 0.0001:.2f}"
            )

        # Default: Local
        return ModelDecision(
            model_name="nomic-local",
            model_type="local",
            reason="Default: Local model meets requirements"
        )

    def select_transcription_model(
        self,
        audio_duration_seconds: float,
        privacy_tier: str,
        quality_requirement: str
    ) -> ModelDecision:
        """Select transcription model."""

        # Privacy override
        if privacy_tier in ["private", "sensitive"]:
            return ModelDecision(
                model_name="mlx-whisper-large",
                model_type="local",
                reason="Privacy requires local transcription"
            )

        # Quality for important content
        if quality_requirement == "critical":
            return ModelDecision(
                model_name="openai-whisper",
                model_type="api",
                reason="Critical quality: API has best accuracy"
            )

        # Cost optimization for long audio
        if audio_duration_seconds > 3600:  # > 1 hour
            api_cost = (audio_duration_seconds / 60) * 0.006
            return ModelDecision(
                model_name="mlx-whisper-large",
                model_type="local",
                reason=f"Long audio: Local saves ${api_cost:.2f}"
            )

        # Default: Local large model
        return ModelDecision(
            model_name="mlx-whisper-large",
            model_type="local",
            reason="Default: Local model meets requirements"
        )
```

---

## Running Tests

### Quick Test (Development)

```bash
# Run with small sample
pytest tests/test_ab_comparison.py -k "quick" -v
```

### Full Benchmark (Before Decisions)

```bash
# Run complete A/B comparison
python -m tests.ab_test_runner \
    --config tests/ab_config.yaml \
    --output results/ab_report.md

# View results
cat results/ab_report.md
```

### Continuous Monitoring

```python
# Log quality metrics over time
def log_search_quality(query: str, results: List, user_clicked: Optional[str]):
    """Track implicit quality signals."""
    metrics = {
        "timestamp": datetime.now().isoformat(),
        "query": query,
        "num_results": len(results),
        "top_result_id": results[0].doc_id if results else None,
        "user_selected": user_clicked,
        "was_top_result_selected": user_clicked == results[0].doc_id if results else False
    }
    append_to_log("search_quality.jsonl", metrics)
```

---

## Cost Calculator

```python
# src/utils/cost_calculator.py

@dataclass
class CostEstimate:
    local_cost: float  # Always 0, but tracks compute time
    api_cost: float
    recommendation: str

def estimate_monthly_cost(
    documents_per_month: int,
    avg_pages_per_doc: int,
    audio_hours_per_month: float,
    queries_per_month: int
) -> CostEstimate:
    """Estimate monthly costs for local vs API."""

    # Embedding costs (API)
    tokens_per_page = 500
    total_tokens = documents_per_month * avg_pages_per_doc * tokens_per_page
    embedding_api_cost = (total_tokens / 1000) * 0.00013  # text-embedding-3-large

    # Transcription costs (API)
    transcription_api_cost = audio_hours_per_month * 60 * 0.006  # $0.006/min

    # Query costs (minimal for embeddings, already indexed)
    query_api_cost = (queries_per_month * 50 / 1000) * 0.00013  # 50 tokens per query

    total_api_cost = embedding_api_cost + transcription_api_cost + query_api_cost

    # Generate recommendation
    if total_api_cost < 10:
        rec = f"API cost is low (${total_api_cost:.2f}/mo). Consider API for quality."
    elif total_api_cost < 50:
        rec = f"Moderate API cost (${total_api_cost:.2f}/mo). Hybrid recommended."
    else:
        rec = f"High API cost (${total_api_cost:.2f}/mo). Local strongly recommended."

    return CostEstimate(
        local_cost=0.0,
        api_cost=total_api_cost,
        recommendation=rec
    )
```

---

## Quality Thresholds

Based on benchmarks, use these thresholds for decision-making:

| Metric | Acceptable | Good | Excellent |
|--------|-----------|------|-----------|
| Retrieval Accuracy @10 | > 0.70 | > 0.85 | > 0.95 |
| MRR | > 0.50 | > 0.70 | > 0.85 |
| Transcription WER | < 0.15 | < 0.08 | < 0.03 |
| Query Latency (p95) | < 500ms | < 200ms | < 100ms |

**Rule of Thumb**: If local is within 5% of API quality, use local. If gap is 5-15%, use hybrid. If gap is >15%, consider API for quality-critical use cases.

---

*Run benchmarks before making technology decisions. Update this document with actual results.*
