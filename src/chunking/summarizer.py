"""
Multi-Resolution Summarizer

Generates parent-level summaries from child chunks, providing a quick
overview layer for search results without reading all children.
"""

import logging

logger = logging.getLogger(__name__)

SUMMARY_PROMPT = """\
Summarize the following section in 2-3 sentences. Focus on the key topics and takeaways.

Section:
{text}

Summary:"""


class MultiResolutionSummarizer:
    """Generates summaries at the parent chunk level."""

    def __init__(self, llm_provider=None, max_text_chars: int = 4000):
        self._provider = llm_provider
        self._max_chars = max_text_chars

    @property
    def provider(self):
        if self._provider is None:
            from src.llm.provider import get_default_provider

            self._provider = get_default_provider()
        return self._provider

    async def summarize_parent(
        self, parent_text: str, child_chunks: list[str] | None = None
    ) -> str:
        """Generate a summary for a parent chunk.

        Args:
            parent_text: Full parent chunk text.
            child_chunks: Optional list of child chunk texts (for context).

        Returns:
            Summary string (2-3 sentences), or empty string on failure.
        """
        try:
            text = parent_text[: self._max_chars]
            prompt = SUMMARY_PROMPT.format(text=text)
            response = await self.provider.generate(prompt, max_tokens=150)
            return response.strip()
        except Exception as e:
            logger.warning(f"Summary generation failed: {e}")
            return ""
