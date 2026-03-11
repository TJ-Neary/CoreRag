"""
Contextual Retrieval — Context Generator

Implements Anthropic's Contextual Retrieval technique: prepend LLM-generated
context to each chunk before embedding. This situates each chunk within the
full document, improving retrieval accuracy by ~49%.

The context prefix is stored alongside the chunk text but the original text
is preserved for display. Only the concatenation (context + chunk) is embedded.
"""

import asyncio
import hashlib
import json
import logging
import re

logger = logging.getLogger(__name__)

# In-memory context cache to avoid redundant LLM calls within a session
_context_cache: dict[str, str] = {}

CONTEXT_PROMPT = """\
<document>
{doc_text}
</document>

Here is a chunk from that document:
<chunk>
{chunk_text}
</chunk>

Provide a short context (2-3 sentences) that situates this chunk within the document. \
Focus on: what section this is from, what topic it covers, and how it relates to the \
document's overall subject. Return ONLY the context, no preamble."""

BATCH_CONTEXT_PROMPT = """\
<document>
{doc_text}
</document>

Below are {n} chunks from this document. For each chunk, provide a short context \
(2-3 sentences) that situates it within the document. Focus on: what section it is \
from, what topic it covers, and how it relates to the document's overall subject.

{chunks_block}

Return a JSON array with exactly {n} objects. Each object must have:
- "id": the chunk number (integer, starting from 0)
- "context": the context string (2-3 sentences)

Example for 2 chunks: [{{"id": 0, "context": "This chunk..."}}, {{"id": 1, "context": "This chunk..."}}]

Return ONLY the JSON array. No markdown fences, no explanation, no preamble."""


class ContextGenerator:
    """Generates contextual prefixes for chunks using LLM."""

    def __init__(self, llm_provider=None, max_doc_chars: int = 8000):
        """
        Args:
            llm_provider: LLM provider instance (from src.llm.provider).
                          If None, uses get_default_provider().
            max_doc_chars: Max characters of document text to include in prompt.
        """
        self._provider = llm_provider
        self._max_doc_chars = max_doc_chars

    @property
    def provider(self):
        if self._provider is None:
            from src.llm.provider import get_default_provider

            self._provider = get_default_provider()
        return self._provider

    async def generate_context(self, document_text: str, chunk_text: str) -> str:
        """Generate a context prefix for a single chunk.

        Args:
            document_text: Full document text (truncated internally).
            chunk_text: The chunk to contextualize.

        Returns:
            Context string (2-3 sentences), or empty string on failure.
        """
        cache_key = self._cache_key(document_text, chunk_text)
        if cache_key in _context_cache:
            return _context_cache[cache_key]

        try:
            doc_truncated = document_text[: self._max_doc_chars]
            prompt = CONTEXT_PROMPT.format(doc_text=doc_truncated, chunk_text=chunk_text)

            response = await self.provider.generate("", prompt)
            context = response.strip()

            _context_cache[cache_key] = context
            return context

        except Exception as e:
            logger.warning(f"Context generation failed: {e}")
            return ""

    async def generate_contexts_batch(
        self,
        document_text: str,
        chunk_texts: list[str],
        concurrency: int = 3,
    ) -> list[str]:
        """Generate context prefixes for a batch of chunks (one LLM call per chunk).

        Uses a semaphore to limit concurrent LLM calls.

        Args:
            document_text: Full document text.
            chunk_texts: List of chunk texts to contextualize.
            concurrency: Max concurrent LLM calls.

        Returns:
            List of context strings (same order as chunk_texts).
        """
        semaphore = asyncio.Semaphore(concurrency)

        async def _generate_one(chunk_text: str) -> str:
            async with semaphore:
                return await self.generate_context(document_text, chunk_text)

        tasks = [_generate_one(ct) for ct in chunk_texts]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Replace exceptions with empty strings
        return [r if isinstance(r, str) else "" for r in results]

    async def generate_contexts_batch_multi(
        self,
        document_text: str,
        chunk_texts: list[str],
        max_chunks_per_call: int = 50,
    ) -> list[str]:
        """Generate context prefixes for multiple chunks in a single LLM call.

        Sends all chunks (up to max_chunks_per_call) in one prompt and parses
        a JSON array response. For parent groups larger than max_chunks_per_call,
        splits into sub-batches. Falls back to individual calls on parse failure.

        Args:
            document_text: Full document text (truncated to max_doc_chars).
            chunk_texts: List of chunk texts to contextualize.
            max_chunks_per_call: Max chunks per LLM call (sub-batch limit).

        Returns:
            List of context strings (same order as chunk_texts).
        """
        if not chunk_texts:
            return []

        # Single chunk — use the simpler single-chunk prompt
        if len(chunk_texts) == 1:
            ctx = await self.generate_context(document_text, chunk_texts[0])
            return [ctx]

        results: list[str] = [""] * len(chunk_texts)

        # Sub-batch if needed
        for batch_start in range(0, len(chunk_texts), max_chunks_per_call):
            batch_end = min(batch_start + max_chunks_per_call, len(chunk_texts))
            batch = chunk_texts[batch_start:batch_end]

            batch_results = await self._generate_multi_call(document_text, batch)

            for i, ctx in enumerate(batch_results):
                results[batch_start + i] = ctx

        return results

    async def _generate_multi_call(self, document_text: str, chunk_texts: list[str]) -> list[str]:
        """Execute one multi-chunk LLM call and parse the JSON response.

        Falls back to individual calls if JSON parsing fails.
        """
        doc_truncated = document_text[: self._max_doc_chars]
        n = len(chunk_texts)

        # Build chunks block with labeled XML tags
        chunks_parts = []
        for i, ct in enumerate(chunk_texts):
            # Truncate very long chunks to keep prompt manageable
            ct_truncated = ct[:2000] if len(ct) > 2000 else ct
            chunks_parts.append(f'<chunk id="{i}">\n{ct_truncated}\n</chunk>')
        chunks_block = "\n\n".join(chunks_parts)

        prompt = BATCH_CONTEXT_PROMPT.format(doc_text=doc_truncated, n=n, chunks_block=chunks_block)

        try:
            response = await self.provider.generate("", prompt)
            parsed = self._parse_batch_response(response, n)

            if parsed is not None:
                # Cache each result
                for i, ctx in enumerate(parsed):
                    if ctx:
                        cache_key = self._cache_key(document_text, chunk_texts[i])
                        _context_cache[cache_key] = ctx
                return parsed

            # Parse failed — fall back to individual calls
            logger.warning(
                f"Batch JSON parse failed for {n} chunks, falling back to individual calls"
            )
            return await self.generate_contexts_batch(document_text, chunk_texts, concurrency=2)

        except Exception as e:
            logger.warning(f"Batch context generation failed: {e}")
            return [""] * len(chunk_texts)

    @staticmethod
    def _parse_batch_response(response: str, expected_count: int) -> list[str] | None:
        """Parse a JSON array response from the batch prompt.

        Returns list of context strings in order, or None if parsing fails.
        """
        text = response.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*\n?", "", text)
            text = re.sub(r"\n?```\s*$", "", text)
            text = text.strip()

        # Try to find the JSON array in the response
        # Look for the outermost [...]
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return None

        json_str = text[start : end + 1]

        try:
            arr = json.loads(json_str)
        except json.JSONDecodeError:
            return None

        if not isinstance(arr, list):
            return None

        # Build results indexed by "id" field
        results = [""] * expected_count
        for item in arr:
            if not isinstance(item, dict):
                continue
            idx = item.get("id")
            ctx = item.get("context", "")
            if isinstance(idx, int) and 0 <= idx < expected_count and isinstance(ctx, str):
                results[idx] = ctx.strip()

        # Accept if we got at least 50% of expected results
        filled = sum(1 for r in results if r)
        if filled < expected_count * 0.5:
            return None

        return results

    def _cache_key(self, document_text: str, chunk_text: str) -> str:
        """Generate a cache key from document prefix + chunk text."""
        content = document_text[:500] + "|" + chunk_text
        return hashlib.sha256(content.encode()).hexdigest()[:24]

    @staticmethod
    def clear_cache() -> None:
        """Clear the in-memory context cache."""
        _context_cache.clear()
