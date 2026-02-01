"""
Sample documents for testing the PKM system.

Provides realistic test data for:
- Embedding quality tests
- Chunking strategy tests
- Search accuracy tests
- Privacy detection tests
"""

from dataclasses import dataclass
from typing import Dict, List

# Sample markdown documents of varying sizes
SAMPLE_MARKDOWN = {
    "short": """# Quick Note

This is a brief note about Python programming.

Key points:
- Python is interpreted
- It uses indentation for blocks
- Very readable syntax
""",

    "medium": """# Project Planning Document

## Overview

This document outlines the project planning methodology we use for software development projects.

## Phase 1: Discovery

During discovery, we identify:
- Stakeholder needs
- Technical requirements
- Budget constraints
- Timeline expectations

The discovery phase typically takes 2-4 weeks depending on project complexity.

## Phase 2: Design

Design involves creating:
- Architecture diagrams
- Database schemas
- API specifications
- UI/UX mockups

All designs must be reviewed and approved before implementation begins.

## Phase 3: Implementation

Development follows an agile methodology with:
- 2-week sprints
- Daily standups
- Sprint reviews
- Retrospectives

Code quality is maintained through:
- Automated testing (80% coverage minimum)
- Code reviews
- CI/CD pipelines
- Static analysis

## Conclusion

Following this methodology ensures consistent, high-quality project delivery.
""",

    "technical": """# Machine Learning Pipeline Architecture

## Data Ingestion Layer

The data ingestion layer handles multiple input sources:

```python
class DataIngester:
    def __init__(self, config: IngestionConfig):
        self.sources = config.sources
        self.validators = config.validators

    async def ingest(self, source_id: str) -> DataFrame:
        source = self.sources[source_id]
        raw_data = await source.fetch()
        validated = self.validators.validate(raw_data)
        return validated
```

### Supported Sources
- REST APIs with pagination
- S3 buckets (Parquet, CSV, JSON)
- Databases (PostgreSQL, MongoDB)
- Streaming sources (Kafka, Kinesis)

## Feature Engineering

Feature engineering transforms raw data into ML-ready features:

1. **Numeric features**: Scaling, normalization, binning
2. **Categorical features**: One-hot encoding, embedding lookup
3. **Text features**: TF-IDF, embeddings, n-grams
4. **Temporal features**: Lag features, rolling statistics

## Model Training

Training uses distributed computing for scalability:

```python
trainer = DistributedTrainer(
    model=model,
    dataset=dataset,
    config=TrainingConfig(
        batch_size=32,
        learning_rate=1e-4,
        epochs=100,
        early_stopping_patience=5
    )
)
metrics = trainer.train()
```

## Inference Pipeline

Real-time inference with sub-100ms latency requirements.
""",
}

# Sample queries with expected relevant documents
SEARCH_TEST_CASES = [
    {
        "query": "How do I plan a software project?",
        "expected_doc": "medium",
        "expected_sections": ["Phase 1: Discovery", "Phase 2: Design"],
        "min_score": 0.7
    },
    {
        "query": "Python programming syntax",
        "expected_doc": "short",
        "expected_sections": ["Quick Note"],
        "min_score": 0.6
    },
    {
        "query": "machine learning data pipeline architecture",
        "expected_doc": "technical",
        "expected_sections": ["Data Ingestion Layer", "Feature Engineering"],
        "min_score": 0.75
    },
    {
        "query": "code review and testing practices",
        "expected_doc": "medium",
        "expected_sections": ["Phase 3: Implementation"],
        "min_score": 0.65
    },
]

# Semantic similarity pairs for embedding quality testing
SIMILARITY_PAIRS = [
    # High similarity (should score > 0.8)
    {
        "text_a": "Machine learning models require training data to learn patterns.",
        "text_b": "ML algorithms need labeled datasets to identify relationships.",
        "expected_similarity": "high",
        "min_score": 0.8
    },
    {
        "text_a": "The Python programming language uses indentation for code blocks.",
        "text_b": "In Python, whitespace indentation defines scope instead of braces.",
        "expected_similarity": "high",
        "min_score": 0.8
    },
    # Medium similarity (should score 0.5-0.8)
    {
        "text_a": "Database indexes improve query performance.",
        "text_b": "SQL queries can be optimized using proper indexing strategies.",
        "expected_similarity": "medium",
        "min_score": 0.5,
        "max_score": 0.85
    },
    # Low similarity (should score < 0.5)
    {
        "text_a": "The weather today is sunny and warm.",
        "text_b": "Distributed systems require careful handling of network partitions.",
        "expected_similarity": "low",
        "max_score": 0.4
    },
]

# Privacy test samples
PRIVACY_TEST_SAMPLES = {
    "clean": """
# Meeting Notes

Discussed project timeline with the team. Agreed on Q2 launch date.
Next steps:
- Review design documents
- Schedule stakeholder meeting
- Update project tracker
""",

    "has_email": """
# Contact Information

For questions, reach out to john.doe@example.com or jane.smith@company.org.
""",

    "has_phone": """
# Emergency Contacts

Call support at (555) 123-4567 or the backup line 555-987-6543.
""",

    "has_ssn": """
# Employee Record (SENSITIVE)

Employee ID: EMP-12345
SSN: 123-45-6789
Start Date: 2024-01-15
""",

    "has_api_key": """
# Configuration

api_key = "sk-abc123def456ghi789jkl012mno345pqr678stu901vwx"
database_url = "postgresql://localhost:5432/mydb"
""",

    "has_password": """
# Server Setup

1. SSH into server
2. Login with:
   username: admin
   password: SuperSecret123!
3. Run deployment script
""",

    "has_credit_card": """
# Payment Information

Card: 4111111111111111
Exp: 12/25
CVV: 123
""",
}

# Chunking test cases
CHUNKING_TEST_CASES = [
    {
        "name": "headers_preserved",
        "input": """# Main Title

## Section One

Content for section one goes here.

## Section Two

Content for section two goes here.
""",
        "expected_chunks": 2,
        "validation": lambda chunks: all(
            chunk.strip().startswith("##") or chunk.strip().startswith("#")
            for chunk in chunks
        )
    },
    {
        "name": "code_blocks_intact",
        "input": """# Code Example

Here's some Python:

```python
def hello_world():
    print("Hello, World!")
    return True
```

And here's the explanation.
""",
        "validation": lambda chunks: any(
            "def hello_world():" in chunk and "return True" in chunk
            for chunk in chunks
        )
    },
]


@dataclass
class TestDocument:
    """A test document with metadata."""
    id: str
    content: str
    expected_chunks: int
    expected_tier: str
    tags: List[str]


# Full test document set
TEST_DOCUMENTS: List[TestDocument] = [
    TestDocument(
        id="doc_001",
        content=SAMPLE_MARKDOWN["short"],
        expected_chunks=1,
        expected_tier="public",
        tags=["programming", "python", "notes"]
    ),
    TestDocument(
        id="doc_002",
        content=SAMPLE_MARKDOWN["medium"],
        expected_chunks=4,
        expected_tier="public",
        tags=["planning", "methodology", "agile"]
    ),
    TestDocument(
        id="doc_003",
        content=SAMPLE_MARKDOWN["technical"],
        expected_chunks=4,
        expected_tier="public",
        tags=["ml", "architecture", "python"]
    ),
    TestDocument(
        id="doc_004",
        content=PRIVACY_TEST_SAMPLES["has_ssn"],
        expected_chunks=1,
        expected_tier="restricted",
        tags=["employee", "hr", "sensitive"]
    ),
]


def get_sample_corpus() -> Dict[str, str]:
    """Get the full sample corpus for testing."""
    return {
        **SAMPLE_MARKDOWN,
        **{f"privacy_{k}": v for k, v in PRIVACY_TEST_SAMPLES.items()}
    }


def get_search_test_cases() -> List[Dict]:
    """Get search test cases."""
    return SEARCH_TEST_CASES


def get_similarity_pairs() -> List[Dict]:
    """Get similarity test pairs."""
    return SIMILARITY_PAIRS
