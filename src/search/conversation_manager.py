"""Conversational Search — multi-turn context-aware query rewriting.

Detects follow-up queries and prepends context from previous search turns
to enable natural multi-turn search conversations.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

_FOLLOW_UP_PRONOUNS = {"it", "this", "that", "they", "them", "those", "these", "its", "their"}
_CONNECTOR_WORDS = {"also", "another", "more", "else", "too", "instead", "besides", "similarly"}


@dataclass
class SearchTurn:
    """A single turn in a search conversation."""

    query: str
    results: list[dict] = field(default_factory=list)
    timestamp: str = ""


class ConversationManager:
    """Manage multi-turn search conversations with context-aware rewriting."""

    def __init__(self, max_turns: int = 10):
        self.max_turns = max_turns
        self._turns: list[SearchTurn] = []

    def rewrite_query(self, follow_up: str) -> str:
        """Rewrite a follow-up query by prepending context from previous turns.

        If the query isn't detected as a follow-up, returns it unchanged.
        """
        if not self._turns or not self._is_follow_up(follow_up):
            return follow_up

        # Get the most recent turn's query as context
        prev = self._turns[-1]
        # Extract topic keywords from previous query (skip short words)
        prev_keywords = [w for w in prev.query.split() if len(w) > 2]
        if not prev_keywords:
            return follow_up

        context = " ".join(prev_keywords[:5])
        rewritten = f"{context} {follow_up}"
        logger.debug(f"Query rewritten: '{follow_up}' -> '{rewritten}'")
        return rewritten

    def add_turn(self, query: str, results: list[dict]) -> None:
        """Record a search turn."""
        self._turns.append(
            SearchTurn(
                query=query,
                results=results[:5],  # Keep only top results for context
                timestamp=datetime.now().isoformat(),
            )
        )
        # Auto-prune
        if len(self._turns) > self.max_turns:
            self._turns = self._turns[-self.max_turns :]

    def _is_follow_up(self, query: str) -> bool:
        """Detect if a query is likely a follow-up to a previous search."""
        words = set(re.findall(r"\b\w+\b", query.lower()))

        # Short queries are likely follow-ups
        if len(words) <= 3 and self._turns:
            return True

        # Queries starting with pronouns
        first_word = query.strip().split()[0].lower() if query.strip() else ""
        if first_word in _FOLLOW_UP_PRONOUNS:
            return True

        # Contains connector words
        if words & _CONNECTOR_WORDS:
            return True

        return False

    def clear(self) -> None:
        """Reset the conversation."""
        self._turns.clear()

    def get_context_summary(self) -> str:
        """Get a brief summary of the conversation so far."""
        if not self._turns:
            return ""
        queries = [t.query for t in self._turns[-3:]]
        return " -> ".join(queries)
