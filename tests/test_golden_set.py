"""
Golden Dataset Regression Tests

Runs the golden_set.yaml test cases to ensure retrieval quality
doesn't regress when making changes to:
- Embedding model
- Chunking strategy
- Re-ranking logic
- Hybrid search weights

Usage:
    pytest tests/test_golden_set.py -v
    pytest tests/test_golden_set.py -v -k "architecture"  # Run tagged subset
"""

import pytest
import yaml
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional
import json
import logging

logger = logging.getLogger(__name__)


@dataclass
class GoldenTestCase:
    """A single golden test case."""
    query: str
    expected_file: str
    expected_in_top: int
    tags: List[str]


@dataclass
class TestResult:
    """Result of a single test case."""
    test_case: GoldenTestCase
    passed: bool
    found_rank: Optional[int]
    found_score: Optional[float]
    actual_results: List[str]
    error: Optional[str] = None


def load_golden_set(path: Optional[Path] = None) -> tuple:
    """Load golden set from YAML file."""
    if path is None:
        path = Path(__file__).parent / "golden_set.yaml"

    with open(path, "r") as f:
        data = yaml.safe_load(f)

    config = data.get("config", {})
    test_cases = []

    for q in data.get("queries", []):
        test_cases.append(GoldenTestCase(
            query=q["query"],
            expected_file=q["expected_file"],
            expected_in_top=q.get("expected_in_top", config.get("required_rank", 3)),
            tags=q.get("tags", [])
        ))

    return config, test_cases


class GoldenSetRunner:
    """
    Runs golden set tests against the retrieval system.
    """

    def __init__(self, retriever, embedder):
        """
        Args:
            retriever: Search retriever (HybridSearcher, ParentChildRetriever)
            embedder: Function to embed query text -> vector
        """
        self.retriever = retriever
        self.embedder = embedder

    async def run_single(self, test_case: GoldenTestCase) -> TestResult:
        """Run a single test case."""
        try:
            # Embed query
            query_vector = await self.embedder(test_case.query)

            # Search
            results = await self.retriever.search(
                query=test_case.query,
                query_vector=query_vector,
                k=test_case.expected_in_top * 2  # Get extra for debugging
            )

            # Extract file paths from results
            result_files = []
            for r in results:
                # Handle different result formats
                if hasattr(r, "metadata"):
                    meta = r.metadata if isinstance(r.metadata, dict) else json.loads(r.metadata)
                    path = meta.get("source_path", "")
                elif isinstance(r, dict):
                    meta = r.get("metadata", {})
                    if isinstance(meta, str):
                        meta = json.loads(meta)
                    path = meta.get("source_path", r.get("document_id", ""))
                else:
                    path = ""

                result_files.append(path)

            # Check if expected file is in results
            found_rank = None
            found_score = None
            for i, path in enumerate(result_files):
                if test_case.expected_file in path or path.endswith(test_case.expected_file):
                    found_rank = i + 1
                    if hasattr(results[i], "score"):
                        found_score = results[i].score
                    elif isinstance(results[i], dict):
                        found_score = results[i].get("score", results[i].get("rrf_score"))
                    break

            passed = found_rank is not None and found_rank <= test_case.expected_in_top

            return TestResult(
                test_case=test_case,
                passed=passed,
                found_rank=found_rank,
                found_score=found_score,
                actual_results=result_files[:test_case.expected_in_top]
            )

        except Exception as e:
            return TestResult(
                test_case=test_case,
                passed=False,
                found_rank=None,
                found_score=None,
                actual_results=[],
                error=str(e)
            )

    async def run_all(self, test_cases: List[GoldenTestCase]) -> List[TestResult]:
        """Run all test cases."""
        results = []
        for tc in test_cases:
            result = await self.run_single(tc)
            results.append(result)

            if result.passed:
                logger.info(f"✓ PASS: {tc.query[:50]}... (rank {result.found_rank})")
            else:
                logger.warning(f"✗ FAIL: {tc.query[:50]}... (expected {tc.expected_file})")
                if result.error:
                    logger.warning(f"  Error: {result.error}")

        return results

    def generate_report(self, results: List[TestResult]) -> str:
        """Generate a human-readable report."""
        passed = sum(1 for r in results if r.passed)
        failed = len(results) - passed

        lines = [
            "=" * 60,
            "Golden Set Regression Test Report",
            "=" * 60,
            f"Total: {len(results)} | Passed: {passed} | Failed: {failed}",
            f"Pass Rate: {passed/len(results)*100:.1f}%",
            "=" * 60,
            ""
        ]

        if failed > 0:
            lines.append("FAILED TESTS:")
            lines.append("-" * 40)
            for r in results:
                if not r.passed:
                    lines.append(f"Query: {r.test_case.query}")
                    lines.append(f"  Expected: {r.test_case.expected_file} (in top {r.test_case.expected_in_top})")
                    if r.found_rank:
                        lines.append(f"  Found at rank: {r.found_rank}")
                    else:
                        lines.append("  Not found in results")
                    lines.append(f"  Actual top results: {r.actual_results}")
                    if r.error:
                        lines.append(f"  Error: {r.error}")
                    lines.append("")

        return "\n".join(lines)


# ============================================
# Pytest Integration
# ============================================

# Load test cases for parameterization
try:
    _config, _test_cases = load_golden_set()
except:
    _config, _test_cases = {}, []


@pytest.fixture
def retriever():
    """Create retriever for testing. Override in conftest.py."""
    pytest.skip("Retriever not configured. Add to conftest.py")


@pytest.fixture
def embedder():
    """Create embedder for testing. Override in conftest.py."""
    pytest.skip("Embedder not configured. Add to conftest.py")


@pytest.mark.parametrize("test_case", _test_cases, ids=[tc.query[:50] for tc in _test_cases])
@pytest.mark.asyncio
async def test_golden_query(test_case: GoldenTestCase, retriever, embedder):
    """Test that each golden query finds the expected file."""
    runner = GoldenSetRunner(retriever, embedder)
    result = await runner.run_single(test_case)

    if result.error:
        pytest.fail(f"Error: {result.error}")

    assert result.passed, (
        f"Expected '{test_case.expected_file}' in top {test_case.expected_in_top}, "
        f"but found at rank {result.found_rank or 'NOT FOUND'}. "
        f"Actual results: {result.actual_results}"
    )


# ============================================
# Standalone Runner
# ============================================

async def main():
    """Run golden set tests standalone."""
    import argparse

    parser = argparse.ArgumentParser(description="Run golden set regression tests")
    parser.add_argument("--tags", nargs="+", help="Only run tests with these tags")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    # Load test cases
    config, test_cases = load_golden_set()

    # Filter by tags if specified
    if args.tags:
        test_cases = [tc for tc in test_cases if any(t in tc.tags for t in args.tags)]

    print(f"Running {len(test_cases)} golden set tests...")

    # Would need actual retriever/embedder here
    # runner = GoldenSetRunner(retriever, embedder)
    # results = await runner.run_all(test_cases)
    # print(runner.generate_report(results))

    print("Note: Configure retriever and embedder to run actual tests")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
