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
import logging

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
        """Generate context prefixes for a batch of chunks.

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

    def _cache_key(self, document_text: str, chunk_text: str) -> str:
        """Generate a cache key from document prefix + chunk text."""
        content = document_text[:500] + "|" + chunk_text
        return hashlib.sha256(content.encode()).hexdigest()[:24]

    @staticmethod
    def clear_cache() -> None:
        """Clear the in-memory context cache."""
        _context_cache.clear()
